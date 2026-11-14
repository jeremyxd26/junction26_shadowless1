"""POST /api/stt (#735): a short spoken question turned into text for the composer. Nothing is stored.

- The body is the clip itself, as the browser's MediaRecorder gives it (audio/webm, audio/mp4 on Safari,
  audio/ogg, or audio/wav), with its Content-Type. `customer_id` and `language` are query parameters, so
  no multipart parser is needed.
- The same checks as /api/ask: the persona allowlist first, with no database (`deps.require_served`); the
  viewer cookie as /api/ask reads it (`known_viewer`, never set here) keys a per-viewer window, next to a
  per-address window, so one visitor cannot spend the budget. A request without a cookie shares one key.
- Limits before the body is read: a known audio type, and a declared Content-Length of at most MAX_BYTES;
  the body is then read with a running cap, so a chunked body cannot go over either. Too large: 413
  `invalid_request`; an unknown type, an empty or unreadable clip, or a WAV clip over 15 s: 400.
- The text goes back as JSON and nowhere else: no audit record, no file, no log line with audio or text.
- Errors as /api/tts: 429 `rate_limited` with Retry-After (the windows, the budget or too many at once), 503
  `model_unavailable` (no key, switched off, an API error, a timeout, or no speech heard).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from core.agent.stt import MAX_BYTES, SttError, SttService, gemini_mime, make_stt_service
from core.app.ratelimit import SlidingWindowLimiter

from .deps import require_served
from .errors import envelope
from .viewer import known_viewer

log = logging.getLogger("uvicorn.error")
router = APIRouter()

STT_PER_MINUTE_ADDRESS = 10   # a few spoken questions while trying the demo
STT_PER_HOUR_VIEWER = 40
CUSTOMER = r"^CUST[0-9]{5}$"


def _limiters(request: Request) -> tuple[SlidingWindowLimiter, SlidingWindowLimiter]:
    state = request.app.state
    if getattr(state, "stt_limiters", None) is None:
        state.stt_limiters = (SlidingWindowLimiter({"address": STT_PER_MINUTE_ADDRESS}),
                              SlidingWindowLimiter({"viewer": STT_PER_HOUR_VIEWER}, window_s=3600.0))
    return state.stt_limiters


def stt_service(app: Any) -> SttService:
    """Built once per process: one ledger. Tests put their own on app.state.stt_service."""
    service = getattr(app.state, "stt_service", None)
    if service is None:
        service = app.state.stt_service = make_stt_service()
    return service


def too_large(language: str) -> JSONResponse:
    return envelope("invalid_request", language, status=413)


async def read_capped(request: Request, cap: int) -> bytes | None:
    """The body, or None as soon as it goes over `cap` bytes (the rest is not read)."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > cap:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/api/stt", response_model=None)
async def post_stt(request: Request, customer_id: str = "", language: str = "en") -> dict[str, Any] | JSONResponse:
    lang = language if language in ("en", "fi") else "en"
    request.state.language = lang
    if not re.fullmatch(CUSTOMER, customer_id) or language not in ("en", "fi"):
        return envelope("invalid_request", lang)
    require_served(request, customer_id)
    content_type = request.headers.get("content-type")
    if gemini_mime(content_type) is None:
        return envelope("invalid_request", lang)
    declared = request.headers.get("content-length", "").strip()
    if declared.isdigit() and int(declared) > MAX_BYTES:
        return too_large(lang)
    from .labels import client_address

    per_minute, per_hour = _limiters(request)
    for limiter, keys in ((per_minute, {"address": client_address(request)}),
                          (per_hour, {"viewer": known_viewer(request) or "no-cookie"})):
        allowed, retry_after = limiter.allow(keys)
        if not allowed:
            return envelope("rate_limited", lang, headers={"Retry-After": str(retry_after)})
    audio = await read_capped(request, MAX_BYTES)
    if audio is None:
        return too_large(lang)
    try:
        text = await run_in_threadpool(stt_service(request.app).transcribe, audio, content_type, lang)
    except SttError as exc:
        log.info("stt: %s, %d bytes", exc.code, len(audio))   # the code and the size only
        if exc.code == "too_large":
            return too_large(lang)
        if exc.code in ("empty", "unsupported", "too_long"):
            return envelope("invalid_request", lang)
        if exc.code in ("budget", "busy"):
            return envelope("rate_limited", lang, headers={"Retry-After": str(exc.retry_after or 60)})
        return envelope("model_unavailable", lang)
    return {"text": text, "language": lang}
