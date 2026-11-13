"""Database-backed tests for get_spending and the evidence store.

Skipped without DATABASE_URL. The reference sums are written as plain SQL with hard-coded dates,
independent of the tool's period resolver, classification and selection code. Every query is for
one customer and tx_date <= as_of (2026-09-30).
"""

import json
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest

from core.tools import evidence
from core.tools.context import ToolContext
from core.tools.spending import get_spending

AS_OF = date(2026, 9, 30)
NON_SPEND = ("Salary", "Other Income", "Invest Withdraw", "Invest Deposit", "Salary Sweep")


def ctx_for(conn, customer_id, language="en"):
    return ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn, language=language)


def sql_sum(conn, customer_id, start, end, where, params=()):
    row = conn.execute(
        f"""SELECT COALESCE(sum(-amount_eur), 0), count(*) FROM transactions
            WHERE customer_id = %s AND tx_date <= %s AND tx_date BETWEEN %s AND %s AND {where}""",
        (customer_id, AS_OF, start, end, *params),
    ).fetchone()
    return Decimal(row[0]), row[1]


def as_dec(number):
    return Decimal(str(number.value))


@pytest.mark.parametrize("customer_id", ["CUST00007", "CUST00008"])
def test_taxi_last_month_matches_sql(conn, customer_id):
    res = get_spending(ctx_for(conn, customer_id),
                       {"period": {"preset": "last_month"}, "filter": {"mcc_groups": ["taxi"]}})
    expected, n = sql_sum(conn, customer_id, date(2026, 8, 1), date(2026, 8, 31), "mcc = '4121'")
    assert n > 0
    assert (res.data.period.start, res.data.period.end) == (date(2026, 8, 1), date(2026, 8, 31))
    assert as_dec(res.data.total) == expected
    assert res.data.tx_count.value == n
    assert res.data.total.method == "spending.total@1" and res.data.tx_count.method == "spending.n_tx@1"


def test_taxi_last_month_empty(conn):
    res = get_spending(ctx_for(conn, "CUST00001"),
                       {"period": {"preset": "last_month"}, "filter": {"mcc_groups": ["taxi"]}})
    assert sql_sum(conn, "CUST00001", date(2026, 8, 1), date(2026, 8, 31), "mcc = '4121'") == (0, 0)
    assert (res.data.total.value, res.data.tx_count.value) == (0, 0)
    assert res.notes == ["No transactions in this period."]
    r = evidence.resolve(conn, res.data.total.evidence_ref, "CUST00001")
    assert (r.row_count, r.reconciles, r.rows) == (0, True, [])


@pytest.mark.parametrize("customer_id", ["CUST00007", "CUST00008"])
def test_restaurants_last_3_months_matches_sql(conn, customer_id):
    res = get_spending(ctx_for(conn, customer_id),
                       {"period": {"preset": "last_3_months"}, "filter": {"categories": ["Restaurants"]}})
    expected, n = sql_sum(conn, customer_id, date(2026, 7, 1), date(2026, 9, 30), "category = 'Restaurants'")
    assert n > 0
    assert (res.data.period.start, res.data.period.end) == (date(2026, 7, 1), date(2026, 9, 30))
    assert (as_dec(res.data.total), res.data.tx_count.value) == (expected, n)


@pytest.mark.parametrize("customer_id", ["CUST00007", "CUST00008"])
def test_total_by_category_last_month_matches_sql(conn, customer_id):
    res = get_spending(ctx_for(conn, customer_id),
                       {"period": {"preset": "last_month"}, "group_by": "category", "top_n": 10})
    rows = conn.execute(
        """SELECT category, sum(-amount_eur) FROM transactions
           WHERE customer_id = %s AND tx_date <= %s AND tx_date BETWEEN %s AND %s
             AND category <> ALL(%s) GROUP BY category""",
        (customer_id, AS_OF, date(2026, 8, 1), date(2026, 8, 31), list(NON_SPEND)),
    ).fetchall()
    expected = {c: Decimal(s) for c, s in rows}
    got = {g.key: as_dec(g.amount) for g in res.data.groups}
    assert got == expected                                   # no "other" group with top_n 10
    assert as_dec(res.data.total) == sum(expected.values())
    assert [g.key for g in res.data.groups] == sorted(expected, key=lambda c: (-expected[c], c))


@pytest.mark.parametrize("customer_id", ["CUST00007", "CUST00008"])
def test_every_evidence_ref_reconciles(conn, customer_id):
    res = get_spending(ctx_for(conn, customer_id),
                       {"period": {"preset": "last_month"}, "group_by": "category", "top_n": 3,
                        "compare_to": "previous_period"})
    assert res.data.comparison is not None and res.data.groups[-1].key == "other"
    kinds = set()
    for ref in res.evidence:
        r = evidence.resolve(conn, ref, customer_id, limit=200)
        kinds.add(r.kind)
        assert r.reconciles is True, ref
        if r.kind == "transactions":
            assert r.row_count == len(r.rows) or r.next_cursor is not None
    assert kinds == {"transactions", "composite"}


def test_evidence_pagination_and_rows(conn):
    res = get_spending(ctx_for(conn, "CUST00008"),
                       {"period": {"preset": "last_3_months"}, "filter": {"categories": ["Restaurants"]}})
    ref = res.data.total.evidence_ref
    first = evidence.resolve(conn, ref, "CUST00008", limit=5)
    seen, cursor = list(first.rows), first.next_cursor
    while cursor:
        page = evidence.resolve(conn, ref, "CUST00008", limit=5, cursor=cursor)
        seen += page.rows
        cursor = page.next_cursor
    assert len(seen) == first.row_count == res.data.tx_count.value
    assert sum(-Decimal(r["amount"]) for r in seen) == as_dec(res.data.total)
    assert {r["category"] for r in seen} == {"Restaurants"}
    assert all(r["merchant"] is None or not any(ch.isdigit() for ch in r["merchant"]["label"]) for r in seen)


def test_evidence_of_another_customer_is_refused(conn):
    res = get_spending(ctx_for(conn, "CUST00008"), {"period": {"preset": "last_month"}})
    with pytest.raises(evidence.EvidenceForbidden):
        evidence.resolve(conn, res.data.total.evidence_ref, "CUST00007")


def test_refs_stable_across_calls_and_languages(conn):
    args = {"period": {"preset": "last_month"}, "group_by": "category", "compare_to": "previous_period"}
    a = get_spending(ctx_for(conn, "CUST00007"), args)
    b = get_spending(ctx_for(conn, "CUST00007", language="fi"), args)
    assert a.evidence == b.evidence
    assert a.data.total.label != b.data.total.label  # labels differ, refs do not


def test_model_view_has_no_rows_ids_or_refs(conn):
    for group_by in ("merchant", "category", "week"):
        res = get_spending(ctx_for(conn, "CUST00008"),
                           {"period": {"preset": "last_3_months"}, "group_by": group_by, "compare_to": "previous_period"})
        text = json.dumps(res.model_view)
        for forbidden in (r"CUST\d", r"MRC-", r"ev_[0-9a-f]", r"\btx_\d", r"customer", r"balance", r'"rows"'):
            assert not re.search(forbidden, text), (group_by, forbidden)
    merchant_view = get_spending(ctx_for(conn, "CUST00008"),
                                 {"period": {"preset": "last_3_months"}, "group_by": "merchant"}).model_view
    assert all(g["key"].startswith("store_") or g["key"] in ("other", "no_merchant") for g in merchant_view["groups"])


def test_merchant_alias_filter_round_trip(conn):
    view = get_spending(ctx_for(conn, "CUST00008"),
                        {"period": {"preset": "last_3_months"}, "group_by": "merchant", "top_n": 5}).data
    top = next(g for g in view.groups if g.key.startswith("store_"))  # bills have no merchant
    res = get_spending(ctx_for(conn, "CUST00008"),
                       {"period": {"preset": "last_3_months"}, "filter": {"merchant": top.key}})
    assert res.data.total.value == top.amount.value
    with pytest.raises(ValueError):
        get_spending(ctx_for(conn, "CUST00008"),
                     {"period": {"preset": "last_3_months"}, "filter": {"merchant": "store_zzz"}})


# metrics.md section 1, worked numbers: month averages over 2026-04-01 .. 2026-09-30 (6 months).
BASKET_MONTH_AVG = {
    "CUST00001": {"regular_essentials": "1278.77", "unexpected_necessities": "409.17", "everyday_spending": "399.99"},
    "CUST00002": {"regular_essentials": "1129.45", "unexpected_necessities": "142.42", "everyday_spending": "430.29"},
    "CUST00006": {"regular_essentials": "169.32", "unexpected_necessities": "34.23", "everyday_spending": "49.99"},
}


@pytest.mark.parametrize("customer_id", sorted(BASKET_MONTH_AVG))
def test_basket_classification_matches_metrics_worked_numbers(conn, customer_id):
    res = get_spending(ctx_for(conn, customer_id),
                       {"period": {"preset": "last_6_months"}, "group_by": "basket", "top_n": 10})
    assert (res.data.period.start, res.data.period.end) == (date(2026, 4, 1), date(2026, 9, 30))
    # round(total / n_months, 2) as in 02_baskets.sql: PostgreSQL rounds half away from zero
    got = {g.key: str((as_dec(g.amount) / 6).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
           for g in res.data.groups}
    assert got == BASKET_MONTH_AVG[customer_id]
