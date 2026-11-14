"""The glossary (#568) on the shared database: the four personas, one customer per query, one connection, every
write rolled back (force_rollback). The own Number is the existing tool's Number: safe to spend is the hero's own
Number (the same value and evidence ref as the overview), the buffer is safe to spend's cushion.
Skipped without DATABASE_URL."""

from __future__ import annotations

from contextlib import contextmanager

import psycopg
import pytest
from fastapi.testclient import TestClient

from core.agent import glossary
from core.app.main import create_app
from core.app.settings import Settings

PERSONAS = ("CUST00860", "CUST00493", "CUST00349", "CUST00849")


class StubPool:
    """Hands out the test's connection, which is inside a rolled-back transaction."""

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
    conn = psycopg.connect(url.get_secret_value(), autocommit=True, application_name="core-tests-glossary")
    conn.execute("SET statement_timeout = '60s'")
    yield conn
    conn.close()


@pytest.fixture
def client(db_conn, monkeypatch, tmp_path):
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit"))
    with db_conn.transaction(force_rollback=True):
        app = create_app(Settings(_env_file=None, database_url=None))
        with TestClient(app, raise_server_exceptions=False) as c:
            app.state.pool = StubPool(db_conn)
            yield c


def ask(client, persona: str, question: str, language: str) -> dict:
    r = client.post("/api/ask", json={"customer_id": persona, "message": question, "language": language},
                    headers={"Accept": "application/json"})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("persona", PERSONAS)
def test_safe_to_spend_is_defined_with_the_heros_own_number(client, persona):
    answer = ask(client, persona, "What is safe to spend?", "en")
    assert answer["outcome"] == "answered"
    assert answer["text_rendered"].startswith(glossary.BY_KEY["safe_to_spend"].text[0])
    (number,) = answer["numbers"].values()
    assert number["method"].startswith("safe_to_spend.safe_to_spend_7d")
    r = client.get(f"/api/overview/{persona}")
    assert r.status_code == 200, r.text
    hero = r.json()["hero"]["primary"]
    assert (number["value"], number["evidence_ref"]) == (hero["value"], hero["evidence_ref"])


@pytest.mark.parametrize("persona", PERSONAS)
def test_the_buffer_is_safe_to_spends_cushion_in_finnish(client, persona):
    answer = ask(client, persona, "Mikä on puskuri?", "fi")
    assert answer["outcome"] == "answered"
    assert answer["text_rendered"].startswith(glossary.BY_KEY["buffer"].text[1])
    (number,) = answer["numbers"].values()
    assert number["method"].startswith("safe_to_spend.cushion")


@pytest.mark.parametrize("persona", PERSONAS)
def test_a_term_without_a_number_is_the_definition_alone(client, persona):
    answer = ask(client, persona, "What is a budget?", "en")
    assert answer["outcome"] == "answered" and answer["numbers"] == {}
    assert answer["text_rendered"] == glossary.BY_KEY["budget"].text[0]
