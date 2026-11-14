"""The spending filter's sub-groups (#497): takeaway 5814, bars 5813, cinemas 7832. No database.

A filter on a sub-group selects its codes, and its total is labelled with the group. A row keeps its one MCC
group, so the restaurants group (5812, 5813, 5814) and breakdowns by group do not change."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from core.tools import config
from core.tools.classify import classify
from core.tools.context import ToolContext
from core.tools.db import Tx
from core.tools.spending import get_spending
from core.tools.tests.test_tools_safe_to_save_pure import FakeStore

AS_OF = date(2026, 9, 30)
SEPTEMBER = {"preset": "custom", "start": "2026-09-01", "end": "2026-09-30"}


def tx(i, day, category, amount, mcc):
    d = date(2026, 9, day)
    return Tx(i, d, datetime.combine(d, datetime.min.time()), category, "purchase", None, mcc, Decimal(amount))


HISTORY = [tx(1, 2, "Restaurants", "-30.00", "5812"), tx(2, 3, "Restaurants", "-12.50", "5814"),
           tx(3, 4, "Restaurants", "-8.00", "5814"), tx(4, 5, "Restaurants", "-9.90", "5813"),
           tx(5, 6, "Entertainment", "-14.00", "7832"), tx(6, 7, "Groceries", "-60.00", "5411")]


def run(args, language="en"):
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=FakeStore(), language=language, _history=HISTORY)
    return get_spending(ctx, {"period": SEPTEMBER, **args})


@pytest.mark.parametrize("group,total,label_en,label_fi", [
    ("takeaway", 20.5, "Takeaway and fast food", "Pikaruoka ja noutoruoka"),
    ("bars", 9.9, "Bars", "Baarit"),
    ("cinemas", 14.0, "Cinemas", "Elokuvateatterit"),
])
def test_a_sub_group_filter_selects_its_codes_and_names_the_group(group, total, label_en, label_fi):
    result = run({"filter": {"mcc_groups": [group]}})
    assert (result.data.total.value, result.data.total.label) == (total, label_en)
    assert run({"filter": {"mcc_groups": [group]}}, "fi").data.total.label == label_fi


def test_the_restaurants_group_and_the_rows_own_groups_do_not_change():
    assert run({"filter": {"mcc_groups": ["restaurants"]}}).data.total.value == 60.4    # 5812 + 5813 + 5814
    rows = classify(HISTORY, AS_OF, {})
    assert {c.tx.mcc: c.mcc_group for c in rows} == {"5812": "restaurants", "5814": "restaurants",
                                                      "5813": "restaurants", "7832": None, "5411": "groceries"}
    assert set(config.MCC_TO_GROUP) == {m for codes in config.MCC_GROUPS.values() for m in codes}


def test_a_breakdown_by_group_keeps_the_rows_own_groups():
    groups = {g.key: g.amount.value for g in run({"group_by": "mcc_group"}).data.groups}
    assert groups.get("restaurants") == 60.4 and "takeaway" not in groups and "bars" not in groups
