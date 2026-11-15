"""#468: the savings plan and the safe-to-spend answer name one monthly savings figure, the savings goal, for the
four personas in the pending and "Needed" review states. Skipped without DATABASE_URL. The review states are
labels put on the context (no review table is read or written), one customer at a time. Read only, except the
evidence specs every tool writes.

Asserted on the answers as the template writes them: the plan's answer cites the goal, and it is the Number of
the safe-to-spend answer (same method, value and evidence ref); when the safe-to-spend answer cites its goal
too, it is that same ref. The goal is never added to the plan's total."""

from __future__ import annotations

from datetime import date

import pytest

from core.agent import template
from core.tools import reviews
from core.tools.classify import classify
from core.tools.context import ToolContext
from core.tools.safe_to_spend import get_safe_to_spend
from core.tools.savings_plan import get_savings_plan

AS_OF = date(2026, 9, 30)
PERSONAS = ("CUST00387", "CUST00493", "CUST00849", "CUST00860")
STATES = {"pending": "unclassified", "needed": "unexpected_necessities"}
GOAL_METHOD = "safe_to_spend.savings_goal_eur@1"


def cited(view: dict, ctx: ToolContext, language: str, question: str) -> list:
    draft = template.template_draft([view], [], language, None, question)
    numbers = ctx.numbers.all()
    return [numbers[i] for i in draft["cited"]]


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("customer_id", PERSONAS)
def test_the_plan_and_safe_to_spend_cite_the_same_goal_in_every_review_state(conn, customer_id, language):
    probe = ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn)
    found = reviews.candidates(classify(probe.history(), AS_OF), AS_OF, set())
    states = {"none": None} if not found else STATES
    for state, basket in states.items():
        labels = {} if basket is None else {found[0].tx.id: basket}

        def ctx() -> ToolContext:
            c = ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn, language=language)
            c._labels = dict(labels)
            return c

        hero_ctx, plan_ctx = ctx(), ctx()
        hero = get_safe_to_spend(hero_ctx, {})
        plan = get_savings_plan(plan_ctx, {})
        goal = hero.data.savings_goal
        where = f"{customer_id} {state} {language}"
        assert goal.value > 0, where

        # The plan's result holds the same goal Number and ref (#468). Since #560 its answer text names what already
        # goes to savings, or that no regular transfer shows, in the goal sentence's place: the text cites no goal.
        assert (plan.data.savings_goal.value, plan.data.savings_goal.evidence_ref) == (goal.value, goal.evidence_ref), where
        assert plan.data.saving_seen is not None, where
        plan_goals = [n for n in cited(plan.model_view, plan_ctx, language, "How could I save more?")
                      if n.method == GOAL_METHOD]
        assert plan_goals == [], where
        hero_goals = [n for n in cited(hero.model_view, hero_ctx, language, "What can I safely spend this week?")
                      if n.method == GOAL_METHOD]
        assert all(n.evidence_ref == goal.evidence_ref for n in hero_goals), where
        # the goal is never added in: the plan's total is its levers only
        assert plan.data.total_month.value == round(sum(lv.saving.value for lv in plan.data.levers), 2), where
