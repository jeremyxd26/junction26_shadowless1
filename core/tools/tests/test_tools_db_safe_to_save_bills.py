"""Database-backed tests for the safe-to-save columns of 03_safe_to_spend.sql (metrics.md 3.1, #53) and the
per-bill output 03_safe_to_spend_bills.sql (metrics.md 3.2, #44).

Skipped without DATABASE_URL. One customer per query, tx_date <= as_of, read only.
"""

from datetime import date
from decimal import Decimal

import pytest

from core.tools import metric_sql
from core.tools.bills import get_recurring_bills
from core.tools.context import ToolContext

AS_OF = date(2026, 9, 30)
D = Decimal
PERSONAS = ["CUST00860", "CUST00493", "CUST00349", "CUST00849"]
SAMPLE = ["CUST00001", "CUST00002", "CUST00006"]

# metrics.md 3.1 and the contract examples card.safe_to_save* (as_of 2026-09-30, no labels):
# free until payday, everyday until payday, safe to save, free month, everyday month, safe to save monthly,
# essentials shortfall, reason, reason category, reason amount
SAVE_WORKED = {
    "CUST00860": ("12567.56", "295.28", "12272.28", "783.79", "599.18", "184.61", "0.00", None, None, None),
    "CUST00849": ("819.62", "258.98", "560.64", "725.47", "525.52", "199.95", "0.00", None, None, None),
    "CUST00019": ("573.53", "288.46", "285.07", "398.89", "585.33", "0.00", "0.00",
                  "largest_everyday_category", "Restaurants", "186.93"),
    "CUST00002": ("198.47", "188.40", "10.07", "-1.59", "382.30", "0.00", "1.59",
                  "essentials_exceed_income", None, "1.59"),
    "CUST00001": ("3523.49", "196.72", "3326.77", "448.66", "399.17", "49.48", "0.00", None, None, None),
    "CUST00006": ("4370.15", "24.59", "4345.56", "136.30", "49.89", "86.41", "0.00", None, None, None),
}
SAVE_COLUMNS = ("free_until_payday_eur", "everyday_until_payday_eur", "safe_to_save_eur", "free_month_eur",
                "everyday_month_eur", "safe_to_save_monthly_eur", "essentials_shortfall_month_eur",
                "save_reason", "save_reason_category", "save_reason_month_eur")

# metrics.md 3.2: (series_key, status, bill_due_eur) per bill due before payday 2026-10-15
BILLS_WORKED = {
    "CUST00001": [("housing_payment", "done_this_month", "528.38"), ("utilities_payment", "spread", "57.94")],
    "CUST00002": [("housing_payment", "skipped_this_month", "897.39"), ("utilities_payment", "spread", "48.75")],
    "CUST00006": [("utilities_payment", "spread", "65.76")],
}


def cases(customer_ids):
    """The persona cases run on the shared database; any other customer is a sample customer, read only on a
    private database (the sample_customer marker, #502, #508)."""
    return [c if c in PERSONAS else pytest.param(c, marks=pytest.mark.sample_customer) for c in customer_ids]


def as_text(value):
    return None if value is None else str(value)


@pytest.mark.parametrize("customer_id", cases(sorted(SAVE_WORKED)))
def test_safe_to_save_columns_equal_the_worked_numbers(conn, customer_id):
    row = metric_sql.run_one(conn, "03_safe_to_spend.sql", customer_id, AS_OF, {"cushion_eur": "100"})
    assert tuple(as_text(row[c]) for c in SAVE_COLUMNS) == SAVE_WORKED[customer_id]


# the two reason branches are CUST00019 and CUST00002 (sample); every persona can save something
@pytest.mark.parametrize("customer_id", cases(sorted(SAVE_WORKED) + ["CUST00349", "CUST00493"]))
def test_safe_to_save_rules(conn, customer_id):
    r = metric_sql.run_one(conn, "03_safe_to_spend.sql", customer_id, AS_OF, {"cushion_eur": "100"})
    # computed from unrounded terms, rounded once: within a cent of the displayed parts, never below 0
    assert abs(max(r["free_month_eur"] - r["everyday_month_eur"], D(0)) - r["safe_to_save_monthly_eur"]) <= D("0.01")
    assert abs(max(r["free_until_payday_eur"] - r["everyday_until_payday_eur"], D(0)) - r["safe_to_save_eur"]) <= D("0.01")
    assert r["safe_to_save_eur"] >= 0 and r["safe_to_save_monthly_eur"] >= 0 and r["essentials_shortfall_month_eur"] >= 0
    # a reason only when the month leaves nothing, chosen by the sign of free month
    if r["safe_to_save_monthly_eur"] > 0:
        assert r["save_reason"] is None and r["save_reason_month_eur"] is None
    elif r["free_month_eur"] < 0:
        assert r["save_reason"] == "essentials_exceed_income"
        assert r["save_reason_month_eur"] == r["essentials_shortfall_month_eur"] == -r["free_month_eur"]
    else:
        assert r["save_reason"] == "largest_everyday_category"
        assert r["save_reason_category"] not in (None, "Health")  # R9


@pytest.mark.parametrize("customer_id", cases(SAMPLE + PERSONAS))
def test_per_bill_rows_add_up_to_bills_due(conn, customer_id):
    total = metric_sql.run_one(conn, "03_safe_to_spend.sql", customer_id, AS_OF, {"cushion_eur": "100"})
    rows = metric_sql.run(conn, "03_safe_to_spend_bills.sql", customer_id, AS_OF)
    assert rows and all(r["customer_id"] == customer_id for r in rows)
    # each row rounded on its own, the total rounded once: at most half a cent per row apart
    assert abs(sum(r["bill_due_eur"] for r in rows) - total["bills_due_eur"]) <= D("0.005") * len(rows)
    assert all(r["next_payday"] == total["next_payday"] for r in rows)
    for r in rows:
        assert r["bill_due_eur"] > 0
        assert r["status"] in ("spread", "done_this_month", "upcoming", "late", "skipped_this_month")
        if r["status"] == "spread":
            assert r["occurrences"] == 0 and r["pro_rata_days"] == total["days_to_payday"]
        else:
            assert r["occurrences"] >= 1 and r["pro_rata_days"] == 0 and r["first_due_date"] <= r["next_payday"]


@pytest.mark.parametrize("customer_id", cases(sorted(BILLS_WORKED)))
def test_per_bill_rows_equal_the_worked_numbers(conn, customer_id):
    rows = metric_sql.run(conn, "03_safe_to_spend_bills.sql", customer_id, AS_OF)
    got = [(r["series_key"], r["status"], str(r["bill_due_eur"])) for r in rows]
    assert got == BILLS_WORKED[customer_id]


@pytest.mark.parametrize("customer_id", cases(SAMPLE + PERSONAS))
def test_per_bill_rows_equal_the_bills_tool(conn, customer_id):
    """safe_to_spend.bill_due_eur@1: the SQL rows and get_recurring_bills' due amounts are the same numbers."""
    rows = metric_sql.run(conn, "03_safe_to_spend_bills.sql", customer_id, AS_OF)
    sql = sorted((r["category"], r["status"], D(r["bill_due_eur"])) for r in rows)
    ctx = ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn, language="en")
    items = get_recurring_bills(ctx).data.bills
    tool = sorted((b.category, b.status, D(str(b.due_until_payday.value))) for b in items
                  if b.due_until_payday.value != 0)
    assert sql == tool
