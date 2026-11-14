"""The what-if words on the database (#346, #377), the four demo personas one at a time. Skipped without
DATABASE_URL. Read only, except the evidence specs every tool writes.

- Every example the what-if rule offers when it asks which spending leads to a real what-if (an estimate, not
  "nothing to cut") for each persona, in English and Finnish.
- "what if I took 10% fewer taxis?" is planned by the rules and named in words on the card (#377)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core.agent.model import PlanInput
from core.agent.rules import WHAT_IF_WHICH_OPTIONS, claim
from core.tools.context import ToolContext
from core.tools.what_if import run_what_if

AS_OF = date(2026, 9, 30)
PERSONAS = ("CUST00349", "CUST00493", "CUST00849", "CUST00860")
TOOLS = [{"name": "run_what_if", "description": "", "parameters_json_schema": {}}]


def planned(question: str, language: str) -> dict:
    found = claim(PlanInput(question=question, language=language, as_of=AS_OF.isoformat(), tools=TOOLS))
    assert found.rule == "what_if" and found.calls[0].name == "run_what_if", (question, found)
    return found.calls[0].args


@pytest.mark.parametrize("customer_id", PERSONAS)
def test_every_example_asked_back_is_a_real_what_if_for_each_persona(conn, customer_id):
    for i, language in enumerate(("en", "fi")):
        for option in WHAT_IF_WHICH_OPTIONS[i]:
            with_cut = option.rstrip("?") + (" by 10%?" if language == "en" else " 10 %?")
            args = planned(with_cut, language)
            result = run_what_if(ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn, language=language), args)
            data = result.data
            assert data.status in ("estimate", "estimate_with_caveat"), (customer_id, option, data.status)
            assert Decimal(str(data.saving_per_month.value)) > 0, (customer_id, option)


@pytest.mark.parametrize("question,language,label", [
    ("what if I took 10% fewer taxis?", "en", "Spend 10% less on taxis"),
    ("Entä jos käyttäisin takseja 10 % vähemmän?", "fi", "Käytä 10 % vähemmän: taksit"),
])
def test_the_taxi_what_if_is_planned_by_the_rules_and_named_in_words(conn, question, language, label):
    args = planned(question, language)
    assert args == {"selection": {"kind": "mcc", "value": "4121"}, "cut_pct": 10}
    result = run_what_if(ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=conn, language=language), args)
    assert result.data.scenario.label == label and result.card.title == label
    assert result.data.status == "estimate" and result.data.saving_per_month.value > 0
