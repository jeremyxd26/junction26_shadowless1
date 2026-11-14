"""The answer pipeline through the tool cache (#86): a repeated question is answered from the cache with
the same events and the tool runs once (a lane still takes its connection first, by design; a cached
result runs no SQL on it). No database."""

from __future__ import annotations

import logging
from decimal import Decimal

from agent_fakes import AUG, FakeArgs, FakeData, fake_spending, run

from core.agent.model import FunctionCall, ScriptedModel
from core.agent.orchestrator import AskRequest, LabelSteps
from core.agent.registry import Registry, ToolSpec
from core.tools.formatting import display
from core.tools.models import Card, Number, ToolResult, Unit

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


# ---- viewers (#144, #253, #283): the answer's label state is the viewer's, and so is its cache key ----

SPIKE = 606016   # the lead persona's spike purchase
A, B, C = "a" * 64, "b" * 64, "c" * 64
SAFE = [FunctionCall("fake_safe", {}), FunctionCall("finish")]
SAFE_TEXT = {"language": "en", "text": "You can safely spend {{n1}}.", "cited": ["n1"], "lesson_key": None}


def viewer_steps(answers: dict[str, str]) -> LabelSteps:
    """The overview's label step as a fake: a viewer who answered sees the spike in that basket, anyone
    else sees it pending (`unclassified`), as reviews.ensure_pending_for gives each viewer their set."""
    def establish(ctx):
        ctx._labels = {SPIKE: answers.get(ctx.viewer, "unclassified")}
        return None
    return LabelSteps(establish=establish, card=lambda ctx, review: None, enabled=lambda: True)


def safe_registry(calls):
    """Stands in for get_safe_to_spend: 180.26 when the spike is a "Needed" purchase, 221.58 while it is
    pending (the lead persona's two values)."""
    def tool(ctx, args):
        value = Decimal("180.26") if ctx._labels == {SPIKE: "unexpected_necessities"} else Decimal("221.58")
        calls.append((ctx.viewer, str(value)))
        n = ctx.numbers.register(Number(value=float(value), unit=Unit.EUR, period=AUG, method="safe_to_spend.x@1",
                                        evidence_ref=f"ev_safe{value}".replace(".", ""), label="Safe to spend",
                                        display=display(value, Unit.EUR, ctx.language)))
        card = Card(card_id="card_safe", type="metric", title="Safe to spend", evidence_ref=n.evidence_ref, primary=n)
        return ToolResult(tool="fake_safe", data={}, card=card, evidence=[n.evidence_ref],
                          model_view={"tool": "fake_safe", "safe": {"id": n.id, "value": n.value, "unit": "eur",
                                                                   "label": n.label}, "notes": []})

    reg = Registry()
    reg.register(ToolSpec("fake_safe", "Safe to spend.", FakeArgs, tool, ("Working", "Lasken")))
    return reg


def ask_as(make_pipeline, calls, data, viewer):
    pipe = make_pipeline(ScriptedModel(plans=[SAFE], drafts=[SAFE_TEXT]), safe_registry(calls), data)
    pipe.labels = viewer_steps({A: "unexpected_necessities"})       # A answered "Needed"; B and C did not
    events = []
    pipe.run(AskRequest(customer_id="CUST00860", message="What can I safely spend this week?", language="en",
                        viewer=viewer), lambda e, p: events.append((e, p)))
    return [p["card"]["primary"]["value"] for e, p in events if e == "card"]


def test_two_viewers_with_different_answers_get_their_own_cached_answers(make_pipeline, tool_cache_off,
                                                                         monkeypatch, caplog):
    """A answered the spike review "Needed": A's answers use A's entries (180.26). B has not answered: B's
    answers 221.58, never A's numbers. C is in B's state and gets B's entry. The viewer is never in a key
    or a log line."""
    monkeypatch.setattr(tool_cache_off, "mode", "memory")
    caplog.set_level(logging.DEBUG)
    calls: list[tuple] = []
    data = FakeData()
    assert ask_as(make_pipeline, calls, data, A) == [180.26]
    assert ask_as(make_pipeline, calls, data, B) == [221.58]
    assert ask_as(make_pipeline, calls, data, A) == [180.26]       # from A's entry
    assert ask_as(make_pipeline, calls, data, C) == [221.58]       # from B's entry: same label set
    assert calls == [(A, "180.26"), (B, "221.58")]                  # the tool ran once per label set
    assert tool_cache_off.stats.misses == 2 and tool_cache_off.stats.hits == 2
    for viewer in (A, B, C):
        assert not [r for r in caplog.records if viewer in r.getMessage()]


def test_another_customer_never_gets_the_cached_result(make_pipeline, tool_cache_off, monkeypatch):
    monkeypatch.setenv("SPIKE_REVIEWS", "off")
    monkeypatch.setattr(tool_cache_off, "mode", "memory")
    calls: list[str] = []
    data = FakeData()
    run(make_pipeline(ScriptedModel(plans=[SPEND], drafts=[GOOD]), counting_registry(calls), data))
    run(make_pipeline(ScriptedModel(plans=[SPEND], drafts=[GOOD]), counting_registry(calls), data),
        customer_id="CUST00493")
    assert calls == ["CUST00860", "CUST00493"]
