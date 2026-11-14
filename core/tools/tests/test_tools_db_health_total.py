"""#571 on the database, the four personas (one customer per query): the rules' plan for a plain health total is the
Health category's total, equal to a plain SQL sum, with evidence that reconciles; labelled Health. Skipped without
DATABASE_URL."""

from datetime import date
from decimal import Decimal

import pytest

from core.agent.model import PlanInput
from core.agent.rules import claim
from core.tools import evidence
from core.tools.context import ToolContext
from core.tools.spending import get_spending

AS_OF = date(2026, 9, 30)
PERSONAS = ["CUST00860", "CUST00493", "CUST00349", "CUST00849"]
TOOLS = [{"name": "get_spending", "description": "", "parameters_json_schema": {}}]


@pytest.mark.parametrize("customer_id", PERSONAS)
@pytest.mark.parametrize("question, language", [("How much did I spend at the pharmacy last month?", "en"),
                                                ("Paljonko käytin lääkkeisiin viime kuussa?", "fi")])
def test_the_health_total_is_the_category_sum(conn, customer_id, question, language):
    planned = [c for c in claim(PlanInput(question=question, language=language, as_of=AS_OF.isoformat(),
                                          tools=TOOLS)).calls if c.name == "get_spending"]
    assert len(planned) == 1 and planned[0].args["filter"] == {"categories": ["Health"]}
    res = get_spending(ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn, language=language), planned[0].args)
    expected, n = conn.execute(
        """SELECT COALESCE(sum(-amount_eur), 0), count(*) FROM transactions
           WHERE customer_id = %s AND tx_date <= %s AND tx_date BETWEEN %s AND %s AND category = 'Health'""",
        (customer_id, AS_OF, date(2026, 8, 1), date(2026, 8, 31))).fetchone()
    assert Decimal(str(res.data.total.value)) == Decimal(expected) and res.data.tx_count.value == n
    assert res.data.total.label in ("Health", "Terveys")              # the category's label, never the user's word
    rows = evidence.resolve(conn, res.data.total.evidence_ref, customer_id, limit=50)
    assert rows.reconciles and {r["category"] for r in rows.rows} <= {"Health"}
