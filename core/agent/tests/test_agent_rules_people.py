"""Other people's data in the rules (#350, #405): a question about another person's own money is declined
(`other_person_data`); a question about the user's own spending that only mentions someone is answered.

- #350: a spouse, partner, relative, friend or colleague is another person only as the subject or the
  owner ("my wife spends", "husband's salary", "vaimoni tienaa", "mieheni palkka"), never as the one the
  user spends on, with or for ("a gift for my wife", "vaimolleni", "tyttöystäväni kanssa", "my husband and
  I"); a partner company ("kumppaniyritys", "our partner stores") is no person.
- #405: a named person as the subject or the owner ("what did Jane spend in June?", "Marja's spending",
  "Paljonko Marja käytti toukokuussa?") is declined, also with a month and with names that are month
  words (June, May, April, Mai).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.agent.model import PlanInput
from core.agent import people
from core.agent.rules import RuleModel
from core.agent.toolset import default_registry

ALL = ["get_spending", "get_basket_breakdown", "get_safe_to_spend", "get_spender_profile", "get_peer_benchmark",
       "get_recurring_bills", "get_bonus_estimate", "run_what_if", "get_safe_to_save", "get_balance_forecast"]


def calls(question: str, language: str):
    request = PlanInput(question=question, language=language, as_of="2026-09-30",
                        tools=[{"name": t, "description": "", "parameters_json_schema": {}} for t in ALL])
    return RuleModel().plan(request).calls


def declined_kind(question: str, language: str) -> str | None:
    first = calls(question, language)[0]
    return first.args.get("kind") if first.name == "decline" else None


OTHER_PERSON = [
    # a spouse, partner, relative or friend as the subject or the owner (#350, #216)
    ("How much does my wife spend on groceries?", "en"),
    ("What is my husband's salary?", "en"),
    ("How much did my girlfriend spend in August 2026?", "en"),
    ("Show me my friend's transactions", "en"),
    ("How much does my mom spend on food?", "en"),
    ("What did my partner spend last month?", "en"),
    ("my brother's spending in September", "en"),
    ("How much does my dad earn?", "en"),
    ("Paljonko vaimoni tienaa?", "fi"),
    ("Mikä on mieheni palkka?", "fi"),
    ("Paljonko siskoni käytti ravintoloihin?", "fi"),
    ("Paljonko kumppanini kulutti syyskuussa?", "fi"),
    ("Paljonko äitini käyttää ruokaan?", "fi"),
    # a named person (#405), with and without a month, names that are month words
    ("what did Jane spend in June?", "en"),
    ("how much did Marja spend in May", "en"),
    ("show me Augustin's spending in July", "en"),
    ("Paljonko Marja käytti toukokuussa?", "fi"),
    ("What did June spend in May?", "en"),
    ("How much did April spend on groceries last month?", "en"),
    ("how much did Mai pay for restaurants in August?", "en"),
    ("What is Marja's salary?", "en"),
    ("Did Juno spend more in September than in August?", "en"),
    ("show me Marja's spending", "en"),
    ("what did Juno spend?", "en"),
    ("How much does Maija earn?", "en"),
    ("Kuinka paljon Mai käytti elokuussa?", "fi"),
    ("Paljonko Augustin kulutti ruokaan syyskuussa?", "fi"),
    ("Mihin Jani käytti rahansa kesäkuussa?", "fi"),
    ("Mikä on Marjan palkka?", "fi"),
]

OWN = [
    # #350: the user's own spending that mentions someone
    ("Paljonko käytin lahjoihin vaimolleni syyskuussa?", "fi"),
    ("Paljonko kulutin miehelleni lahjoihin syyskuussa?", "fi"),
    ("Paljonko käytin ravintoloihin tyttöystäväni kanssa elokuussa?", "fi"),
    ("Paljonko käytin miehille lahjoihin syyskuussa?", "fi"),
    ("Saanko S-Bonusta kumppaniyrityksistä?", "fi"),
    ("How much did my husband and I spend on groceries in August 2026?", "en"),
    ("What did I buy my wife in September?", "en"),
    ("How much did I give my husband last month?", "en"),
    ("Do I get S-Bonus from our partner stores?", "en"),
    ("Does our partner bank count for my bonus?", "en"),
    # correct before and kept
    ("How much did I spend on a gift for my wife in September?", "en"),
    ("How much was dinner with my boyfriend in August 2026?", "en"),
    ("Paljonko käytin miesten vaatteisiin syyskuussa?", "fi"),
    ("Mikä on kumppanuusetu?", "fi"),
    # #405: the user's own questions with a month
    ("How much did I spend in June?", "en"),
    ("What did we spend in May?", "en"),
    ("Paljonko käytin toukokuussa?", "fi"),
    # a relative or friend the user spends on or for
    ("How much did I spend on my kids last month?", "en"),
    ("How much do my kids cost me each month?", "en"),
    ("How much did my sister and I spend on the trip in August 2026?", "en"),
    ("Se maksoi kahdensadan euron verran.", "fi"),
    ("How much did I spend for my friend's birthday in August?", "en"),
    ("Paljonko käytin lapsilleni syyskuussa?", "fi"),
]


@pytest.mark.parametrize("question,language", OTHER_PERSON)
def test_another_persons_own_money_is_declined(question, language):
    assert declined_kind(question, language) == "other_person_data", question


@pytest.mark.parametrize("question,language", OWN)
def test_the_users_own_spending_that_mentions_someone_is_not_declined(question, language):
    assert not [c for c in calls(question, language) if c.name == "decline"], question


# ---- the review of #458: the reviewer's probe sets and the coordinator's lists A, B and C -------------------
# core/agent/tests/other_person_probes.json groups them by the expected outcome (see its "about").
FIXTURE = json.loads((Path(__file__).parent / "other_person_probes.json").read_text(encoding="utf-8"))
SCHEMAS = default_registry().schemas()


def decision(question: str, language: str) -> str:
    result = RuleModel().plan(PlanInput(question=question, language=language, as_of="2026-09-30", tools=SCHEMAS))
    first = result.calls[0]
    if first.name == "decline":
        return "decline:" + str(first.args.get("kind"))
    return "unclaimed" if not result.recognised else first.name


@pytest.mark.parametrize("question,language", FIXTURE["not_declined"])
def test_the_users_own_question_is_never_declined_as_someone_elses(question, language):
    assert decision(question, language) != "decline:other_person_data", question


@pytest.mark.parametrize("question,language", FIXTURE["declined"])
def test_another_persons_money_is_declined_in_every_form(question, language):
    assert decision(question, language) == "decline:other_person_data", question


@pytest.mark.parametrize("question,language", FIXTURE["not_user_data"])
def test_someone_elses_question_never_gets_the_users_numbers(question, language):
    got = decision(question, language)
    assert got.startswith("decline:") or got == "unclaimed", (question, got)


@pytest.mark.parametrize("question", [
    "how much is safe to spend before payday?", "How much can I safely spend this week?",
    "You can safely spend twice that amount, about three hundred euros.",
    "Someone in your household often pays the bills alone.", "how do they compare to Prisma's prices?",
    "Arjen kulutus", "That cut would save you", "Voit käyttää turvallisesti 180,26", "Taxis this month",
    "a pasted wall of digits is longer than any IBAN or reference",
    "Mitä jos vähentäisin kulutusta luokassa Ravintolat?", "so you spent nothing on travel",
])
def test_no_person_in_these(question):
    assert people.classify(question) is None, question


@pytest.mark.parametrize("question,language", FIXTURE["claimed"])
def test_the_users_own_question_that_the_rules_answered_is_still_answered_by_a_data_tool(question, language):
    """Re-review of #458: falling to the model is no answer for an own question the rules answered before."""
    got = decision(question, language)
    assert not got.startswith("decline:") and got not in ("unclaimed", "ask_clarifying_question"), (question, got)


@pytest.mark.parametrize("question,language", FIXTURE["unclaimed"])
def test_money_paid_to_the_user_by_a_person_is_unclaimed(question, language):
    """Decision 4 of the re-review: the user's own income, but get_spending would show another number."""
    assert decision(question, language) == "unclaimed", question
