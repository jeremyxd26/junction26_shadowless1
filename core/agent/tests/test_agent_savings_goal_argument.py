"""#447 (r-sec): the savings goal (#391) is not something a plan can set. Until the app has a control for
the goal, no tool declaration offers `savings_goal`, a model plan that passes it is rejected as an invalid
argument (the error goes back to the model, never the value), and the tool then runs with the default goal.
The rules never pass it either. No database."""

from __future__ import annotations

import json

import pytest
from agent_fakes import FakeData, audit_records, fake_spending, run

from core.agent.model import FunctionCall, PlanInput, ScriptedModel
from core.agent.registry import CallRejected, Registry, ToolSpec
from core.agent.rules import RuleModel
from core.agent.toolset import default_registry
from core.tools.safe_to_spend import GetSafeToSpendArgs

GOAL_TOOLS = ("get_safe_to_spend", "get_safe_to_save", "get_balance_forecast", "explain_bill")


def test_no_tool_declaration_offers_a_savings_goal():
    declarations = default_registry().schemas()
    assert "savings_goal" not in json.dumps(declarations)
    names = {d["name"] for d in declarations}
    assert "get_safe_to_spend" in names


@pytest.mark.parametrize("name", GOAL_TOOLS)
def test_a_plan_that_passes_a_savings_goal_is_rejected(name):
    registry = default_registry()
    if name not in registry.tools:
        pytest.skip(f"{name} is not a planner tool")
    with pytest.raises(CallRejected) as exc:
        registry.parse(name, {"savings_goal": 500})
    assert exc.value.code == "invalid_arguments" and "500" not in str(exc.value)


def spy_registry(calls: list):
    def get_safe_to_spend(ctx, args: GetSafeToSpendArgs):
        calls.append(args.model_dump())
        return fake_spending(ctx, None)
    reg = Registry()
    reg.register(ToolSpec("get_safe_to_spend", "Safe to spend.", GetSafeToSpendArgs, get_safe_to_spend,
                          ("Working out", "Lasken")))
    return reg


def test_a_model_plan_with_a_goal_never_reaches_the_tool_and_the_default_goal_holds(make_pipeline):
    calls: list = []
    good = {"language": "en", "text": "You spent {{n1}} on restaurants in August 2026.", "cited": ["n1"],
            "lesson_key": None}
    model = ScriptedModel(plans=[[FunctionCall("get_safe_to_spend", {"savings_goal": 500})],
                                 [FunctionCall("get_safe_to_spend", {}), FunctionCall("finish")]], drafts=[good])
    pipe = make_pipeline(model, reg=spy_registry(calls), data=FakeData())
    run(pipe, "What can I safely spend this week?")
    assert calls == [{}]                                   # the tool ran once, without a goal: the default
    assert [r.response for r in model.plan_inputs[1].responses] == [{"error": "invalid_arguments"}]
    statuses = [c["status"] for t in audit_records(pipe)[-1]["planner_turns"] for c in t.get("calls", [])]
    assert "rejected: invalid_arguments" in statuses


@pytest.mark.parametrize("question", ["What can I safely spend this week?", "Save 500 a month first: what can I spend?",
                                      "Paljonko voin käyttää tällä viikolla, jos säästän 500 euroa?"])
def test_the_rules_never_pass_a_goal(question):
    plan = RuleModel().plan(PlanInput(question=question, language="auto", as_of="2026-09-30",
                                      tools=default_registry().schemas(), history=[]))
    assert all("savings_goal" not in (c.args or {}) for c in plan.calls)
