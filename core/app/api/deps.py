"""Request helpers: the served-customer allowlist, a pooled connection, the known-customer check and
the evidence table.

Database problems of any kind (no pool, pool timeout, driver error) become 503 `data_unavailable`;
the log line carries the exception class name only, never driver text.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from fastapi import Request
from psycopg_pool import PoolTimeout

from core.tools import db as tools_db

from .errors import ApiError
from .personas import load_personas

log = logging.getLogger("uvicorn.error")

CUSTOMER_ID_PATTERN = r"^CUST[0-9]{5}$"
EVIDENCE_REF_PATTERN = r"^ev_[0-9a-f]{12}$"
POOL_TIMEOUT_S = 5.0

_evidence_table_lock = threading.Lock()


@contextmanager
def connection(request: Request) -> Iterator[psycopg.Connection]:
    """One pooled connection for the request (autocommit, statement_timeout 60 s, see core/app/db.py)."""
    pool = request.app.state.pool
    if pool is None:
        raise ApiError("data_unavailable")
    try:
        with pool.connection(timeout=POOL_TIMEOUT_S) as conn:
            ensure_evidence_table(request, conn)
            yield conn
    except (PoolTimeout, psycopg.Error) as exc:
        log.warning("database problem on %s (%s)", request.url.path, type(exc).__name__)
        raise ApiError("data_unavailable") from None


def ensure_evidence_table(request: Request, conn: psycopg.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS coach_evidence, once per process (the only DDL the service runs)."""
    if getattr(request.app.state, "evidence_table_ready", False):
        return
    with _evidence_table_lock:
        if not getattr(request.app.state, "evidence_table_ready", False):
            tools_db.ensure_evidence_table(conn)
            request.app.state.evidence_table_ready = True


# ---- which customers are served (#101) ------------------------------------------------------------
# In demo mode only the personas of core/config/personas.yaml are served. Any other id, whether it
# exists in the data or not, gets the same 404 customer_not_found from configuration alone, before a
# connection is taken, so a real customer cannot be told from a missing one and walking the ids reads
# and writes nothing. DEMO_CUSTOMERS=all widens it to every customer of the data (local eval runs).
# The personas file is the allowlist; the database still confirms each served id once per process
# (require_customer), because the file could name an id that a different data load does not hold.

_known_customers: set[str] = set()   # ids the database confirmed in this process (positive results only)
_known_lock = threading.Lock()


def served_customers(settings: Any) -> frozenset[str] | None:
    """The customer ids the API serves, or None for every customer of the data (DEMO_CUSTOMERS=all)."""
    if settings.demo_customers == "all":
        return None
    return frozenset(p["customer_id"] for p in load_personas()["personas"])


def require_served(request: Request, customer_id: str) -> None:
    """404 customer_not_found unless this customer is served. No database access."""
    served = served_customers(request.app.state.settings)
    if served is not None and customer_id not in served:
        raise ApiError("customer_not_found")


@contextmanager
def customer_connection(request: Request, customer_id: str) -> Iterator[psycopg.Connection]:
    """The one entry for every endpoint that names a customer: the allowlist first (no database),
    then a pooled connection, then the existence check (once per process and customer)."""
    require_served(request, customer_id)
    with connection(request) as conn:
        require_customer(conn, customer_id)
        yield conn


def require_customer(conn: psycopg.Connection, customer_id: str) -> None:
    """404 customer_not_found unless the id is a known customer (one indexed lookup).

    A found id is remembered for the life of the process (the dataset is static), so a warm request
    makes no lookup; a missing id is never remembered. Endpoints call customer_connection, which
    applies the allowlist before this.
    """
    with _known_lock:
        if customer_id in _known_customers:
            return
    row = conn.execute("SELECT 1 FROM customers WHERE customer_id = %s", (customer_id,)).fetchone()
    if row is None:
        raise ApiError("customer_not_found")
    with _known_lock:
        _known_customers.add(customer_id)
