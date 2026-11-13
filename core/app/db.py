"""A small connection pool for the shared PostgreSQL database.

The database is small (2 GB RAM, 25 connections), so each process holds at most two connections,
and every session runs with `statement_timeout = '60s'`. The pool is synchronous on purpose:
psycopg's async mode does not work with the default event loop on Windows, and blocking calls run
in FastAPI's thread pool (`def` endpoints).
"""

from __future__ import annotations

import logging

import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout

MAX_CONNECTIONS = 2
CONNECT_TIMEOUT_S = 5
READY_TIMEOUT_S = 3.0

log = logging.getLogger("uvicorn.error")


def _configure(conn: psycopg.Connection) -> None:
    # The connection is in autocommit mode, so the setting holds for the whole session.
    conn.execute("SET statement_timeout = '60s'")


def create_pool(database_url: str) -> ConnectionPool:
    """Create a closed pool; the caller opens it (`pool.open()`) and closes it."""
    return ConnectionPool(
        database_url,
        min_size=1,
        max_size=MAX_CONNECTIONS,
        kwargs={
            "autocommit": True,
            "connect_timeout": CONNECT_TIMEOUT_S,
            "application_name": "shadowless1-core",
        },
        configure=_configure,
        check=ConnectionPool.check_connection,  # drop connections that died, e.g. after a database restart
        open=False,
        name="core",
    )


def check_ready(pool: ConnectionPool | None, timeout: float = READY_TIMEOUT_S) -> str | None:
    """Run `SELECT 1`. Return None when the database answers, otherwise a short reason.

    The reason never contains the connection string or the driver's error text.
    """
    if pool is None:
        return "DATABASE_URL is not set"
    try:
        with pool.connection(timeout=timeout) as conn:
            conn.execute("SELECT 1")
    except PoolTimeout:
        log.warning("readyz: no database connection within %.0f s", timeout)
        return "database unreachable"
    except psycopg.Error as exc:
        log.warning("readyz: database error (%s)", type(exc).__name__)
        return "database error"
    return None
