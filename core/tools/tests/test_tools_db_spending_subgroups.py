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


def test_restaurants_and_bars_is_the_restaurants_number_never_the_bars_alone(conn):
    """Review of #514, F2: the rules plan "restaurants and bars" as the Restaurants category, which holds the bars."""
    from core.agent.model import PlanInput
    from core.agent.rules import claim
    from core.agent.toolset import KNOWN_TOOLS

    tools = [{"name": t.function, "description": "", "parameters_json_schema": {}} for t in KNOWN_TOOLS]
    found = claim(PlanInput(question="how much did I spend on restaurants and bars last month", language="en",
                            as_of=AS_OF.isoformat(), tools=tools))
    ctx = ToolContext(customer_id=LEAD, as_of=AS_OF, conn=conn)
    asked = get_spending(ctx, found.calls[0].args).data.total
    restaurants = get_spending(ctx, {"period": {"preset": "last_month"},
                                     "filter": {"categories": ["Restaurants"]}}).data.total
    bars = get_spending(ctx, {"period": {"preset": "last_month"}, "filter": {"mcc_groups": ["bars"]}}).data.total
    assert (asked.label, asked.value) == (restaurants.label, restaurants.value) == ("Restaurants", restaurants.value)
    assert restaurants.value > bars.value
