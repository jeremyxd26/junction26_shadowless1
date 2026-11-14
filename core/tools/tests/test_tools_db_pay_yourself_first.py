"""#391 acceptance: pay yourself first, for the four personas in every spike-review state. Skipped without
DATABASE_URL. The review states are labels put on the context (no review table is read or written), one
customer at a time; each state runs 03_safe_to_spend.sql once, shared by both tools.

Asserted on the tools' own Number objects and 03's row, to the cent apart from rounding:
- the savings goal is one figure per customer: the same in every state (the spike review's purchase is
  left out of its run rates whatever the answer), rounded down to 10 euros;
- safe to spend x 30.4375/7 + goal <= free month, with equality when the budget side sets the limit:
  the spend and save figures no longer overlap (the #381 finding);
- the balance-side identity of #381 still holds;
- the hero and the safe-to-save card carry the same goal and weekly figure (the same evidence refs), the
  safe-to-spend evidence lists the goal as a part, and every number of the hero card reconciles."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core.tools import evidence, metric_sql, reviews
from core.tools.classify import classify
from core.tools.context import ToolContext
from core.tools.safe_to_save import get_safe_to_save
from core.tools.safe_to_spend import get_safe_to_spend, metric_row

AS_OF = date(2026, 9, 30)
GOALS = {"CUST00860": 360, "CUST00493": 420, "CUST00349": 600, "CUST00849": 190}
STATES = {"none": None, "pending": "unclassified", "needed": "unexpected_necessities", "my_choice": "everyday_spending"}
WEEKS_A_MONTH = Decimal("30.4375") / 7
ROUNDING = Decimal("0.05")


def d(number) -> Decimal:
    return Decimal(str(number.value))


@pytest.mark.parametrize("customer_id", sorted(GOALS))
def test_spend_and_save_add_up_and_the_goal_does_not_move_with_the_review(conn, customer_id):
    probe = ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn)
    found = reviews.candidates(classify(probe.history(), AS_OF), AS_OF, set())
    spike = found[0].tx.id if found else None
    states = {"none": None} if spike is None else STATES
    goals = set()
    for state, basket in states.items():
        labels = {} if basket is None else {spike: basket}

        def ctx():
            c = ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn)
            c._labels = dict(labels)
            return c

        hero_result = get_safe_to_spend(ctx(), {})
        hero, save = hero_result.data, get_safe_to_save(ctx(), {}).data
        _, row = metric_row(ctx())
        free_month = metric_sql.decimal(row["free_month_eur"])
        weekly, goal = d(hero.safe_to_spend), d(hero.savings_goal)
        where = f"{customer_id} {state}"
        goals.add(goal)

        assert goal == GOALS[customer_id] and goal % 10 == 0, where
        assert weekly * WEEKS_A_MONTH + goal <= free_month + ROUNDING, where
        if hero.binding_limit == "budget":
            assert abs(weekly * WEEKS_A_MONTH + goal - free_month) <= ROUNDING, where
        stock, n = d(save.stock), metric_sql.decimal(row["days_to_payday"])
        if stock > 0:
            pace = weekly / 7 * n
            assert abs((pace + stock - metric_sql.decimal(row["free_until_payday_eur"]))
                       - (pace - metric_sql.decimal(row["everyday_until_payday_eur"]))) <= ROUNDING, where

        assert save.savings_goal.evidence_ref == hero.savings_goal.evidence_ref, where
        assert save.safe_to_spend_week.evidence_ref == hero.safe_to_spend.evidence_ref, where
        parts = {p["role"]: p["ref"] for p in evidence.resolve(conn, hero.safe_to_spend.evidence_ref, customer_id).parts}
        assert parts["goal"] == hero.savings_goal.evidence_ref, where
        card = hero_result.card
        refs = [card.primary.evidence_ref] + [n.evidence_ref for n in card.secondary] + [
            c["amount"]["evidence_ref"] for c in card.components]
        for ref in refs:
            assert evidence.resolve(conn, ref, customer_id, limit=1).reconciles is True, (where, ref)
    assert len(goals) == 1


@pytest.mark.parametrize("basket, subtitle", [
    ("unclassified", "You could set aside about €360.00 a month on top of spending about €138.79 a week."),
    ("unexpected_necessities", "Your goal is €360.00 a month; at your usual pace about €184.61 a month would be left."),
])
def test_the_lead_personas_safe_to_save_subtitle(conn, basket, subtitle):
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=conn)
    ctx._labels = {606016: basket}
    assert get_safe_to_save(ctx, {}).card.subtitle == subtitle
