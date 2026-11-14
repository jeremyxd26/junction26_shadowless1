"""The why answer's template is the designed writer (#552, the stand after #574): no `llm_unavailable` warning with
the model on, off, over budget or paused, and none with no key either; the planner turns record the template. No
database: a fake get_safe_to_spend with Sanna's view, its Numbers registered as the tool does."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from agent_fakes import audit_records, registry, run
from test_agent_safe_to_spend_checks import view

from core.agent.model import ComposeInput, ModelError, PlanInput, PlanResult
from core.agent.registry import ToolSpec
from core.agent.rules import RuleModel
from core.tools.formatting import display
from core.tools.models import Args, Number, Period, ToolResult, Unit

WEEK = Period(start=date(2026, 10, 1), end=date(2026, 10, 7), label="Next 7 days")
WHY = "Why is my safe to spend so low?"


class NoArgs(Args):
    pass


def fake_safe_to_spend(ctx, args: NoArgs) -> ToolResult:
    v = view()

    def reg(key, unit):
        node = v[key] if key in v else None
        n = ctx.numbers.register(Number(value=node["value"], unit=unit, period=WEEK, method=f"safe_to_spend.{key}@1",
                                        evidence_ref=f"ev_{key[:8]:x<8}0000", label=node["label"],
                                        display=display(Decimal(str(node["value"])), unit, ctx.language)))
        v[key] = {**node, "id": n.id}

    for key, unit in (("safe_to_spend", Unit.EUR), ("free_until_payday", Unit.EUR), ("balance_limit", Unit.EUR),
                      ("budget_limit", Unit.EUR), ("savings_goal", Unit.EUR_PER_MONTH), ("usual_week", Unit.EUR)):
        reg(key, unit)
    for c in v["components"]:
        n = ctx.numbers.register(Number(value=c["amount"]["value"], unit=Unit.EUR, period=WEEK,
                                        method=f"safe_to_spend.{c['key']}@1", evidence_ref="ev_component0001",
                                        label=c["amount"]["label"],
                                        display=display(Decimal(str(c["amount"]["value"])), Unit.EUR, ctx.language)))
        c["amount"] = {**c["amount"], "id": n.id}
    return ToolResult(tool="get_safe_to_spend", data={}, card=None, evidence=[], model_view=v)


SPEC = ToolSpec("get_safe_to_spend", "Safe to spend.", NoArgs, fake_safe_to_spend, ("Looking", "Katson"))


class RulesPlanning:
    """The rule planner with a language model's state: `reason` is what unavailable_reason gives (None: the model
    is on). Its composer must never be asked for the why answer."""

    model_id = "rules-planning"

    def __init__(self, reason=None):
        self.reason, self.composed = reason, []

    def unavailable_reason(self, kind=None):
        return self.reason

    def plan(self, request: PlanInput) -> PlanResult:
        return RuleModel().plan(request)

    def compose(self, request: ComposeInput):
        self.composed.append(request)
        raise ModelError("the composer was asked")


@pytest.mark.parametrize("reason", [None, "off", "budget", "pause"])
def test_the_why_answer_carries_no_warning_with_the_model_on_off_over_budget_or_paused(make_pipeline, reason):
    model = RulesPlanning(reason)
    pipe = make_pipeline(model, registry(SPEC))
    done = dict(run(pipe, WHY, language="en"))["done"]
    assert done["outcome"] == "answered" and "llm_unavailable" not in done["warnings"], done["warnings"]
    assert "because your monthly budget sets the limit" in done["text"] and model.composed == []
    turns = audit_records(pipe)[-1]["planner_turns"]
    assert turns[-1] == {"round": len(turns), "source": "template", "template_answer": True}


def test_the_why_answer_carries_no_warning_with_no_key_either(make_pipeline):
    pipe = make_pipeline(RuleModel(), registry(SPEC))
    done = dict(run(pipe, "Miksi minulla on nyt vähemmän käytettävissä?", language="fi"))["done"]
    assert done["outcome"] == "answered" and "llm_unavailable" not in done["warnings"]
    assert "koska kuukausibudjettisi asettaa rajan" in done["text"]


def test_the_plain_safe_to_spend_answer_still_warns_when_the_template_stands_in(make_pipeline):
    # not the designed writer: with the model paused, the template writes in its place and says so (#244)
    pipe = make_pipeline(RulesPlanning("pause"), registry(SPEC))
    done = dict(run(pipe, "What can I safely spend this week?", language="en"))["done"]
    assert done["outcome"] == "answered" and "llm_unavailable" in done["warnings"]


def test_the_plain_answer_with_the_model_on_is_composed_and_carries_no_warning(make_pipeline):
    good = {"language": "en", "text": "About {{n1}} is safe to spend this week, after setting aside {{n5}} first.",
            "cited": ["n1", "n5"], "lesson_key": None}

    class Composing(RulesPlanning):
        def compose(self, request):
            from core.agent.model import ComposeResult
            import json
            self.composed.append(request)
            return ComposeResult(text=json.dumps(good))

    model = Composing()
    done = dict(run(make_pipeline(model, registry(SPEC)), "What can I safely spend this week?", language="en"))["done"]
    assert len(model.composed) == 1 and "llm_unavailable" not in done["warnings"] and done["text"].startswith("About")
