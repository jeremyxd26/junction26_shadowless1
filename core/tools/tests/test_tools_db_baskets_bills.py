"""Database-backed tests for get_basket_breakdown and get_recurring_bills.

Skipped without DATABASE_URL. Both tools are compared, for the three sample customers of
metrics.md, with the output of the metric SQL files run for a one-customer range and with the
worked numbers in metrics.md sections 1 to 3. Every query is for one customer and tx_date <= as_of.
"""

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from core.tools import evidence, recurring
from core.tools.baskets import get_basket_breakdown
from core.tools.bills import get_recurring_bills
from core.tools.context import ToolContext
from core.tools.formatting import money

AS_OF = date(2026, 9, 30)
METRICS = Path(__file__).resolve().parents[2] / "metrics"
CUSTOMERS = ["CUST00001", "CUST00002", "CUST00006"]


def ctx_for(conn, customer_id, language="en"):
    return ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn, language=language)


def next_id(customer_id):
    return f"CUST{int(customer_id[4:]) + 1:05d}"


def run_metric(conn, file_name, customer_id):
    """Run a metric SQL file for [customer_id, next id) and return the last result as dicts."""
    conn.execute("SELECT set_config('app.demo_today', %s, false), set_config('app.customer_from', %s, false), "
                 "set_config('app.customer_to', %s, false)", (AS_OF.isoformat(), customer_id, next_id(customer_id)))
    rows = None
    with conn.cursor() as cur:
        cur.execute((METRICS / file_name).read_text(encoding="utf-8"))
        for _ in cur.results():
            if cur.description:
                names = [d.name for d in cur.description]
                rows = [dict(zip(names, r)) for r in cur.fetchall()]
    conn.execute("SET statement_timeout = '60s'")
    return rows


def dec(number):
    return Decimal(str(number.value))


# ---- baskets ---------------------------------------------------------------------------------------

# metrics.md section 1, worked numbers (window 2026-04-01 .. 2026-09-30, month averages and shares)
BASKETS_WORKED = {
    "CUST00001": {"regular_essentials": ("1278.77", "61.2"), "unexpected_necessities": ("409.17", "19.6"),
                  "everyday_spending": ("399.99", "19.2")},
    "CUST00002": {"regular_essentials": ("1129.45", "66.4"), "unexpected_necessities": ("142.42", "8.4"),
                  "everyday_spending": ("430.29", "25.3")},
    "CUST00006": {"regular_essentials": ("169.32", "66.8"), "unexpected_necessities": ("34.23", "13.5"),
                  "everyday_spending": ("49.99", "19.7")},
}


@pytest.mark.parametrize("customer_id", CUSTOMERS)
def test_baskets_match_02_baskets_sql_and_worked_numbers(conn, customer_id):
    res = get_basket_breakdown(ctx_for(conn, customer_id), {"period": {"preset": "last_6_months"}})
    data = res.data
    assert (data.period.start, data.period.end, data.monthly_average, data.n_months) == (
        date(2026, 4, 1), date(2026, 9, 30), True, 6)
    sql = {r["basket"]: r for r in run_metric(conn, "02_baskets.sql", customer_id)}
    got = {b.key: b for b in data.baskets}
    assert set(got) == set(sql)
    for key, row in sql.items():
        b = got[key]
        assert (dec(b.amount), dec(b.share)) == (row["month_avg_eur"], row["share_pct"]), key
        assert b.amount.method == "baskets.month_avg_eur@1" and b.amount.unit.value == "eur_per_month"
        # the amount's evidence is exactly the transactions classified into that basket
        r = evidence.resolve(conn, b.amount.evidence_ref, customer_id, limit=200)
        assert r.reconciles and r.row_count == row["n_tx"]
        rows, cursor = list(r.rows), r.next_cursor
        while cursor:
            page = evidence.resolve(conn, b.amount.evidence_ref, customer_id, limit=200, cursor=cursor)
            rows += page.rows
            cursor = page.next_cursor
        assert sum(-Decimal(x["amount"]) for x in rows) == row["total_eur"]
    worked = {k: (str(dec(b.amount)), str(dec(b.share))) for k, b in got.items()}
    assert worked == BASKETS_WORKED[customer_id]


@pytest.mark.parametrize("customer_id", CUSTOMERS)
def test_basket_total_matches_spender_profile_and_shares_add_up(conn, customer_id):
    res = get_basket_breakdown(ctx_for(conn, customer_id), {"period": {"preset": "last_6_months"}})
    sql = run_metric(conn, "05_spender_profile.sql", customer_id)[0]
    assert dec(res.data.total) == sql["spend_month_eur"]
    assert res.data.total.method == "spender_profile.spend_month_eur@1"
    shares = sum(dec(b.share) for b in res.data.baskets)
    assert abs(shares - 100) <= Decimal("0.2")
    for b in res.data.baskets:  # every category of the basket is listed and they add up
        assert abs(sum(dec(c.amount) for c in b.categories) - dec(b.amount)) <= Decimal("0.01") * len(b.categories)


def test_part_month_period_uses_period_totals(conn):
    res = get_basket_breakdown(ctx_for(conn, "CUST00001"),
                               {"period": {"preset": "custom", "start": "2026-09-01", "end": "2026-09-14"}})
    assert not res.data.monthly_average and res.data.n_months is None
    assert res.data.total.method == "spending.total@1"
    assert all(b.amount.method == "baskets.total_eur@1" and b.amount.unit.value == "eur" for b in res.data.baskets)
    expected = Decimal(conn.execute(
        """SELECT COALESCE(sum(-amount_eur), 0) FROM transactions
           WHERE customer_id = %s AND tx_date <= %s AND tx_date BETWEEN %s AND %s AND category <> ALL(%s)""",
        ("CUST00001", AS_OF, date(2026, 9, 1), date(2026, 9, 14),
         ["Salary", "Other Income", "Invest Withdraw", "Invest Deposit", "Salary Sweep"])).fetchone()[0])
    assert dec(res.data.total) == expected == sum(dec(b.amount) for b in res.data.baskets)


def test_health_is_only_a_line_inside_a_full_breakdown(conn):
    res = get_basket_breakdown(ctx_for(conn, "CUST00001"), {"period": {"preset": "last_6_months"}})
    unexpected = next(b for b in res.data.baskets if b.key == "unexpected_necessities")
    assert "Health" in [c.key for c in unexpected.categories]
    assert all(c.key != "Health" for b in res.data.baskets if b.key != "unexpected_necessities" for c in b.categories)
    text = " ".join([res.card.title, res.card.subtitle or ""] + res.notes)
    assert "Health" not in text and "health" not in text


# ---- recurring bills -------------------------------------------------------------------------------

# metrics.md sections 2 and 3, worked numbers (today 2026-09-30)
BILLS_WORKED = {
    "CUST00001": {"due": "586.32", "series": {
        "salary": ("2364.88", 15, "done_this_month", date(2026, 10, 15)),
        "housing_payment": ("528.38", 4, "done_this_month", date(2026, 10, 4)),
        "investment_deposit": ("227.74", 18, "done_this_month", date(2026, 10, 18)),
        "utilities_payment": ("117.57", None, "spread", None)}},
    "CUST00002": {"due": "946.14", "series": {
        "salary": ("1592.42", 15, "done_this_month", date(2026, 10, 15)),
        "housing_payment": ("897.39", 4, "skipped_this_month", date(2026, 10, 4)),
        "utilities_payment": ("98.93", None, "spread", None)}},
    "CUST00006": {"due": "65.76", "series": {
        "salary": ("3223.66", 15, "done_this_month", date(2026, 10, 15)),
        "salary_sweep": ("2885.82", 16, "done_this_month", date(2026, 10, 16)),
        "utilities_payment": ("133.45", None, "spread", None)}},
}


@pytest.mark.parametrize("customer_id", CUSTOMERS)
def test_series_match_01_recurring_sql_and_worked_numbers(conn, customer_id):
    ctx = ctx_for(conn, customer_id)
    series = {s.key: s for s in recurring.detect(ctx.history(), AS_OF)}
    sql = {r["series_key"]: r for r in run_metric(conn, "01_recurring.sql", customer_id)}
    assert set(series) == set(sql)
    for key, row in sql.items():
        s = series[key]
        assert (s.direction, s.months_present, s.tx_per_month, s.typical_day, s.status, s.next_expected,
                s.last_date, s.last_tx_id, s.n_tx_this_month) == (
            row["direction"], row["months_present"], row["tx_per_month"], row["typical_day"], row["status"],
            row["next_expected_date"], row["last_date"], row["last_tx_id"], row["n_tx_this_month"]), key
        assert money(s.typical_month) == row["typical_month_eur"], key
    for key, (typical, day, status, nxt) in BILLS_WORKED[customer_id]["series"].items():
        s = series[key]
        assert (str(money(s.typical_month)), s.status, s.next_expected) == (typical, status, nxt)
        if day is not None:
            assert s.typical_day == day


@pytest.mark.parametrize("customer_id", CUSTOMERS)
def test_bills_due_match_03_safe_to_spend_sql_and_worked_numbers(conn, customer_id):
    res = get_recurring_bills(ctx_for(conn, customer_id))
    sql = run_metric(conn, "03_safe_to_spend.sql", customer_id)[0]
    assert dec(res.data.upcoming_total) == sql["bills_due_eur"] == Decimal(BILLS_WORKED[customer_id]["due"])
    assert (res.data.next_payday, res.data.salary_status) == (sql["next_payday"], sql["salary_status"])
    assert sum(dec(b.due_until_payday) for b in res.data.bills) == dec(res.data.upcoming_total)
    keys = {b.bill_id for b in res.data.bills}
    assert "bill_salary_sweep" not in keys and "bill_salary" not in keys    # transfer and income are not bills
    assert [i.key for i in res.data.income] == ["salary"]
    assert res.data.upcoming_total.method == "safe_to_spend.bills_due_eur@1"
    assert all(b.due_until_payday.method == "safe_to_spend.bill_due_eur@1" for b in res.data.bills)
    assert all(b.typical_month.method == "recurring.typical_month_eur@1" for b in res.data.bills)
    assert (res.card.estimate is not None) == any(b.status == "spread" for b in res.data.bills)


def test_series_evidence_is_the_series_transactions(conn):
    res = get_recurring_bills(ctx_for(conn, "CUST00001"))
    housing = next(b for b in res.data.bills if b.bill_id == "bill_housing_payment")
    r = evidence.resolve(conn, housing.typical_month.evidence_ref, "CUST00001", limit=200)
    n = conn.execute("""SELECT count(*) FROM transactions WHERE customer_id = %s AND tx_date <= %s
                        AND tx_type = 'housing_payment' AND tx_date BETWEEN %s AND %s""",
                     ("CUST00001", AS_OF, date(2026, 4, 1), date(2026, 9, 30))).fetchone()[0]
    assert r.reconciles and r.row_count == n == len(r.rows)
    assert {x["category"] for x in r.rows} == {"Housing"} and all(x["merchant"] is None for x in r.rows)


# ---- both tools ------------------------------------------------------------------------------------

@pytest.mark.parametrize("customer_id", CUSTOMERS)
def test_every_evidence_ref_reconciles(conn, customer_id):
    for res in (get_basket_breakdown(ctx_for(conn, customer_id), {"period": {"preset": "last_6_months"}}),
                get_recurring_bills(ctx_for(conn, customer_id))):
        for ref in res.evidence:
            assert evidence.resolve(conn, ref, customer_id, limit=200).reconciles is True, (res.tool, ref)


def test_model_views_have_no_rows_ids_or_refs(conn):
    for customer_id in CUSTOMERS:
        for language in ("en", "fi"):
            ctx = ctx_for(conn, customer_id, language)
            for res in (get_basket_breakdown(ctx, {"period": {"preset": "last_6_months"}}),
                        get_recurring_bills(ctx)):
                text = json.dumps(res.model_view, ensure_ascii=False)
                for forbidden in (r"CUST\d", r"MRC-", r"ev_[0-9a-f]", r"\btx_\d", r"customer", r"balance", r'"rows"'):
                    assert not re.search(forbidden, text), (res.tool, forbidden)
                assert res.card is not None and res.card.type in ("breakdown", "bills")


def test_refs_are_the_same_in_both_languages(conn):
    a = get_recurring_bills(ctx_for(conn, "CUST00002"))
    b = get_recurring_bills(ctx_for(conn, "CUST00002", "fi"))
    assert a.evidence == b.evidence and a.data.bills[0].label != b.data.bills[0].label
