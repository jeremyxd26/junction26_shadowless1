"""The answer's label state on the shared database (#196): the lead persona, one connection, every
write rolled back (force_rollback), and her review rows deleted inside that transaction first, so the
dev demo state neither affects the test nor is changed by it. Skipped without DATABASE_URL."""

from __future__ import annotations

from contextlib import contextmanager

import psycopg
import pytest
from agent_fakes import AS_OF
from fastapi.testclient import TestClient

from core.agent.api import label_steps
from core.agent.audit import AuditLog
from core.agent.model import FunctionCall, ScriptedModel
from core.agent.orchestrator import AskRequest, Pipeline
from core.agent.toolset import default_registry
from core.app.main import create_app
from core.app.settings import Settings
from core.tools import reviews

LEAD = "CUST00860"
SAFE_METHOD = "safe_to_spend.safe_to_spend_7d"


class StubPool:
    """Hands out the test's connection, which is inside a rolled-back transaction."""

    def __init__(self, conn) -> None:
        self.conn = conn

    @contextmanager
    def connection(self, timeout: float | None = None):
        yield self.conn

    def close(self) -> None:
        pass


class Counting:
    """The connection, counting every statement sent (execute calls on it and on its cursors)."""

    def __init__(self, conn) -> None:
        self._conn = conn
        self.statements = 0

    def execute(self, *args, **kwargs):
        self.statements += 1
        return self._conn.execute(*args, **kwargs)

    def cursor(self, *args, **kwargs):
        return _Cursor(self, self._conn.cursor(*args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._conn, name)


class _Cursor:
    def __init__(self, owner: Counting, cur) -> None:
        self._owner, self._cur = owner, cur

    def execute(self, *args, **kwargs):
        self._owner.statements += 1
        return self._cur.execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        self._owner.statements += 1
        return self._cur.executemany(*args, **kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._cur.__exit__(*exc)

    def __iter__(self):
        return iter(self._cur)

    def __getattr__(self, name):
        return getattr(self._cur, name)


class OneConnection:
    """DataAccess on one connection, without connection_if_free: calls run one by one (stable counts)."""

    def __init__(self, conn) -> None:
        self.conn = conn

    def customer_exists(self, customer_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM customers WHERE customer_id = %s", (customer_id,)).fetchone() is not None

    @contextmanager
    def connection(self):
        yield self.conn


@pytest.fixture(scope="module")
def db_conn():
    url = Settings().database_url
    if url is None:
        pytest.skip("DATABASE_URL is not set")
    conn = psycopg.connect(url.get_secret_value(), autocommit=True, application_name="core-tests-ask-labels")
    conn.execute("SET statement_timeout = '60s'")
    yield conn
    conn.close()


@pytest.fixture
def rolled_back(db_conn, monkeypatch, tmp_path):
    monkeypatch.setenv("SPIKE_REVIEWS", "on")
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit"))
    with db_conn.transaction(force_rollback=True):
        reviews.reset(db_conn, [LEAD])
        yield db_conn


@pytest.fixture
def client(rolled_back):
    app = create_app(Settings(_env_file=None, database_url=None))
    with TestClient(app, raise_server_exceptions=False) as c:
        app.state.pool = StubPool(rolled_back)
        yield c


def ask(client, question="How much can I safely spend?") -> dict:
    r = client.post("/api/ask", json={"customer_id": LEAD, "message": question, "language": "en"},
                    headers={"Accept": "application/json"})
    assert r.status_code == 200, r.text
    return r.json()


def safe_number(answer: dict) -> dict:
    return next(c["primary"] for c in answer["cards"] if (c.get("primary") or {}).get("method", "").startswith(SAFE_METHOD))


def overview(client) -> dict:
    r = client.get(f"/api/overview/{LEAD}")
    assert r.status_code == 200, r.text
    return r.json()


def test_the_first_answer_shows_the_pending_state_like_the_overview_that_follows(client):
    first = ask(client)                                  # the very first request: no review exists yet
    number = safe_number(first)
    assert number["value"] == 221.58
    review = next(c for c in first["cards"] if c["type"] == "review")
    hero = overview(client)["hero"]["primary"]
    assert (hero["value"], hero["evidence_ref"]) == (221.58, number["evidence_ref"])   # the same Number
    assert overview(client)["reviews"][0]["tx_ref"] == review["tx_ref"]                 # created once

    r = client.post("/api/baskets/label", json={"customer_id": LEAD, "tx_ref": review["tx_ref"],
                                                "basket": "unexpected_necessities", "language": "en"})
    assert r.status_code == 200, r.text
    after = ask(client)
    number = safe_number(after)
    assert number["value"] == 180.26 and not [c for c in after["cards"] if c["type"] == "review"]
    hero = overview(client)["hero"]["primary"]
    assert (hero["value"], hero["evidence_ref"]) == (180.26, number["evidence_ref"])


def run(pipeline, question="How much can I safely spend?"):
    events = []
    pipeline.run(AskRequest(customer_id=LEAD, message=question, language="en"), lambda e, p: events.append((e, p)))
    return events


def test_statement_count_of_an_answer_with_two_tool_calls(rolled_back, tmp_path, capsys):
    """Before: every tool call reads the labels itself. After: one read for the answer, shared."""
    plan = [FunctionCall("get_safe_to_spend", {}),
            FunctionCall("get_basket_breakdown", {"period": {"preset": "last_6_months"}}), FunctionCall("finish")]

    def measure(steps):
        counting = Counting(rolled_back)
        pipe = Pipeline(default_registry(), ScriptedModel(plans=[plan], drafts=["no json", "no json"]),
                        OneConnection(counting), as_of=AS_OF, audit=AuditLog(tmp_path / "a"), labels=steps)
        events = run(pipe)
        assert dict(events).get("done"), events
        return counting.statements

    first = measure(label_steps())     # the first answer creates Sanna's pending review
    after = measure(label_steps())     # the review exists: the warm path
    before = measure(None)             # the old way: each call reads the labels
    with capsys.disabled():
        print(f"\nstatements, answer with two tool calls: before {before}, after {after} "
              f"(first answer, creating the review: {first})")
    assert after < before
