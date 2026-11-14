"""get_bonus_estimate on the shared database for the lead persona CUST00860 (#158). Skipped without
DATABASE_URL. One customer, the session connection (statement_timeout 60 s); the only writes are the
evidence specs the tool stores in coach_evidence.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from core.tools import bonus, evidence
from core.tools.baskets import months_with_history
from core.tools.context import ToolContext
from core.tools.formatting import money
from core.tools.spending import get_spending

LEAD = "CUST00860"
AS_OF = date(2026, 9, 30)


def run(conn, share_pct=None):
    ctx = ToolContext(customer_id=LEAD, as_of=AS_OF, conn=conn)
    return bonus.get_bonus_estimate(ctx, {} if share_pct is None else {"share_pct": share_pct}), ctx


def test_grocery_base_is_the_spending_tools_number_and_every_ref_reconciles(conn):
    result, ctx = run(conn)
    d = result.data
    period = d.grocery_month.period
    assert (period.start, period.end) == (date(2026, 4, 1), date(2026, 9, 30))
    # G = get_spending's Groceries total for the same period divided by n_months, to the cent
    spent = get_spending(ToolContext(customer_id=LEAD, as_of=AS_OF, conn=conn),
                         {"period": {"preset": "last_6_months"}, "filter": {"categories": ["Groceries"]}}).data
    assert (spent.period.start, spent.period.end) == (period.start, period.end)
    n_months = months_with_history(period.start, period.end, ctx.history()[0].tx_date)
    assert Decimal(str(d.grocery_month.value)) == money(Decimal(str(spent.total.value)) / n_months)
    # the derived numbers follow the document's formulas from G
    check = bonus.estimate(Decimal(str(d.grocery_month.value)), 100)
    assert Decimal(str(d.total_month.value)) == check.total_month and d.status == check.status
    for n in (d.grocery_month, d.level_base, d.bonus_percent, d.bonus_month, d.payment_benefit_month,
              d.total_month, d.total_year):
        res = evidence.resolve(conn, n.evidence_ref, LEAD)
        assert res.reconciles is True, f"{n.method} {n.evidence_ref} does not reconcile"


def test_the_result_is_stable_across_two_calls(conn):
    first, second = run(conn)[0].data, run(conn)[0].data
    refs = lambda d: [d.grocery_month.evidence_ref, d.level_base.evidence_ref, d.bonus_percent.evidence_ref,  # noqa: E731
                      d.bonus_month.evidence_ref, d.payment_benefit_month.evidence_ref,
                      d.total_month.evidence_ref, d.total_year.evidence_ref]
    assert refs(first) == refs(second)
    assert first.model_dump() == second.model_dump()


def test_a_share_changes_the_level_base_but_not_the_grocery_ref(conn):
    full, half = run(conn)[0].data, run(conn, share_pct=50)[0].data
    assert half.grocery_month.evidence_ref == full.grocery_month.evidence_ref
    assert Decimal(str(half.level_base.value)) == money(Decimal(str(full.grocery_month.value)) * 50 / 100)
