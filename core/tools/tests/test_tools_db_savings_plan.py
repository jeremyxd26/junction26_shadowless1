"""get_savings_plan on the shared database (#369), for the four personas only. Skipped without DATABASE_URL.
Read only, except the evidence specs every tool writes; SPIKE_REVIEWS is off (conftest), so no label is read."""

from __future__ import annotations

from datetime import date

import pytest

from core.tools import evidence
from core.tools.context import ToolContext
from core.tools.savings_plan import get_savings_plan
from core.tools.what_if import run_what_if

AS_OF = date(2026, 9, 30)
PERSONAS = {   # docs/design/metrics.md section 13
    "CUST00860": ((45.91, "Lifestyle", 17.26), 63.17, 758.04),
    "CUST00493": ((20.53, "Lifestyle", 9.85), 30.38, 364.56),
    "CUST00387": ((42.19, "Entertainment", 11.99), 54.18, 650.16),
    "CUST00849": ((55.50, "Entertainment", 11.62), 67.12, 805.44),
}


def context(conn, customer_id):
    return ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn)


@pytest.mark.parametrize("customer_id", sorted(PERSONAS))
def test_the_plan_of_each_persona(conn, customer_id):
    (first, other_key, other), month, year = PERSONAS[customer_id]
    result = get_savings_plan(context(conn, customer_id), {})
    d = result.data
    assert [(lv.key, lv.saving.value) for lv in d.levers] == [("Restaurants", first), (other_key, other)]
    assert (d.total_month.value, d.total_year.value) == (month, year)
    assert d.total_month.value == round(first + other, 2)   # the S-Bonus never in the total (#411: not shown at all)
    assert "bonus_estimate." not in result.card.model_dump_json() and "bonus_extra" not in result.model_view
    for n in (d.total_month, d.total_year):
        assert evidence.resolve(conn, n.evidence_ref, customer_id).reconciles is True


@pytest.mark.parametrize("customer_id", sorted(PERSONAS))
def test_the_first_lever_is_the_what_if_answer_to_the_cent(conn, customer_id):
    """The plan composes the what-if tool: its window and baseline, so "cut restaurants by 20%" in the chat
    and the plan's first row are the same number, with the same evidence ref."""
    plan = get_savings_plan(context(conn, customer_id), {}).data.levers[0].saving
    chat = run_what_if(context(conn, customer_id),
                       {"selection": {"kind": "category", "value": "Restaurants"}, "cut_pct": 20}).data.saving_per_month
    assert (plan.value, plan.evidence_ref, plan.period) == (chat.value, chat.evidence_ref, chat.period)
