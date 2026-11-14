"""scripts/demo_check.py (issue #130) against a standard-library stub of the service: every stage
passes, one wrong number fails, a missing route is NOT DEPLOYED, and the spike review is left pending
even when a step fails. No database, no network beyond 127.0.0.1."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("demo_check", ROOT / "scripts" / "demo_check.py")
demo_check = importlib.util.module_from_spec(_spec)
sys.modules["demo_check"] = demo_check  # dataclasses look the module up while it loads
_spec.loader.exec_module(demo_check)

LEAD = demo_check.LEAD
TX_REF = "txr_abcdefghijklmnop"


def num(value, ref="ev_000000000001"):
    return {"value": value, "unit": "eur", "evidence_ref": ref, "display": f"€{value}"}


class Stub:
    """The service's demo path, with switches for the failure cases."""

    def __init__(self, saving=45.91, off=(), hero_after_needed=180.26, undo="ok", reconciles=True, ask_429=False,
                 malformed_whatif=False, needed_delay=0.0, label_list=False, effect="absent"):
        self.effect = effect               # absent | null | match | mismatch | no_text (#382, #485)
        self.needed_delay = needed_delay   # a slow "Needed", applied after the delay (maybe after the undo)
        self.label_list = label_list
        self.saving = saving
        self.off = set(off)
        self.hero_after_needed = hero_after_needed
        self.undo = undo                  # ok | 500 | drop
        self.reconciles = reconciles
        self.ask_429 = ask_429
        self.ask_warnings: tuple | list = ()   # warnings of the /api/ask answers (#244)
        self.malformed_whatif = malformed_whatif
        self.state = "pending"
        self.paths: list[str] = []

    def overview(self):
        pending = self.state == "pending"
        items = [{"key": "regular_essentials", "amount": num(1889.04, "ev_000000000002")},
                 {"key": "unexpected_necessities", "amount": num(341.08 if pending else 521.15, "ev_000000000003")},
                 {"key": "everyday_spending", "amount": num(600.41, "ev_000000000004")}]
        if pending:
            items.append({"key": "unclassified", "amount": num(180.07, "ev_000000000005")})
        reviews = [{"type": "review", "tx_ref": TX_REF, "amount": num(1080.42, "ev_000000000006"),
                    "current_basket": {"key": "unclassified"}}] if pending else []
        hero_value = 221.58 if pending else self.hero_after_needed
        return {"customer_id": LEAD, "hero": {"type": "metric", "primary": num(hero_value, "ev_000000000001")},
                "cards": [{"type": "breakdown", "evidence_ref": "ev_000000000007", "items": items}],
                "reviews": reviews}

    def handle(self, method, path, query, body):
        self.paths.append(f"{method} {path}")
        not_found = (404, {"error": {"code": "not_found", "message": "No such route."}})
        if path == "/healthz":
            return 200, {"status": "ok"}
        if path == "/readyz":
            return 200, {"status": "ready"}
        if path == "/api/personas":
            return 200, {"personas": [{"customer_id": c} for c in demo_check.ref("personas")]}
        if path == f"/api/overview/{LEAD}":
            return 200, self.overview()
        if path.startswith("/api/overview/"):
            return 404, {"error": {"code": "customer_not_found", "message": "We couldn't find this customer."}}
        if path.startswith("/api/evidence/"):
            if query.get("customer_id") == [LEAD]:
                return 200, {"evidence_ref": path.rsplit("/", 1)[1], "rows": [], "reconciles": self.reconciles}
            return 403, {"error": {"code": "evidence_forbidden", "message": "Not yours."}}
        if path == "/api/whatif" and method == "POST":
            if self.malformed_whatif:
                return 200, ["not", "an", "object"]
            return 200, {"baseline_per_month": num(229.56), "saving_per_month": num(self.saving)}
        if path == "/api/baskets/label" and method == "POST" and "label" not in self.off:
            if body.get("tx_ref") != TX_REF:
                return 404, {"error": {"code": "tx_ref_not_found", "message": "No such purchase."}}
            if body.get("basket") is None:
                if self.undo == "500":
                    return 500, {"error": {"code": "internal", "message": "Something went wrong."}}
                if self.undo == "drop":
                    return "drop", None
                self.state = "pending"
                return 200, {"review_state": "pending", "changes": []}
            if self.label_list:
                return 200, ["not", "an", "object"]
            if self.needed_delay:
                import time
                time.sleep(self.needed_delay)
            self.state = "answered"
            body = {"review_state": "answered",
                    "changes": [{"key": "safe_to_spend", "before": num(221.58), "after": num(180.26)}]}
            if self.effect == "null":
                body["effect"] = None
            elif self.effect != "absent":
                after = 999.0 if self.effect == "mismatch" else 180.26
                text = "" if self.effect == "no_text" else "Your safe to spend this week goes from €221.58 to €180.26."
                body["effect"] = {"items": [{"key": "safe_to_spend", "before": num(221.58), "after": num(after)}],
                                  "text": text, "text_rendered": text, "numbers": {}}
            return 200, body
        if path == "/api/ask" and method == "POST" and self.ask_429:
            return 429, {"error": {"code": "rate_limited", "message": "Too many requests."}}
        if path == "/api/ask" and method == "POST" and "ask" not in self.off:
            return 200, {"outcome": "answered", "warnings": list(self.ask_warnings), "cited": ["n1"],
                         "numbers": {"n1": num(180.26, "ev_000000000008")}}
        return not_found


@pytest.fixture
def serve():
    servers = []

    def start(stub: Stub) -> str:
        class Handler(BaseHTTPRequestHandler):
            def _reply(self, method):
                url = urlparse(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                status, payload = stub.handle(method, url.path, parse_qs(url.query), body)
                if status == "drop":  # close the connection without an answer
                    self.close_connection = True
                    self.connection.shutdown(2)
                    return
                raw = json.dumps(payload).encode()
                self.send_response(status)
                if status == 429:
                    self.send_header("Retry-After", "37")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self._reply("GET")

            def do_POST(self):
                self._reply("POST")

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def run(url, *args):
    lines: list[str] = []
    code = demo_check.main(["--base-url", url, *args], out=lines.append)
    return code, lines


def line(lines, name):
    return next(row for row in lines if row.startswith(name))


def test_every_stage_passes(serve):
    stub = Stub()
    code, lines = run(serve(stub))
    assert code == 0, "\n".join(lines)
    stages = [row for row in lines if not row.startswith("--")]
    assert len(stages) == 11 and all(" PASS " in row for row in stages), "\n".join(lines)
    assert stub.state == "pending"
    assert stub.paths.count("POST /api/ask") == 4


def test_one_wrong_number_fails_with_expected_and_received(serve):
    code, lines = run(serve(Stub(saving=45.92)), "--no-ask")
    row = line(lines, "what-if")
    assert code == 1 and " FAIL " in row and "expected 45.91" in row and "got 45.92" in row
    assert sum(" FAIL " in row for row in lines) == 1


def test_a_stage_that_is_not_deployed(serve):
    stub = Stub(off={"label", "ask"})
    stub.state = "answered"  # no review card: the route is probed with an unknown tx_ref, nothing written
    url = serve(stub)
    code, lines = run(url)
    assert code == 0
    assert " NOT DEPLOYED " in line(lines, "spike review")
    assert all(" NOT DEPLOYED " in row for row in lines if row.startswith("ask:"))
    assert run(url, "--require-all")[0] == 1


def test_the_review_is_left_pending_when_a_step_fails(serve):
    stub = Stub(hero_after_needed=999.0)
    code, lines = run(serve(stub), "--no-ask")
    row = line(lines, "spike review")
    assert code == 1 and " FAIL " in row and "hero after Needed" in row
    assert stub.state == "pending"
    assert stub.paths.count("POST /api/baskets/label") == 2  # the answer and its undo


def test_no_ask_and_ask_limit(serve):
    stub = Stub()
    url = serve(stub)
    code, lines = run(url, "--no-ask")
    assert code == 0 and "POST /api/ask" not in stub.paths
    assert all(" SKIPPED " in row for row in lines if row.startswith("ask:"))
    code, lines = run(url, "--ask-limit", "1")
    assert code == 0 and stub.paths.count("POST /api/ask") == 1


@pytest.mark.parametrize("mode", ["500", "drop"])
@pytest.mark.parametrize("earlier_failure", [False, True])
def test_a_failed_undo_is_loud_whatever_happened_before(serve, mode, earlier_failure):
    # Review of PR #180: the undo is judged in every case; a failed one names the persona, the tx_ref,
    # the status and the repair commands, and the run exits 1.
    stub = Stub(undo=mode, hero_after_needed=999.0 if earlier_failure else 180.26)
    code, lines = run(serve(stub), "--no-ask")
    text = "\n".join(lines)
    assert code == 1
    loud = next(row for row in lines if row.startswith("UNDO FAILED"))
    assert f"{LEAD} may be left answered" in loud and TX_REF in loud
    assert ("status 500" in loud) if mode == "500" else ("request failed" in loud)
    assert "python core/scripts/reset_reviews.py CUST00860" in text and "curl -s -X POST" in text
    assert " FAIL " in line(lines, "spike review")
    if earlier_failure:
        assert "hero after Needed" in line(lines, "spike review")


def test_evidence_that_does_not_reconcile_fails(serve):
    code, lines = run(serve(Stub(reconciles=False)), "--no-ask")
    assert code == 1 and "reconciles" in line(lines, "evidence refs") and " FAIL " in line(lines, "evidence refs")
    assert run(serve(Stub(reconciles=None)), "--no-ask")[0] == 0   # null: nothing to add up


def test_a_malformed_response_fails_its_stage_and_the_run_goes_on(serve):
    code, lines = run(serve(Stub(malformed_whatif=True)), "--no-ask")
    assert code == 1 and " FAIL " in line(lines, "what-if")
    assert " PASS " in line(lines, "spike review")              # the later stages still ran


def test_a_429_stops_the_questions_with_retry_after(serve):
    stub = Stub(ask_429=True)
    code, lines = run(serve(stub))
    first = line(lines, "ask: Where did my money go?")
    assert code == 1 and " FAIL " in first and "Retry-After 37" in first
    assert stub.paths.count("POST /api/ask") == 1
    assert all(" SKIPPED " in row for row in lines if row.startswith("ask:") and "Where did" not in row)


def test_not_deployed_lines_name_the_route_and_status(serve):
    stub = Stub(off={"label", "ask"})
    stub.state = "answered"
    code, lines = run(serve(stub))
    assert "POST /api/baskets/label -> 404" in line(lines, "spike review")
    assert "POST /api/ask -> 404" in line(lines, "ask: Where did my money go?")


def test_the_time_limit_ends_the_run(serve):
    code, lines = run(serve(Stub()), "--no-ask", "--time-limit", "0")
    assert code == 1 and "time limit" in line(lines, "health and readiness")


def test_a_late_needed_after_the_undo_is_caught(serve, monkeypatch):
    # Second review of PR #180: "Needed" times out on this side, the undo answers 200 pending, and the
    # server applies "Needed" afterwards. The re-check after the undo sees the card gone and is loud.
    monkeypatch.setattr(demo_check, "TIMEOUT_S", 0.5)
    monkeypatch.setattr(demo_check, "RECHECK_WAIT_S", 1.5)
    stub = Stub(needed_delay=1.2)
    code, lines = run(serve(stub), "--no-ask")
    assert code == 1
    loud = next(row for row in lines if row.startswith("UNDO FAILED"))
    assert TX_REF in loud and "not back" in loud
    assert "python core/scripts/reset_reviews.py CUST00860" in "\n".join(lines)


def test_the_review_stage_does_not_start_without_enough_time(serve, monkeypatch):
    monkeypatch.setattr(demo_check, "REVIEW_MIN_LEFT_S", 3600)
    stub = Stub()
    code, lines = run(serve(stub), "--no-ask")
    assert code == 1 and "not started" in line(lines, "spike review")
    assert "POST /api/baskets/label" not in stub.paths and stub.state == "pending"


def test_a_label_answer_that_is_not_an_object_says_so(serve):
    code, lines = run(serve(Stub(label_list=True)), "--no-ask")
    assert code == 1 and "not a JSON object" in line(lines, "spike review")



# ---- #244: --expect-model --------------------------------------------------------------------------------

@pytest.mark.parametrize("warnings, option, passes", [
    ([], "any", True), (["llm_unavailable"], "any", True),
    ([], "on", True), (["llm_unavailable"], "on", False),
    (["llm_unavailable"], "off", True), ([], "off", False),
])
def test_the_ask_checks_require_answered_and_the_warning_follows_expect_model(serve, warnings, option, passes):
    stub = Stub()
    stub.ask_warnings = warnings
    code, lines = run(serve(stub), "--expect-model", option)
    asks = [row for row in lines if row.startswith("ask:")]
    assert len(asks) == 4 and all((" PASS " in row) == passes for row in asks), "\n".join(lines)
    assert (code == 0) == passes


# ---- #485: the effect branch of the spike review (#382) -----------------------------------------------------

@pytest.mark.parametrize("effect,passes,why", [
    ("absent", True, ""), ("null", True, ""),                         # no effect: the branch is skipped
    ("match", True, ""),                                              # the overview's number and a text
    ("mismatch", False, "effect safe_to_spend after Needed"),        # another number than the hero
    ("no_text", False, "effect text after Needed"),
])
def test_the_effect_is_checked_when_present_and_the_undo_still_runs(serve, effect, passes, why):
    stub = Stub(effect=effect)
    code, lines = run(serve(stub), "--no-ask")
    row = line(lines, "spike review")
    assert (" PASS " in row) is passes and (code == 0) is passes, row
    assert why in row
    assert stub.state == "pending" and stub.paths.count("POST /api/baskets/label") == 2   # the undo ran
