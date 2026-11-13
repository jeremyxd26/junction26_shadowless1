"""A small connection pool for the shared PostgreSQL database.

The database is small (2 GB RAM, 25 connections), so each process holds at most two connections,
and every session runs with `statement_timeout = '60s'`. The pool is synchronous on purpose:
psycopg's async mode does not work with the default event loop on Windows, and blocking calls run
in FastAPI's thread pool (`def` endpoints).

Nothing from the connection string may reach the logs. libpq repeats parts of a malformed URL in
its error text (for example the tail of a password with an unencoded `@` as a host name), so:
- `valid_database_url` rejects a malformed URL before any connection attempt;
- `DriverLogRedactor` rewrites every record of psycopg's loggers: exception arguments become their
  class name, other free-text arguments are hidden, tracebacks are dropped, and repeated
  "error connecting" warnings are reported with a growing interval instead of once per attempt.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg_pool import ConnectionPool, PoolTimeout

MAX_CONNECTIONS = 2
CONNECT_TIMEOUT_S = 5
READY_TIMEOUT_S = 3.0
POOL_NAME = "core"

NOT_SET = "DATABASE_URL is not set"
MALFORMED = "DATABASE_URL is malformed"

log = logging.getLogger("uvicorn.error")


def valid_database_url(database_url: str) -> bool:
    """True when libpq can parse the URL and its host is plausible. Never logs the URL."""
    try:
        params = conninfo_to_dict(database_url)
    except Exception:  # the exception text repeats parts of the URL, so it is dropped
        return False
    # A password with an unencoded "@" makes libpq read the password's tail as part of the host.
    return "@" not in str(params.get("host") or "")


class DriverLogRedactor(logging.Filter):
    """Keep connection details and libpq error text out of psycopg's log records."""

    _LOOKS_LIKE_CONNINFO = re.compile(r"://|@|\b(host|hostaddr|user|password|dbname|port)\s*=", re.I)

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 first_interval: float = 5.0, max_interval: float = 300.0) -> None:
        super().__init__()
        self._clock = clock
        self._first_interval = first_interval
        self._max_interval = max_interval
        self._interval = first_interval
        self._next_report = float("-inf")
        self._suppressed = 0

    def reset(self) -> None:
        """Report the next connection failure at once (a new pool starts a new series)."""
        self._interval = self._first_interval
        self._next_report = float("-inf")
        self._suppressed = 0

    def filter(self, record: logging.LogRecord) -> bool:
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        if str(record.msg).startswith("error connecting"):
            return self._connection_failure(record)
        args = record.args
        if isinstance(args, dict):
            record.args = {k: self._safe(v) for k, v in args.items()}
        elif isinstance(args, tuple):
            record.args = tuple(self._safe(a) for a in args)
        try:
            text = record.getMessage()
        except Exception:
            text = "://"  # cannot format: hide it below
        if self._LOOKS_LIKE_CONNINFO.search(text):
            record.msg, record.args = "database driver message hidden (%s)", (record.levelname,)
        return True

    def _connection_failure(self, record: logging.LogRecord) -> bool:
        """One line per growing interval (5 s, 10 s, ... up to 5 min) instead of one per attempt."""
        now = self._clock()
        if now < self._next_report:
            self._suppressed += 1
            return False
        exc = next((a for a in (record.args or ()) if isinstance(a, BaseException)), None)
        record.msg = "database connection attempt failed (%s)"
        record.args = (type(exc).__name__ if exc is not None else "unknown error",)
        if self._suppressed:
            record.msg += "; %d more failed attempts since the last report"
            record.args += (self._suppressed,)
        self._suppressed = 0
        self._next_report = now + self._interval
        self._interval = min(self._interval * 2, self._max_interval)
        return True

    @staticmethod
    def _safe(value: object) -> object:
        if isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str) and value == POOL_NAME:
            return value
        if isinstance(value, BaseException):
            return type(value).__name__
        return f"<{type(value).__name__}>"


_REDACTOR = DriverLogRedactor()
DRIVER_LOGGERS = ("psycopg", "psycopg.pool", "psycopg_pool.sched")


def install_log_redaction() -> None:
    """Attach the redactor to every psycopg logger (idempotent)."""
    for name in DRIVER_LOGGERS:
        logging.getLogger(name).addFilter(_REDACTOR)


def _configure(conn: psycopg.Connection) -> None:
    # The connection is in autocommit mode, so the setting holds for the whole session.
    conn.execute("SET statement_timeout = '60s'")


def create_pool(database_url: str) -> ConnectionPool:
    """Create a closed pool; the caller opens it (`pool.open()`) and closes it.

    Call it only with a URL that passed `valid_database_url`.
    """
    install_log_redaction()
    _REDACTOR.reset()
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
        name=POOL_NAME,
    )


def check_ready(pool: ConnectionPool | None, missing_reason: str = NOT_SET,
                timeout: float = READY_TIMEOUT_S) -> str | None:
    """Run `SELECT 1`. Return None when the database answers, otherwise a short fixed reason.

    Without a pool the reason is `missing_reason` (URL not set or malformed). The reason never
    contains the connection string or the driver's error text; logs carry the exception class only.
    """
    if pool is None:
        return missing_reason
    try:
        with pool.connection(timeout=timeout) as conn:
            conn.execute("SELECT 1")
    except PoolTimeout:
        log.warning("readyz: no database connection within %.0f s", timeout)
        return "database unreachable"
    except Exception as exc:  # anything else, including psycopg.Error: class name only
        log.warning("readyz: database error (%s)", type(exc).__name__)
        return "database error"
    return None
