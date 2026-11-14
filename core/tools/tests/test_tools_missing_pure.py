"""Missing data in get_spending (#379, part B): a category never used, too few purchases. No database."""

from __future__ import annotations

from datetime import date

import pytest
from test_tools_baskets_bills_pure import _FakeStore, tx

from core.tools.classify import classify
from core.tools.context import ToolContext
from core.tools.missing import MissingData
from core.tools.spending import get_spending, top_categories

TODAY = date(2026, 9, 30)


def history():
    return [
        tx(1, date(2026, 8, 3), "Groceries", "-120.00"), tx(2, date(2026, 8, 9), "Groceries", "-80.00"),
        tx(3, date(2026, 8, 12), "Restaurants", "-45.00"), tx(4, date(2026, 8, 20), "Health", "-500.00"),
        tx(5, date(2026, 9, 2), "Lifestyle", "-60.00"), tx(6, date(2026, 6, 14), "Travel", "-203.95"),
        tx(7, date(2026, 9, 25), "Salary", "2500.00", tx_type="salary"),
    ]


def ctx(lang="en"):
    return ToolContext(customer_id="CUST00042", as_of=TODAY, conn=_FakeStore(), language=lang, _history=history())


def test_a_category_never_used_is_category_absent_with_the_customers_own_categories():
    with pytest.raises(MissingData) as exc:
        get_spending(ctx(), {"period": {"preset": "last_month"}, "filter": {"categories": ["Entertainment"]}})
    assert exc.value.reason == "category_absent"
    keys = [c["key"] for c in exc.value.details["top"]]
    assert "Health" not in keys and keys[:2] == ["Travel", "Groceries"]   # largest first, Health never (R9)


def test_a_category_used_before_but_not_in_the_period_is_an_empty_period_not_absent():
    result = get_spending(ctx(), {"period": {"preset": "last_month"}, "filter": {"categories": ["Travel"]}})
    assert result.model_view["total"]["value"] == 0


def test_too_few_purchases_are_shown_and_marked():
    result = get_spending(ctx(), {"period": {"preset": "last_6_months"}, "filter": {"categories": ["Travel"]}})
    assert result.model_view["total"]["value"] == 203.95
    assert any("no monthly habit" in n for n in result.model_view["notes"])


def test_the_top_categories_leave_health_out():
    rows = classify(history(), TODAY, None)
    assert "Health" not in [c["key"] for c in top_categories(rows, "en")]


def test_the_what_if_sql_default_for_too_few_purchases_is_the_setting():
    import re
    from pathlib import Path

    from core.tools import config
    sql = (Path(__file__).resolve().parents[2] / "metrics" / "04_what_if.sql").read_text(encoding="utf-8")
    m = re.search(r"app\.whatif_min_tx', true\), ''\), '(\d+)'\)", sql)
    assert m and int(m.group(1)) == config.TOO_FEW_TRANSACTIONS


@pytest.mark.parametrize("kind,value,lang,expected", [
    ("mcc", "1234", "en", "MCC 1234"),               # a code list without a name: never "purchases with MCC ..."
    ("mcc", "1234,5678", "fi", "MCC 1234, 5678"),
    ("category", "Travel", "en", "travel"),
])
def test_a_too_few_sentence_names_a_code_list_once(kind, value, lang, expected):
    from core.tools.what_if import WhatIfSelection, _purchases_of, _what
    sel = WhatIfSelection(kind=kind, value=value)
    assert _purchases_of(sel, _what(sel, None, lang), lang) == expected


@pytest.mark.parametrize("period,noted", [({"preset": "last_month"}, False), ({"preset": "last_6_months"}, True)])
def test_the_too_few_note_is_about_a_habit_over_months_never_one_month(period, noted):
    # review of #534: two grocery purchases in August are no "habit" question; over six months they are
    result = get_spending(ctx(), {"period": period, "filter": {"categories": ["Groceries"]}})
    assert result.model_view["tx_count"]["value"] == 2
    assert any("no monthly habit" in n for n in result.model_view["notes"]) is noted
