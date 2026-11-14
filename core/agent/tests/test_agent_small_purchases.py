"""Small purchases in the answer pipeline (#256): the rule claims only the plain question, and the template's
takeaway sentence passes the real validator, for every count from 1 to 31, in English and Finnish."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from core.agent import template
from core.agent.model import PlanInput
from core.agent.rules import RuleModel
from core.agent.validator import allowed_from, validate
from core.tools.tests.test_tools_small_purchases_pure import FIVE, august, run, tx

ALL = ["get_spending", "get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "get_safe_to_save",
       "run_what_if", "get_spender_profile", "get_peer_benchmark", "get_bonus_estimate", "get_small_purchases"]
AS_OF = date(2026, 9, 30)


def plan(question, language="en"):
    request = PlanInput(question=question, language=language, as_of=AS_OF.isoformat(),
                        tools=[{"name": t, "description": "", "parameters_json_schema": {}} for t in ALL])
    return RuleModel().plan(request)


def names(result):
    return [c.name for c in result.calls]


# ---- the rule ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("question,lang", [
    ("Where do my small purchases go?", "en"),
    ("How much do I spend on coffees and snacks?", "en"),
    ("How much did my small purchases cost in the last 3 months?", "en"),   # the default period may be named
    ("Mihin pienet ostokset menevät?", "fi"),
    ("Mihin pienet ostokset menevat?", "fi"),                                  # typed without dots
    ("Paljonko käytän kahviin ja välipaloihin?", "fi"),
    ("Paljonko pikkuostoksiin menee?", "fi"),
])
def test_the_plain_small_purchases_question_plans_the_tool_with_its_defaults(question, lang):
    result = plan(question, lang)
    assert result.recognised and names(result) == ["get_small_purchases", "finish"]
    assert result.calls[0].args == {}


@pytest.mark.parametrize("question,lang,tool", [
    ("Where did my money go?", "en", "get_basket_breakdown"),
    ("Mihin rahani menivät?", "fi", "get_basket_breakdown"),
    ("How could I save more?", "en", "get_safe_to_save"),
])
def test_the_rule_never_catches_the_baskets_or_save_more_question(question, lang, tool):
    assert names(plan(question, lang))[0] == tool


@pytest.mark.parametrize("question", [
    "Where do my small purchases under €5 go?",
    "How much were my small purchases in July?",
    "Small purchases last month?",
    "Mihin pienet ostokset menivät elokuussa?",
])
def test_an_amount_or_another_period_is_never_answered_for_the_defaults(question):
    """#142: the rule does not read them, so it hands the question on instead of answering another one."""
    result = plan(question, "fi" if "pienet" in question else "en")
    assert not result.recognised and "get_small_purchases" not in names(result)
    assert "get_spending" not in names(result)


def test_a_cut_of_small_purchases_is_the_what_if_rule_not_this_one():
    result = plan("What if I cut small purchases by 20%?")
    assert "get_small_purchases" not in names(result)


# ---- the sentence ------------------------------------------------------------------------------------------

def compose(history, language="en", **args):
    result, _, ctx = run(history, language=language, **args)
    view = result.model_view
    numbers = ctx.numbers.all()
    draft = template.template_draft([view], [], language, None, "Where do my small purchases go?")
    out, errors = validate(draft, language=language, numbers=numbers,
                           allowed=allowed_from(numbers.values(), [view], AS_OF))
    assert errors == [], (draft["text"], errors)
    return draft["text"], {nid: numbers[nid] for nid in draft["cited"]}


def restaurants(n: int) -> list:
    """n small restaurant purchases spread over July to September (EUR 3.10 each)."""
    return [tx(i, date(2026, 7, 1) + timedelta(days=(i * 3) % 92), "Restaurants", "-3.10") for i in range(1, n + 1)]


def test_the_summary_sentence_in_english():
    text, cited = compose(restaurants(31))
    assert text.startswith("1 Jul – 30 Sep 2026: {{")
    assert "small purchases of {{" in text and "added up to {{" in text and "a month — most of them at " \
           "restaurants and cafés." in text
    assert [n.method for n in cited.values()] == ["small_purchases.count@1", "small_purchases.max_amount_eur@1",
                                                  "small_purchases.total_eur@1", "small_purchases.month_avg_eur@1"]


def test_the_summary_sentence_in_finnish():
    text, _ = compose(restaurants(31), "fi")
    assert "pientä ostosta (enintään {{" in text and "maksoi yhteensä {{" in text
    assert text.endswith("kuukaudessa — suurin osa ravintoloissa ja kahviloissa.")


def test_the_largest_part_when_no_category_has_more_than_half():
    text, _ = compose(august(*FIVE))                     # Restaurants 38.8 % of the small total
    assert "the largest part at restaurants and cafés." in text


def test_few_and_none():
    few, cited = compose(restaurants(4))
    assert "Only {{" in few and "small purchases of {{" in few and "not much to see here." in few
    assert len(cited) == 3                               # count, limit, total: no month average needed
    one, _ = compose(restaurants(1))
    assert "small purchase of {{" in one                 # singular
    fi_one, _ = compose(restaurants(1), "fi")
    assert "pieni ostos (enintään {{" in fi_one
    none, cited = compose([tx(1, date(2026, 8, 3), "Groceries", "-30.00")])
    assert "No small purchases of {{" in none and len(cited) == 1


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("n", range(1, 32))
def test_every_count_passes_the_validator(language, n):
    """A count next to a month or a date could read as a day; words always stand between them."""
    compose(restaurants(n), language)
