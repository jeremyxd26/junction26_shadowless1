"""The answer pipeline through the tool cache (#86): a repeated question is answered from the cache with
the same events and the tool runs once (a lane still takes its connection first, by design; a cached
result runs no SQL on it). No database."""

from __future__ import annotations

from agent_fakes import FakeArgs, FakeData, fake_spending, run

from core.agent.model import FunctionCall, ScriptedModel
from core.agent.registry import Registry, ToolSpec

SPEND = [FunctionCall("fake_spending", {"category": "Restaurants"}), FunctionCall("finish")]
GOOD = {"language": "en", "text": "In August 2026 you spent {{n1}} on restaurants, over {{n2}} visits.",
        "cited": ["n1", "n2"], "lesson_key": None}


def counting_registry(calls):
    def tool(ctx, args):
        calls.append(ctx.customer_id)
        return fake_spending(ctx, args)

    reg = Registry()
    reg.register(ToolSpec("fake_spending", "Restaurants spending.", FakeArgs, tool, ("Looking", "Katson")))
    return reg


def answer_events(events):
    """The events without the per-answer ids (meta and done carry the conversation and answer ids)."""
    return [(e, {k: v for k, v in p.items() if k != "answer_id"}) for e, p in events if e != "meta"]


def test_a_repeated_question_is_served_from_the_cache(make_pipeline, tool_cache_off, monkeypatch):
    monkeypatch.setenv("SPIKE_REVIEWS", "off")      # no database here: no labels
    monkeypatch.setattr(tool_cache_off, "mode", "memory")
    calls: list[str] = []
    data = FakeData()
    first = run(make_pipeline(ScriptedModel(plans=[SPEND], drafts=[GOOD]), counting_registry(calls), data))
    second = run(make_pipeline(ScriptedModel(plans=[SPEND], drafts=[GOOD]), counting_registry(calls), data))
    assert calls == ["CUST00860"]                                    # the tool ran once
    assert tool_cache_off.stats.hits == 1 and tool_cache_off.stats.misses == 1
    assert answer_events(second) == answer_events(first)            # same cards, numbers, text and ids


def test_another_customer_never_gets_the_cached_result(make_pipeline, tool_cache_off, monkeypatch):
    monkeypatch.setenv("SPIKE_REVIEWS", "off")
    monkeypatch.setattr(tool_cache_off, "mode", "memory")
    calls: list[str] = []
    data = FakeData()
    run(make_pipeline(ScriptedModel(plans=[SPEND], drafts=[GOOD]), counting_registry(calls), data))
    run(make_pipeline(ScriptedModel(plans=[SPEND], drafts=[GOOD]), counting_registry(calls), data),
        customer_id="CUST00493")
    assert calls == ["CUST00860", "CUST00493"]
