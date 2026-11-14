"""Secret setting values never reach a log line, whichever logger writes it (#198).

The canary cases come from the review of PR #183. Every value is built from parts at run time, so no
literal in this file looks like a credential or a URL with a password.
"""

from __future__ import annotations

import io
import logging
import urllib.parse
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.app import secret_mask

PW = "Pw" + "q7Zx" + "Canary9"
KEY = "AIza" + "FAKE" + "CANARYKEY123"
HOST = "canary" + "-db" + ".invalid"
URL = "".join(["postgresql", "://", "user", ":", PW, "@", HOST, "/x"])
CANARIES = (PW, KEY, HOST, PW.upper())


@pytest.fixture
def masked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Install the mask for canary settings only (no .env), and collect everything the handlers print."""
    env = {"DATABASE_URL": URL, "GEMINI_API_KEY": KEY, "SHORT_TOKEN": "abc12", "EMPTY_SECRET": "",
           "GEMINI_MODEL": "gemini-canary-model"}
    count = secret_mask.install(environ=env, env_file=tmp_path / "missing.env")
    buf = io.StringIO()
    handlers = []

    def attach(logger: logging.Logger, fmt: str = "%(levelname)s %(name)s %(message)s") -> None:
        handler = logging.StreamHandler(buf)
        handler.setFormatter(logging.Formatter(fmt))
        logger.addHandler(handler)
        handlers.append((logger, handler))

    yield buf, attach, count
    for logger, handler in handlers:
        logger.removeHandler(handler)
    secret_mask.install()  # back to the real environment's values


def assert_clean(text: str) -> None:
    assert text, "nothing was logged"
    for canary in CANARIES:
        assert canary not in text, f"canary {canary[:4]}… leaked"
    assert urllib.parse.quote(URL, safe="") not in text


def test_patterns_skip_short_empty_and_public_settings(masked):
    _, _, count = masked
    values = secret_mask.secret_values({"DATABASE_URL": URL, "GEMINI_API_KEY": KEY, "SHORT_TOKEN": "abc12",
                                        "EMPTY_SECRET": "", "GEMINI_MODEL": "gemini-canary-model"},
                                       env_file=Path("does-not-exist.env"))
    assert count == len(values)
    assert PW in values and KEY in values and HOST in values and URL in values
    assert urllib.parse.quote(URL, safe="") in values
    assert "abc12" not in values and "" not in values                     # shorter than 6 / empty
    assert not any("gemini-canary-model" in v for v in values)            # not a secret name


@pytest.mark.parametrize("logger_name", ["", "uvicorn.error", "thirdparty.created.later"])
def test_messages_and_args_are_masked_on_any_logger(masked, logger_name):
    buf, attach, _ = masked
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    attach(logger)
    logger.warning("dsn %s key %s", URL, KEY)                         # %-style arguments
    logger.warning(f"f-string dsn {URL} key {KEY}")                   # already in the message
    logger.warning("line1\nline2 " + URL + "\nline3 " + KEY)          # multi-line
    logger.warning("enc " + urllib.parse.quote(URL, safe=""))          # URL-encoded
    logger.warning("pw alone %s, upper %s", PW, PW.upper())            # bare password, any case
    logger.warning("bytes %r", URL.encode())                           # bytes argument
    logger.warning("mapping %(dsn)s", {"dsn": URL})                    # mapping arguments
    assert_clean(buf.getvalue())
    assert buf.getvalue().count(secret_mask.MASK) >= 9


def test_uvicorn_access_log_keeps_its_format(masked):
    """The access formatter unpacks the five arguments; they are masked in place, not replaced."""
    from uvicorn.logging import AccessFormatter

    buf, _, _ = masked
    logger = logging.getLogger("uvicorn.access")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(buf)
    handler.setFormatter(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    logger.addHandler(handler)
    try:
        logger.info('%s - "%s %s HTTP/%s" %d', "1.2.3.4", "GET", "/x?k=" + KEY + "&d=" + URL, "1.1", 200)
        logger.info("free text dsn " + URL)
    finally:
        logger.removeHandler(handler)
    text = buf.getvalue()
    assert_clean(text)
    assert '1.2.3.4 - "GET /x?k=***&d=' in text and "200" in text


def test_exceptions_with_chained_causes_are_masked(masked):
    buf, attach, _ = masked
    for name in ("", "uvicorn.error"):
        logger = logging.getLogger(name)
        attach(logger)
        try:
            try:
                raise ValueError("inner " + URL)
            except ValueError as inner:
                raise RuntimeError("outer key " + KEY) from inner
        except RuntimeError:
            logger.exception("failed while handling %s", HOST)
    text = buf.getvalue()
    assert_clean(text)
    assert "Traceback" in text and "RuntimeError: outer key ***" in text and "ValueError: inner" in text


def test_extra_fields_and_stack_info_are_masked(masked):
    buf, attach, _ = masked
    logger = logging.getLogger("uvicorn.error")
    attach(logger, "%(message)s dsn=%(dsn)s key=%(key)s")
    logger.warning("with extra", extra={"dsn": URL, "key": KEY})
    attach(logging.getLogger("thirdparty.stack"))
    logging.getLogger("thirdparty.stack").warning("stack " + PW, stack_info=True)
    assert_clean(buf.getvalue())


def test_a_handler_added_later_to_a_non_propagating_logger_is_covered(masked):
    buf, attach, _ = masked
    logger = logging.getLogger("thirdparty.withhandler")
    logger.propagate = False
    try:
        attach(logger)
        logger.warning("dsn %s key %s", URL, KEY)
    finally:
        logger.propagate = True
    assert_clean(buf.getvalue())


def test_driver_child_logger_with_a_direct_handler(masked):
    from core.app import db

    buf, attach, _ = masked
    db.install_log_redaction()
    pq = logging.getLogger("psycopg.pq")
    attach(pq, "CHILDHANDLER %(message)s")
    pq.warning(f"auth failed for secret {PW}")
    pq.warning(f"key {KEY}")
    pq.warning("conn " + URL)
    assert_clean(buf.getvalue())


def test_the_mask_never_raises(masked):
    buf, attach, _ = masked

    class Broken:
        def __str__(self) -> str:
            raise RuntimeError("cannot render " + PW)

    logger = logging.getLogger("thirdparty.broken")
    attach(logger)
    logger.warning("object %s and %s", Broken(), URL)   # must not raise into the caller
    text = buf.getvalue()
    assert PW not in text and KEY not in text


def test_a_start_up_error_does_not_echo_the_value(monkeypatch: pytest.MonkeyPatch):
    from core.app.settings import Settings

    for name in ("DATABASE_URL", "DB_POOL_MAX", "API_DOCS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", URL)
    monkeypatch.setenv("DB_POOL_MAX", PW)          # an invalid value that happens to be a secret
    with pytest.raises(ValidationError) as caught:
        Settings(_env_file=None)
    text = str(caught.value)
    assert "db_pool_max" in text
    assert PW not in text and URL not in text
