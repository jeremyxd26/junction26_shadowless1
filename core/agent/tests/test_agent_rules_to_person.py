"""#542: money the user gave, sent, lent, paid or bought something for a person, with no category or filter for the
person, never gets the unfiltered total. No model, no database: the rule claim only (rules.claim)."""

from __future__ import annotations

import pytest

from core.agent import people
from core.agent.model import PlanInput
from core.agent.rules import claim

AS_OF = "2026-09-30"
ALL = ["get_spending", "get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "get_safe_to_save",
       "run_what_if", "get_spender_profile", "get_peer_benchmark", "get_bonus_estimate"]


def decided(question, language):
    return claim(PlanInput(question=question, language=language, as_of=AS_OF,
                           tools=[{"name": t, "description": "", "parameters_json_schema": {}} for t in ALL]))


def unfiltered_total(found):
    return any(c.name == "get_spending" and not c.args.get("filter") for c in found.calls)


TO_A_PERSON = [
    "How much did I give my husband last month?",
    "What did I buy my wife in September?",
    "How much did I send my mom in August?",
    "How much did I lend my brother last month?",
    "How much did I give Marja last month?",
    "How much did I pay Jane in June?",
    "What did I get my dad in September?",
    "How much did I spend on my wife last month?",
    "Paljonko annoin miehelleni viime kuussa?",
    "Mitä ostin vaimolleni syyskuussa?",
    "Paljonko lähetin äidilleni elokuussa?",
    "Paljonko annoin Marjalle viime kuussa?",
    "Paljonko maksoin äidilleni elokuussa?",
    "Paljonko käytin vaimooni syyskuussa?",
    "Paljonko käytin lapsiini elokuussa?",
    "paljonko käytin lapsilleni syyskuussa",
    "Paljonko annoin miehelleni viime kuussa",          # typed without the question mark
    "Paljonko lahetin aidilleni elokuussa?",            # typed without dots
]


@pytest.mark.parametrize("language", ("en", "fi"))
@pytest.mark.parametrize("question", TO_A_PERSON)
def test_money_to_a_person_never_gets_the_unfiltered_total(question, language):
    found = decided(question, language)
    assert not unfiltered_total(found), (question, found)
    assert not (found.calls and found.calls[0].name == "decline"), (question, found)   # the user's own: not refused


@pytest.mark.parametrize("question, filt", [
    ("How much did I spend on restaurants with my girlfriend in August?", {"categories": ["Restaurants"]}),
    ("Paljonko käytin ravintoloihin tyttöystäväni kanssa elokuussa?", {"categories": ["Restaurants"]}),
    ("How much did my husband and I spend on groceries in August 2026?", {"categories": ["Groceries"]}),
    ("How much did I spend on groceries for my kids last month?", {"categories": ["Groceries"]}),
])
def test_a_person_with_a_real_filter_keeps_it(question, filt):
    found = decided(question, "fi" if "ä" in question else "en")
    assert [c.name for c in found.calls if c.name != "finish"] == ["get_spending"], (question, found)
    assert found.calls[0].args["filter"] == filt


@pytest.mark.parametrize("question", [
    "How much did I spend last month?",
    "I bought my brother a gift, how much did I spend in August?",   # the part that asks: August's spending
])
def test_the_users_total_is_still_the_total(question):
    found = decided(question, "en")
    assert [c.name for c in found.calls if c.name != "finish"] == ["get_spending"], (question, found)


@pytest.mark.parametrize("question, verdict", [
    ("How much did my mom give me last month?", "unclaimed"),          # paid to the user: unclaimed, as before
    ("How much did my husband spend last month?", "decline"),          # someone else's money: declined, as before
])
def test_money_from_or_of_another_person_keeps_its_verdict(question, verdict):
    found = decided(question, "en")
    if verdict == "unclaimed":
        assert found.rule is None, (question, found)
    else:
        assert found.calls[0].name == "decline" and found.calls[0].args["kind"] == "other_person_data"


@pytest.mark.parametrize("question, expected", [
    ("How much did I give my husband?", True), ("How much did I pay Marja?", True),
    ("Paljonko annoin miehelleni?", True), ("Mitä ostin Marjalle?", True), ("Paljonko käytin vaimooni?", True),
    ("How much did I pay Elisa?", False),         # a payee, not a person
    ("How much did I pay for rent?", False), ("How much did I get back?", False),
    ("Paljonko maksoin Elisalle?", False), ("Paljonko käytin kaupalle?", False),
])
def test_to_person(question, expected):
    assert people.to_person(question) is expected, question
