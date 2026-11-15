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
# Two personas: the reference sums are plain SQL, so any customer with taxi and restaurant rows in the
# period and more than three spending categories proves them; the shared database is for the personas (#508).
CUSTOMERS = ["CUST00860", "CUST00493"]


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


@pytest.mark.parametrize("customer_id", CUSTOMERS)
def test_taxi_last_month_matches_sql(conn, customer_id):
    res = get_spending(ctx_for(conn, customer_id),
                       {"period": {"preset": "last_month"}, "filter": {"mcc_groups": ["taxi"]}})
    expected, n = sql_sum(conn, customer_id, date(2026, 8, 1), date(2026, 8, 31), "mcc = '4121'")
    assert n > 0
    assert (res.data.period.start, res.data.period.end) == (date(2026, 8, 1), date(2026, 8, 31))
    assert as_dec(res.data.total) == expected
    assert res.data.tx_count.value == n
    assert res.data.total.method == "spending.total@1" and res.data.tx_count.method == "spending.n_tx@1"


def test_parking_last_month_empty(conn):
    # CUST00493 parked nowhere in August (every persona took a taxi then)
    res = get_spending(ctx_for(conn, "CUST00493"),
                       {"period": {"preset": "last_month"}, "filter": {"mcc_groups": ["parking"]}})
    assert sql_sum(conn, "CUST00493", date(2026, 8, 1), date(2026, 8, 31), "mcc = '7523'") == (0, 0)
    assert (res.data.total.value, res.data.tx_count.value) == (0, 0)
    assert res.notes == ["No transactions in this period."]
    r = evidence.resolve(conn, res.data.total.evidence_ref, "CUST00493")
    assert (r.row_count, r.reconciles, r.rows) == (0, True, [])


@pytest.mark.parametrize("customer_id", CUSTOMERS)
def test_restaurants_last_3_months_matches_sql(conn, customer_id):
    res = get_spending(ctx_for(conn, customer_id),
                       {"period": {"preset": "last_3_months"}, "filter": {"categories": ["Restaurants"]}})
    expected, n = sql_sum(conn, customer_id, date(2026, 7, 1), date(2026, 9, 30), "category = 'Restaurants'")
    assert n > 0
    assert (res.data.period.start, res.data.period.end) == (date(2026, 7, 1), date(2026, 9, 30))
    assert (as_dec(res.data.total), res.data.tx_count.value) == (expected, n)


@pytest.mark.parametrize("customer_id", CUSTOMERS)
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


@pytest.mark.parametrize("customer_id", CUSTOMERS)
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


@pytest.mark.parametrize("customer_id", CUSTOMERS)
def test_comparison_and_other_group_match_sql(conn, customer_id):
    res = get_spending(ctx_for(conn, customer_id),
                       {"period": {"preset": "last_month"}, "group_by": "category", "top_n": 3,
                        "compare_to": "previous_period"})
    spend = "category <> ALL(%s)"
    aug, _ = sql_sum(conn, customer_id, date(2026, 8, 1), date(2026, 8, 31), spend, (list(NON_SPEND),))
    jul, _ = sql_sum(conn, customer_id, date(2026, 7, 1), date(2026, 7, 31), spend, (list(NON_SPEND),))
    cmp = res.data.comparison
    assert (cmp.baseline.period.start, cmp.baseline.period.end) == (date(2026, 7, 1), date(2026, 7, 31))
    assert as_dec(cmp.baseline) == jul
    assert as_dec(cmp.change) == aug - jul
    assert as_dec(cmp.change_pct) == ((aug - jul) / jul * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    assert cmp.tone.value == ("worse" if aug > jul else "better" if aug < jul else "neutral")
    top, other = res.data.groups[:3], res.data.groups[3]
    assert other.key == "other"
    assert as_dec(other.amount) == aug - sum(as_dec(g.amount) for g in top)
    jul_by_cat = dict(conn.execute(
        """SELECT category, sum(-amount_eur) FROM transactions
           WHERE customer_id = %s AND tx_date <= %s AND tx_date BETWEEN %s AND %s GROUP BY category""",
        (customer_id, AS_OF, date(2026, 7, 1), date(2026, 7, 31)),
    ).fetchall())
    for g in top:
        assert as_dec(g.change) == as_dec(g.amount) - Decimal(jul_by_cat.get(g.key, 0)), g.key


def test_time_groupings_have_no_per_group_change(conn):
    for group_by in ("month", "week"):
        res = get_spending(ctx_for(conn, "CUST00860"),
                           {"period": {"preset": "last_3_months"}, "group_by": group_by,
                            "compare_to": "previous_period"})
        assert res.data.comparison is not None
        assert res.data.groups and all(g.change is None for g in res.data.groups), group_by
        assert sum(as_dec(g.amount) for g in res.data.groups) == as_dec(res.data.total)
    months = [g.key for g in get_spending(ctx_for(conn, "CUST00860"),
                                          {"period": {"preset": "last_3_months"}, "group_by": "month"}).data.groups]
    assert months == ["2026-07", "2026-08", "2026-09"]


@pytest.mark.skip(reason="the first Eetu, CUST00349, is no persona since #882: the database runs read the four personas only, and none of them has a regular investment deposit")
def test_tone_is_neutral_for_saving_and_counts_are_integers(conn):
    # CUST00349 invests every month: an August deposit in both years
    res = get_spending(ctx_for(conn, "CUST00349"),
                       {"period": {"preset": "last_month"}, "filter": {"categories": ["Invest Deposit"]},
                        "compare_to": "same_period_last_year"})
    assert res.data.comparison.tone.value == "neutral"
    assert isinstance(res.data.tx_count.value, int)
    assert isinstance(res.model_view["tx_count"]["value"], int)
    assert re.search(r'"tx_count": \{"id": "n\d+", "value": \d+,', json.dumps(res.model_view))


def test_evidence_pagination_and_rows(conn):
    res = get_spending(ctx_for(conn, "CUST00860"),
                       {"period": {"preset": "last_3_months"}, "filter": {"categories": ["Restaurants"]}})
    ref = res.data.total.evidence_ref
    first = evidence.resolve(conn, ref, "CUST00860", limit=5)
    seen, cursor = list(first.rows), first.next_cursor
    while cursor:
        page = evidence.resolve(conn, ref, "CUST00860", limit=5, cursor=cursor)
        seen += page.rows
        cursor = page.next_cursor
    assert len(seen) == first.row_count == res.data.tx_count.value
    assert sum(-Decimal(r["amount"]) for r in seen) == as_dec(res.data.total)
    assert {r["category"] for r in seen} == {"Restaurants"}
    assert all(r["merchant"] is None or not any(ch.isdigit() for ch in r["merchant"]["label"]) for r in seen)


def test_evidence_collision_is_detected_in_the_store(conn):
    res = get_spending(ctx_for(conn, "CUST00860"), {"period": {"preset": "last_month"}})
    ref = res.data.total.evidence_ref
    _, stored = evidence.load(conn, ref)
    forged = dict(stored, value="0.01")                       # a different spec under an existing ref
    with pytest.raises(evidence.EvidenceCollision):
        evidence.write(conn, {ref: forged})
    assert evidence.load(conn, ref)[1] == stored              # unchanged
    assert evidence.resolve(conn, ref, "CUST00860").reconciles is True


def test_evidence_of_another_customer_is_refused(conn):
    res = get_spending(ctx_for(conn, "CUST00860"), {"period": {"preset": "last_month"}})
    with pytest.raises(evidence.EvidenceForbidden):
        evidence.resolve(conn, res.data.total.evidence_ref, "CUST00493")


def test_refs_stable_across_calls_and_languages(conn):
    args = {"period": {"preset": "last_month"}, "group_by": "category", "compare_to": "previous_period"}
    a = get_spending(ctx_for(conn, "CUST00860"), args)
    b = get_spending(ctx_for(conn, "CUST00860", language="fi"), args)
    assert a.evidence == b.evidence
    assert a.data.total.label != b.data.total.label  # labels differ, refs do not


def test_model_view_has_no_rows_ids_or_refs(conn):
    for group_by in ("merchant", "category", "week"):
        res = get_spending(ctx_for(conn, "CUST00860"),
                           {"period": {"preset": "last_3_months"}, "group_by": group_by, "compare_to": "previous_period"})
        text = json.dumps(res.model_view)
        for forbidden in (r"CUST\d", r"MRC-", r"ev_[0-9a-f]", r"\btx_\d", r"customer", r"balance", r'"rows"'):
            assert not re.search(forbidden, text), (group_by, forbidden)
    merchant_view = get_spending(ctx_for(conn, "CUST00860"),
                                 {"period": {"preset": "last_3_months"}, "group_by": "merchant"}).model_view
    assert all(g["key"].startswith("store_") or g["key"] in ("other", "no_merchant") for g in merchant_view["groups"])


def test_merchant_alias_filter_round_trip(conn):
    view = get_spending(ctx_for(conn, "CUST00860"),
                        {"period": {"preset": "last_3_months"}, "group_by": "merchant", "top_n": 5}).data
    top = next(g for g in view.groups if g.key.startswith("store_"))  # bills have no merchant
    res = get_spending(ctx_for(conn, "CUST00860"),
                       {"period": {"preset": "last_3_months"}, "filter": {"merchant": top.key}})
    assert res.data.total.value == top.amount.value
    with pytest.raises(ValueError):
        get_spending(ctx_for(conn, "CUST00860"),
                     {"period": {"preset": "last_3_months"}, "filter": {"merchant": "store_zzz"}})


# metrics.md section 1, worked numbers: month averages over 2026-04-01 .. 2026-09-30 (6 months).
BASKET_MONTH_AVG = {
    "CUST00001": {"regular_essentials": "1278.77", "unexpected_necessities": "409.17", "everyday_spending": "399.99"},
    "CUST00002": {"regular_essentials": "1129.45", "unexpected_necessities": "142.42", "everyday_spending": "430.29"},
    "CUST00006": {"regular_essentials": "169.32", "unexpected_necessities": "34.23", "everyday_spending": "49.99"},
}


# the worked numbers of metrics.md: sample customers, on a private database only (#502, #508)
@pytest.mark.parametrize("customer_id", [pytest.param(c, marks=pytest.mark.sample_customer)
                                         for c in sorted(BASKET_MONTH_AVG)])
def test_basket_classification_matches_metrics_worked_numbers(conn, customer_id):
    res = get_spending(ctx_for(conn, customer_id),
                       {"period": {"preset": "last_6_months"}, "group_by": "basket", "top_n": 10})
    assert (res.data.period.start, res.data.period.end) == (date(2026, 4, 1), date(2026, 9, 30))
    # round(total / n_months, 2) as in 02_baskets.sql: PostgreSQL rounds half away from zero
    got = {g.key: str((as_dec(g.amount) / 6).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
           for g in res.data.groups}
    assert got == BASKET_MONTH_AVG[customer_id]


@pytest.mark.parametrize("question,start,end,label", [
    ("how much did I spend over the last 5 years?", date(2024, 10, 1), date(2026, 9, 30), "1 Oct 2024 – 30 Sep 2026"),
    ("how much did I spend the year before last?", date(2024, 10, 1), date(2024, 12, 31), "1 Oct – 31 Dec 2024"),
])
def test_a_period_partly_before_the_data_shows_the_period_answered_not_the_one_asked(conn, question, start, end,
                                                                                     label):
    # #379 part B (the coordinator): until the partly-outside sentence follows, the card and the note name
    # the real period, from the data's first day, never 2021 or 1 January 2024
    from core.agent.rules import plan_spending
    res = get_spending(ctx_for(conn, "CUST00860"), plan_spending(question, AS_OF))
    assert (res.data.period.start, res.data.period.end, res.data.period.label) == (start, end, label)
    assert res.card.subtitle == label and any(label in n for n in res.notes)
    assert "2021" not in json.dumps(res.model_view, default=str) and "1 Jan 2024" not in json.dumps(res.model_view, default=str)
