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
    assert filter_label(["Restaurants"], ["taxi"], [], None, "en") == "Restaurants and taxi"
    assert filter_label(["Restaurants"], [], ["everyday_spending"], None, "fi") == "Ravintolat ja arjen kulutus"
    assert filter_label([], [], [], "Grocery store A", "en") == "Grocery store A"          # an alias keeps its case
    assert filter_label(["Restaurants"], [], [], "Grocery store A", "en") == "Restaurants and Grocery store A"
    assert filter_label([], [], [], None, "en") is None


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
