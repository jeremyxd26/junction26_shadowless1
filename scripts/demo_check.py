#!/usr/bin/env python3
"""Demo path smoke check (issue #130): one command against a running service.

    python scripts/demo_check.py --base-url https://sentti.jeremyxd.dev --require-all
    python scripts/demo_check.py --base-url http://localhost:8000 --no-ask      # no model calls

Stages, in the order the presenter walks them: health, personas, the lead persona's overview, its
evidence refs, the persona allowlist, the what-if, the spike review (answer "Needed", then undo) and
the four brief questions through /api/ask (JSON mode).

One line per stage: name, PASS / FAIL / NOT DEPLOYED / SKIPPED, the time, and for a failure the
expected and the received value. A route that answers 405, or 404 without one of the service's own
error codes, is NOT DEPLOYED (the line names the route and the status). Exit code 0 only when no stage
failed; --require-all also fails on NOT DEPLOYED.

Rules: standard library only; no secrets; no retries. The only writes are the label answer and its
undo for the lead persona. The undo always runs once the answer was sent, and its result is checked
whatever happened before; a failed undo prints a loud line with the repair commands. A cookie jar keeps
the viewer cookie (#144), so the label answer is this run's own. Without --no-ask, at most four
questions go to the model (--ask-limit); a 429 stops the questions. The whole run ends within
--time-limit seconds (the undo is exempt), so do not run it in a loop.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# ---- reference values: one table, each with its source ------------------------------------------
LEAD = "CUST00860"
OTHER_PERSONA = "CUST00493"
REFERENCE: dict[str, tuple[Any, str]] = {
    "personas": (("CUST00860", "CUST00493", "CUST00349", "CUST00849"), "docs/design/personas.md:12"),
    "regular_essentials": (1889.04, "docs/design/personas.md:136"),
    "unexpected_necessities": (521.15, "docs/design/personas.md:136 (spike answered Needed, or no review)"),
    "unexpected_necessities_pending": (341.08, "docs/design/personas.md:136 (without the 1,080.42 one-off)"),
    "everyday_spending": (600.41, "docs/design/personas.md:136"),
    "unclassified_pending": (180.07, "docs/design/personas.md:89: 1,080.42 / 6 (the one-off over the 6-month window)"),
    "spike_amount": (1080.42, "docs/design/personas.md:89"),
    "safe_to_spend": (180.26, "docs/design/personas.md:109; contracts/api.md section 10 (after Needed)"),
    "safe_to_spend_pending": (221.58, "contracts/api.md section 10 (while the review is pending)"),
    "what_if_baseline_month": (229.56, "docs/design/personas.md:191 (dining out)"),
    "what_if_saving_month": (45.91, "docs/design/personas.md:191 (dining out, 20%)"),
}
NON_PERSONA = "CUST00001"   # a customer of the data who is not a persona (#101)
UNKNOWN = "CUST99999"       # no such customer
BRIEF_QUESTIONS = ("Where did my money go?", "What kind of spender am I?", "What can I safely spend this week?",
                   "How could I save more?")
TOLERANCE = 0.005
TIMEOUT_S = 15
ASK_TIMEOUT_S = 45
TIME_LIMIT_S = 60
REVIEW_MIN_LEFT_S = 15   # the review stage starts only with this much of the time limit left
RECHECK_WAIT_S = 2.0     # after a "Needed" without a response: look again after this long
REPAIR_SCRIPT = f"python core/scripts/reset_reviews.py {LEAD}"


def ref(name: str) -> Any:
    return REFERENCE[name][0]


# ---- HTTP -----------------------------------------------------------------------------------------

@dataclass
class Response:
    status: int
    body: Any  # parsed JSON, or None
    route: str = ""
    retry_after: str | None = None


class Client:
    """One base URL and one cookie jar; every request is sent once (no retries). Requests stop at the
    deadline, except those sent with `exempt=True` (the undo)."""

    def __init__(self, base_url: str, time_limit: float = TIME_LIMIT_S) -> None:
        self.base = base_url.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.requests = 0
        self.deadline = time.monotonic() + time_limit

    def left(self) -> float:
        return self.deadline - time.monotonic()

    def call(self, method: str, path: str, body: Any = None, timeout: float = TIMEOUT_S,
             exempt: bool = False) -> Response:
        if not exempt:
            if self.left() <= 0:
                raise TimeLimit()
            timeout = max(1.0, min(timeout, self.left()))
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Accept": "application/json", "Content-Type": "application/json"})
        self.requests += 1
        retry_after = None
        try:
            with self.opener.open(req, timeout=timeout) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw, retry_after = e.code, e.read(), e.headers.get("Retry-After")
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = None
        return Response(status, parsed, f"{method} {path.split('?')[0]}", retry_after)


def not_deployed(r: Response) -> bool:
    """405, or 404 that is not one of the service's own answers (an unknown route)."""
    if r.status == 405:
        return True
    return r.status == 404 and error_code(r) in (None, "not_found")


def error_code(r: Response) -> str | None:
    if isinstance(r.body, dict) and isinstance(r.body.get("error"), dict):
        return r.body["error"].get("code")
    return None


# ---- stages ---------------------------------------------------------------------------------------

class StageFailed(Exception):
    def __init__(self, what: str, expected: Any, got: Any) -> None:
        super().__init__(f"{what}: expected {expected!r}, got {got!r}")


class NotDeployed(Exception):
    pass


class TimeLimit(Exception):
    pass


class RateLimited(Exception):
    pass


def expect(what: str, expected: Any, got: Any) -> None:
    ok = (isinstance(expected, float) and isinstance(got, (int, float)) and abs(got - expected) <= TOLERANCE) \
        or expected == got
    if not ok:
        raise StageFailed(what, expected, got)


def ok_json(r: Response, what: str, status: int = 200) -> Any:
    if not_deployed(r):
        raise NotDeployed(f"{r.route} -> {r.status}")
    if r.status != status:
        raise StageFailed(f"{what} status", status, f"{r.status} {error_code(r) or ''}".strip())
    if not isinstance(r.body, dict):
        raise StageFailed(f"{what} body", "a JSON object", "not a JSON object")
    return r.body


def value(number: Any) -> Any:
    return number.get("value") if isinstance(number, dict) else None


def baskets(overview: dict) -> dict[str, float]:
    """Basket key -> amount of the overview's breakdown card."""
    for card in overview.get("cards") or []:
        if card.get("type") == "breakdown":
            return {i.get("key"): value(i.get("amount")) for i in card.get("items") or []}
    raise StageFailed("breakdown card", "present", "missing")


def pending_review(overview: dict) -> dict | None:
    return next((r for r in overview.get("reviews") or [] if r.get("tx_ref")), None)


def evidence_refs(node: Any, out: list[str]) -> list[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "evidence_ref" and isinstance(v, str) and v.startswith("ev_") and v not in out:
                out.append(v)
            else:
                evidence_refs(v, out)
    elif isinstance(node, list):
        for v in node:
            evidence_refs(v, out)
    return out


@dataclass
class Result:
    name: str
    status: str
    ms: int
    detail: str = ""


class Check:
    expect_model = "any"   # --expect-model: on | off | any

    def __init__(self, client: Client, out: Callable[[str], None] = print) -> None:
        self.c = client
        self.out = out
        self.results: list[Result] = []
        self.overview: dict | None = None
        self.undo_failed = False
        self.stop_asking: str | None = None

    def line(self, res: Result) -> None:
        self.results.append(res)
        self.out(f"{res.name:<44} {res.status:<13} {res.ms:>6} ms  {res.detail}".rstrip())

    def stage(self, name: str, fn: Callable[[], str | None]) -> None:
        t = time.perf_counter()
        try:
            note = fn() or ""
            status = "PASS"
        except NotDeployed as e:
            status, note = "NOT DEPLOYED", str(e)
        except StageFailed as e:
            status, note = "FAIL", str(e)
        except TimeLimit:
            status, note = "FAIL", "time limit reached before this stage finished"
        except RateLimited as e:
            status, note = "FAIL", str(e)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            cut = self.c.left() <= 0  # the request's timeout was shortened to what was left of the limit
            status, note = "FAIL", "time limit reached (a request was cut short)" if cut else f"request failed ({type(e).__name__})"
        except Exception as e:  # noqa: BLE001 - a malformed response fails this stage, not the run
            status, note = "FAIL", f"unexpected response ({type(e).__name__})"
        self.line(Result(name, status, int((time.perf_counter() - t) * 1000), note))

    def skip(self, name: str, why: str) -> None:
        self.line(Result(name, "SKIPPED", 0, why))

    # 1
    def health(self) -> str:
        expect("/healthz", 200, self.c.call("GET", "/healthz").status)
        r = self.c.call("GET", "/readyz")
        expect("/readyz", (200, "ready"), (r.status, (r.body or {}).get("status") if isinstance(r.body, dict) else None))
        return ""

    # 2
    def personas(self) -> str:
        body = ok_json(self.c.call("GET", "/api/personas"), "/api/personas")
        ids = [p.get("customer_id") for p in body.get("personas") or []]
        expect("persona ids (lead first)", list(ref("personas")), ids)
        return ""

    # 3
    def overview_stage(self) -> str:
        ov = ok_json(self.c.call("GET", f"/api/overview/{LEAD}"), "overview")
        self.overview = ov
        b = baskets(ov)
        review = pending_review(ov)
        expect("regular_essentials", ref("regular_essentials"), b.get("regular_essentials"))
        expect("everyday_spending", ref("everyday_spending"), b.get("everyday_spending"))
        if review is not None:
            expect("unexpected_necessities (review pending)", ref("unexpected_necessities_pending"),
                   b.get("unexpected_necessities"))
            expect("unclassified (review pending)", ref("unclassified_pending"), b.get("unclassified"))
            expect("review amount", ref("spike_amount"), value(review.get("amount")))
        else:
            expect("unexpected_necessities", ref("unexpected_necessities"), b.get("unexpected_necessities"))
            expect("unclassified", None, b.get("unclassified"))
        hero = ov.get("hero")
        state = "review pending" if review is not None else "no review card"
        if hero is None:
            return f"{state}; hero not present"
        expected = ref("safe_to_spend_pending") if review is not None else ref("safe_to_spend")
        expect("hero safe to spend", expected, value(hero.get("primary")))
        return state

    # 4
    def evidence(self) -> str:
        if self.overview is None:
            raise StageFailed("overview", "loaded", "not loaded")
        refs = evidence_refs(self.overview, [])
        if not refs:
            raise StageFailed("evidence refs in the overview", "at least one", 0)
        for e in refs:
            body = ok_json(self.c.call("GET", f"/api/evidence/{e}?customer_id={LEAD}"), f"evidence {e}")
            if body.get("reconciles") is False:  # null is fine: nothing to add up
                raise StageFailed(f"evidence {e} reconciles", "true or null", False)
        r = self.c.call("GET", f"/api/evidence/{refs[0]}?customer_id={OTHER_PERSONA}")
        expect("a ref asked for another persona", (403, "evidence_forbidden"), (r.status, error_code(r)))
        return f"{len(refs)} refs resolve and reconcile; another persona gets 403"

    # 5
    def allowlist(self) -> str:
        a = self.c.call("GET", f"/api/overview/{NON_PERSONA}")
        b = self.c.call("GET", f"/api/overview/{UNKNOWN}")
        expect("unknown customer", (404, "customer_not_found"), (b.status, error_code(b)))
        expect("non-persona customer, same as unknown", (b.status, b.body), (a.status, a.body))
        return ""

    # 6
    def what_if(self) -> str:
        body = {"customer_id": LEAD, "language": "en",
                "scenario": {"selection": {"kind": "category", "value": "Restaurants"}, "cut_pct": 20}}
        res = ok_json(self.c.call("POST", "/api/whatif", body), "/api/whatif")
        expect("baseline_per_month", ref("what_if_baseline_month"), value(res.get("baseline_per_month")))
        expect("saving_per_month", ref("what_if_saving_month"), value(res.get("saving_per_month")))
        return ""

    # 7
    def spike_review(self) -> str:
        if self.overview is None:
            raise StageFailed("overview", "loaded", "not loaded")
        review = pending_review(self.overview)
        if review is None:
            # Is the label route there at all? An unknown tx_ref writes nothing.
            probe = self.c.call("POST", "/api/baskets/label", {"customer_id": LEAD, "tx_ref": "txr_0000000000000000",
                                                               "basket": "unexpected_necessities", "language": "en"})
            if not_deployed(probe):
                raise NotDeployed(f"{probe.route} -> {probe.status}")
            raise StageFailed("a pending review card for the lead persona", "present",
                              f"none (repair: {REPAIR_SCRIPT})")
        tx_ref = review["tx_ref"]
        if self.c.left() < REVIEW_MIN_LEFT_S:  # never start a write that the time limit could cut short
            raise StageFailed("time left for the review stage", f">= {REVIEW_MIN_LEFT_S} s",
                              f"{max(0, self.c.left()):.0f} s (not started; the persona is untouched)")
        label = {"customer_id": LEAD, "tx_ref": tx_ref, "language": "en"}
        failure: Exception | None = None
        sent = False
        no_response = False
        try:
            sent = True  # from here on an answer may have been written, so the undo must run
            try:
                # Exempt from the time limit, like the undo: a "Needed" cut short on this side could
                # still be applied by the server after the undo.
                needed = self.c.call("POST", "/api/baskets/label", {**label, "basket": "unexpected_necessities"},
                                     timeout=TIMEOUT_S, exempt=True)
            except (urllib.error.URLError, TimeoutError, OSError):
                no_response = True
                raise
            res = ok_json(needed, "label Needed")
            expect("review_state after Needed", "answered", res.get("review_state"))
            changes = {c.get("key"): c for c in res.get("changes") or []}
            expect("safe_to_spend change after Needed", ref("safe_to_spend"),
                   value((changes.get("safe_to_spend") or {}).get("after")))
            after = ok_json(self.c.call("GET", f"/api/overview/{LEAD}"), "overview after Needed")
            expect("review card after Needed", None, pending_review(after))
            expect("unexpected_necessities after Needed", ref("unexpected_necessities"),
                   baskets(after).get("unexpected_necessities"))
            if after.get("hero") is not None:
                expect("hero after Needed", ref("safe_to_spend"), value(after["hero"].get("primary")))
        except Exception as e:  # noqa: BLE001 - judged after the undo, below
            failure = e
        finally:
            undo_ok, undo_detail = self.undo(label) if sent else (True, "")
        if undo_ok and no_response and not self.card_back(tx_ref):
            # "Needed" got no response: the server may apply it after the undo. The card must be back
            # now and still be back a moment later.
            undo_ok, undo_detail = False, "the review card is not back after the undo (a late \"Needed\"?)"
        if not undo_ok:
            self.undo_failed = True
            self.out(f"UNDO FAILED - {LEAD} may be left answered (tx_ref {tx_ref}, {undo_detail})")
            self.out(f"  repair: curl -s -X POST {self.c.base}/api/baskets/label -H 'Content-Type: application/json' "
                     f"-d '{json.dumps({**label, 'basket': None})}'")
            self.out(f"  or, reliably: {REPAIR_SCRIPT}  (with per-viewer answers, #144, a bare curl acts as "
                     f"another viewer, so the reset script is the repair that always works)")
        if failure is not None:
            raise failure
        if not undo_ok:
            raise StageFailed("undo", "200, review_state 'pending'", undo_detail)
        back = ok_json(self.c.call("GET", f"/api/overview/{LEAD}"), "overview after undo")
        expect("review card back after undo", tx_ref, (pending_review(back) or {}).get("tx_ref"))
        if back.get("hero") is not None:
            expect("hero after undo", ref("safe_to_spend_pending"), value(back["hero"].get("primary")))
        return "Needed then undo; left pending"

    def card_back(self, tx_ref: str) -> bool:
        """The review card is back now and still RECHECK_WAIT_S later (exempt requests)."""
        for attempt in range(2):
            if attempt:
                time.sleep(RECHECK_WAIT_S)
            try:
                r = self.c.call("GET", f"/api/overview/{LEAD}", timeout=TIMEOUT_S, exempt=True)
            except Exception:  # noqa: BLE001 - not knowing counts as not back
                return False
            if not isinstance(r.body, dict) or (pending_review(r.body) or {}).get("tx_ref") != tx_ref:
                return False
        return True

    def undo(self, label: dict) -> tuple[bool, str]:
        """Send the undo (exempt from the time limit) and judge it; never raises."""
        try:
            r = self.c.call("POST", "/api/baskets/label", {**label, "basket": None}, timeout=TIMEOUT_S, exempt=True)
        except Exception as e:  # noqa: BLE001 - a dropped connection is a failed undo, reported loudly
            return False, f"request failed ({type(e).__name__})"
        state = r.body.get("review_state") if isinstance(r.body, dict) else None
        if r.status == 200 and state == "pending":
            return True, ""
        return False, f"status {r.status}, review_state {state!r}"

    # 8
    def ask(self, question: str) -> str:
        body = {"customer_id": LEAD, "message": question, "language": "en"}
        r = self.c.call("POST", "/api/ask", body, timeout=ASK_TIMEOUT_S)
        if r.status == 429:
            self.stop_asking = f"rate limited (429), Retry-After {r.retry_after or '?'} s"
            raise RateLimited(f"{self.stop_asking}; the remaining questions are not sent")
        res = ok_json(r, "/api/ask")
        expect("outcome", "answered", res.get("outcome"))
        # #244: with the model off the template answers with llm_unavailable, still "answered".
        warned = "llm_unavailable" in (res.get("warnings") or [])
        if self.expect_model == "on":
            expect("llm_unavailable warning (model on)", False, warned)
        elif self.expect_model == "off":
            expect("llm_unavailable warning (model off)", True, warned)
        numbers = res.get("numbers") or {}
        missing = [i for i in res.get("cited") or [] if not (numbers.get(i) or {}).get("evidence_ref")]
        expect("cited numbers without an evidence ref", [], missing)
        return f"{len(res.get('cited') or [])} numbers, each with an evidence ref"


def run(base_url: str, ask: bool = True, ask_limit: int = 4, out: Callable[[str], None] = print,
        time_limit: float = TIME_LIMIT_S, expect_model: str = "any") -> tuple[list[Result], Check]:
    check = Check(Client(base_url, time_limit), out)
    check.expect_model = expect_model
    check.stage("health and readiness", check.health)
    check.stage("personas (four, lead first)", check.personas)
    check.stage(f"overview {LEAD}", check.overview_stage)
    check.stage("evidence refs of the overview", check.evidence)
    check.stage("non-persona id = unknown id", check.allowlist)
    check.stage("what-if: dining out -20%", check.what_if)
    check.stage("spike review: Needed, then undo", check.spike_review)
    for i, question in enumerate(BRIEF_QUESTIONS):
        name = f"ask: {question}"
        if not ask:
            check.skip(name, "--no-ask")
        elif i >= ask_limit:
            check.skip(name, f"--ask-limit {ask_limit}")
        elif check.stop_asking:
            check.skip(name, f"not sent: {check.stop_asking}")
        else:
            check.stage(name, lambda q=question: check.ask(q))
    out(f"-- {check.c.requests} requests to {base_url}")
    return check.results, check


def main(argv: list[str] | None = None, out: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(description="Check the demo path against a running service.")
    ap.add_argument("--base-url", required=True, help="e.g. https://sentti.jeremyxd.dev or http://localhost:8000")
    ap.add_argument("--no-ask", action="store_true", help="skip /api/ask (it may call the language model)")
    ap.add_argument("--ask-limit", type=int, default=len(BRIEF_QUESTIONS), help="at most this many questions")
    ap.add_argument("--require-all", action="store_true", help="NOT DEPLOYED counts as a failure")
    ap.add_argument("--time-limit", type=float, default=TIME_LIMIT_S, help="seconds for the whole run (default 60)")
    ap.add_argument("--expect-model", choices=("on", "off", "any"), default="any",
                    help="on: answers must not carry llm_unavailable; off: they must (the template wrote them); "
                         "any: not checked (default)")
    args = ap.parse_args(argv)
    results, check = run(args.base_url, ask=not args.no_ask, ask_limit=max(0, args.ask_limit), out=out,
                         time_limit=args.time_limit, expect_model=args.expect_model)
    failed = [r for r in results if r.status == "FAIL" or (args.require_all and r.status == "NOT DEPLOYED")]
    counts = {s: sum(r.status == s for r in results) for s in ("PASS", "FAIL", "NOT DEPLOYED", "SKIPPED")}
    verdict = " -> FAIL" if failed or check.undo_failed else " -> OK"
    out("-- " + ", ".join(f"{n} {s.lower()}" for s, n in counts.items()) + verdict)
    return 1 if failed or check.undo_failed else 0


if __name__ == "__main__":
    sys.exit(main())
