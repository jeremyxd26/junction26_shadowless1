"""POST /api/tts (#730): one of our own answers read aloud with a Gemini TTS voice, as a WAV file.

- The body names an answer by its id, never a text: what is read is built from the answer's audit record
  (core/agent/audit.py), which the pipeline writes for every answer. Its language is the answer's resolved
  language. Since #811 that is a spoken script of the answer (core/agent/spoken.py: numbers in words, at
  most two of them, no links, one sentence on where the numbers come from), not the screen text; a record
  the script cannot read falls back to `text_rendered` (the numbers filled in, as the user saw it).
- The same checks as /api/ask: the persona allowlist first, with no database (`deps.require_served`); then
  the record must belong to the body's customer. An unknown id, an id of another customer's answer and an
  answer without text are one answer: 404 `not_found`. The audit record holds no viewer key by design
  (#144), so the binding is the customer plus an answer id nobody can guess.
- A per-address window keeps one client from spending the voice budget (core/agent/tts.py has the rest:
  the cache, the own daily budget, the switch file).
- Errors: 429 `rate_limited` with Retry-After (the window, the budget or too many at once), 503
  `model_unavailable` (no key, switched off, an API error or a timeout). The app then uses the device voice.
- This handler is synchronous (run in the thread pool), so a slow first request still fills the cache when
  the app has already given up and spoken with the device voice.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ConfigDict, Field

from core.agent.spoken import spoken_script
from core.agent.tts import TtsError, TtsService, make_tts_service
from core.app.ratelimit import SlidingWindowLimiter

from .deps import require_served
from .errors import envelope
from .schemas import Language, Model

log = logging.getLogger("uvicorn.error")
router = APIRouter()

TTS_PER_MINUTE_ADDRESS = 20   # a demo taps a few answers; a cache hit is cheap but still counts here


class TtsRequest(Model):
    model_config = ConfigDict(extra="forbid")   # an unknown field (a text) is a 400

    customer_id: str = Field(pattern=r"^CUST[0-9]{5}$")
    answer_id: str = Field(pattern=r"^ans_[a-z0-9]{8}$")
    language: Language = "en"                    # the language of an error message only


def _limiter(request: Request) -> SlidingWindowLimiter:
    state = request.app.state
    if getattr(state, "tts_limiter", None) is None:
        state.tts_limiter = SlidingWindowLimiter({"address": TTS_PER_MINUTE_ADDRESS})
    return state.tts_limiter


def tts_service(app: Any) -> TtsService:
    """Built once per process: one ledger and one cache. Tests put their own on app.state.tts_service."""
    service = getattr(app.state, "tts_service", None)
    if service is None:
        service = app.state.tts_service = make_tts_service()
    return service


def answer_record(app: Any, answer_id: str) -> dict[str, Any] | None:
    """The answer's audit record. Tests put their own AuditLog on app.state.tts_audit."""
    audit = getattr(app.state, "tts_audit", None)
    if audit is None:
        from core.agent.api import get_agent   # at call time: core.agent.api imports this package

        audit = get_agent(app).audit
    return audit.find(answer_id)


# Fewer voice requests than this left in the 24 hours: the answer carries `X-Tts-Budget: low`, and the app
# stops fetching ahead (it reads an answer only on a tap); with the budget used up the device voice reads.
LOW_TTS_LEFT = 50


def budget_header(service: TtsService) -> dict[str, str]:
    left = service.remaining()
    return {"X-Tts-Budget": "low" if left is not None and left < LOW_TTS_LEFT else "ok"}


@router.post("/api/tts", response_model=None)
def post_tts(request: Request, body: TtsRequest) -> Response | JSONResponse:
    request.state.language = body.language
    require_served(request, body.customer_id)
    from .labels import client_address

    allowed, retry_after = _limiter(request).allow({"address": client_address(request)})
    if not allowed:
        return envelope("rate_limited", body.language, headers={"Retry-After": str(retry_after)})
    record = answer_record(request.app, body.answer_id)
    text = (record or {}).get("text_rendered") or ""
    if record is None or record.get("customer_id") != body.customer_id or not text.strip():
        return envelope("not_found", body.language)
    language = ((record.get("language") or {}).get("resolved")) or body.language
    language = language if language in ("en", "fi") else "en"
    script = spoken_script(record) or text
    try:
        audio, cached = tts_service(request.app).speak(script, language)
    except TtsError as exc:
        log.info("tts %s: %s", body.answer_id, exc.code)
        if exc.code in ("budget", "busy"):
            return envelope("rate_limited", body.language, headers={"Retry-After": str(exc.retry_after or 60), "X-Tts-Budget": "low"})
        return envelope("model_unavailable", body.language)
    log.info("tts %s: %s, %d bytes", body.answer_id, "cache" if cached else "model", len(audio))
    headers = {"Cache-Control": "private, max-age=3600", **budget_header(tts_service(request.app))}
    return Response(audio, media_type="audio/wav", headers=headers)
