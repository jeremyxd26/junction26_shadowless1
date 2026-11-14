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
])
def test_another_persons_cost_is_their_data(question, language):
    found = decided(question, language)
    assert found.calls and found.calls[0].name == "decline" and found.calls[0].args["kind"] == "other_person_data"


@pytest.mark.parametrize("question, language", [
    ("How much did I spend on my husband's birthday last month?", "en"),
    ("How much did I spend on restaurants last month?", "en"),
    ("Paljonko käytin ravintoloihin viime kuussa?", "fi"),
])
def test_the_users_own_spending_keeps_its_answer(question, language):
    found = decided(question, language)
    assert not (found.calls and found.calls[0].name == "decline"), (question, found)
    assert found.reason not in ("week_part", "pronoun"), (question, found)
