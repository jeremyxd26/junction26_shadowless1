"""The answer reads the labels of the request's viewer (#253), on the shared database: the lead persona,
one connection, every write rolled back, on session-private copies of the review tables
(reviews.private_tables), so the live table is never touched. Skipped without DATABASE_URL."""

from __future__ import annotations

from contextlib import contextmanager

import psycopg
import pytest
from fastapi.testclient import TestClient

from core.app.api import viewer
from core.app.main import create_app
from core.app.settings import Settings
from core.tools import reviews

LEAD = "CUST00860"
SAFE_METHOD = "safe_to_spend.safe_to_spend_7d"
A, B = viewer.new_value(), viewer.new_value()


class StubPool:
    def __init__(self, conn) -> None:
        self.conn = conn

    @contextmanager
    def connection(self, timeout: float | None = None):
        yield self.conn

    def close(self) -> None:
        pass


@pytest.fixture(scope="module")
def db_conn():
    url = Settings().database_url
    if url is None:
        pytest.skip("DATABASE_URL is not set")
    conn = psycopg.connect(url.get_secret_value(), autocommit=True, application_name="core-tests-ask-viewer")
    conn.execute("SET statement_timeout = '60s'")
    yield conn
    conn.close()


@pytest.fixture
def client(db_conn, monkeypatch, tmp_path):
    monkeypatch.setenv("SPIKE_REVIEWS", "on")
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit"))
    with db_conn.transaction(force_rollback=True):
        reviews.private_tables(db_conn)  # no lock on the shared tables
        app = create_app(Settings(_env_file=None, database_url=None))
        with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as c:
            app.state.pool = StubPool(db_conn)
            yield c


def as_viewer(client, value: str) -> None:
    client.cookies.clear()
    client.cookies.set(viewer.COOKIE, value, domain="testserver.local")


def safe_to_spend(client, value: str) -> float:
    as_viewer(client, value)
    r = client.post("/api/ask", json={"customer_id": LEAD, "message": "What can I safely spend this week?",
                                      "language": "en"}, headers={"Accept": "application/json"})
    assert r.status_code == 200, r.text
    return next(c["primary"]["value"] for c in r.json()["cards"]
                if (c.get("primary") or {}).get("method", "").startswith(SAFE_METHOD))


def test_two_viewers_get_their_own_safe_to_spend_in_the_chat(client):
    as_viewer(client, A)
    card = client.get(f"/api/overview/{LEAD}").json()["reviews"][0]       # the review, created for everyone
    as_viewer(client, A)
    r = client.post("/api/baskets/label", json={"customer_id": LEAD, "tx_ref": card["tx_ref"],
                                                "basket": "unexpected_necessities", "language": "en"})
    assert r.status_code == 200, r.text
    assert safe_to_spend(client, A) == 180.26     # A answered "Needed": the hero and the chat agree
    assert safe_to_spend(client, B) == 221.58     # B has not answered: still pending
