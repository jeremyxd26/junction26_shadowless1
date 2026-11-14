"""Small purchases in the answer pipeline (#256): the rule claims only the plain question (a whitelist, review of
#390), and the template's takeaway passes the real validator for every count from 1 to 31, in English and Finnish,
in at most three numbers."""

from __future__ import annotations

import re
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


def lang_of(question: str) -> str:
    return "fi" if re.search(r"pien|pikku|kahvi|mihin|paljonko", question, re.I) else "en"


# ---- the rule: a whitelist --------------------------------------------------------------------------------

CLAIMED = [
    "Where do my small purchases go?",
    "How much do I spend on coffees and snacks?",
    "How much did my small purchases cost in the last 3 months?",     # the default period may be named
    "Show me my small purchases",
    "How many small purchases did I make?",
    "Mihin pienet ostokset menevät?",
    "Mihin pienet ostokset menevat?",                                    # typed without dots
    "Mihin pienet ostokseni menevät?",
    "Paljonko käytän kahviin ja välipaloihin?",
    "Paljonko pikkuostoksiin menee?",
    "Mihin rahani menivät pienissä ostoksissa?",                         # review of #390: not the baskets rule
]


@pytest.mark.parametrize("question", CLAIMED)
def test_the_plain_question_is_claimed_with_the_defaults(question):
    result = plan(question, lang_of(question))
    assert result.recognised and names(result) == ["get_small_purchases", "finish"], question
    assert result.calls[0].args == {}


# Review of #390: every phrase that was claimed wrongly. A period or amount in words or digits, a filter, the
# singular, a stop: anything more than the plain question hands the message on.
HANDED_ON = [
    "small purchases under ten euros", "small purchases under a fiver", "small purchases less than five euros",
    "small purchases up to twenty euros", "pienet ostokset alle kymmenen euroa",
    "small purchases yesterday", "small purchases today", "small purchases last year",
    "small purchases over the last half year", "small purchases over the past quarter", "small purchases on Friday",
    "small purchases on Mondays", "small purchases at the weekend", "small purchases during the summer",
    "small purchases at Christmas", "small purchases before payday", "small purchases in sept",
    "pienet ostokset eilen", "pienet ostokset viime vuonna", "pienet ostokset perjantaina", "pienet ostokset marras",
    "Where do my small purchases go? Use the last year.",
    "What was that small purchase?", "what was that small purchase on Tuesday", "What was my biggest small purchase?",
    "Show me the small purchase at the cafe yesterday", "I made a small purchase yesterday, can I get a refund?",
    "What if I stopped small purchases?",
    "small purchases and subscriptions", "small purchases excluding restaurants", "small purchases from restaurants",
    "Where do my small purchases under €5 go?", "How much were my small purchases in July?",
    "Small purchases last month?", "Mihin pienet ostokset menivät elokuussa?",
    "Paljonko pienistä ostoksista kertyy",                                # "kertyy" is no filler word
]


@pytest.mark.parametrize("question", HANDED_ON)
def test_anything_more_than_the_plain_question_is_handed_on(question):
    result = plan(question, lang_of(question))
    assert "get_small_purchases" not in names(result), question
    assert "get_spending" not in names(result), question


@pytest.mark.parametrize("question,lang,tool", [
    ("Where did my money go?", "en", "get_basket_breakdown"),
    ("Mihin rahani menivät?", "fi", "get_basket_breakdown"),
    ("How could I save more?", "en", "get_safe_to_save"),
])
def test_the_rule_never_catches_the_baskets_or_save_more_question(question, lang, tool):
    assert names(plan(question, lang))[0] == tool


def test_a_cut_of_small_purchases_is_the_what_if_rule_not_this_one():
    assert "get_small_purchases" not in names(plan("What if I cut small purchases by 20%?"))


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


def rendered(history, language="en", **args):
    """The sentence as the user reads it: every token replaced by its Number's display."""
    text, cited = compose(history, language, **args)
    return re.sub(r"\{\{(n\d+)\}\}", lambda m: cited[m.group(1)].display, text)


def restaurants(n: int) -> list:
    """n small restaurant purchases spread over July to September (EUR 3.10 each)."""
    return [tx(i, date(2026, 7, 1) + timedelta(days=(i * 3) % 92), "Restaurants", "-3.10") for i in range(1, n + 1)]


def test_the_summary_sentence_in_english():
    _, cited = compose(restaurants(31))
    assert rendered(restaurants(31)) == ("You spent €96.10 on 31 small purchases in the last three months, about "
                                         "€32.03 a month, most of them at restaurants and cafés.")
    assert [n.method for n in cited.values()] == ["small_purchases.total_eur@1", "small_purchases.count@1",
                                                  "small_purchases.month_avg_eur@1"]


def test_the_summary_sentence_in_finnish():
    assert rendered(restaurants(31), "fi") == ("Käytit 96,10 € pieniin ostoksiin viimeisen kolmen kuukauden aikana: "
                                               "31 ostosta, noin 32,03 € / kk, suurin osa ravintoloissa ja kahviloissa.")


def purchases(category: str, n: int, amount: str = "-3.10") -> list:
    """n small purchases of one category spread over July to September."""
    return [tx(i, date(2026, 7, 1) + timedelta(days=(i * 3) % 92), category, amount) for i in range(1, n + 1)]


@pytest.mark.parametrize("category,en,fi", [
    ("Restaurants", "most of them at restaurants and cafés.", "suurin osa ravintoloissa ja kahviloissa."),
    ("Entertainment", "most of them on entertainment.", "suurin osa viihteessä."),
    ("Lifestyle", "most of them on lifestyle shopping.", "suurin osa lifestyle-ostoksissa."),
])
def test_each_category_takes_its_own_preposition(category, en, fi):
    """#465: "most of them at entertainment" read wrong; each category carries its preposition."""
    assert rendered(purchases(category, 12)).endswith(en)
    assert rendered(purchases(category, 12), "fi").endswith(fi)


def test_a_category_outside_the_table_is_on_its_label():
    view = {"tool": "get_small_purchases", "period_preset": "last_3_months", "takeaway": {"kind": "summary"},
            "count": {"id": "n1", "value": 12, "unit": "count", "label": "x"},
            "total": {"id": "n2", "value": 37.2, "unit": "eur", "label": "x"},
            "max_amount": {"id": "n3", "value": 10.0, "unit": "eur", "label": "x"},
            "categories": [{"key": "Groceries", "label": "Groceries", "share": {"value": 80.0}}]}
    assert template.small_purchases_sentence(view, "en")[0].endswith("most of them on groceries.")
    fi_view = {**view, "categories": [{"key": "Groceries", "label": "Ruokaostokset", "share": {"value": 80.0}}]}
    assert template.small_purchases_sentence(fi_view, "fi")[0].endswith("suurin osa luokassa Ruokaostokset.")


def test_one_month_has_no_monthly_average():
    """#465: for one month the average a month would only repeat the total."""
    text, cited = compose(august(*FIVE), period={"preset": "last_month"})
    assert "small_purchases.month_avg_eur@1" not in [n.method for n in cited.values()]
    assert rendered(august(*FIVE), period={"preset": "last_month"}) == (
        "You spent €25.00 on 5 small purchases last month, the largest part at restaurants and cafés.")
    assert "/ kk" not in rendered(august(*FIVE), "fi", period={"preset": "last_month"})


@pytest.mark.parametrize("language,expected", [
    ("en", "You spent €96.10 on 31 small purchases of €25.00 or less in the last three months, most of them at "
           "restaurants and cafés."),
    ("fi", "Käytit 96,10 € pieniin ostoksiin viimeisen kolmen kuukauden aikana: 31 ostosta rajalla 25,00 €, suurin "
           "osa ravintoloissa ja kahviloissa."),
])
def test_a_limit_other_than_the_default_is_named_in_place_of_the_monthly_average(language, expected):
    """#465: "of €25.00 or less", the limit's own Number; still three numbers (the monthly average gives way)."""
    text, cited = compose(restaurants(31), language, max_amount=25)
    assert rendered(restaurants(31), language, max_amount=25) == expected
    assert [n.method for n in cited.values()] == ["small_purchases.total_eur@1", "small_purchases.count@1",
                                                  "small_purchases.max_amount_eur@1"]


def test_a_limit_other_than_the_default_in_the_few_and_none_sentences():
    assert rendered(restaurants(4), max_amount=25) == ("Only 4 small purchases of €25.00 or less in the last three "
                                                      "months, €12.40 in all: not much to see here.")
    assert rendered(restaurants(4), "fi", max_amount=25) == ("Vain 4 pientä ostosta rajalla 25,00 € viimeisen "
                                                            "kolmen kuukauden aikana, yhteensä 12,40 €: tässä ei ole "
                                                            "paljon nähtävää.")
    none = [tx(1, date(2026, 8, 3), "Groceries", "-30.00")]
    assert rendered(none, max_amount=25) == "No small purchases of €25.00 or less in the last three months."
    assert rendered(none, "fi", max_amount=25) == ("Ei yhtään pientä ostosta rajalla 25,00 € viimeisen kolmen "
                                                  "kuukauden aikana.")


def test_the_largest_part_when_no_category_has_more_than_half():
    assert rendered(august(*FIVE)).endswith("the largest part at restaurants and cafés.")   # Restaurants 38.8 %


def test_few_and_none():
    assert rendered(restaurants(4)) == ("Only 4 small purchases in the last three months, €12.40 in all: not "
                                        "much to see here.")
    assert rendered(restaurants(1)) == ("Only 1 small purchase in the last three months, €3.10 in all: not "
                                        "much to see here.")
    assert rendered(restaurants(1), "fi") == ("Vain 1 pieni ostos viimeisen kolmen kuukauden aikana, yhteensä 3,10 €: tässä ei "
                                              "ole paljon nähtävää.")
    none = [tx(1, date(2026, 8, 3), "Groceries", "-30.00")]
    assert rendered(none) == "No small purchases in the last three months."
    assert rendered(none, "fi") == "Ei yhtään pientä ostosta viimeisen kolmen kuukauden aikana."


def test_a_preset_period_in_words_and_another_period_by_its_label():
    assert rendered(august(*FIVE), period={"preset": "last_month"}).startswith(
        "You spent €25.00 on 5 small purchases last month,")
    assert "viime kuussa" in rendered(august(*FIVE), "fi", period={"preset": "last_month"})
    custom = rendered(august(*FIVE), period={"preset": "custom", "start": "2026-08-01", "end": "2026-08-20"})
    assert custom.startswith("You spent €25.00 on 5 small purchases in 1–20 Aug 2026,")


@pytest.mark.parametrize("language", ["en", "fi"])
def test_no_unit_is_said_twice_and_the_limit_stays_on_the_card(language):
    text = rendered(restaurants(31), language)
    assert "a month a month" not in text and "/ kk kuukaudessa" not in text
    assert "10.00" not in text and "10,00" not in text


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("n", range(1, 32))
def test_every_count_passes_the_validator_in_at_most_three_numbers(language, n):
    """A count next to a month or a date could read as a day; words always stand between them. The length
    rule: at most three numbers in the text (review of #390)."""
    text, cited = compose(restaurants(n), language)
    assert len(re.findall(r"\{\{n\d+\}\}", text)) == len(cited) <= 3
