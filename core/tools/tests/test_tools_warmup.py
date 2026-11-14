"""Tests for the warm-up command (core/tools/warmup.py). No database: the calls are fake tools."""

from datetime import date

import pytest

from core.tools import warmup
from core.tools.cache import ToolCache
from core.tools.models import Args, ToolResult
from core.tools.warmup import WarmCall

PERSONAS = ["CUST00860", "CUST00493", "CUST00349", "CUST00849"]


class EmptyArgs(Args):
    pass


calls_made: list[tuple[str, str]] = []


def fake_tool(ctx, args):
    calls_made.append((ctx.customer_id, ctx.language))
    return ToolResult(tool="fake_tool", data=None, model_view={"tool": "fake_tool"})


FAKE_CALLS = (
    WarmCall("fake", __name__, "fake_tool", "EmptyArgs", {}),
    WarmCall("not merged yet", "core.tools.no_such_module", "get_nothing", "NothingArgs", {}),
)


def test_the_personas_are_the_four_of_personas_yaml():
    assert warmup.persona_ids() == PERSONAS


def test_warm_runs_every_call_once_and_then_serves_hits(monkeypatch):
    calls_made.clear()
    cache = ToolCache(mode="memory")
    monkeypatch.setattr("core.tools.labels.basket_labels", lambda *a, **k: {})   # no labels, no read
    lines: list[str] = []
    rows = warmup.warm(cache, None, PERSONAS, ["en", "fi"], date(2026, 9, 30), out=lines.append, calls=FAKE_CALLS)
    assert len(rows) == 4 * 2 * 2 and len(lines) == len(rows)
    assert sorted(calls_made) == sorted((c, lang) for c in PERSONAS for lang in ("en", "fi"))
    assert {r.source for r in rows if r.tool == "fake_tool"} == {"tool"}
    assert {r.source for r in rows if r.tool == "get_nothing"} == {"missing"}   # skipped, like #59's discovery
    again = warmup.warm(cache, None, PERSONAS, ["en"], date(2026, 9, 30), out=lambda _: None, calls=FAKE_CALLS)
    assert {r.source for r in again if r.tool == "fake_tool"} == {"memory"}
    assert len(calls_made) == 8                                                  # nothing recomputed


def test_warm_refuses_customers_outside_the_personas():
    with pytest.raises(ValueError, match="personas only"):
        warmup.warm(ToolCache(mode="memory"), None, ["CUST00001"], ["en"], date(2026, 9, 30), calls=FAKE_CALLS)
    with pytest.raises(SystemExit):
        warmup.main(["--customers", "CUST00860,CUST00001", "--list"])


def test_cli_rejects_answers_until_the_pipeline_is_merged():
    assert warmup.ANSWERS_ENABLED is False
    with pytest.raises(SystemExit):
        warmup.main(["--answers", "--list"])


def test_cli_lists_the_plan_without_a_database(capsys):
    assert warmup.main(["--list", "--lang", "en"]) == 0
    text = capsys.readouterr().out
    for name in ("get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "run_what_if"):
        assert name in text
    assert "CUST00860,CUST00493,CUST00349,CUST00849" in text


def test_cli_needs_the_disk_layer(monkeypatch, capsys):
    monkeypatch.setenv("TOOL_CACHE", "memory")
    assert warmup.main(["--lang", "en"]) == 2
    assert "TOOL_CACHE=disk" in capsys.readouterr().err


def test_the_brief_questions_are_the_apps_suggested_questions():
    from core.app.api import texts

    assert list(warmup.BRIEF_QUESTIONS) == list(texts.SUGGESTED_QUESTIONS)


def test_answer_requests_cover_the_demo_script():
    requests = warmup.answer_requests(PERSONAS)
    assert len(requests) == 4 * 2 * 4
    assert {"customer_id": "CUST00860", "language": "fi", "message": "Millainen kuluttaja olen?"} in requests
    assert all(set(r) == {"customer_id", "language", "message"} for r in requests)


def test_warm_calls_use_the_pipelines_arguments():
    by_tool = {c.function: c.args for c in warmup.CALLS if c.function != "get_recurring_bills"}
    assert by_tool["get_basket_breakdown"] == {"period": {"preset": "last_6_months"}}
    assert by_tool["get_peer_benchmark"] == {"metric": "spend_total"}
    assert by_tool["run_what_if"] == {"selection": {"kind": "category", "value": "Restaurants"}, "cut_pct": 20}
    bills = [c.args for c in warmup.CALLS if c.function == "get_recurring_bills"]
    assert bills == [{"include_income": False}, {}]           # the overview's card and the bills question



def evidence_tool(ctx, args):
    calls_made.append((ctx.customer_id, ctx.language))
    ref = f"ev_{ctx.customer_id[-3:]}{ctx.language}000000"[:15]
    return ToolResult(tool="evidence_tool", data=None, evidence=[ref], model_view={"tool": "evidence_tool"})


class EvidenceConn:
    """Answers the warm-up's one coach_evidence query per persona with the refs that still exist."""

    def __init__(self, existing):
        self.existing = set(existing)
        self.queries = 0

    def execute(self, sql, params=None):
        self.queries += 1
        customer_id, refs = params
        rows = [(r,) for r in refs if r in self.existing]

        class _Res:
            def fetchall(self):
                return rows
        return _Res()


def test_cached_results_whose_evidence_is_gone_are_computed_again(monkeypatch):
    calls_made.clear()
    cache = ToolCache(mode="memory")
    monkeypatch.setattr("core.tools.labels.basket_labels", lambda *a, **k: {})   # no labels, no read
    calls = (WarmCall("evidence", __name__, "evidence_tool", "EmptyArgs", {}),)
    warmup.warm(cache, None, ["CUST00860"], ["en", "fi"], date(2026, 9, 30), out=lambda _: None, calls=calls)
    assert len(calls_made) == 2
    conn = EvidenceConn(existing={"ev_860en000000"})                  # the fi result's evidence is gone
    rows = warmup.warm(cache, conn, ["CUST00860"], ["en", "fi"], date(2026, 9, 30), out=lambda _: None,
                       calls=calls)
    assert conn.queries == 1                                           # one query for the persona
    assert [(r.language, r.source) for r in rows] == [("en", "memory"), ("fi", "memory"), ("fi", "recomputed")]
    assert calls_made[-1] == ("CUST00860", "fi") and len(calls_made) == 3



def test_a_failed_evidence_check_does_not_stop_the_other_personas(monkeypatch):
    calls_made.clear()
    cache = ToolCache(mode="memory")
    monkeypatch.setattr("core.tools.labels.basket_labels", lambda *a, **k: {})   # no labels, no read
    calls = (WarmCall("evidence", __name__, "evidence_tool", "EmptyArgs", {}),)
    two = ["CUST00860", "CUST00493"]
    warmup.warm(cache, None, two, ["en"], date(2026, 9, 30), out=lambda _: None, calls=calls)

    class BrokenConn:
        def execute(self, sql, params=None):
            raise RuntimeError("database went away")

    lines: list[str] = []
    rows = warmup.warm(cache, BrokenConn(), two, ["en"], date(2026, 9, 30), out=lines.append, calls=calls)
    assert [r.source for r in rows] == ["memory", "memory"]            # both personas still served
    assert sum("evidence check failed (RuntimeError)" in line for line in lines) == 2



probe_seen: list[tuple] = []


def probe_tool(ctx, args):
    from core.tools import labels
    from core.tools.cache import labels_key_of

    probe_seen.append((ctx.language, ctx.labels_key, labels_key_of(labels.for_context(ctx))))
    return ToolResult(tool="probe_tool", data=None, model_view={})


def test_a_label_write_between_two_languages_never_stores_a_value_under_another_key(monkeypatch):
    """The reviewer's probe of #213: the key and the label set travel together into the next language;
    a label write after the first read changes neither the key nor the tool's labels of that persona."""
    from core.tools import labels

    reads = []

    def basket_labels(conn, cid, as_of, now=None, viewer=None):
        reads.append(cid)
        return {} if len(reads) == 1 else {5: "everyday_spending"}   # a label write lands after the first read

    monkeypatch.setattr(labels, "basket_labels", basket_labels)
    probe_seen.clear()
    calls = (WarmCall("probe", __name__, "probe_tool", "EmptyArgs", {}),)
    warmup.warm(ToolCache(mode="memory"), None, ["CUST00860"], ["en", "fi"], date(2026, 9, 30),
                out=lambda _: None, calls=calls)
    assert [lang for lang, _, _ in probe_seen] == ["en", "fi"]
    assert all(key == tool_labels for _, key, tool_labels in probe_seen)     # the key is the tool's labels
    assert reads == ["CUST00860"]                                             # one label read per persona


def test_a_preset_key_without_its_labels_is_never_trusted(monkeypatch):
    from core.tools import labels
    from core.tools.cache import labels_key_of
    from core.tools.context import ToolContext

    monkeypatch.setattr(labels, "basket_labels", lambda conn, cid, as_of, now=None, viewer=None: {5: "everyday_spending"})
    ctx = ToolContext(customer_id="CUST00860", as_of=date(2026, 9, 30), conn=None)
    ctx.labels_key = "a key from another context"
    ToolCache(mode="memory").ensure_labels_key(ctx)
    assert ctx.labels_key == labels_key_of({5: "everyday_spending"}) and ctx._labels == {5: "everyday_spending"}
