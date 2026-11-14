"""No part of DATABASE_URL may reach the logs or a response, whatever libpq makes of it."""

from __future__ import annotations

import logging

import psycopg
import pytest
from fastapi.testclient import TestClient

from core.app.db import (
    MALFORMED,
    DriverLogRedactor,
    install_log_redaction,
    valid_database_url,
)
from core.app.main import create_app
from core.app.settings import Settings

# libpq echoes the token: invalid percent-encoded token: "SECRETPW%zz"
BAD_PERCENT = "postgresql://coach:SECRETPW%zz@127.0.0.1:1/coach"
# An unencoded "@" in the password: libpq would try to resolve the host "RETPW@127.0.0.1"
UNENCODED_AT = "postgresql://coach:SEC@RETPW@127.0.0.1:1/coach"
# Valid URL whose host cannot be resolved: libpq's error repeats the host
UNRESOLVABLE = "postgresql://coach:PWMARKER@markerhost.invalid:5432/coach"


@pytest.fixture
def all_logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Capture every record, including psycopg's DEBUG and INFO records."""
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="psycopg")
    return caplog


def readyz_for(url: str) -> tuple[int, str]:
    with TestClient(create_app(Settings(_env_file=None, database_url=url))) as client:
        response = client.get("/readyz")
    return response.status_code, response.text


def test_url_validation():
    assert valid_database_url("postgresql://coach:pw@db.example:5432/coach")
    assert valid_database_url("postgresql://coach:p%40ss@db.example/coach")  # an encoded @ is fine
    assert not valid_database_url(BAD_PERCENT)
    assert not valid_database_url(UNENCODED_AT)


@pytest.mark.parametrize("url, marker", [(BAD_PERCENT, "SECRETPW"), (UNENCODED_AT, "RETPW")])
def test_malformed_url_is_never_logged(clean_env, all_logs, url, marker):
    status, body = readyz_for(url)
    assert status == 503
    assert MALFORMED in body
    assert marker not in body
    assert marker not in all_logs.text
    assert "DATABASE_URL is malformed" in all_logs.text


def test_connection_errors_are_redacted(clean_env, all_logs):
    status, body = readyz_for(UNRESOLVABLE)
    assert status == 503
    for marker in ("markerhost", "PWMARKER", "coach:"):
        assert marker not in body
        assert marker not in all_logs.text
    assert "database connection attempt failed (OperationalError)" in all_logs.text


def test_driver_records_lose_free_text_and_tracebacks(all_logs):
    install_log_redaction()
    pool_log = logging.getLogger("psycopg.pool")
    try:
        raise psycopg.OperationalError("failed to resolve host 'SEC@RETHOST'")
    except psycopg.OperationalError as exc:
        pool_log.warning("task run %s failed: %s: %s", "AddConnection(host=x)", "OperationalError", exc, exc_info=True)
    pool_log.warning("discarding broken connection: %s", "<Connection host=secret-host user=coach>")
    logging.getLogger("psycopg").debug("<psycopg.Connection (host=secret-host user=coach)>: Explicit rollback from: ")
    for marker in ("RETHOST", "secret-host", "user=coach", "Traceback"):
        assert marker not in all_logs.text
    assert "OperationalError" in all_logs.text


def test_connection_failures_are_reported_with_a_growing_interval():
    clock = iter([0, 1, 2, 5, 6, 15, 16])
    redactor = DriverLogRedactor(clock=lambda: next(clock), first_interval=5.0, max_interval=300.0)

    def failure() -> logging.LogRecord:
        return logging.LogRecord("psycopg.pool", logging.WARNING, __file__, 1, "error connecting in %r: %s",
                                 ("core", psycopg.OperationalError("host 'SECRET' failed")), None)

    shown = []
    for _ in range(7):
        record = failure()
        if redactor.filter(record):
            shown.append(record.getMessage())
    assert shown == [
        "database connection attempt failed (OperationalError)",
        "database connection attempt failed (OperationalError); 2 more failed attempts since the last report",
        "database connection attempt failed (OperationalError); 1 more failed attempts since the last report",
    ]


@pytest.mark.parametrize("name", ["psycopg.pq", "psycopg.pool.worker", "psycopg_pool.sched", "psycopg_pool.any.child"])
def test_records_of_child_loggers_are_redacted(all_logs, name):
    """A filter on a parent logger never sees a child logger's records; the redacting handler does (#62)."""
    install_log_redaction()
    child = logging.getLogger(name)
    child.warning("connecting with %s", "host=child-secret-host user=coach")
    child.warning("connection string host=child-secret-host2 password=child-pw")
    for marker in ("child-secret-host", "child-pw", "user=coach"):
        assert marker not in all_logs.text
    assert "connecting with <str>" in all_logs.text
    assert "database driver message hidden (WARNING)" in all_logs.text


def test_a_child_loggers_connection_failure_is_reported_once(all_logs):
    """The redactor runs once per record: a failure from a child logger is shown, not suppressed twice."""
    install_log_redaction()
    from core.app import db

    db._REDACTOR.reset()
    logging.getLogger("psycopg.pool").warning("error connecting in %r: %s", "core",
                                              psycopg.OperationalError("host 'child-SECRET' failed"))
    assert "database connection attempt failed (OperationalError)" in all_logs.text
    assert "child-SECRET" not in all_logs.text


@pytest.mark.parametrize("name", ["psycopg.pq", "psycopg.transaction", "psycopg.waiting", "psycopg_pool.sched_async"])
def test_a_handler_attached_directly_to_a_driver_logger_sees_only_redacted_records(name):
    """Review of #62: a handler someone attaches to a driver child logger itself gets the record before any
    parent handler; the logger-level filter has redacted it already."""
    install_log_redaction()
    seen: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    logger = logging.getLogger(name)
    capture = Capture()
    logger.addHandler(capture)
    level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        logger.warning("connecting to %s", "host=direct-secret-host user=coach password=direct-pw")
        logger.warning("connection string host=direct-secret-host2 password=direct-pw2")
    finally:
        logger.removeHandler(capture)
        logger.setLevel(level)
    assert seen
    for marker in ("direct-secret-host", "direct-pw", "user=coach"):
        assert all(marker not in line for line in seen), seen
