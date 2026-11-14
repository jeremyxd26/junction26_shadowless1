"""metric_sql.run sets the one-customer range and as_of itself; no caller setting can replace them (#122)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pytest
from psycopg import pq

from core.tools import evidence, metric_sql

AS_OF = date(2026, 9, 30)


class FakeConnection:
    """Records every statement; enough of a psycopg connection for run()."""

    def __init__(self):
        self.calls: list[tuple[str, tuple | None]] = []
        self.info = type("Info", (), {"transaction_status": pq.TransactionStatus.IDLE})()

    @contextmanager
    def transaction(self):
        self.calls.append(("BEGIN", None))
        yield

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def cursor(self):
        conn = self

        class Cursor:
            description = None

            def execute(self, sql):
                conn.calls.append(("<metric file>", None))

            def nextset(self):
                return None

        return Cursor()

    def set_configs(self) -> list[tuple[str, str]]:
        """Every set_config call in sequence, as (name, value)."""
        return [(params[0], params[1]) for sql, params in self.calls if sql.startswith("SELECT set_config")]

    def settings(self) -> dict[str, str]:
        """The app.* settings in force at the end: a later set_config of a name wins, as in PostgreSQL."""
        out: dict[str, str] = {}
        for name, value in self.set_configs():
            out[name.lower()] = value   # PostgreSQL setting names ignore case
        return out


def test_the_issues_case_raises_before_the_database_is_touched():
    """The acceptance test of #122, as written: a settings key for the customer range."""
    conn = FakeConnection()
    with pytest.raises(ValueError, match="reserved"):
        metric_sql.run(conn, "04_what_if.sql", "CUST00860", AS_OF,
                       {"customer_from": "CUST00000", "customer_to": "CUST99999"})
    assert conn.calls == []


@pytest.mark.parametrize("name", [
    "demo_today", "customer_from", "customer_to", "customer_anything",
    "Customer_from", "CUSTOMER_TO", "Demo_Today", " customer_from", "customer_from ", "demo_today\n", "\tcustomer_to",
])
def test_reserved_names_in_any_case_or_with_whitespace_are_refused_before_the_database(name):
    conn = FakeConnection()
    with pytest.raises(ValueError, match="reserved"):
        metric_sql.run(conn, "04_what_if.sql", "CUST00860", AS_OF, {name: "CUST00000"})
    assert conn.calls == []
    assert metric_sql.is_reserved_setting(name)   # evidence.resolve refuses such a stored spec too


@pytest.mark.parametrize("name", ["what-if", "app.whatif", "whatif pct", "", "whatif;drop", "ÅÄÖ"])
def test_malformed_names_are_refused_before_the_database(name):
    conn = FakeConnection()
    with pytest.raises(ValueError, match="bad setting name"):
        metric_sql.run(conn, "04_what_if.sql", "CUST00860", AS_OF, {name: "x"})
    assert conn.calls == []


def test_a_normal_call_sets_the_one_customer_range_and_as_of():
    conn = FakeConnection()
    metric_sql.run(conn, "04_what_if.sql", "CUST00860", AS_OF, {"whatif": "category:Restaurants", "whatif_pct": "20"})
    # the real sequence: the caller's settings, then the server's date and customer range
    assert conn.set_configs() == [
        ("app.whatif", "category:Restaurants"), ("app.whatif_pct", "20"),
        ("app.demo_today", "2026-09-30"), ("app.customer_from", "CUST00860"), ("app.customer_to", "CUST00861"),
    ]
    assert conn.calls[0] == ("BEGIN", None) and conn.calls[1][0] == "SET TRANSACTION READ ONLY"
    assert conn.calls[-1][0] == "<metric file>"


def test_the_range_is_set_last_even_if_a_name_slipped_past_the_check(monkeypatch):
    """Defence in depth: with the check disabled, the server's three set_config calls still come after
    the caller's, so they are the ones in force (not only by a dict overwrite)."""
    monkeypatch.setattr(metric_sql, "check_settings", lambda settings: None)
    conn = FakeConnection()
    metric_sql.run(conn, "04_what_if.sql", "CUST00860", AS_OF,
                   {"customer_from": "CUST00000", "customer_to": "CUST99999", "demo_today": "2099-01-01"})
    assert conn.set_configs() == [
        ("app.customer_from", "CUST00000"), ("app.customer_to", "CUST99999"), ("app.demo_today", "2099-01-01"),
        ("app.demo_today", "2026-09-30"), ("app.customer_from", "CUST00860"), ("app.customer_to", "CUST00861"),
    ]
    s = conn.settings()
    assert (s["app.customer_from"], s["app.customer_to"], s["app.demo_today"]) == ("CUST00860", "CUST00861", "2026-09-30")


# ---- evidence.resolve: a stored metric spec with a reserved or malformed setting is refused (403) ------

class FakeEvidenceConnection:
    """Answers the evidence store's load with one stored spec and records every statement."""

    def __init__(self, owner: str, spec: dict):
        self.owner, self.spec, self.calls = owner, spec, []

    def execute(self, sql, params=None):
        self.calls.append(sql)
        conn = self

        class Result:
            def fetchone(self):
                if sql == evidence.LOAD_SQL:
                    return conn.owner, conn.spec
                return (1,) if "FROM customers" in sql else None   # the API's existence check finds the persona

        return Result()


def metric_spec(settings: dict) -> dict:
    return {"v": 1, "kind": "metric", "customer_id": "CUST00860", "as_of": "2026-09-30",
            "method": "safe_to_spend.safe_to_spend_7d_eur@1",
            "source": {"file": "03_safe_to_spend.sql", "column": "safe_to_spend_7d_eur", "settings": settings},
            "value": "180.26"}


@pytest.mark.parametrize("settings", [
    {"customer_from": "CUST00000"}, {"Customer_from": "CUST00000"}, {" demo_today": "2099-01-01"},
    {"what-if": "x"}, {"app.whatif": "x"}, {"": "x"},
])
def test_resolve_refuses_a_stored_spec_with_a_reserved_or_malformed_setting(settings):
    conn = FakeEvidenceConnection("CUST00860", metric_spec(settings))
    with pytest.raises(evidence.EvidenceForbidden):
        evidence.resolve(conn, "ev_0123456789ab", "CUST00860")
    assert conn.calls == [evidence.LOAD_SQL]   # nothing ran after the spec was loaded


def test_the_evidence_endpoint_answers_403_for_such_a_spec():
    """EvidenceForbidden is the API's 403 evidence_forbidden, not a 500. Only the pool is faked, so the
    endpoint's own customer checks (the persona allowlist of #101, where present, and the existence
    check) run as in production, for the persona CUST00860."""
    from fastapi.testclient import TestClient

    from core.app.main import create_app
    from core.app.settings import Settings

    stored = FakeEvidenceConnection("CUST00860", metric_spec({"what-if": "x"}))

    class Pool:
        @contextmanager
        def connection(self, timeout=None):
            yield stored

    with TestClient(create_app(Settings(_env_file=None, database_url=None)), raise_server_exceptions=False) as client:
        client.app.state.pool = Pool()
        response = client.get("/api/evidence/ev_0123456789ab", params={"customer_id": "CUST00860"})
        client.app.state.pool = None
    assert response.status_code == 403 and response.json()["error"]["code"] == "evidence_forbidden"
    assert evidence.LOAD_SQL in stored.calls   # the spec was loaded, and then refused
