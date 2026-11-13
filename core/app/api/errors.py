"""The contract's error envelope (contracts/api.md section 4) and the app-wide handlers for it.

Every error leaves the service as `{"error": {"code", "message", "retryable"}}` with a fixed,
localised message. No exception text, driver message or connection detail is ever included; logs
carry the exception class name only.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import texts

log = logging.getLogger("uvicorn.error")

STATUS = {
    "invalid_request": 400,
    "customer_not_found": 404,
    "evidence_not_found": 404,
    "evidence_forbidden": 403,
    "invalid_scenario": 422,
    "rate_limited": 429,
    "data_unavailable": 503,
    "llm_unavailable": 503,
    "internal": 500,
}
RETRYABLE = {"rate_limited", "data_unavailable", "llm_unavailable", "internal"}


class ApiError(Exception):
    """An error with a contract code. The message comes from texts.ERRORS, never from the cause."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def language_of(request: Request) -> str:
    return "fi" if request.query_params.get("lang") == "fi" else "en"


def envelope(code: str, language: str) -> JSONResponse:
    body = {"error": {"code": code, "message": texts.pick(texts.ERRORS[code], language),
                      "retryable": code in RETRYABLE}}
    return JSONResponse(body, status_code=STATUS[code])


async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
    return envelope(exc.code, language_of(request))


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return envelope("invalid_request", language_of(request))


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled error on %s (%s)", request.url.path, type(exc).__name__)
    return envelope("internal", language_of(request))


def install(app: FastAPI) -> None:
    """App-wide: also used by /api/ask (#59), whose validation errors are 400 envelopes too."""
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled)
