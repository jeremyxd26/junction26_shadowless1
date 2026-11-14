"""#497 on the database, the lead persona CUST00860 only: spending on takeaway, bars and cinemas over the what-if
window is filtered, labelled with its group and reconciles; takeaway and bars together never exceed the
restaurants group. Skipped without DATABASE_URL. Read only, except the evidence specs every tool writes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core.app.api import evidence as evidence_api
from core.tools import evidence
from core.tools.context import ToolContext
from core.tools.spending import get_spending

AS_OF = date(2026, 9, 30)
LEAD = "CUST00860"
WINDOW = {"preset": "custom", "start": "2026-04-01", "end": "2026-09-30"}


def total(conn, group: str):
    ctx = ToolContext(customer_id=LEAD, as_of=AS_OF, conn=conn)
    return get_spending(ctx, {"period": WINDOW, "filter": {"mcc_groups": [group]}}).data.total


@pytest.mark.parametrize("group,label", [("takeaway", "Takeaway and fast food"), ("bars", "Bars"),
                                         ("cinemas", "Cinemas")])
def test_a_sub_group_total_is_named_and_reconciles(conn, group, label):
    n = total(conn, group)
    assert n.label == label and n.value > 0
    res = evidence.resolve(conn, n.evidence_ref, LEAD)
    assert res.reconciles is True
    assert evidence_api.build(conn, res, LEAD, "en").title.startswith(label + ", ")


def test_takeaway_and_bars_are_inside_the_restaurants_group(conn):
    parts = Decimal(str(total(conn, "takeaway").value)) + Decimal(str(total(conn, "bars").value))
    assert parts <= Decimal(str(total(conn, "restaurants").value))
