"""get_small_purchases against its reference SQL, 08_small_purchases.sql (#256), for the four personas only.
Skipped without DATABASE_URL. Read only, except the evidence specs every tool writes; SPIKE_REVIEWS is off
(conftest), so no label is read."""

from __future__ import annotations

from datetime import date

import pytest

from core.tools import metric_sql
from core.tools.context import ToolContext
from core.tools.small_purchases import get_small_purchases

AS_OF = date(2026, 9, 30)
PERSONAS = ("CUST00860", "CUST00493", "CUST00387", "CUST00849")


def number(n):
    return None if n is None else n.value


def money(v):
    return None if v is None else float(v)


@pytest.mark.parametrize("customer_id", PERSONAS)
def test_the_tool_and_the_reference_sql_agree(conn, customer_id):
    rows = metric_sql.run(conn, "08_small_purchases.sql", customer_id, AS_OF, {})
    total_row = next(r for r in rows if r["category"] == "all")
    d = get_small_purchases(ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn), {}).data
    assert (d.period.start, d.period.end) == (total_row["period_start"], total_row["period_end"])
    assert (d.count.value, d.total.value) == (total_row["count"], money(total_row["total_eur"]))
    assert number(d.average) == money(total_row["avg_eur"])
    assert number(d.month_average) == money(total_row["month_avg_eur"])
    assert d.flexible_total.value == money(total_row["flexible_total_eur"])
    assert number(d.share) == money(total_row["share_pct"])
    assert [(c.key, c.amount.value, number(c.share)) for c in d.categories] == [
        (r["category"], money(r["total_eur"]), money(r["share_pct"])) for r in rows if r["category"] != "all"]


def test_the_persona_numbers_of_the_design_document(conn):
    """docs/design/metrics.md section 12: count and total of the last 3 complete months, EUR 10."""
    got = {}
    for customer_id in PERSONAS:
        d = get_small_purchases(ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn), {}).data
        got[customer_id] = (d.count.value, d.total.value, number(d.month_average), d.few)
    assert got == {"CUST00860": (4, 28.73, 9.58, True), "CUST00493": (31, 156.04, 52.01, False),
                   "CUST00387": (5, 30.63, 10.21, False), "CUST00849": (1, 8.64, 2.88, True)}
