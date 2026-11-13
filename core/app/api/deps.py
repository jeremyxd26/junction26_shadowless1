"""Request helpers: a pooled connection, the known-customer check and the evidence table.

Database problems of any kind (no pool, pool timeout, driver error) become 503 `data_unavailable`;
the log line carries the exception class name only, never driver text.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from fastapi import Request
from psycopg_pool import PoolTimeout

from core.tools import db as tools_db

from .errors import ApiError

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


def require_customer(conn: psycopg.Connection, customer_id: str) -> None:
    """404 customer_not_found unless the id is a known customer (one indexed lookup)."""
    row = conn.execute("SELECT 1 FROM customers WHERE customer_id = %s", (customer_id,)).fetchone()
    if row is None:
        raise ApiError("customer_not_found")
