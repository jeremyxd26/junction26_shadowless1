"""#560 on the database, the four personas (one customer per query): what already goes to savings beside the plan.
Only CUST00349 has a recurring investment deposit; the other three have none. Skipped without DATABASE_URL."""

from datetime import date

import pytest

from core.tools import evidence
from core.tools.bills import get_recurring_bills
from core.tools.context import ToolContext
from core.tools.savings_plan import get_savings_plan

AS_OF = date(2026, 9, 30)
PERSONAS = ["CUST00860", "CUST00493", "CUST00349", "CUST00849"]


def ctx_for(conn, customer_id, language="en"):
    return ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn, language=language)


def test_cust00349_already_sets_aside_its_investment_deposit(conn):
    data = get_savings_plan(ctx_for(conn, "CUST00349"), {}).data
    assert (data.saving_seen, data.already_saving.value, data.already_share.value) == (True, 242.95, 7.7)
    deposit = next(b for b in get_recurring_bills(ctx_for(conn, "CUST00349"), {}).data.bills
                   if b.category == "Invest Deposit")
    # the bills tool's own Number: the same method, value and evidence
    assert (data.already_saving.method, data.already_saving.value, data.already_saving.evidence_ref) == (
        deposit.typical_month.method, deposit.typical_month.value, deposit.typical_month.evidence_ref)
    rows = evidence.resolve(conn, data.already_saving.evidence_ref, "CUST00349", limit=50)
    assert rows.reconciles and rows.row_count == 6 and {r["category"] for r in rows.rows} == {"Invest Deposit"}
    share = evidence.resolve(conn, data.already_share.evidence_ref, "CUST00349")
    assert share.reconciles and share.kind == "composite"


@pytest.mark.parametrize("customer_id", ["CUST00860", "CUST00493", "CUST00849"])
def test_a_persona_without_a_regular_transfer_gets_no_numbers(conn, customer_id):
    data = get_savings_plan(ctx_for(conn, customer_id), {}).data
    assert (data.saving_seen, data.already_saving, data.already_share) == (False, None, None)


@pytest.mark.parametrize("customer_id, total, goal", [
    ("CUST00860", 63.17, 360.0), ("CUST00493", 30.38, 420.0), ("CUST00349", 76.99, 600.0), ("CUST00849", 67.12, 190.0),
])
def test_the_plan_total_and_the_goal_are_as_before(conn, customer_id, total, goal):
    data = get_savings_plan(ctx_for(conn, customer_id), {}).data
    assert (data.total_month.value, data.savings_goal.value) == (total, goal)
