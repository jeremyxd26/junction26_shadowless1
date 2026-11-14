"""#673: a Finnish period sent alone plans spending for that period. The bare-period rule full-matches the message
against PRESETS, so each month alternative must end on the whole word (#656 had made it end in the prefix "kuukau",
and these messages got the general question back). No model, no database."""

from __future__ import annotations

import pytest

from core.agent import guard
from core.agent.model import PlanInput
from core.agent.rules import RuleModel
from core.agent.toolset import default_registry

TOOLS = default_registry().schemas()


def first_call(message: str):
    plan = RuleModel().plan(PlanInput(question=guard.clean(message), language="fi", as_of="2026-09-30", tools=TOOLS,
                                      history=[]))
    return next((c.name, c.args) for c in plan.calls if c.name != "finish")


ROWS = [(f"{gen} {n} kuukauden{tail}", preset)
        for gen in ("viimeisen", "viimeisten")
        for numbers, preset in ((("kolmen", "3"), "last_3_months"), (("kuuden", "6"), "last_6_months"),
                                (("kahdentoista", "12"), "last_12_months"))
        for n in numbers
        for tail in ("", " aikana")]


@pytest.mark.parametrize("message, preset", ROWS)
def test_a_bare_finnish_period_plans_spending_for_it(message, preset):
    assert first_call(message) == ("get_spending", {"period": {"preset": preset}})
    assert first_call(message[0].upper() + message[1:] + "?") == ("get_spending", {"period": {"preset": preset}})


def test_every_form_is_a_row():
    assert len(ROWS) == 24 and {p for _, p in ROWS} == {"last_3_months", "last_6_months", "last_12_months"}
