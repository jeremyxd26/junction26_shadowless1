"""POST /api/ask (contracts/api.md section 7) and the internal GET /api/audit/{answer_id}.

Step 0 runs before any stream is opened, and its failures are plain HTTP errors with the error
envelope: 400 invalid_request (bad body, message empty or over 500 characters), 429 rate_limited,
404 customer_not_found, 503 data_unavailable. After that the answer is either a server-sent event
stream (Accept: text/event-stream; a `: ping` comment every 10 seconds while the pipeline works) or
one JSON object (section 7.4). Inside the stream a failure is one `error` event.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from core.agent.audit import AuditLog
from core.agent.conversation import ConversationStore
from core.agent.orchestrator import AskRequest, DataAccess, DataUnavailable, Pipeline, error_envelope
from core.agent.rules import RuleModel
from core.agent.toolset import default_registry

router = APIRouter()

PING_S = 10.0
MAX_MESSAGE = 500
CONNECTION_TIMEOUT_S = 5.0
CUSTOMER_SQL = "SELECT 1 FROM customers WHERE customer_id = %s"

ERROR_TEXT = {
    "invalid_request": "The request is not valid.",
    "customer_not_found": "We couldn't find this customer.",
    "rate_limited": "Too many questions at once. Please wait a moment.",
}


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(min_length=1, max_length=32)
    conversation_id: str | None = Field(default=None, max_length=64)
    message: str
    language: Literal["en", "fi", "auto"] = "auto"


class PoolData:
    """DataAccess on the app's connection pool (core/app/db.py): short per-customer reads only."""

    def __init__(self, app) -> None:
        self._app = app

    @contextmanager
    def connection(self) -> Iterator[Any]:
        pool = self._app.state.pool
        if pool is None:
            raise DataUnavailable()
        try:
            with pool.connection(timeout=CONNECTION_TIMEOUT_S) as conn:
                yield conn
        except (PoolTimeout, psycopg.OperationalError):
            raise DataUnavailable() from None

    def customer_exists(self, customer_id: str) -> bool:
        with self.connection() as conn:
            return conn.execute(CUSTOMER_SQL, (customer_id,)).fetchone() is not None


class RateLimiter:
    """A simple per-process counter: at most `per_minute` asks per customer (0 turns it off)."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        if self.per_minute <= 0:
            return True, 0
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > 60:
                hits.popleft()
            if len(hits) >= self.per_minute:
                return False, int(60 - (now - hits[0])) + 1
            hits.append(now)
            return True, 0


@dataclass
class Agent:
    pipeline: Pipeline
    data: DataAccess
    audit: AuditLog
    limiter: RateLimiter = field(default_factory=lambda: RateLimiter(int(os.environ.get("ASK_RATE_LIMIT_PER_MIN", "10"))))


def build_agent(app) -> Agent:
    """The service's agent: the built-in tools, the keyword model (until the Gemini adapter) and the
    app's pool. Tests put their own Agent on app.state.agent instead."""
    data = PoolData(app)
    audit = AuditLog()
    pipeline = Pipeline(default_registry(), RuleModel(), data, as_of=app.state.settings.demo_today,
                        store=ConversationStore(), audit=audit)
    return Agent(pipeline=pipeline, data=data, audit=audit)


def get_agent(app) -> Agent:
    agent = getattr(app.state, "agent", None)
    if agent is None:
        agent = app.state.agent = build_agent(app)
    return agent


def _error(status: int, code: str, message: str, retryable: bool = False, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "retryable": retryable}}, status_code=status,
                        headers=headers)


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


async def _stream(pipeline: Pipeline, req: AskRequest) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: str, payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (event, payload))

    def work() -> None:
        try:
            pipeline.run(req, emit)  # never raises: failures become an `error` event
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    worker = loop.run_in_executor(None, work)
    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=PING_S)
        except asyncio.TimeoutError:
            yield ": ping\n\n"
            continue
        if item is None:
            break
        yield _sse(*item)
    await worker


def _collect(pipeline: Pipeline, req: AskRequest) -> tuple[int, dict[str, Any]]:
    """Run the pipeline and assemble the non-streaming response (section 7.4)."""
    meta: dict[str, Any] = {}
    done: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    numbers: dict[str, Any] = {}
    cards: list[Any] = []

    def emit(event: str, payload: dict[str, Any]) -> None:
        nonlocal done, error
        if event == "meta":
            meta.update(payload)
        elif event == "card":
            cards.append(payload["card"])
        elif event == "numbers":
            numbers.update(payload["numbers"])
        elif event == "done":
            done = payload
        elif event == "error":
            error = payload

    pipeline.run(req, emit)
    if error is not None or done is None:
        envelope = (error or {}).get("error") or error_envelope("internal", meta.get("language", "en"))
        return (503 if envelope["code"] == "data_unavailable" else 500), {"error": envelope}
    body = {**meta, **done, "numbers": {k: v for k, v in numbers.items() if k in done["cited"]}, "cards": cards}
    return 200, body


@router.post("/api/ask")
async def ask(request: Request):
    agent = get_agent(request.app)
    try:
        body = AskBody.model_validate(await request.json())
    except (ValidationError, ValueError, TypeError):
        return _error(400, "invalid_request", ERROR_TEXT["invalid_request"])
    message = body.message.strip()
    if not message or len(body.message) > MAX_MESSAGE:
        return _error(400, "invalid_request", ERROR_TEXT["invalid_request"])
    allowed, retry_after = agent.limiter.allow(body.customer_id)
    if not allowed:
        return _error(429, "rate_limited", ERROR_TEXT["rate_limited"], True, {"Retry-After": str(retry_after)})
    try:
        exists = await run_in_threadpool(agent.data.customer_exists, body.customer_id)
    except DataUnavailable:
        return JSONResponse({"error": error_envelope("data_unavailable", "en")}, status_code=503)
    if not exists:
        return _error(404, "customer_not_found", ERROR_TEXT["customer_not_found"])

    req = AskRequest(customer_id=body.customer_id, message=body.message, language=body.language,
                     conversation_id=body.conversation_id)
    if "text/event-stream" in request.headers.get("accept", ""):
        return StreamingResponse(_stream(agent.pipeline, req), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    status, payload = await run_in_threadpool(_collect, agent.pipeline, req)
    return JSONResponse(payload, status_code=status)


@router.get("/api/audit/{answer_id}")
async def audit_record(answer_id: str, request: Request):
    """Internal: the audit record of one answer (agent-core.md section 9.1). Not part of the app contract."""
    if not answer_id.startswith("ans_") or len(answer_id) > 32:
        return _error(404, "not_found", "No such answer.")
    record = await run_in_threadpool(get_agent(request.app).audit.find, answer_id)
    if record is None:
        return _error(404, "not_found", "No such answer.")
    return JSONResponse(record)
