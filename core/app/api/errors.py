"""The contract's error envelope (contracts/api.md section 4) and the app-wide handlers for it.

Every error leaves the service as `{"error": {"code", "message", "retryable"}}` with a fixed,
localised message. No exception text, driver message or connection detail is ever included.

Unexpected exceptions are caught by CatchAll, a middleware that does not re-raise: Starlette's own
500 handler would log the full traceback, with the exception's text, after any handler ran. The log
line carries the request path, the exception class name and a request id, never the exception text.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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
    "not_found": 404,  # contract addition (#79): an unknown route; the contract has no generic code yet
}
RETRYABLE = {"rate_limited", "data_unavailable", "llm_unavailable", "internal"}


class ApiError(Exception):
    """An error with a contract code. The message comes from texts.ERRORS, never from the cause."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def language_of(request: Request) -> str:
    return "fi" if request.query_params.get("lang") == "fi" else "en"


def envelope(code: str, language: str, status: int | None = None,
             headers: dict[str, str] | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": texts.pick(texts.ERRORS[code], language),
                      "retryable": code in RETRYABLE}}
    return JSONResponse(body, status_code=status or STATUS[code], headers=headers)


async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
    return envelope(exc.code, language_of(request))


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return envelope("invalid_request", language_of(request))


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Unknown routes (404 `not_found`), wrong methods (405) and other HTTP errors keep their status and
    get the envelope instead of FastAPI's {"detail": ...}; the Allow header of a 405 is kept."""
    status = exc.status_code
    code = ("not_found" if status == 404 else "rate_limited" if status == 429
            else "internal" if status >= 500 else "invalid_request")
    return envelope(code, language_of(request), status=status, headers=getattr(exc, "headers", None))


class CatchAll:
    """Turns any unhandled exception into the contract's 500 envelope, without re-raising it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_and_track(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_and_track)
        except Exception as exc:  # noqa: BLE001 - the point of this middleware
            request_id = uuid.uuid4().hex[:12]
            # %r: the decoded path could carry a line break (%0d%0a) and forge a log line otherwise
            log.error("unhandled error on %r (%s), request %s", scope.get("path"), type(exc).__name__, request_id)
            if started:  # a streamed response is already under way: nothing more can be sent
                return
            response = envelope("internal", language_of(Request(scope)), headers={"X-Request-Id": request_id})
            await response(scope, receive, send)


def install(app: FastAPI) -> None:
    """App-wide: also used by /api/ask (#59), whose validation errors are 400 envelopes too."""
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    # Innermost user middleware (inside CORS, so a 500 still carries the CORS headers), just outside
    # the router's exception handlers. add_middleware would put it outermost, outside CORS.
    app.user_middleware.append(Middleware(CatchAll))
