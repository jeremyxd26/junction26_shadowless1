"""Pure logic of get_basket_breakdown and get_recurring_bills. No database."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from core.tools import evidence, recurring
from core.tools.baskets import is_whole_months, months_with_history
from core.tools.bills import _ordinal
from core.tools.classify import classify
from core.tools.db import Tx
from core.tools.formatting import display
from core.tools.models import Unit


def tx(i, d, category, amount, tx_type="purchase", merchant=None, mcc=None):
    return Tx(i, d, datetime.combine(d, datetime.min.time()), category, tx_type, merchant, mcc, Decimal(amount))


# ---- status and next expected date (metrics.md section 2 table) ------------------------------------

@pytest.mark.parametrize("today, paid, expected", [
    (date(2026, 9, 14), False, ("upcoming", date(2026, 9, 15))),            # before the typical day
    (date(2026, 9, 15), False, ("upcoming", date(2026, 9, 16))),            # on it: still upcoming, tomorrow
    (date(2026, 9, 16), False, ("late", date(2026, 9, 17))),                # 1 day after: late, due tomorrow
    (date(2026, 9, 22), False, ("late", date(2026, 9, 23))),                # 7 days after: still late
    (date(2026, 9, 23), False, ("skipped_this_month", date(2026, 10, 15))),  # 8 days after: skipped
    (date(2026, 9, 20), True, ("done_this_month", date(2026, 10, 15))),
])
def test_bill_status_around_the_typical_day(today, paid, expected):
    assert recurring.status_and_next(today, "out", 1, paid, 15) == expected


def test_income_status_and_spread_and_month_end_clamp():
    assert recurring.status_and_next(date(2026, 9, 20), "in", 1, False, 15) == ("late", date(2026, 9, 30))
    assert recurring.status_and_next(date(2026, 9, 30), "in", 1, False, 15) == ("late", date(2026, 10, 1))
    assert recurring.status_and_next(date(2026, 9, 20), "out", 3, False, 15) == ("spread", None)
    # typical day 31 in a 30-day month is the 30th; next month is clamped to its own end
    assert recurring.status_and_next(date(2026, 9, 29), "out", 1, False, 31) == ("upcoming", date(2026, 9, 30))
    assert recurring.status_and_next(date(2026, 1, 31), "out", 1, True, 31) == ("done_this_month", date(2026, 2, 28))


def test_percentile_disc_is_the_lower_median():
    assert recurring.percentile_disc_half([1, 3]) == 1
    assert recurring.percentile_disc_half([3, 1, 1]) == 1
    assert recurring.percentile_disc_half([3, 3, 3, 1]) == 3


# ---- series detection (01_recurring.sql) -----------------------------------------------------------

TODAY = date(2026, 9, 30)   # window 2026-04-01 .. 2026-09-30


def history_for_series():
    h, i = [], 0
    for m in range(4, 10):  # April .. September
        i += 1
        h.append(tx(i, date(2026, m, 4), "Housing", "-800.00", "housing_payment"))
        for d in (5, 15, 25):
            i += 1
            h.append(tx(i, date(2026, m, d), "Utilities", f"-{30 + d}.00", "utilities_payment"))
        i += 1
        h.append(tx(i, date(2026, m, 15), "Salary", "2500.00", "salary"))
        i += 1
        h.append(tx(i, date(2026, m, 16), "Salary Sweep", "-2000.00", "salary_sweep"))
        i += 1
        h.append(tx(i, date(2026, m, 10), "Entertainment", "-9.99", merchant="MRC-ENT-0001", mcc="7999"))  # stable
        if m >= 7:  # only 3 months: not recurring
            i += 1
            h.append(tx(i, date(2026, m, 12), "Lifestyle", "-20.00", merchant="MRC-LIF-0001", mcc="5999"))
        i += 1
        h.append(tx(i, date(2026, m, 20), "Restaurants", "-15.00", merchant="MRC-RES-0001", mcc="5812"))
        i += 1
        h.append(tx(i, date(2026, m, 21), "Restaurants", "-25.00", merchant="MRC-RES-0001", mcc="5812"))  # twice a month
    return h


def test_detect_series():
    by_key = {s.key: s for s in recurring.detect(history_for_series(), TODAY)}
    assert set(by_key) == {"housing_payment", "utilities_payment", "salary", "salary_sweep", "MRC-ENT-0001"}
    assert by_key["utilities_payment"].status == "spread" and by_key["utilities_payment"].tx_per_month == 3
    assert by_key["housing_payment"].typical_month == Decimal("800.00") and by_key["housing_payment"].typical_day == 4
    assert by_key["salary"].direction == "in" and by_key["salary"].status == "done_this_month"
    assert by_key["MRC-ENT-0001"].kind == "merchant"


def test_payday_and_bills_due():
    series = recurring.detect(history_for_series(), TODAY)
    pay = recurring.payday(series, TODAY)
    assert (pay.date, pay.salary_status, pay.days) == (date(2026, 10, 15), "received_this_month", 15)
    dues = {d.series.key: d for d in recurring.bills_due(series, TODAY, pay)}
    assert "salary_sweep" not in dues and "salary" not in dues           # a transfer and income: no bills
    assert dues["housing_payment"].due_dates == (date(2026, 10, 4),)     # paid in September, due on the 4th
    assert dues["utilities_payment"].factor == (Decimal(15), Decimal("30.4375"))
    assert dues["MRC-ENT-0001"].due_dates == (date(2026, 10, 10),)


def test_bills_due_total_rounds_once_while_items_round_each():
    """Metrics wins: total = round(sum of unrounded terms); items are rounded one by one."""
    from core.tools import config
    from core.tools.classify import classify
    from core.tools.selection import Selection, select, value_of

    h = []
    for i, m in enumerate(range(4, 10), 1):   # two monthly bills of 10.00, each due 1/3 of a month
        h.append(tx(i, date(2026, m, 5), "Housing", "-10.00", "housing_payment"))
        h.append(tx(100 + i, date(2026, m, 6), "Utilities", "-10.00", "utilities_payment"))
    rows = classify(h, TODAY)
    both = Selection(direction="out", start=date(2026, 4, 1), end=TODAY,
                     series_keys=("housing_payment", "utilities_payment"))
    total = value_of(select(rows, both), both, config.METHODS["bills_due"],
                     {"factors": {"housing_payment": ["1", "3"], "utilities_payment": ["1", "3"]}})
    one = Selection(direction="out", start=date(2026, 4, 1), end=TODAY, series_key="housing_payment")
    item = value_of(select(rows, one), one, config.METHODS["bill_due"], {"factor_num": "1", "factor_den": "3"})
    assert (item, 2 * item, total) == (Decimal("3.33"), Decimal("6.66"), Decimal("6.67"))


def test_payday_without_salary_and_skipped_bill():
    h = [tx(i, date(2026, m, 3), "Housing", "-500.00", "housing_payment") for i, m in enumerate(range(3, 9), 1)]
    series = recurring.detect(h, TODAY)
    pay = recurring.payday(series, TODAY)
    assert (pay.date, pay.salary_status) == (TODAY + timedelta(days=30), "no_salary_series")
    housing = series[0]
    assert housing.status == "skipped_this_month"                        # due on the 3rd, now 27 days late
    due = recurring.bills_due(series, TODAY, pay)[0]
    assert due.due_dates == (date(2026, 10, 3),)                          # September skipped, October counts


class _FakeStore:
    """Stands in for the database in evidence.write (ON CONFLICT DO NOTHING, then read back)."""

    def __init__(self):
        self.rows = {}

    def cursor(self):
        store = self

        class _Cur:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def executemany(self, sql, params):
                for ref, _customer, spec in params:
                    store.rows.setdefault(ref, spec.obj)

        return _Cur()

    def execute(self, sql, params):
        class _Res:
            def __init__(self, rows):
                self._rows = rows

            def fetchall(self):
                return self._rows

        return _Res([(r, self.rows[r]) for r in params[0] if r in self.rows])


def test_merchant_bill_goes_through_the_tool_without_its_id():
    import json

    from core.tools.bills import get_recurring_bills
    from core.tools.context import ToolContext

    ctx = ToolContext(customer_id="CUST00042", as_of=TODAY, conn=_FakeStore(), _history=history_for_series())
    res = get_recurring_bills(ctx)
    merchant_bill = next(b for b in res.data.bills if b.category == "Entertainment")
    assert merchant_bill.bill_id.startswith("bill_") and len(merchant_bill.bill_id) == 15
    assert merchant_bill.label == "Entertainment A"                       # the alias label
    assert (merchant_bill.status, merchant_bill.typical_day) == ("done_this_month", 10)
    text = json.dumps([res.data.model_dump(mode="json"), res.card.model_dump(mode="json"), res.model_view])
    assert "MRC-" not in text and "CUST" not in json.dumps(res.model_view)
    assert merchant_bill.due_until_payday.value == 9.99                   # due on 10 Oct, before payday


# ---- baskets ---------------------------------------------------------------------------------------

def test_spike_and_customer_label_move_a_transaction_between_baskets():
    h = [tx(i, date(2026, 9, 1 + i), "Groceries", "-20.00", merchant=f"MRC-GRO-{i:04d}", mcc="5411")
         for i in range(1, 11)]
    h.append(tx(50, date(2026, 9, 20), "Groceries", "-150.00", merchant="MRC-GRO-0001", mcc="5411"))  # > 5 x 20
    by_id = {c.tx.id: c for c in classify(h, TODAY)}
    assert by_id[1].basket == "regular_essentials"
    assert by_id[50].basket == "unexpected_necessities"                   # the spike moved it
    labelled = {c.tx.id: c for c in classify(h, TODAY, {1: "everyday_spending"})}
    assert labelled[1].basket == "everyday_spending" and labelled[1].overridden   # a customer label wins


def test_shares_add_up_to_100_within_rounding():
    parts = [Decimal("1278.77"), Decimal("409.17"), Decimal("399.99")]
    whole = sum(parts)
    shares = [evidence.compute_formula("share_pct", {"part": p, "whole": whole}) for p in parts]
    assert shares == [Decimal("61.2"), Decimal("19.6"), Decimal("19.2")]
    assert abs(sum(shares) - 100) <= Decimal("0.1") * len(shares)


def test_whole_months_and_months_with_history():
    assert is_whole_months(date(2026, 4, 1), date(2026, 9, 30))
    assert not is_whole_months(date(2026, 9, 1), date(2026, 9, 14))
    assert months_with_history(date(2026, 4, 1), date(2026, 9, 30), date(2024, 10, 3)) == 6
    assert months_with_history(date(2026, 4, 1), date(2026, 9, 30), date(2026, 7, 20)) == 3
    assert months_with_history(date(2026, 4, 1), date(2026, 9, 30), date(2026, 9, 30)) == 1


def test_display_units_and_ordinals():
    assert display(Decimal("1180.21"), Unit.EUR_PER_MONTH) == "€1,180.21 a month"
    assert display(Decimal("1180.21"), Unit.EUR_PER_MONTH, "fi") == "1 180,21 € / kk"
    assert [_ordinal(d, "en") for d in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 31)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "31st"]
