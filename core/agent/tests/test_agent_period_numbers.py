"""#665: a period gets the period it names. A number in a period phrase is matched whole ("viimeisen 120 päivän" is not
twelve months), "the last N months / days" is the custom range it names, the number may stand before "viimeisen", a
narrowing word ("so far", "lately") never outranks the period it narrows, and a message naming two different periods
gets the period question back unless one rule answers both (this month and last month: the comparison). The answer to
that question is the period. No model, no database; the data's last day is 30 Sep 2026."""

from __future__ import annotations

import pytest

from core.agent import guard
from core.agent.model import PlanInput
from core.agent.rules import RuleModel
from core.agent.toolset import default_registry

TOOLS = default_registry().schemas()


def first_call(message: str, history: list | None = None):
    lang = guard.detect_language(message) or "en"
    plan = RuleModel().plan(PlanInput(question=guard.clean(message), language=lang, as_of="2026-09-30", tools=TOOLS,
                                      history=history or []))
    return next((c.name, c.args) for c in plan.calls if c.name != "finish")


def custom(start: str, end: str = "2026-09-30") -> dict:
    return {"preset": "custom", "start": start, "end": end}


RESTAURANTS = {"categories": ["Restaurants"]}


@pytest.mark.parametrize("question, period", [
    # a whole number: never the preset of its first digits
    ("Paljonko käytin ravintoloihin viimeisen 120 päivän aikana?", custom("2026-06-03")),
    ("How much did I spend on restaurants in the last 120 days?", custom("2026-06-03")),
    ("How much did I spend on restaurants in the last 36 months?", custom("2023-10-01")),
    ("Paljonko käytin ravintoloihin viimeisen 36 kuukauden aikana?", custom("2023-10-01")),
    ("Paljonko käytin ravintoloihin viimeisten 13 kuukauden aikana?", custom("2025-09-01")),
    ("Paljonko käytin ravintoloihin viimeisen 30 päivän aikana?", custom("2026-09-01")),
    # the presets' own counts and wordings are unchanged
    ("Paljonko käytin ravintoloihin viimeisen 12 kk aikana?", {"preset": "last_12_months"}),
    ("Paljonko käytin ravintoloihin viimeisen vuoden aikana?", {"preset": "last_12_months"}),
    ("How much did I spend on restaurants in the last 3 months?", {"preset": "last_3_months"}),
    # the number before "viimeisen"
    ("Paljonko käytin ravintoloihin kolmen viimeisen kuukauden aikana?", {"preset": "last_3_months"}),
    ("Paljonko käytin ravintoloihin kuuden viimeisen kuukauden aikana?", {"preset": "last_6_months"}),
    ("Paljonko käytin ravintoloihin kahdentoista viimeisen kuukauden aikana?", {"preset": "last_12_months"}),
    ("Paljonko käytin ravintoloihin kahden viimeisen kuukauden aikana?", custom("2026-08-01")),
    # no number: the past complete month, as before
    ("Paljonko käytin ravintoloihin viimeisen kuukauden aikana?", custom("2026-09-01")),
])
def test_a_period_gets_the_period_it_names(question, period):
    assert first_call(question) == ("get_spending", {"filter": RESTAURANTS, "period": period})


def test_the_new_year_is_not_twelve_months():
    name, args = first_call("Paljonko käytin viimeisen vuodenvaihteen jälkeen?")
    assert (args.get("period") or {}).get("preset") != "last_12_months"


def test_the_breakdown_gets_the_counted_range_too():
    """The other routes that read the period get the range named, not six or twelve months."""
    assert first_call("Mihin rahani menivät viimeisen 120 päivän aikana?") == (
        "get_basket_breakdown", {"period": custom("2026-06-03")})


@pytest.mark.parametrize("question, question_back", [
    ("Paljonko käytin ruokaan viimeisten 12 kuukauden ja viimeisten 3 kuukauden aikana?", "Mitä ajanjaksoa tarkoitat?"),
    ("How much did I spend on groceries in the last 12 months and the last 3 months?", "Which period do you mean?"),
    ("How much did I spend on groceries in the last 120 days and the last 6 months?", "Which period do you mean?"),
])
def test_two_different_periods_get_the_period_question(question, question_back):
    name, args = first_call(question)
    assert name == "ask_clarifying_question" and args["question"] == question_back


@pytest.mark.parametrize("question, period", [
    ("How much did I spend this month and last month?", {"preset": "this_month"}),
    ("How much did I spend this week and last week?", {"preset": "this_week"}),
])
def test_this_and_last_month_are_both_answered_by_the_comparison(question, period):
    assert first_call(question) == ("get_spending", {"period": period, "compare_to": "previous_period"})


@pytest.mark.parametrize("question, period", [
    ("How much have I spent so far this year?", {"preset": "year_to_date"}),
    ("Paljonko olen käyttänyt tähän mennessä tänä vuonna?", {"preset": "year_to_date"}),
    ("How much did I spend on restaurants lately, in the last six months?", {"preset": "last_6_months"}),
    ("How much have I spent so far?", {"preset": "this_month"}),
])
def test_a_narrowing_word_never_outranks_the_period(question, period):
    name, args = first_call(question)
    assert name == "get_spending" and args["period"] == period


def test_beside_another_rules_question_the_question_of_which_is_meant_stays():
    name, args = first_call("What can I safely spend this week and this month?")
    assert name == "ask_clarifying_question" and args["question"] == "Which of these do you mean?"


TWO = "Paljonko käytin ruokaan viimeisten 12 kuukauden ja viimeisten 3 kuukauden aikana?"


@pytest.mark.parametrize("answer, preset", [("Viimeiset 3 kuukautta", "last_3_months"),
                                            ("viimeisen 12 kuukauden aikana", "last_12_months")])
def test_the_answer_to_the_period_question_is_the_period(answer, preset):
    """The answer is planned with the question it answers; its own period wins over the table's first one."""
    assert first_call(answer, [{"question": TWO, "calls": []}]) == (
        "get_spending", {"filter": {"categories": ["Groceries"]}, "period": {"preset": preset}})


def test_an_answer_to_a_question_without_a_period_is_unchanged():
    assert first_call("Viime kuukausi", [{"question": "Paljonko käytin ravintoloihin?", "calls": []}]) == (
        "get_spending", {"filter": RESTAURANTS, "period": {"preset": "last_month"}})
