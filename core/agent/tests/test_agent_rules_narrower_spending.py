"""#639: a spending wording narrower than any filter is never answered with the unfiltered total, and the rows of the
reviews of #635 and #647 get their own answer. No model, no database: the rule claim only (rules.claim)."""

from __future__ import annotations

import pytest

from core.agent.model import PlanInput
from core.agent.rules import claim

TOOLS = [{"name": t, "description": "", "parameters_json_schema": {}} for t in
         ("get_spending", "get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "get_bonus_estimate",
          "run_what_if", "get_spender_profile", "get_peer_benchmark")]


def decided(question, language, history=None):
    return claim(PlanInput(question=question, language=language, as_of="2026-09-30", tools=TOOLS,
                           history=history or []))


def calls(found):
    return [(c.name, c.args) for c in found.calls if c.name != "finish"]


def unfiltered_total(found):
    return any(name == "get_spending" and not (args or {}).get("filter") for name, args in calls(found))


@pytest.mark.parametrize("question, language", [
    ("Paljonko Bonusta olen saanut kaikkiaan?", "fi"), ("How much Bonus have I received in total?", "en"),
    ("Paljonko S-Bonusta olen saanut tänä vuonna?", "fi"),
])
def test_the_bonus_received_is_the_s_bonus_estimate_never_the_spending_total(question, language):
    found = decided(question, language)
    assert calls(found) == [("get_bonus_estimate", {})], (question, found)   # the estimate, no share assumed


@pytest.mark.parametrize("question, language, received", [
    ("Paljonko Bonusta olen saanut kaikkiaan?", "fi", True), ("How much Bonus have I received this year?", "en", True),
    ("Paljonko S-Bonusta saisin?", "fi", False), ("How much S-Bonus could I get?", "en", False),
])
def test_the_rule_planner_marks_a_question_about_the_bonus_received(question, language, received):
    from core.agent.rules import RuleModel
    plan = RuleModel().plan(PlanInput(question=question, language=language, as_of="2026-09-30", tools=TOOLS))
    assert [c.name for c in plan.calls if c.name != "finish"] == ["get_bonus_estimate"]
    assert plan.bonus_received is received


@pytest.mark.parametrize("question, language", [("Paljonko Bonusta olen saanut kaikkiaan?", "fi"),
                                                ("How much Bonus have I received in total?", "en")])
def test_the_bonus_received_answer_says_first_that_it_is_not_in_the_data(make_pipeline, question, language):
    # review of #679: the estimate is a what-if, so a designed lead says the Bonus received is not visible; no number
    from decimal import Decimal

    from agent_fakes import AUG, FakeArgs, registry, run

    from core.agent import template
    from core.agent.registry import ToolSpec
    from core.agent.rules import RuleModel
    from core.tools.formatting import display
    from core.tools.models import Number, ToolResult, Unit

    class BonusArgs(FakeArgs):
        share_pct: int | None = None

    def bonus(ctx, args):
        def n(value, unit, label, ref):
            return ctx.numbers.register(Number(value=value, unit=unit, period=AUG, method=f"bonus_estimate.{ref}@1",
                                               evidence_ref=f"ev_bonus0000{ref[:3]}", label=label,
                                               display=display(Decimal(str(value)), unit, ctx.language)))
        share, month = n(100, Unit.PERCENT, "Share at S-Group stores", "share"), n(25.15, Unit.EUR_PER_MONTH, "a", "month")
        year = n(301.8, Unit.EUR_PER_YEAR, "a year", "year")
        view = {"tool": "get_bonus_estimate", "kind": "estimate", "status": "estimate",
                **{k: {"id": v.id, "value": v.value, "unit": v.unit.value, "label": v.label}
                   for k, v in (("share", share), ("total_month", month), ("total_year", year))},
                "reason": None, "lowest_level": None, "assumptions": []}
        return ToolResult(tool="get_bonus_estimate", data={}, model_view=view)

    spec = ToolSpec("get_bonus_estimate", "S-Bonus estimate.", BonusArgs, bonus, ("Looking", "Katson"))
    events = run(make_pipeline(RuleModel(), registry(spec)), question, language=language)
    done = dict(events)["done"]
    lead = template.pick(template.BONUS_RECEIVED_LEAD, language)
    assert done["outcome"] == "answered" and done["text"].startswith(lead), done["text"]
    assert len(done["text"]) > len(lead) + 10                         # the estimate follows the lead
    assert not any(ch.isdigit() for ch in lead)                        # the lead carries no number of its own


@pytest.mark.parametrize("question, language", [("How much bonus did I get from work last year?", "en"),
                                                ("Paljonko bonusta sain töistä viime vuonna?", "fi")])
def test_a_bonus_from_work_is_no_s_bonus(question, language):
    assert not any(name == "get_bonus_estimate" for name, _ in calls(decided(question, language))), question


@pytest.mark.parametrize("question, language", [
    ("how much did I spend at the weekend last month?", "en"), ("How much did I spend on weekdays in August?", "en"),
    ("How much did I spend on restaurants at weekends in August?", "en"),
    ("Paljonko käytin viikonloppuisin viime kuussa?", "fi"), ("Paljonko käytin arkipäivisin elokuussa?", "fi"),
    ("how much did I spend on it last month?", "en"), ("Paljonko käytin siihen viime kuussa?", "fi"),
])
def test_a_week_part_or_an_empty_pronoun_is_asked_back_never_the_whole_period(question, language):
    found = decided(question, language)
    assert found.rule is None and found.reason in ("week_part", "pronoun"), (question, found)
    assert not unfiltered_total(found)


@pytest.mark.parametrize("question, language", [
    ("What did my insurance cost me last month?", "en"), ("Paljonko vakuutukseni maksoi viime kuussa?", "fi"),
    ("What did the loan cost me last month?", "en"),
])
def test_a_past_cost_of_a_bill_is_the_unknown_thing_breakdown_not_the_bills_due(question, language):
    found = decided(question, language)
    assert found.rule == "unknown_object" and [n for n, _ in calls(found)] == ["get_basket_breakdown"], (question, found)


@pytest.mark.parametrize("question, language", [
    ("How much is the car insurance bill?", "en"), ("Paljonko vakuutuksen lasku on?", "fi"),
    ("Paljonko auton vakuutuksen lasku on?", "fi"), ("When is my insurance bill due?", "en"),
    ("Paljonko minun pitää maksaa vuokraa?", "fi"),
])
def test_a_present_bill_or_the_rent_owed_is_the_bills_tool(question, language):
    assert [n for n, _ in calls(decided(question, language))] == ["get_recurring_bills"], question


@pytest.mark.parametrize("question, language", [
    ("How much did my husband's phone plan cost?", "en"), ("What does my husband's phone plan cost him?", "en"),
    ("What did my mother's insurance cost her?", "en"), ("What did my wife's gym cost her?", "en"),
    ("Paljonko mieheni liittymä maksoi?", "fi"), ("Paljonko miehen liittymä maksoi?", "fi"),
    ("Mitä vaimoni vakuutus maksaa?", "fi"),
])
def test_another_persons_cost_is_their_data(question, language):
    found = decided(question, language)
    assert found.calls and found.calls[0].name == "decline" and found.calls[0].args["kind"] == "other_person_data"


@pytest.mark.parametrize("question, language", [
    ("How much did I spend on my husband's birthday last month?", "en"),
    ("Paljonko mieheni liittymä maksoi minulle?", "fi"), ("Paljonko liittymäni maksaa?", "fi"),
    ("How much did I spend on restaurants last month?", "en"),
    ("Paljonko käytin ravintoloihin viime kuussa?", "fi"),
])
def test_the_users_own_spending_keeps_its_answer(question, language):
    found = decided(question, language)
    assert not (found.calls and found.calls[0].name == "decline"), (question, found)
    assert found.reason not in ("week_part", "pronoun"), (question, found)
