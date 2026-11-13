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


def ctx_for(conn, customer_id, language="en", as_of=AS_OF):
    return ToolContext(customer_id=customer_id, as_of=as_of, conn=conn, language=language)


def next_id(customer_id):
    return f"CUST{int(customer_id[4:]) + 1:05d}"


def run_metric(conn, file_name, customer_id, as_of=AS_OF):
    """Run a metric SQL file for [customer_id, next id) at as_of and return the last result as dicts."""
    conn.execute("SELECT set_config('app.demo_today', %s, false), set_config('app.customer_from', %s, false), "
                 "set_config('app.customer_to', %s, false)", (as_of.isoformat(), customer_id, next_id(customer_id)))
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
    # metrics wins: the total is 03's rounded sum; each item is rounded on its own (0.01 each at most)
    items = sum(dec(b.due_until_payday) for b in res.data.bills)
    assert abs(items - dec(res.data.upcoming_total)) <= Decimal("0.01") * len(res.data.bills)
    keys = {b.bill_id for b in res.data.bills}
    assert "bill_salary_sweep" not in keys and "bill_salary" not in keys    # transfer and income are not bills
    assert [i.key for i in res.data.income] == ["salary"]
    assert res.data.upcoming_total.method == "safe_to_spend.bills_due_eur@1"
    assert all(b.due_until_payday.method == "safe_to_spend.bill_due_eur@1" for b in res.data.bills)
    assert all(b.typical_month.method == "recurring.typical_month_eur@1" for b in res.data.bills)
    assert (res.card.estimate is not None) == any(b.status == "spread" for b in res.data.bills)


# Dates metrics.md itself checks for CUST00001 (sections 2 and 3): salary upcoming on 2026-09-14 (payday
# the next day), upcoming on its typical day 2026-05-15 (that month's salary came on the 29th, expected
# tomorrow), and late on 2026-05-20 (payday = month end).
@pytest.mark.parametrize("as_of, salary_status, payday", [
    (date(2026, 9, 14), "upcoming", date(2026, 9, 15)),
    (date(2026, 5, 15), "upcoming", date(2026, 5, 16)),
    (date(2026, 5, 20), "late", date(2026, 5, 31)),
])
def test_dates_with_salary_not_yet_paid_match_the_sql(conn, as_of, salary_status, payday):
    ctx = ctx_for(conn, "CUST00001", as_of=as_of)
    series = {s.key: s for s in recurring.detect(ctx.history(), as_of)}
    sql01 = {r["series_key"]: r for r in run_metric(conn, "01_recurring.sql", "CUST00001", as_of)}
    assert set(series) == set(sql01)
    for key, row in sql01.items():
        s = series[key]
        assert (s.status, s.next_expected, s.typical_day, money(s.typical_month)) == (
            row["status"], row["next_expected_date"], row["typical_day"], row["typical_month_eur"]), key
        expected_late = row["late_share_12m"]
        assert (s.late_share_12m is None) == (expected_late is None), key
        if expected_late is not None:
            assert s.late_share_12m.quantize(Decimal("0.01")) == expected_late, key
    res = get_recurring_bills(ctx)
    sql03 = run_metric(conn, "03_safe_to_spend.sql", "CUST00001", as_of)[0]
    assert (res.data.salary_status, res.data.next_payday) == (salary_status, payday)
    assert (res.data.salary_status, res.data.next_payday) == (sql03["salary_status"], sql03["next_payday"])
    # Metrics wins: the total is exactly 03's bills_due_eur (the rounded sum of unrounded terms), also
    # on 2026-05-20, where the sum of the rounded items is a cent higher.
    assert dec(res.data.upcoming_total) == sql03["bills_due_eur"]
    items = sum(dec(b.due_until_payday) for b in res.data.bills)
    assert abs(items - dec(res.data.upcoming_total)) <= Decimal("0.01") * len(res.data.bills)
    if as_of == date(2026, 5, 20):
        assert (dec(res.data.upcoming_total), items) == (Decimal("278.36"), Decimal("278.37"))
    for ref in res.evidence:
        assert evidence.resolve(conn, ref, "CUST00001", limit=200).reconciles is True


def test_the_bills_due_total_has_one_ref_and_resolves_to_all_bill_transactions(conn):
    res = get_recurring_bills(ctx_for(conn, "CUST00001"))
    total = res.data.upcoming_total
    assert sum(1 for ref in res.evidence if ref == total.evidence_ref) == 1
    r = evidence.resolve(conn, total.evidence_ref, "CUST00001", limit=200)
    n = conn.execute("""SELECT count(*) FROM transactions WHERE customer_id = %s AND tx_date <= %s
                        AND tx_type IN ('housing_payment', 'utilities_payment', 'investment_deposit')
                        AND tx_date BETWEEN %s AND %s""",
                     ("CUST00001", AS_OF, date(2026, 4, 1), date(2026, 9, 30))).fetchone()[0]
    assert r.kind == "transactions" and r.reconciles is True and r.row_count == n


@pytest.mark.parametrize("customer_id", CUSTOMERS)
def test_baskets_at_a_second_as_of_match_02_baskets_sql(conn, customer_id):
    as_of = date(2026, 9, 14)  # window 2026-03-01 .. 2026-08-31 (metrics.md section 9)
    res = get_basket_breakdown(ctx_for(conn, customer_id, as_of=as_of), {"period": {"preset": "last_6_months"}})
    assert (res.data.period.start, res.data.period.end) == (date(2026, 3, 1), date(2026, 8, 31))
    sql = {r["basket"]: r for r in run_metric(conn, "02_baskets.sql", customer_id, as_of)}
    got = {b.key: (dec(b.amount), dec(b.share)) for b in res.data.baskets}
    assert got == {k: (r["month_avg_eur"], r["share_pct"]) for k, r in sql.items()}


@pytest.mark.parametrize("customer_id", CUSTOMERS)
def test_baskets_for_one_month(conn, customer_id):
    res = get_basket_breakdown(ctx_for(conn, customer_id), {"period": {"preset": "last_month"}})
    assert (res.data.period.start, res.data.period.end, res.data.n_months) == (date(2026, 8, 1), date(2026, 8, 31), 1)
    rows = conn.execute(
        """SELECT category, sum(-amount_eur) FROM transactions
           WHERE customer_id = %s AND tx_date <= %s AND tx_date BETWEEN %s AND %s AND category <> ALL(%s)
           GROUP BY category""",
        (customer_id, AS_OF, date(2026, 8, 1), date(2026, 8, 31),
         ["Salary", "Other Income", "Invest Withdraw", "Invest Deposit", "Salary Sweep"])).fetchall()
    by_category = {c: Decimal(s) for c, s in rows}
    assert dec(res.data.total) == sum(by_category.values())                  # one month: average = total
    listed = {c.key: dec(c.amount) for b in res.data.baskets for c in b.categories}
    assert sum(listed.values()) == sum(by_category.values())
    assert set(listed) == set(by_category) or all(by_category[c] == 0 for c in set(by_category) - set(listed))


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
