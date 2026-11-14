"""Rule-model regressions from conversational QA on the dev environment (#307).

A test marked xfail(strict=True) records a confirmed gap with its issue: it passes while the gap is
there and fails as soon as the fix lands, so the fixer removes the marker. The guard tests without a
marker hold today and must keep holding after the fix.
"""

from __future__ import annotations

import pytest

from core.agent.model import PlanInput
from core.agent.rules import RuleModel

ALL = ["get_spending", "get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "run_what_if",
       "get_spender_profile", "get_peer_benchmark"]


def plan(question, history=None, language="en"):
    request = PlanInput(question=question, language=language, as_of="2026-09-30",
                        tools=[{"name": t, "description": "", "parameters_json_schema": {}} for t in ALL],
                        history=history or [])
    return RuleModel().plan(request)


def spending_periods(result):
    return [c.args.get("period") for c in result.calls if c.name == "get_spending"]


# --- #298: a month name or abbreviation inside another word is not a month ---------------------

# Fixed by #298 (in PR #384): a month is a whole word, or a Finnish month stem with "kuu".
@pytest.mark.parametrize("question", [
    "can you summarize my spending?",          # sum-MAR-ize
    "maybe I spend too much on groceries?",    # MAY-be
    "help me decide how much to spend on food",  # DEC-ide
    "how much did I spend at the doctor?",     # d-OCT-or
    "can I afford a new sofa, maybe next month?",
])
def test_no_month_is_read_from_inside_a_word(question):
    for period in spending_periods(plan(question)):
        assert period.get("preset") != "custom", f"{question!r} planned the custom period {period}"


# Fixed by #298 (in PR #384): no month from a name, and another person's profile is not claimed.
@pytest.mark.parametrize("question,lang", [
    ("show me Marja's spending", "en"),
    ("show me Jani's groceries", "en"),
    ("Paljonko Jani käyttää ruokaan?", "fi"),
    ("what did Juno spend?", "en"),
    ("did Augustin pay more for rent than me?", "en"),
    ("what kind of spender is Marjatta?", "en"),
])
def test_another_persons_name_is_declined_or_left_to_the_model(question, lang):
    result = plan(question, language=lang)
    names = [c.name for c in result.calls]
    declined = names == ["decline"] and result.calls[0].args.get("kind") == "other_person_data"
    assert declined or not result.recognised, f"{question!r} planned {names} with the user's own data"


@pytest.mark.parametrize("question,lang,start,end", [
    ("How much did I spend in March?", "en", "2026-03-01", "2026-03-31"),
    ("What did I spend in May 2026?", "en", "2026-05-01", "2026-05-31"),
    ("How much did I spend on groceries in Jan?", "en", "2026-01-01", "2026-01-31"),
    ("Paljonko käytin toukokuussa?", "fi", "2026-05-01", "2026-05-31"),
])
def test_a_named_month_keeps_its_period(question, lang, start, end):
    periods = spending_periods(plan(question, language=lang))
    assert {"preset": "custom", "start": start, "end": end} in periods, periods


def test_a_friend_is_still_declined():
    result = plan("how much did my friend Octavia spend?")
    assert [(c.name, c.args.get("kind")) for c in result.calls] == [("decline", "other_person_data")]


# --- #300: an elliptical follow-up is planned with the conversation, or left to the model ---------

# Fixed by #300: a follow-up keeps the previous turn's tool, filter and period (rules.claim, _follow_up).

# The previous turn of the QA conversation: September's everyday spending by category.
EVERYDAY_SEPTEMBER = [{
    "question": "ok and what does everyday spending include exactly?",
    "calls": [{"name": "get_spending", "args": {"filter": {"baskets": ["everyday_spending"]},
                                                "period": {"preset": "this_month"}, "group_by": "category"}}],
    "results": [],
}]


@pytest.mark.parametrize("question", ["compared to August?", "vs August?"])
def test_compared_to_a_month_after_a_september_turn_compares_september(question):
    result = plan(question, history=EVERYDAY_SEPTEMBER)
    if not result.recognised:
        return  # handed to the model planner, which sees the history
    calls = [c for c in result.calls if c.name == "get_spending"]
    assert calls, [c.name for c in result.calls]
    args = calls[0].args
    assert args.get("period") in ({"preset": "this_month"},
                                  {"preset": "custom", "start": "2026-09-01", "end": "2026-09-30"}), args
    assert args.get("compare_to") == "previous_period", args
    assert args.get("filter") == {"baskets": ["everyday_spending"]}, args
