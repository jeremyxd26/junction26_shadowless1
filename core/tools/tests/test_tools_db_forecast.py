"""get_balance_forecast against the database (#257): the four demo personas only, labels off (conftest).
Skipped without DATABASE_URL. Each persona runs 03_safe_to_spend.sql once per tool call."""

from __future__ import annotations

from datetime import date

import pytest

from core.app.api.schemas import BreakdownCard
from core.tools import evidence
from core.tools.context import ToolContext
from core.tools.forecast import get_balance_forecast
from core.tools.safe_to_spend import get_safe_to_spend

AS_OF = date(2026, 9, 30)
# balance today, bills before payday, usual spending a day, lowest point (14 Oct, the day before payday), status
EXPECTED = {
    "CUST00860": (14276.35, 928.50, 66.79, 12418.91, "comfortable"),
    "CUST00493": (10745.42, 1290.78, 14.71, 9254.15, "comfortable"),
    "CUST00349": (24310.32, 754.25, 46.70, 22906.97, "comfortable"),
    "CUST00849": (1902.64, 662.59, 42.99, 641.43, "above_zero"),
}


@pytest.mark.parametrize("customer_id", sorted(EXPECTED))
def test_the_forecast_uses_the_heros_balance_and_bills_and_every_number_reconciles(conn, customer_id):
    forecast = get_balance_forecast(ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn), {})
    hero = get_safe_to_spend(ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn), {})
    components = {c.key: c.amount for c in hero.data.components}
    data = forecast.data

    # The hero's own Numbers: same value, same evidence ref.
    for mine, key in ((data.balance_now, "balance"), (data.bills_until_payday, "bills_due")):
        assert (mine.value, mine.evidence_ref) == (components[key].value, components[key].evidence_ref)
    assert data.next_payday == hero.data.next_payday == date(2026, 10, 15)

    balance, bills, pace, low, status = EXPECTED[customer_id]
    assert (data.balance_now.value, data.bills_until_payday.value, data.daily_pace.value, data.lowest.value,
            data.status) == (balance, bills, pace, low, status)
    assert data.lowest_date == date(2026, 10, 14) and data.first_below_zero is None

    # Every number of the card re-runs and reconciles; the lowest point opens the hero's balance, the
    # bills due by that day and the pace.
    for number in (data.lowest, data.daily_pace, *(s.balance for s in data.steps)):
        assert evidence.resolve(conn, number.evidence_ref, customer_id).reconciles is True
    parts = {p["role"]: p for p in evidence.resolve(conn, data.lowest.evidence_ref, customer_id).parts}
    assert parts["balance"]["ref"] == components["balance"].evidence_ref
    assert parts["pace"]["ref"] == data.daily_pace.evidence_ref
    assert evidence.resolve(conn, parts["bills"]["ref"], customer_id).reconciles is True

    card = forecast.card.model_dump(mode="json")
    BreakdownCard.model_validate(card)
    assert card["display_hint"] == "time_series" and card["total"]["value"] == low
    assert [i["key"] for i in card["items"]][0] == "2026-09-30" and card["items"][-1]["key"] == "2026-10-14"
    assert [a["type"] for a in card["actions"]] == (["open_evidence"] if status == "comfortable"
                                                    else ["open_evidence", "ask"])


def test_with_a_pending_review_the_forecast_still_uses_the_heros_numbers(conn):
    """The lead persona with her spike review pending, as the dev demo serves her: the labels go into
    03's settings, so the hero's balance spec changes and the forecast's must change with it. The labels
    are put on the contexts; no review table is read."""
    def ctx():
        c = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=conn)
        c._labels = {606016: "unclassified"}
        return c

    forecast, hero = get_balance_forecast(ctx(), {}), get_safe_to_spend(ctx(), {})
    components = {c.key: c.amount for c in hero.data.components}
    data = forecast.data
    for mine, key in ((data.balance_now, "balance"), (data.bills_until_payday, "bills_due")):
        assert (mine.value, mine.evidence_ref) == (components[key].value, components[key].evidence_ref)
    plain = get_balance_forecast(ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=conn), {}).data
    assert data.balance_now.evidence_ref != plain.balance_now.evidence_ref   # the labels are in the spec
    assert data.daily_pace.value == plain.daily_pace.value                    # a pending spike is not usual spending
    for number in (data.lowest, data.daily_pace, *(s.balance for s in data.steps)):
        assert evidence.resolve(conn, number.evidence_ref, "CUST00860").reconciles is True
