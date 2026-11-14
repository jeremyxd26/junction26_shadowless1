"""#567: a breakdown's "Other" (the purchases with no merchant group) and "Everything else" (the rest after the top
items) have the evidence title the tool gives them, in both languages, never "Total spending" / "Kulutus yhteensä".
Number label = card item = evidence title, as for the other items; the values do not change and the items still add
up to the breakdown's total. No database: fake rows and a fake evidence store."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from core.app.api import evidence as evidence_api
from core.tools.context import ToolContext
from core.tools.db import Tx
from core.tools.spending import get_spending
from core.tools.tests.test_tools_safe_to_save_pure import FakeStore

AS_OF = date(2026, 9, 30)
SEPTEMBER = {"preset": "custom", "start": "2026-09-01", "end": "2026-09-30"}


def tx(i, d, category, amount, mcc=None):
    return Tx(i, d, datetime.combine(d, datetime.min.time()), category, "purchase", None, mcc, Decimal(amount))


HISTORY = [tx(1, date(2026, 9, 1), "Housing", "-800.00"),                    # no merchant code: "Other"
           tx(2, date(2026, 9, 5), "Groceries", "-60.00", "5411"),
           tx(3, date(2026, 9, 9), "Restaurants", "-31.10", "5814"),
           tx(4, date(2026, 9, 12), "Transportation", "-18.50", "4121"),
           tx(5, date(2026, 9, 18), "Home & Tech", "-45.00", "5732"),
           tx(6, date(2026, 9, 20), "Travel", "-120.00")]                      # no merchant code: "Other"

NAMES = {"en": {"other": "Other", "rest": "Everything else"}, "fi": {"other": "Muut", "rest": "Kaikki muu"}}
TOTALS = ("Total spending", "Kulutus yhteensä")


def breakdown(by, language, top_n=2):
    store = FakeStore()
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=store, language=language, _history=HISTORY)
    result = get_spending(ctx, {"period": SEPTEMBER, "group_by": by, "top_n": top_n})
    return result, store


@pytest.mark.parametrize("language", ["en", "fi"])
def test_other_and_everything_else_by_merchant_group_carry_their_own_title(language):
    result, store = breakdown("mcc_group", language)
    labels = {g.key: g.label for g in result.data.groups}
    assert labels["no_mcc_group"] == NAMES[language]["other"] and labels["other"] == NAMES[language]["rest"]
    for g in result.data.groups:
        title = evidence_api._label_of(store.rows[g.amount.evidence_ref], language)
        assert title == g.label and title not in TOTALS, (g.key, title)
    assert sum(Decimal(str(g.amount.value)) for g in result.data.groups) == Decimal(str(result.data.total.value))


@pytest.mark.parametrize("language", ["en", "fi"])
def test_everything_else_by_category_carries_its_own_title(language):
    result, store = breakdown("category", language)
    rest = next(g for g in result.data.groups if g.key == "other")
    assert rest.label == NAMES[language]["rest"]
    assert evidence_api._label_of(store.rows[rest.amount.evidence_ref], language) == NAMES[language]["rest"]


def test_everything_else_within_a_filter_is_not_named_after_the_filter():
    store = FakeStore()
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=store, language="en", _history=HISTORY)
    result = get_spending(ctx, {"period": SEPTEMBER, "filter": {"categories": ["Housing", "Travel", "Groceries"]},
                                "group_by": "category", "top_n": 1})
    rest = next(g for g in result.data.groups if g.key == "other")
    assert evidence_api._label_of(store.rows[rest.amount.evidence_ref], "en") == "Everything else"


def test_the_values_and_methods_do_not_change():
    result, store = breakdown("mcc_group", "en")
    for g in result.data.groups:
        spec = store.rows[g.amount.evidence_ref]
        assert spec["method"] == g.amount.method and Decimal(spec["value"]) == Decimal(str(g.amount.value))


@pytest.mark.parametrize("language, expected", [("en", "Groceries (card purchases, Restaurants)"),
                                                ("fi", "Ruokaostokset (korttiostot, Ravintolat)")])
def test_a_card_purchase_group_within_another_category_has_one_bracket(language, expected):
    """A group named like a category, filtered with ANOTHER category (an empty intersection only a model plan
    reaches): one bracket, never "Groceries (card purchases) (Restaurants)" (#567)."""
    from core.tools.spending import filter_label
    assert filter_label(["Restaurants"], ["groceries"], [], None, language) == expected
    assert filter_label(["Groceries"], ["groceries"], [], None, language).count("(") == 1
