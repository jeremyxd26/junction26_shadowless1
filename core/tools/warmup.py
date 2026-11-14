"""Warm the tool cache for the four demo personas, so the demo never waits for the shared database.

    python -m core.tools.warmup                      # all four personas, English and Finnish
    python -m core.tools.warmup --lang en --customers CUST00860
    python -m core.tools.warmup --list               # the plan, no database

Run it at the end of a deploy (after the service restart) and by hand, inside the service container,
so it writes the sqlite file the service reads (/srv/var/cache, the persistent var/ of #78):
`docker exec <service container> python -m core.tools.warmup || true`. It must never fail a deploy: a
failed call is reported and skipped, and the exit code is only informative. It fills the disk layer of
the tool cache (core/tools/cache.py, TOOL_CACHE=disk), which the service reads on its first request. For each persona and language it calls the tools of the overview and of the four questions of
the challenge brief, with the same arguments the overview and the answer pipeline's question rules use,
and prints the time and the source (computed or already cached) of every call. A cached result whose
evidence rows are gone from coach_evidence (a reset database) is treated as a miss and computed again:
one query per persona checks the refs.

Limits: only the customers of core/config/personas.yaml, never more; one database connection with the
tools' 60 s statement timeout; the tools write their evidence specs, as on any request.

Model answers: the demo's scripted questions should also be sent once through POST /api/ask, so their
answers come from the model-response cache. That needs the answer pipeline (#59) and the Gemini adapter
(#66); until both are merged ANSWERS_ENABLED is False and --answers refuses. The requests are already
listed by answer_requests().
"""

from __future__ import annotations

import argparse
import importlib
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from core.tools import config
from core.tools.cache import ToolCache, setting
from core.tools.context import ToolContext

ROOT = Path(__file__).resolve().parents[2]
PERSONAS_FILE = ROOT / "core" / "config" / "personas.yaml"
LANGUAGES = ("en", "fi")
ANSWERS_ENABLED = False   # switch on once #59 (POST /api/ask) and #66 (model adapter) are merged


@dataclass(frozen=True)
class WarmCall:
    purpose: str
    module: str
    function: str
    args_model: str
    args: dict[str, Any]


# The overview's tools (core/app/api/overview.py) and the tools behind the four brief questions, with
# the arguments of the answer pipeline's question rules (core/agent/rules.py on #59). Arguments are
# validated before the key is made, so {} and the explicit defaults share one entry.
CALLS: tuple[WarmCall, ...] = (
    WarmCall("overview card; Where did my money go?", "core.tools.baskets", "get_basket_breakdown",
             "GetBasketBreakdownArgs", {"period": {"preset": "last_6_months"}}),
    WarmCall("overview bills card", "core.tools.bills", "get_recurring_bills", "GetRecurringBillsArgs",
             {"include_income": False}),
    WarmCall("bills question", "core.tools.bills", "get_recurring_bills", "GetRecurringBillsArgs", {}),
    WarmCall("overview hero; What can I safely spend this week?", "core.tools.safe_to_spend",
             "get_safe_to_spend", "GetSafeToSpendArgs", {}),
    WarmCall("overview safe-to-save card (#165)", "core.tools.safe_to_save",
             "get_safe_to_save", "GetSafeToSaveArgs", {}),
    WarmCall("What kind of spender am I? (profile)", "core.tools.profile", "get_spender_profile",
             "GetSpenderProfileArgs", {}),
    WarmCall("What kind of spender am I? (peers)", "core.tools.peer", "get_peer_benchmark",
             "GetPeerBenchmarkArgs", {"metric": "spend_total"}),
    WarmCall("How could I save more? (dining out -20%)", "core.tools.what_if", "run_what_if", "RunWhatIfArgs",
             {"selection": {"kind": "category", "value": "Restaurants"}, "cut_pct": 20}),
)

# The partner's four questions (the same pairs as SUGGESTED_QUESTIONS in core/app/api/texts.py).
BRIEF_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("Where did my money go?", "Mihin rahani menivät?"),
    ("What kind of spender am I?", "Millainen kuluttaja olen?"),
    ("What can I safely spend this week?", "Paljonko voin turvallisesti käyttää tällä viikolla?"),
    ("How could I save more?", "Miten voisin säästää enemmän?"),
)


@dataclass(frozen=True)
class Row:
    customer_id: str
    language: str
    tool: str
    source: str          # "tool" (computed now), "memory", "disk", "missing" or "error <Class>"
    ms: int


def persona_ids() -> list[str]:
    data = yaml.safe_load(PERSONAS_FILE.read_text(encoding="utf-8"))
    return [p["customer_id"] for p in data["personas"]]


def available_calls(calls: Iterable[WarmCall] = CALLS) -> list[tuple[WarmCall, Callable | None, type | None]]:
    """Each call with its tool, or None when the tool module is not merged yet (like #59's discovery)."""
    out = []
    for call in calls:
        try:
            module = importlib.import_module(call.module)
            out.append((call, getattr(module, call.function), getattr(module, call.args_model)))
        except (ImportError, AttributeError):
            out.append((call, None, None))
    return out


def answer_requests(customers: Iterable[str], languages: Iterable[str] = LANGUAGES) -> list[dict[str, str]]:
    """The POST /api/ask requests of the demo script: every brief question for every persona and language."""
    lang_index = {"en": 0, "fi": 1}
    return [{"customer_id": c, "language": lang, "message": pair[lang_index[lang]]}
            for c in customers for lang in languages for pair in BRIEF_QUESTIONS]


EVIDENCE_SQL = "SELECT ref FROM coach_evidence WHERE customer_id = %s AND ref = ANY(%s)"


def missing_evidence(conn: Any, customer_id: str, refs: set[str]) -> set[str]:
    """The refs of cached results whose evidence row is gone (a reset database): one query per persona."""
    if not refs or conn is None:
        return set()
    found = {row[0] for row in conn.execute(EVIDENCE_SQL, (customer_id, sorted(refs))).fetchall()}
    return refs - found


def warm(cache: ToolCache, conn: Any, customers: list[str], languages: Iterable[str], as_of: date,
         out: Callable[[str], None] = print, calls: Iterable[WarmCall] = CALLS) -> list[Row]:
    allowed = set(persona_ids())
    if not set(customers) <= allowed:
        raise ValueError("the warm-up runs for the demo personas only")
    tools = available_calls(calls)
    rows: list[Row] = []

    def report(customer_id: str, lang: str, tool: str, source: str, t0: float) -> None:
        row = Row(customer_id, lang, tool, source, round(1000 * (time.perf_counter() - t0)))
        rows.append(row)
        out(f"{row.customer_id}  {row.language}  {row.tool:<22} {row.source:<10} {row.ms:>7} ms")

    def prepare(ctx: ToolContext, call: WarmCall, fn: Callable, args_model: type) -> Any:
        t0 = time.perf_counter()
        try:
            prepared = cache.prepare(call.function, args_model, fn, ctx, call.args)
        except Exception as exc:  # noqa: BLE001 - report and go on with the next call
            report(ctx.customer_id, ctx.language, call.function, f"error {type(exc).__name__}", t0)
            return None
        report(ctx.customer_id, ctx.language, call.function, prepared.source, t0)
        return prepared

    for customer_id in customers:
        # One transactions read and one label read per customer: the label set and the key made from it
        # travel together into every language, so no language reads the labels again.
        history, labels_by_tx, labels_key = None, None, None
        hits = []                          # cached results of this persona, checked against coach_evidence
        for lang in languages:
            ctx = ToolContext(customer_id=customer_id, as_of=as_of, conn=conn, language=lang)
            ctx._history, ctx._labels, ctx.labels_key = history, labels_by_tx, labels_key
            cache.ensure_labels_key(ctx)
            for call, fn, args_model in tools:
                if fn is None:
                    report(customer_id, lang, call.function, "missing", time.perf_counter())
                    continue
                prepared = prepare(ctx, call, fn, args_model)
                if prepared is not None and prepared.hit:
                    hits.append((ctx, call, fn, args_model, prepared))
            history, labels_by_tx, labels_key = ctx._history, ctx._labels, ctx.labels_key
        refs = {ref for *_, p in hits for ref in p.entry.result.evidence}
        try:
            gone = missing_evidence(conn, customer_id, refs)
        except Exception as exc:  # noqa: BLE001 - one persona's failed check never stops the others
            out(f"{customer_id}  evidence check failed ({type(exc).__name__}); cached results kept")
            gone = set()
        for ctx, call, fn, args_model, p in hits:
            if gone & set(p.entry.result.evidence):   # evidence row gone: a miss, computed again
                cache.drop(p.key)
                t0 = time.perf_counter()
                try:
                    cache.prepare(call.function, args_model, fn, ctx, call.args)
                    report(customer_id, ctx.language, call.function, "recomputed", t0)
                except Exception as exc:  # noqa: BLE001
                    report(customer_id, ctx.language, call.function, f"error {type(exc).__name__}", t0)
    return rows


def _as_of(text: str | None) -> date:
    return date.fromisoformat(text or setting("DEMO_TODAY") or config.DEFAULT_AS_OF.isoformat())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m core.tools.warmup", description=__doc__.splitlines()[0])
    parser.add_argument("--lang", default=",".join(LANGUAGES), help="comma-separated: en,fi")
    parser.add_argument("--customers", help="comma-separated subset of the personas (default: all four)")
    parser.add_argument("--as-of", help="DEMO_TODAY (default: the DEMO_TODAY setting, else 2026-09-30)")
    parser.add_argument("--list", action="store_true", help="print the plan and exit; no database")
    parser.add_argument("--answers", action="store_true", help="also warm the model answers (not available yet)")
    opts = parser.parse_args(argv)

    personas = persona_ids()
    customers = opts.customers.split(",") if opts.customers else personas
    outside = [c for c in customers if c not in personas]
    if outside:
        parser.error(f"not a demo persona: {', '.join(outside)} (the warm-up runs for the personas only)")
    languages = [lang for lang in opts.lang.split(",") if lang]
    if not set(languages) <= set(LANGUAGES):
        parser.error("--lang takes en and/or fi")
    if opts.answers and not ANSWERS_ENABLED:
        parser.error("--answers needs the answer pipeline (#59) and the model adapter (#66); not merged yet")
    as_of = _as_of(opts.as_of)

    if opts.list:
        for call, fn, _ in available_calls():
            print(f"{call.function:<22} {call.args}  [{call.purpose}]{'' if fn else '  (tool not merged yet)'}")
        print(f"customers {','.join(customers)}; languages {','.join(languages)}; as_of {as_of}")
        return 0

    cache = ToolCache.from_env()
    if cache.mode != "disk":
        print(f"TOOL_CACHE is {cache.mode}: the service cannot read this warm-up; set TOOL_CACHE=disk", file=sys.stderr)
        return 2

    from core.tools import db

    try:
        conn = db.connect()   # one connection, statement_timeout 60 s; the message never holds the URL
    except db.DatabaseConnectError as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 2
    try:
        db.ensure_evidence_table(conn)
        t0 = time.perf_counter()
        rows = warm(cache, conn, customers, languages, as_of)
    finally:
        conn.close()
    errors = [r for r in rows if r.source.startswith("error")]
    computed = sum(r.source == "tool" for r in rows)
    recomputed = sum(r.source == "recomputed" for r in rows)
    cached = sum(r.source in ("memory", "disk") for r in rows)
    missing = sum(r.source == "missing" for r in rows)
    print(f"warmed {len(customers)} personas x {len(languages)} languages in {time.perf_counter() - t0:.1f} s: "
          f"{computed} computed, {cached} already cached ({recomputed} of them recomputed: evidence missing), "
          f"{missing} tools not merged yet, {len(errors)} errors; "
          f"cache {cache.directory / 'tools.sqlite3'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
