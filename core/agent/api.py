"""POST /api/ask (contracts/api.md section 7) and the internal GET /api/audit/{answer_id}.

Step 0 runs before any stream is opened, and its failures are plain HTTP errors with the error
envelope: 400 invalid_request (bad body, message empty or over 500 characters), 404
customer_not_found (a customer the service does not serve, #101, checked first and without the
database; or an unknown one), 429 rate_limited, 503 data_unavailable. After that the answer is either a server-sent event
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
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg_pool import PoolTimeout
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool

from core.agent import guard
from core.agent.audit import AuditLog
from core.app.api import deps
from core.app.api.errors import envelope
from core.agent.conversation import ConversationStore
from core.agent.orchestrator import AskRequest, DataAccess, DataUnavailable, LabelSteps, Pipeline, error_envelope
from core.agent.rules import RuleModel
from core.agent.toolset import default_registry

router = APIRouter()

PING_S = 10.0
MAX_MESSAGE = 500
CONNECTION_TIMEOUT_S = 5.0
CUSTOMER_SQL = "SELECT 1 FROM customers WHERE customer_id = %s"


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

    def connection(self) -> AbstractContextManager[Any]:
        return self._connect(CONNECTION_TIMEOUT_S)

    def connection_if_free(self, wait: float) -> AbstractContextManager[Any]:
        """A connection only if one is free within `wait` seconds (a second tool lane)."""
        return self._connect(wait)

    @contextmanager
    def _connect(self, timeout: float) -> Iterator[Any]:
        pool = self._app.state.pool
        if pool is None:
            raise DataUnavailable()
        try:
            with pool.connection(timeout=timeout) as conn:
                yield conn
        except (PoolTimeout, psycopg.OperationalError):
            raise DataUnavailable() from None

    def customer_exists(self, customer_id: str) -> bool:
        with self.connection() as conn:
            return conn.execute(CUSTOMER_SQL, (customer_id,)).fetchone() is not None


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


class AskLimits:
    """Per-process limits on POST /api/ask, checked before the stream opens (security issue #85).

    Three sliding one-minute windows; 0 turns a limit off:
    - per client address (ASK_RATE_LIMIT_PER_MIN, default 10): the address uvicorn reports. In the
      image uvicorn runs with --proxy-headers behind Caddy, which replaces X-Forwarded-For, so this is
      the address Caddy saw; changing the customer_id in the body never resets it;
    - global (ASK_RATE_LIMIT_GLOBAL_PER_MIN, default 60): all asks of this process together, which
      also caps how often one customer can be asked about from many addresses;
    - per address and customer (ASK_RATE_LIMIT_CUSTOMER_PER_MIN, default 10): keyed by both, so one
      address that uses up its window for a persona never blocks that persona for anyone else (on
      the public demo, every visitor asks about the same four personas).
    A request counts only if every limit allows it.
    """

    def __init__(self, per_address: int, global_: int, per_customer: int) -> None:
        self.limits = {"address": per_address, "global": global_, "customer": per_customer}
        self._hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> AskLimits:
        return cls(_env_int("ASK_RATE_LIMIT_PER_MIN", 10), _env_int("ASK_RATE_LIMIT_GLOBAL_PER_MIN", 60),
                   _env_int("ASK_RATE_LIMIT_CUSTOMER_PER_MIN", 10))

    def allow(self, address: str, customer_id: str) -> tuple[bool, int]:
        now = time.monotonic()
        keys = {"address": address, "global": "*", "customer": f"{address} {customer_id}"}
        with self._lock:
            retry = 0
            for kind, limit in self.limits.items():
                if limit <= 0:
                    continue
                hits = self._hits[(kind, keys[kind])]
                while hits and now - hits[0] > 60:
                    hits.popleft()
                if len(hits) >= limit:
                    retry = max(retry, int(60 - (now - hits[0])) + 1)
            if retry:
                return False, retry
            for kind, limit in self.limits.items():
                if limit > 0:
                    self._hits[(kind, keys[kind])].append(now)
            return True, 0


def trusted_proxies() -> set[str]:
    """Peers whose X-Forwarded-For is believed; TRUSTED_PROXIES is a comma-separated list, default
    loopback only. In the image (deploy/Dockerfile) uvicorn runs with --proxy-headers behind Caddy,
    which replaces X-Forwarded-For, so the peer uvicorn reports is already the client's address; this
    list matters when the service runs without those flags behind a proxy on the same host."""
    raw = os.environ.get("TRUSTED_PROXIES", "127.0.0.1,::1")
    return {p.strip() for p in raw.split(",") if p.strip()}


def client_address(request: Request) -> str:
    """The client's address as the reverse proxy saw it. X-Forwarded-For is used only when the direct
    peer is a trusted proxy, and then only its rightmost entry: the one our proxy wrote, not anything
    the client sent. From any other peer the header is ignored, so it cannot change the key."""
    peer = request.client.host if request.client else "unknown"
    if peer in trusted_proxies():
        forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
        if forwarded:
            return forwarded[-1]
    return peer


@dataclass
class Agent:
    pipeline: Pipeline
    data: DataAccess
    audit: AuditLog
    limits: AskLimits = field(default_factory=AskLimits.from_env)


def build_agent(app) -> Agent:
    """The service's agent: the built-in tools, the keyword model (until the Gemini adapter) and the
    app's pool. Tests put their own Agent on app.state.agent instead."""
    data = PoolData(app)
    audit = AuditLog()
    pipeline = Pipeline(default_registry(), RuleModel(), data, as_of=app.state.settings.demo_today,
                        store=ConversationStore(), audit=audit, labels=label_steps())
    return Agent(pipeline=pipeline, data=data, audit=audit)


def label_steps() -> LabelSteps:
    """The overview's label functions (#68, #196): the same state for an answer as for the overview."""
    from core.tools import review_card, reviews

    return LabelSteps(establish=reviews.ensure_pending_for, card=review_card.build, enabled=reviews.enabled)


def get_agent(app) -> Agent:
    agent = getattr(app.state, "agent", None)
    if agent is None:
        agent = app.state.agent = build_agent(app)
    return agent


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
        failure = (error or {}).get("error") or error_envelope("internal", meta.get("language", "en"))
        return (503 if failure["code"] == "data_unavailable" else 500), {"error": failure}
    body = {**meta, **done, "numbers": {k: v for k, v in numbers.items() if k in done["cited"]}, "cards": cards}
    return 200, body


@router.post("/api/ask")
async def ask(request: Request):
    agent = get_agent(request.app)
    try:
        body = AskBody.model_validate(await request.json())
    except (ValidationError, ValueError, TypeError):
        return envelope("invalid_request", "en")  # a body that cannot be read has no language
    # Every error from here on is in the request's language (as /api/whatif): the body's `language`,
    # else the question's detected language. The length is checked first, so a huge message is refused
    # before any work on its text, and the detector never sees more than MAX_MESSAGE characters.
    if len(body.message) > MAX_MESSAGE:
        return envelope("invalid_request", body.language if body.language in ("en", "fi") else "en")
    lang = body.language if body.language in ("en", "fi") else guard.detect_language(guard.clean(body.message)) or "en"
    request.state.language = lang
    message = body.message.strip()
    if not message:
        return envelope("invalid_request", lang)
    deps.require_served(request, body.customer_id)  # the persona allowlist (#101): the same 404 as unknown
    allowed, retry_after = agent.limits.allow(client_address(request), body.customer_id)
    if not allowed:
        return envelope("rate_limited", lang, headers={"Retry-After": str(retry_after)})
    try:
        exists = await run_in_threadpool(agent.data.customer_exists, body.customer_id)
    except DataUnavailable:
        return envelope("data_unavailable", lang)
    if not exists:
        return envelope("customer_not_found", lang)

    req = AskRequest(customer_id=body.customer_id, message=body.message, language=body.language,
                     conversation_id=body.conversation_id)
    if "text/event-stream" in request.headers.get("accept", ""):
        return StreamingResponse(_stream(agent.pipeline, req), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    status, payload = await run_in_threadpool(_collect, agent.pipeline, req)
    return JSONResponse(payload, status_code=status)


def audit_api_enabled() -> bool:
    """The audit read endpoint exists only with AUDIT_API=1 (meant for local eval runs): on the dev
    service /api/* is public, and a record holds a customer's question, tool calls and model views."""
    return os.environ.get("AUDIT_API", "").strip() == "1"


# Registered by core/app/main.py only when audit_api_enabled() at start-up (issue #189): with the switch
# off, /api/audit/... is an ordinary unknown path, so nobody can tell that the route exists.
audit_router = APIRouter()


@audit_router.get("/api/audit/{answer_id}")
async def audit_record(answer_id: str, request: Request):
    """Internal: the audit record of one answer (agent-core.md section 9.1). Not part of the app contract.
    The audit files are written whether or not the route exists."""
    if not answer_id.startswith("ans_") or len(answer_id) > 32:
        return envelope("not_found", "en")
    record = await run_in_threadpool(get_agent(request.app).audit.find, answer_id)
    if record is None:
        return envelope("not_found", "en")
    return JSONResponse(record)
