"""POST /api/bill/read (contracts/api.md section 11.4, #250): one sample bill read by the language model and
checked by code. The response is a proposal the user confirms; it holds no Number object.

- Only the gallery's sample bills are read (core/bills/gallery.py); an unknown `sample_id` is a 400.
- The persona allowlist first, with no database (`deps.require_served`), then the read window: per client
  address and per viewer, so one visitor cannot spend the readings' share of the model budget.
- One model request per reading, on the service's model client (core/agent/gemini_client.py): the budget,
  the off-switch, the pauses and the cache are the ones every model call has. The cache key holds the
  image's SHA-256, the prompt and the schema, so a sample costs one request ever, also across a restart.
- When the model may not be used (no key, switched off, out of budget, paused, failed, or an answer that does
  not fit the schema): 503 `model_unavailable`, with no retry; the app offers typing the fields.
- The image is never stored or logged, and neither are the read fields: the log line holds counts only.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ConfigDict, Field

from core.app.ratelimit import SlidingWindowLimiter
from core.bills import gallery
from core.bills.read import BillReadUnavailable, read_bill

from .deps import require_served
from .errors import envelope
from .schemas import Language, Model
from .viewer import viewer_of

log = logging.getLogger("uvicorn.error")
router = APIRouter()

READS_PER_MINUTE_ADDRESS = 6      # a few readings while trying the gallery; the cache answers repeats
READS_PER_HOUR_VIEWER = 30


class BillReadRequest(Model):
    model_config = ConfigDict(extra="forbid")   # an unknown field is a 400

    customer_id: str = Field(pattern=r"^CUST[0-9]{5}$")
    language: Language = "en"
    sample_id: str = Field(pattern=r"^[a-z0-9_]{1,40}$")


def _limiters(request: Request) -> tuple[SlidingWindowLimiter, SlidingWindowLimiter]:
    state = request.app.state
    if getattr(state, "bill_read_limiters", None) is None:
        state.bill_read_limiters = (SlidingWindowLimiter({"address": READS_PER_MINUTE_ADDRESS}),
                                    SlidingWindowLimiter({"viewer": READS_PER_HOUR_VIEWER}, window_s=3600.0))
    return state.bill_read_limiters


def reading_client(app: Any) -> Any | None:
    """The service's model client, or None when the service runs without a model (no key). Tests put their
    own client on app.state.bill_read_client."""
    client = getattr(app.state, "bill_read_client", None)
    if client is not None:
        return client
    from core.agent.api import get_agent   # at call time: core.agent.api imports this package

    model = get_agent(app).pipeline.model
    return getattr(model, "client", None) or getattr(getattr(model, "model", None), "client", None)


def unavailable(language: str) -> JSONResponse:
    return envelope("model_unavailable", language)


@router.post("/api/bill/read", response_model=None)
def post_bill_read(request: Request, response: Response, body: BillReadRequest) -> dict[str, Any] | JSONResponse:
    request.state.language = body.language   # every error from here on is in the body's language
    require_served(request, body.customer_id)
    sample = next((s for s in gallery.gallery() if s.sample_id == body.sample_id), None)
    if sample is None:
        return envelope("invalid_request", body.language)
    from .labels import client_address

    per_minute, per_hour = _limiters(request)
    for limiter, keys in ((per_minute, {"address": client_address(request)}),
                          (per_hour, {"viewer": viewer_of(request, response)})):
        allowed, retry_after = limiter.allow(keys)
        if not allowed:
            return envelope("rate_limited", body.language, headers={"Retry-After": str(retry_after)})
    client = reading_client(request.app)
    if client is None:
        return unavailable(body.language)
    # No check of the model's state first (review of #250, decision D): a reading in the cache is served even
    # while the model may not be used (budget, pause, switch file); only a cache miss needs the model, and
    # the client then refuses it without a request.
    try:
        result = read_bill(client, sample.png.read_bytes(), "image/png", body.language)
    except BillReadUnavailable as exc:
        log.info("bill read %s: model unavailable (%s)", body.sample_id, exc)
        return unavailable(body.language)
    except Exception as exc:  # noqa: BLE001 - any failure of the read is 503; only the class name is logged
        log.warning("bill read %s: failed (%s)", body.sample_id, type(exc).__name__)
        return unavailable(body.language)
    fields = result["fields"]
    found = sum(1 for f in fields.values() if f)
    checked = sum(1 for f in fields.values() if f and f["status"] == "checked")
    log.info("bill read %s: %d fields found, %d checked", body.sample_id, found, checked)   # counts only
    return {"sample_id": body.sample_id, "language": body.language, "fields": fields, "needs_confirmation": True}
