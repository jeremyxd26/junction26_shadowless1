"""A filtered spending total is labelled with its filter, never as all spending (#399). No database.

The sum of Housing and Restaurants was labelled "Spending", carded as "Spending" and explained in the evidence
view as "Total spending, September 2026". Now every part of the filter is named, in the Number label, the card
title, the evidence title and the answer's sentence, in English and Finnish; "Spending" / "Total spending" only
without a filter."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

import pytest

from core.agent import answer_sentences
from core.app.api import evidence as evidence_api
from core.tools import config
from core.tools.context import ToolContext
from core.tools.db import Tx
from core.tools.spending import filter_label, get_spending
from core.tools.tests.test_tools_safe_to_save_pure import FakeStore

AS_OF = date(2026, 9, 30)
SEPTEMBER = {"preset": "custom", "start": "2026-09-01", "end": "2026-09-30"}


def tx(i, d, category, amount):
    return Tx(i, d, datetime.combine(d, datetime.min.time()), category, "purchase", None, None, Decimal(amount))


HISTORY = [tx(1, date(2026, 9, 1), "Housing", "-800.00"), tx(2, date(2026, 9, 5), "Restaurants", "-24.40"),
           tx(3, date(2026, 9, 9), "Restaurants", "-31.10"), tx(4, date(2026, 9, 12), "Travel", "-120.00"),
           tx(5, date(2026, 9, 14), "Groceries", "-60.00")]


def run(args, language="en"):
    store = FakeStore()
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=store, language=language, _history=HISTORY)
    return get_spending(ctx, {"period": SEPTEMBER, **args}), store


@pytest.mark.parametrize("language,expected", [("en", "Housing and restaurants"), ("fi", "Asuminen ja ravintolat")])
def test_a_two_category_total_names_both_in_its_label_card_and_evidence(language, expected):
    result, store = run({"filter": {"categories": ["Housing", "Restaurants"]}}, language)
    total = result.data.total
    assert total.label == expected and total.value == 855.5
    assert result.card.title == expected
    spec = store.rows[total.evidence_ref]
    assert evidence_api._label_of(spec, language) == expected        # the evidence title starts with it
    assert "Total" not in expected and "Kokonais" not in expected
    assert result.model_view["filter_parts"] == 2


def test_three_parts_and_mixed_filters():
    assert filter_label(["Housing", "Restaurants", "Travel"], [], [], None, "en") == "Housing, restaurants and travel"
    # across dimensions the selection is an intersection, so the label is one too (#501)
    assert filter_label(["Restaurants"], ["taxi"], [], None, "en") == "Taxi (Restaurants)"   # review of #528
    assert filter_label(["Restaurants"], [], ["everyday_spending"], None, "fi") == "Ravintolat (arjen kulutus)"
    assert filter_label([], [], [], "Grocery store A", "en") == "Grocery store A"          # an alias keeps its case
    assert filter_label(["Restaurants"], [], [], "Grocery store A", "en") == "Restaurants at Grocery store A"
    assert filter_label([], [], [], None, "en") is None


def test_a_later_part_is_lower_cased_whole():
    """Review of #496, R3: "Home & Tech and housing", "Housing and home & tech" (not "home & Tech")."""
    assert filter_label(["Home & Tech", "Housing"], [], [], None, "en") == "Home & Tech and housing"
    assert filter_label(["Housing", "Home & Tech"], [], [], None, "en") == "Housing and home & tech"


@pytest.mark.parametrize("args,expected", [
    ({"filter": {"categories": ["Home & Tech", "Housing"]}}, " on home & tech and housing "),
    ({"filter": {"mcc_groups": ["electronics_home", "taxi"]}}, " electronics and home, and taxi "),  # #501: readable
])
def test_the_sentence_is_built_from_the_parts(args, expected):
    """Review of #496, R3: a part that itself contains "and" is not split again."""
    result, _ = run(args)
    view = result.model_view
    sentences, _ = answer_sentences.spending(view, "en", lambda s, **kw: True)
    assert expected in " ".join(sentences), sentences


def test_a_duplicate_part_is_counted_once():
    result, _ = run({"filter": {"categories": ["Housing", "Housing"]}}, "fi")
    assert result.model_view["filter_parts"] == 1 and result.model_view["filter_labels"] == ["Asuminen"]
    sentences, _ = answer_sentences.spending(result.model_view, "fi", lambda s, **kw: True)
    assert "luokassa Asuminen" in " ".join(sentences) and "luokissa" not in " ".join(sentences)


@pytest.mark.parametrize("language,label", [("en", "Spending"), ("fi", "Kulutus")])
def test_without_a_filter_the_total_is_spending(language, label):
    result, store = run({}, language)
    assert result.data.total.label == label and result.data.total.value == 1035.5
    spec = store.rows[result.data.total.evidence_ref]
    from core.app.api import texts
    assert evidence_api._label_of(spec, language) == texts.pick(texts.METHODS["spending.total@1"].name, language)
    assert result.model_view["filter_parts"] == 0


def test_one_category_is_labelled_as_before():
    result, store = run({"filter": {"categories": ["Restaurants"]}})
    assert result.data.total.label == "Restaurants"
    assert evidence_api._label_of(store.rows[result.data.total.evidence_ref], "en") == "Restaurants"


def test_a_merchant_filter_in_the_evidence_is_never_total_spending():
    spec = {"kind": "transactions", "method": config.METHODS["total"],
            "selection": {"categories": [], "mcc_groups": [], "baskets": [], "merchant_id": "M0001", "group": None}}
    assert evidence_api._label_of(spec, "en") == "Spending at the chosen merchant"
    assert evidence_api._label_of(spec, "fi") == "Kulutus valitulla kauppiaalla"


@pytest.mark.parametrize("language,expected", [
    ("en", "You spent €855.50 on housing and restaurants in September 2026"),
    ("fi", "käytit 855,50 € luokissa Asuminen ja ravintolat"),
])
def test_the_sentence_names_the_filter(language, expected):
    result, _ = run({"filter": {"categories": ["Housing", "Restaurants"]}}, language)
    sentences, _ = answer_sentences.spending(result.model_view, language, lambda s, **kw: True)
    text = re.sub(r"\{\{(n\d+)\}\}", lambda m: {n["id"]: d for n, d in (
        (result.model_view["total"], result.data.total.display),
        (result.model_view["tx_count"], result.data.tx_count.display))}[m.group(1)], " ".join(sentences))
    assert expected in text, text
    assert "your spending" not in text.lower() and "kulutuksesi" not in text


# ---- #501: filters on more than one dimension, long filters, a part holding the joiner, income ----------------

MERCHANT = "Home and tech store A"


@pytest.mark.parametrize("keys,language,expected", [
    ((["Restaurants"], [], [], MERCHANT), "en", "Restaurants at Home and tech store A"),
    ((["Restaurants"], [], [], MERCHANT), "fi", "Ravintolat kauppiaalla Home and tech store A"),
    ((["Housing"], [], ["everyday_spending"], None), "en", "Housing within everyday spending"),
    ((["Housing"], [], ["everyday_spending"], None), "fi", "Asuminen (arjen kulutus)"),
    ((["Restaurants"], ["taxi"], [], None), "en", "Taxi (Restaurants)"),
    ((["Restaurants"], ["taxi"], [], None), "fi", "Taksi (Ravintolat)"),
])
def test_a_filter_across_dimensions_is_worded_as_an_intersection(keys, language, expected):
    assert filter_label(*keys, language) == expected
    assert "luokissa" not in expected and not re.search(r"\band\b.*\band\b", expected.replace(MERCHANT, "M"))


@pytest.mark.parametrize("keys,merchant_label,expected", [
    ({"categories": ["Restaurants"], "mcc_groups": [], "baskets": [], "merchant_id": "M0001"}, MERCHANT,
     "Restaurants at Home and tech store A"),
    ({"categories": ["Housing"], "mcc_groups": [], "baskets": ["everyday_spending"], "merchant_id": None}, None,
     "Housing within everyday spending"),
    ({"categories": ["Restaurants"], "mcc_groups": ["taxi"], "baskets": [], "merchant_id": None}, None,
     "Taxi (Restaurants)"),
    ({"categories": ["Restaurants"], "mcc_groups": [], "baskets": [], "merchant_id": "M0001"}, None,
     "Restaurants at the chosen merchant"),   # no alias found: neutral, never only "Restaurants"
])
def test_the_evidence_title_of_a_filter_across_dimensions_equals_the_number_label(keys, merchant_label, expected):
    spec = {"kind": "transactions", "method": config.METHODS["total"],
            "selection": {"direction": "out", "group": None, **keys}}
    assert evidence_api._label_of(spec, "en", merchant_label) == expected


def test_the_tool_and_the_evidence_name_a_category_and_a_basket_alike():
    result, store = run({"filter": {"categories": ["Housing"], "baskets": ["regular_essentials"]}})
    label = result.data.total.label
    assert label == "Housing within regular essentials" and result.card.title == label
    assert evidence_api._label_of(store.rows[result.data.total.evidence_ref], "en") == label


@pytest.mark.parametrize("language,expected,sentence", [
    ("en", "Spending in several categories", " on several categories "),   # no digit (review of #528)
    ("fi", "Kulutus useassa luokassa", " useassa luokassa"),
])
def test_five_or_more_parts_are_counted_not_listed(language, expected, sentence):
    six = sorted(config.CATEGORY_LABELS)[:6]
    assert filter_label(six, [], [], None, language) == expected
    result, store = run({"filter": {"categories": six}}, language)
    assert result.data.total.label == expected and len(expected) < 40
    assert evidence_api._label_of(store.rows[result.data.total.evidence_ref], language) == expected
    sentences, _ = answer_sentences.spending(result.model_view, language, lambda s, **kw: True)
    assert sentence in " ".join(sentences) and not re.search(r"\d", re.sub(r"\{\{n\d+\}\}", "", " ".join(
        sentences)).replace("2026", ""))


def test_a_part_that_holds_the_joiner_keeps_the_list_readable():
    assert filter_label(["Home & Tech", "Lifestyle"], [], [], None, "fi") == \
        "Koti ja tekniikka sekä ostokset ja vapaa-aika"
    assert filter_label([], ["electronics_home", "taxi"], [], None, "en") == "Electronics and home, and taxi"
    assert filter_label(["Housing", "Restaurants", "Travel"], [], [], None, "fi") == "Asuminen, ravintolat ja matkailu"


@pytest.mark.parametrize("language,expected", [
    ("en", " on restaurants at Home and tech store A "),
    ("fi", "luokassa Ravintolat kauppiaalla Home and tech store A"),
])
def test_the_sentence_names_a_merchant_without_luokissa(language, expected):
    restaurants = config.label(config.CATEGORY_LABELS["Restaurants"], language)
    view = {"total": {"id": "n1", "value": 55.5, "unit": "eur", "label": "x"}, "tx_count": {"id": "n2", "value": 2,
            "unit": "count", "label": "x"}, "period": "September 2026", "direction": "out", "comparison": None,
            "filter_labels": [restaurants, MERCHANT],
            "filter_dims": [{"kind": "categories", "labels": [restaurants]}, {"kind": "merchant", "labels": [MERCHANT]}]}
    view["total"]["label"] = filter_label(["Restaurants"], [], [], MERCHANT, language)
    sentences, _ = answer_sentences.spending(view, language, lambda s, **kw: True)
    text = " ".join(sentences)
    assert expected in text and "luokissa" not in text, text


@pytest.mark.parametrize("language,expected", [("en", "Income"), ("fi", "Tulot")])
def test_an_unfiltered_income_total_is_never_total_spending_in_the_evidence(language, expected):
    spec = {"kind": "transactions", "method": config.METHODS["total"],
            "selection": {"direction": "in", "categories": [], "mcc_groups": [], "baskets": [], "merchant_id": None,
                          "group": None}}
    assert evidence_api._label_of(spec, language) == expected


# ---- review of #528: Finnish brackets, Finnish casing, the group before its category, counts without digits ----

def test_four_parts_are_listed_and_five_are_counted():
    four, five = sorted(config.CATEGORY_LABELS)[:4], sorted(config.CATEGORY_LABELS)[:5]
    assert filter_label(four, [], [], None, "en") == "Entertainment, groceries, health and home & tech"
    assert filter_label(five, [], [], None, "en") == "Spending in several categories"
    assert filter_label(five, [], [], None, "fi") == "Kulutus useassa luokassa"
    five_groups = sorted(config.MCC_GROUP_LABELS)[:5]
    assert filter_label(["Restaurants"], five_groups, [], None, "fi") == "Kulutus useassa ryhmässä (Ravintolat)"
    assert not re.search(r"\d", filter_label(five, five_groups, ["everyday_spending"], None, "en"))


@pytest.mark.parametrize("keys,en,fi", [
    ((["Transportation"], ["taxi"], [], None), "Taxi (Transportation)", "Taksi (Liikkuminen)"),
    ((["Groceries"], ["groceries"], [], None), "Groceries", "Ruokaostokset"),          # the same name once
    (([], ["taxi"], ["everyday_spending"], None), "Taxi within everyday spending", "Taksi (arjen kulutus)"),
    ((["Restaurants"], ["taxi"], ["everyday_spending"], "Grocery store A"),
     "Taxi (Restaurants) within everyday spending at Grocery store A",
     "Taksi (Ravintolat, arjen kulutus) kauppiaalla Grocery store A"),                # three dimensions
])
def test_a_group_comes_before_its_category_and_three_dimensions_read_as_one(keys, en, fi):
    assert filter_label(*keys, "en") == en and filter_label(*keys, "fi") == fi
    assert "within groceries" not in en and "joista" not in fi and "josta" not in fi


@pytest.mark.parametrize("keys,expected", [
    ((["Housing", "Restaurants"], [], ["everyday_spending", "regular_essentials"], None),
     "luokissa Asuminen ja ravintolat (arjen kulutus ja säännölliset välttämättömät)"),
    ((["Housing"], [], ["everyday_spending"], None), "luokassa Asuminen (arjen kulutus)"),
    ((["Housing", "Restaurants"], [], [], MERCHANT), "luokissa Asuminen ja ravintolat kauppiaalla " + MERCHANT),
])
def test_a_finnish_sentence_across_dimensions_has_no_capital_after_the_first_part(keys, expected):
    from core.tools.spending import filter_dims
    dims = [{"kind": k, "labels": names} for k, names in filter_dims(*keys, "fi")]
    subject = answer_sentences._dims_subject(dims, "fi")
    assert subject == expected
    rest = subject.split(" ", 2)[2].replace(MERCHANT, "")
    assert rest == rest.lower(), subject

