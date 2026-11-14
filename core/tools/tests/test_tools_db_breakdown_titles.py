"""#567 on the shared database: CUST00860's spending breakdown by merchant group; the evidence of "Other" and of
"Everything else" is titled as the tool names the item, never "Total spending". One persona, one connection,
statement_timeout 60 s, every write rolled back. Skipped without DATABASE_URL."""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from core.app.api import evidence as evidence_api
from core.app.settings import Settings
from core.tools.context import ToolContext
from core.tools.spending import get_spending

PERSONA = "CUST00860"


@pytest.fixture(scope="module")
def conn():
    url = Settings().database_url
    if url is None:
        pytest.skip("DATABASE_URL is not set")
    c = psycopg.connect(url.get_secret_value(), autocommit=True, application_name="core-tests-breakdown-titles")
    c.execute("SET statement_timeout = '60s'")
    yield c
    c.close()


@pytest.mark.parametrize("language, other, rest", [("en", "Other", "Everything else"), ("fi", "Muut", "Kaikki muu")])
def test_the_breakdowns_other_and_everything_else_are_titled_by_what_they_hold(conn, language, other, rest):
    with conn.transaction(force_rollback=True):
        ctx = ToolContext(customer_id=PERSONA, as_of=date(2026, 9, 30), conn=conn, language=language)
        result = get_spending(ctx, {"period": {"preset": "last_6_months"}, "group_by": "mcc_group", "top_n": 3})
        titles = {}
        for g in result.data.groups:
            (spec,) = conn.execute("SELECT spec FROM coach_evidence WHERE ref = %s", (g.amount.evidence_ref,)).fetchone()
            titles[g.key] = (g.label, evidence_api._label_of(spec, language))
    assert titles["no_mcc_group"] == (other, other)
    assert titles["other"] == (rest, rest)
    assert all(label == title for label, title in titles.values()), titles
