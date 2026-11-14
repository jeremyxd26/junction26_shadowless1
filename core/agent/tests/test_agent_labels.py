"""The answer's label state (#196): established once per answer, as the overview does, before the model
plans; shared by every tool call; the pending review's card added by the server; counts in the audit;
and no model tool that can write a label (R6). No database (the database test is test_agent_labels_db.py)."""

from __future__ import annotations

import inspect
import sys
from types import SimpleNamespace

import pytest
from agent_fakes import AUG, FakeArgs, audit_records, fake_spending, registry, run

from core.agent.model import FunctionCall, ScriptedModel
from core.agent.orchestrator import MAX_CARDS, LabelSteps
from core.agent.registry import ToolSpec
from core.agent.toolset import default_registry
from core.tools import labels

GOOD = {"language": "en", "text": "In August 2026 you spent {{n1}}.", "cited": ["n1"], "lesson_key": None}
REVIEW_CARD = {"card_id": "card_review", "type": "review", "category": "Home & Tech", "tx_ref": "txr_abcdefghijklmnop"}


class Steps:
    """A fake of the overview's label functions that records what happened, in order."""

    def __init__(self, log: list[str], labels_=None, pending=SimpleNamespace(tx_id=606016), card=REVIEW_CARD):
        self.log = log
        self.labels = {606016: "unclassified", 1: "everyday_spending"} if labels_ is None else labels_
        self.pending = pending
        self.card_value = card

    def establish(self, ctx):
        self.log.append("establish")
        ctx._labels = self.labels
        return self.pending

    def card(self, ctx, review):
        self.log.append("card")
        return self.card_value

    def steps(self) -> LabelSteps:
        return LabelSteps(establish=self.establish, card=self.card, enabled=lambda: True)


class RecordingModel(ScriptedModel):
    def __init__(self, log, **kw):
        super().__init__(**kw)
        self.log = log

    def plan(self, request):
        self.log.append("plan")
        return super().plan(request)


def pipeline(make_pipeline, model, steps, reg=None):
    pipe = make_pipeline(model, reg=reg)
    pipe.labels = steps.steps()
    return pipe


@pytest.mark.parametrize("plan", [
    [FunctionCall("decline", {"kind": "out_of_scope"})],
    [FunctionCall("ask_clarifying_question", {"question": "Which month?", "options": []})],
    [FunctionCall("fake_spending", {}), FunctionCall("finish")],
])
def test_the_model_plan_cannot_change_whether_the_label_state_is_established(make_pipeline, plan):
    # The review is found or created at a fixed point of every answer, before the model plans (R6).
    log: list[str] = []
    run(pipeline(make_pipeline, RecordingModel(log, plans=[plan], drafts=[GOOD]), Steps(log)))
    assert log[:2] == ["establish", "plan"] and log.count("establish") == 1


def test_every_tool_call_shares_the_answers_labels_and_reads_none(make_pipeline, monkeypatch):
    from core.tools.cache import labels_key_of

    def no_read(*args, **kwargs):
        raise AssertionError("a tool call read the labels again")

    monkeypatch.setattr(labels, "basket_labels", no_read)  # the cache's key read goes through it too
    seen = []

    def spy(ctx, args):
        seen.append(ctx._labels)
        assert labels.for_context(ctx) is ctx._labels  # served from the context: no query (ctx.conn is a fake)
        assert ctx.labels_key == labels_key_of(ctx._labels)  # the tool cache's key, without a read
        return fake_spending(ctx, args)

    reg = registry(ToolSpec("second", "second", FakeArgs, spy, ("x", "x")))
    reg.tools["fake_spending"] = ToolSpec("fake_spending", "t", FakeArgs, spy, ("x", "x"))
    steps = Steps([])
    model = ScriptedModel(plans=[[FunctionCall("fake_spending", {}), FunctionCall("second", {}), FunctionCall("finish")]],
                          drafts=[GOOD])
    run(pipeline(make_pipeline, model, steps, reg=reg))
    assert len(seen) == 2 and all(s is steps.labels for s in seen)


SPIKE_TX = SimpleNamespace(id=606016, category="Home & Tech")


def _tool(name, fails=False):
    """A data tool that loads a history holding the spike's purchase (the card checks its category)."""
    def fn(ctx, args):
        if fails:
            raise RuntimeError("the tool failed")
        ctx._history = [SPIKE_TX]
        return fake_spending(ctx, args)
    return ToolSpec(name, name, FakeArgs, fn, ("x", "x"))


def test_the_pending_review_card_joins_a_safe_to_spend_or_basket_answer(make_pipeline):
    log: list[str] = []
    reg = registry(_tool("get_safe_to_spend"))
    model = ScriptedModel(plans=[[FunctionCall("get_safe_to_spend", {}), FunctionCall("finish")]], drafts=[GOOD])
    pipe = pipeline(make_pipeline, model, Steps(log), reg=reg)
    events = run(pipe)
    cards = [p["card"] for e, p in events if e == "card"]
    assert [c["card_id"] for c in cards] == ["card_test0001", "card_review"]
    names = [e for e, _ in events]
    assert names.index("card") < names.index("delta")              # before the answer text
    record = audit_records(pipe)[-1]
    assert record["cards"] == ["card_test0001", "card_review"]
    assert record["label_state"] == {"spike_reviews": "on", "labels": 1, "pending": 1}
    assert "606016" not in str(record["label_state"])               # counts only, never transaction ids


@pytest.mark.parametrize("args,attached", [({"category": "Restaurants"}, False), ({"category": "Home & Tech"}, True)])
def test_a_category_answer_gets_the_card_only_for_the_spikes_category(make_pipeline, args, attached):
    log: list[str] = []
    reg = registry(_tool("get_spending"))
    model = ScriptedModel(plans=[[FunctionCall("get_spending", args), FunctionCall("finish")]], drafts=[GOOD])
    events = run(pipeline(make_pipeline, model, Steps(log), reg=reg))
    assert ("card_review" in [p["card"]["card_id"] for e, p in events if e == "card"]) is attached
    assert ("card" in log) is attached   # review of #231: no card is built (no connection) when not sent



@pytest.mark.parametrize("args,attached", [({"category": "Restaurants"}, False), ({"category": "Home & Tech"}, True)])
def test_without_a_loaded_history_the_cards_own_category_decides(make_pipeline, args, attached):
    # Review of the #231 bridge: a what-if by category runs metric SQL only, and the label step reads the
    # history only when it creates a review, so the history is often not loaded. The card still joins
    # an answer about the spike's category (built, then its own category decides).
    log: list[str] = []
    reg = registry(ToolSpec("run_what_if", "what-if", FakeArgs, fake_spending, ("x", "x")))   # loads no history
    model = ScriptedModel(plans=[[FunctionCall("run_what_if", args), FunctionCall("finish")]], drafts=[GOOD])
    events = run(pipeline(make_pipeline, model, Steps(log), reg=reg))
    assert ("card_review" in [p["card"]["card_id"] for e, p in events if e == "card"]) is attached
    assert "card" in log                       # the category was not known before building

def test_no_card_when_the_triggering_call_failed(make_pipeline):
    log: list[str] = []
    reg = registry(_tool("get_safe_to_spend", fails=True))
    model = ScriptedModel(plans=[[FunctionCall("get_safe_to_spend", {}), FunctionCall("finish")]], drafts=[GOOD])
    events = run(pipeline(make_pipeline, model, Steps(log), reg=reg))
    assert "card" not in log and "card_review" not in [p["card"]["card_id"] for e, p in events if e == "card"]


def test_no_card_without_a_pending_review_or_without_room(make_pipeline):
    log: list[str] = []
    reg = registry(_tool("get_safe_to_spend"))
    model = ScriptedModel(plans=[[FunctionCall("get_safe_to_spend", {}), FunctionCall("finish")]], drafts=[GOOD])
    events = run(pipeline(make_pipeline, model, Steps(log, pending=None), reg=reg))
    assert "card" not in log and [p["card"]["card_id"] for e, p in events if e == "card"] == ["card_test0001"]

    tools = [f"t{i}" for i in range(MAX_CARDS)]
    reg = registry(*[_tool(t) for t in tools[1:]], _tool("get_basket_breakdown"))
    plan = [FunctionCall(t, {}) for t in tools[1:]] + [FunctionCall("get_basket_breakdown", {}), FunctionCall("finish")]

    def distinct(name):  # three tools with three different cards
        def fn(ctx, args):
            result = fake_spending(ctx, args)
            return result.model_copy(update={"card": result.card.model_copy(update={"card_id": f"card_{name}"})})
        return ToolSpec(name, name, FakeArgs, fn, ("x", "x"))
    for t in tools[1:] + ["get_basket_breakdown"]:
        reg.tools[t] = distinct(t)
    events = run(pipeline(make_pipeline, ScriptedModel(plans=[plan], drafts=[GOOD]), Steps([]), reg=reg))
    sent = [p["card"]["card_id"] for e, p in events if e == "card"]
    assert len(sent) == MAX_CARDS and "card_review" not in sent   # the card counts towards the three


def test_without_label_steps_nothing_is_established(make_pipeline):
    pipe = make_pipeline(ScriptedModel(plans=[[FunctionCall("fake_spending", {}), FunctionCall("finish")]],
                                       drafts=[GOOD]))
    run(pipe)
    assert audit_records(pipe)[-1]["label_state"] is None


# ---- R6: no model tool can write a label ----------------------------------------------------------

LABEL_WRITERS = ("label_answer", "reviews.save", "reviews.decide", "INSERT INTO spike_review", "UPDATE spike_review",
                 "DELETE FROM spike_review", "set_label", "/api/baskets/label")


def test_no_registered_tool_can_write_a_label():
    reg = default_registry()
    assert reg.tools, "no tools registered"
    for spec in reg.tools.values():
        assert spec.read_only, spec.name
        module = sys.modules[spec.fn.__module__]
        source = inspect.getsource(module)
        assert not [w for w in LABEL_WRITERS if w in source], (spec.name, module.__name__)
    assert "label" not in " ".join(reg.names()).replace("labels", "")  # no tool named after labelling


def test_the_label_endpoint_is_not_a_model_tool():
    assert all(not name.startswith(("label", "set_", "answer_review", "write")) for name in default_registry().names())
    assert AUG.label  # the fake period is in use (keeps the import honest)
