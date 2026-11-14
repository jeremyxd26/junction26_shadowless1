"""Mask the values of secret settings in every log record of the process (#198).

The service never logs a secret on purpose. This is the net under every logger anyway: the root logger,
uvicorn's loggers, third-party libraries and loggers created later, so a leaked key or database
password cannot reach the journal whoever writes the line.

How every record is covered: `install()` wraps `logging.Handler.handle` once for the whole process.
Every handler runs that method before it emits (the root's handlers, uvicorn's handlers that
`dictConfig` creates after start-up, pytest's capture handlers, a handler attached later to any
logger), so the record is masked before any handler formats it. The masking is idempotent per record.

Secret settings: names ending in KEY, TOKEN, SECRET or PASSWORD, and DATABASE_URL. Their values come
from the process environment and the repository's `.env`, read directly rather than through
`Settings`, so the mask is in place even when the settings fail to validate at start-up. For a URL
the password and the host count as well, and every value also in its URL-encoded forms. A value
shorter than 6 characters is never a pattern. Matching ignores case.

What is masked: the message, every `%`-style argument (in place, so formatters that unpack the
arguments, like uvicorn's access log, keep working), extra fields, the stack text, and the exception
text including chained causes and the traceback (formatted here, then the exception object is dropped
from the record). The filter never raises: if masking fails, the record's text is replaced.
"""

from __future__ import annotations

import logging
import os
import re
import traceback
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MASK = "***"
MIN_LENGTH = 6
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)$", re.I)
_DONE = "_secret_masked"
# LogRecord's own attributes; anything else on a record came from `extra=` and is masked too.
_STANDARD = set(vars(logging.LogRecord("x", logging.INFO, "x", 0, "x", None, None))) | {"message", "asctime"}

_pattern: re.Pattern[str] | None = None
_original_handle = logging.Handler.handle


def is_secret_name(name: str) -> bool:
    return bool(SECRET_NAME.search(name)) or name.upper() == "DATABASE_URL"


def _env_file_values(path: Path) -> dict[str, str]:
    try:
        from dotenv import dotenv_values
    except ImportError:  # python-dotenv is pinned with pydantic-settings; without it only os.environ counts
        return {}
    try:
        return {k: v for k, v in dotenv_values(path).items() if v}
    except Exception:  # an unreadable .env must not stop the service or print anything from it
        return {}


def secret_values(environ: dict[str, str] | None = None, env_file: Path | None = None) -> list[str]:
    """Every text that must never appear in a log line, longest first."""
    sources: dict[str, str] = {}
    sources.update(_env_file_values(env_file if env_file is not None else ROOT / ".env"))
    sources.update(environ if environ is not None else dict(os.environ))  # the real environment wins
    found: set[str] = set()
    for name, raw in sources.items():
        if not is_secret_name(name) or not raw:
            continue
        value = raw.strip().strip("\"'")
        parts = [value]
        if "://" in value:
            try:
                url = urllib.parse.urlsplit(value)
                parts += [url.password or "", urllib.parse.unquote(url.password or ""), url.hostname or ""]
            except ValueError:
                pass
        for part in parts:
            for form in (part, urllib.parse.quote(part, safe=""), urllib.parse.quote_plus(part)):
                if len(form) >= MIN_LENGTH:
                    found.add(form)
    return sorted(found, key=len, reverse=True)


def build_pattern(values: list[str]) -> re.Pattern[str] | None:
    if not values:
        return None
    return re.compile("|".join(re.escape(v) for v in values), re.IGNORECASE)


def mask_text(text: str, pattern: re.Pattern[str] | None = None) -> str:
    pattern = pattern if pattern is not None else _pattern
    if pattern is None or not text:
        return text
    return pattern.sub(MASK, text)


def _mask_value(value: object, pattern: re.Pattern[str]) -> object:
    """A masked copy of one argument; non-text values are kept unless their text holds a secret."""
    if isinstance(value, str):
        return pattern.sub(MASK, value)
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, dict):
        return {k: _mask_value(v, pattern) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_value(v, pattern) for v in value]
    if isinstance(value, tuple):  # a plain tuple; a namedtuple's fields become a plain tuple too
        return tuple(_mask_value(v, pattern) for v in value)
    try:
        text = repr(value) if isinstance(value, (bytes, bytearray)) else str(value)
    except Exception:
        return f"<{type(value).__name__}>"
    return pattern.sub(MASK, text) if pattern.search(text) else value


def mask_record(record: logging.LogRecord, pattern: re.Pattern[str] | None = None) -> None:
    """Mask one record in place (idempotent)."""
    pattern = pattern if pattern is not None else _pattern
    if pattern is None or getattr(record, _DONE, False):
        return
    try:
        if isinstance(record.msg, str):
            record.msg = pattern.sub(MASK, record.msg)
        elif record.msg is not None:
            record.msg = _mask_value(record.msg, pattern)
        if isinstance(record.args, dict):
            record.args = {k: _mask_value(v, pattern) for k, v in record.args.items()}
        elif isinstance(record.args, tuple):
            record.args = tuple(_mask_value(a, pattern) for a in record.args)
        if record.exc_info:
            record.exc_text = "".join(traceback.format_exception(*record.exc_info))  # chained causes included
            record.exc_info = None
        if record.exc_text:
            record.exc_text = pattern.sub(MASK, record.exc_text)
        if record.stack_info:
            record.stack_info = pattern.sub(MASK, record.stack_info)
        for key, value in list(vars(record).items()):
            if key not in _STANDARD and key != _DONE:
                setattr(record, key, _mask_value(value, pattern))
        # Net: a secret built across the format string and its arguments, or hidden in an object's text.
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = None
        if rendered is not None and pattern.search(rendered):
            record.msg, record.args = pattern.sub(MASK, rendered), None
    except Exception:  # never raise from logging, and never let the unmasked text through
        record.msg, record.args = "log record hidden: masking failed (%s)", (record.levelname,)
        record.exc_info = record.exc_text = record.stack_info = None
    setattr(record, _DONE, True)


def _masked_handle(self: logging.Handler, record: logging.LogRecord):
    mask_record(record)
    return _original_handle(self, record)


def install(environ: dict[str, str] | None = None, env_file: Path | None = None) -> int:
    """Build the pattern from the current settings and route every handler through the mask.

    Idempotent; calling it again rebuilds the pattern (tests, a changed environment). Returns the
    number of patterns, never the values.
    """
    global _pattern
    values = secret_values(environ, env_file)
    _pattern = build_pattern(values)
    if logging.Handler.handle is not _masked_handle:
        logging.Handler.handle = _masked_handle
    return len(values)
