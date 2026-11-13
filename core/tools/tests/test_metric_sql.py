"""metric_sql.run sets the one-customer range and as_of itself; no caller setting can replace them (#122)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pytest
from psycopg import pq

from core.tools import metric_sql

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

    def settings(self) -> dict[str, str]:
        """The app.* settings in the order they were set; a later one wins, as in PostgreSQL."""
        out: dict[str, str] = {}
        for sql, params in self.calls:
            if sql.startswith("SELECT set_config"):
                out[params[0].lower()] = params[1]   # PostgreSQL setting names ignore case
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
    assert conn.settings() == {
        "app.whatif": "category:Restaurants", "app.whatif_pct": "20",
        "app.demo_today": "2026-09-30", "app.customer_from": "CUST00860", "app.customer_to": "CUST00861",
    }
    assert conn.calls[0] == ("BEGIN", None) and conn.calls[1][0] == "SET TRANSACTION READ ONLY"
    assert conn.calls[-1][0] == "<metric file>"


def test_the_range_is_set_last_even_if_a_name_slipped_past_the_check(monkeypatch):
    """Defence in depth: with the check disabled, the customer range and as_of still win."""
    monkeypatch.setattr(metric_sql, "check_settings", lambda settings: None)
    conn = FakeConnection()
    metric_sql.run(conn, "04_what_if.sql", "CUST00860", AS_OF,
                   {"customer_from": "CUST00000", "customer_to": "CUST99999", "demo_today": "2099-01-01"})
    s = conn.settings()
    assert (s["app.customer_from"], s["app.customer_to"], s["app.demo_today"]) == ("CUST00860", "CUST00861", "2026-09-30")
