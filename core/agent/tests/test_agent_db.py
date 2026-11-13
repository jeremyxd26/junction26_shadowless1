"""End to end on the shared database for ONE sample customer: the default registry (real
get_spending), the rule model, the validator and the audit record. One connection, statement_timeout
60 s (core/tools/db.py), nothing created except evidence specs in coach_evidence. Skipped without
DATABASE_URL; the connection details and driver errors are never printed."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from conftest import AS_OF, audit_records, run

from core.agent.audit import AuditLog
from core.agent.orchestrator import Pipeline
from core.agent.rules import RuleModel
from core.agent.toolset import default_registry
from core.tools import db

CUSTOMER = "CUST00860"


class OneConnection:
    def __init__(self, conn) -> None:
        self.conn = conn

    def customer_exists(self, customer_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM customers WHERE customer_id = %s", (customer_id,)).fetchone() is not None

    @contextmanager
    def connection(self):
        yield self.conn


@pytest.fixture(scope="module")
def conn():
    if not db.database_url(required=False):
        pytest.skip("DATABASE_URL is not set; the database test is skipped")
    connection = db.connect()
    yield connection
    connection.close()


def test_taxi_question_end_to_end(conn, tmp_path):
    pipe = Pipeline(default_registry(), RuleModel(), OneConnection(conn), as_of=AS_OF, audit=AuditLog(tmp_path))
    events = run(pipe, "How much did I spend on taxis last month?", customer_id=CUSTOMER)
    names = [e for e, _ in events]
    assert names[0] == "meta" and names[-1] == "done" and "card" in names
    done = dict(events)["done"]
    assert done["outcome"] == "answered"

    expected = conn.execute(
        "SELECT COALESCE(sum(-amount_eur), 0), count(*) FROM transactions "
        "WHERE customer_id = %s AND mcc = '4121' AND tx_date BETWEEN '2026-08-01' AND '2026-08-31'",
        (CUSTOMER,)).fetchone()
    numbers = {k: v for e, p in events if e == "numbers" for k, v in p["numbers"].items()}
    by_method = {n["method"]: n for n in numbers.values()}
    assert by_method["spending.total@1"]["value"] == float(expected[0])
    assert by_method["spending.n_tx@1"]["value"] == expected[1]
    assert all(n["evidence_ref"].startswith("ev_") for n in numbers.values())
    assert by_method["spending.total@1"]["display"] in done["text_rendered"]

    record = audit_records(pipe)[-1]
    assert record["customer_id"] == CUSTOMER and record["outcome"] == "answered"
    assert record["tool_outputs"] and "rows" not in str(record["tool_outputs"])
