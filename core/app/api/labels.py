"""POST /api/baskets/label (contracts/api.md section 10, #68): the customer's answer to a review card.

The app calls it when the customer taps an option; it is not a tool of the AI model (R6). The work is
done by core.tools.label_answer in one database transaction; this module maps its outcomes to the
contract's responses:
- 404 tx_ref_not_found for an unknown ref, the ref of a closed (expired) review and another customer's
  ref alike, so nobody can probe for refs (R4);
- 422 basket_not_allowed for a basket key that is not one of the review's two options;
- 400 invalid_request for a malformed body, including a basket value that is not a basket key;
- 429 rate_limited, with Retry-After (#144), in the body's language.
Error messages follow the request's `language`.

Viewer sessions (#144): the answer belongs to the viewer of the request's cookie (core.app.api.viewer).
A request without one gets a new cookie with the response, and the answer is stored under it, so it
never changes what other viewers see. Every label write sets the cookie again with a new Max-Age, so
an answer never outlives its cookie. The audit line never contains the session.

Rate limits (review of #144), all per process and in memory, none shared by all viewers of a customer:
- before any database work, sliding one-minute windows per client address, per (client address,
  customer) and per viewer session (LABEL_RATE_LIMIT_PER_MIN, LABEL_RATE_LIMIT_CUSTOMER_PER_MIN,
  LABEL_RATE_LIMIT_VIEWER_PER_MIN). Nobody can use up another address's or another viewer's budget, so
  a flood never blocks the presenter's tap;
- a one-hour window on NEW viewer sessions per client address (LABEL_NEW_SESSIONS_PER_HOUR): a first
  answer that would admit a session is refused once the address has admitted that many in the hour.
  Only an admitted session counts, and no address is ever stored in the database. With the cap of
  core.tools.reviews.MAX_SESSIONS, filling the table costs hundreds of address-hours.
The client address is the one the reverse proxy saw (core.agent.api.client_address, as /api/ask).
"""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from core.app.ratelimit import SlidingWindowLimiter
from core.tools import label_answer, reviews

from .deps import customer_connection
from .errors import envelope
from .schemas import LabelRequest, LabelResponse
from .viewer import viewer_of

log = logging.getLogger("uvicorn.error")
router = APIRouter()
_limiter_lock = threading.Lock()


def limiters(request: Request) -> tuple[SlidingWindowLimiter, SlidingWindowLimiter]:
    """The label endpoint's limiters, one pair per app, built from its settings on first use:
    (requests per minute, new viewer sessions per hour)."""
    state = request.app.state
    with _limiter_lock:
        if getattr(state, "label_limiters", None) is None:
            s = state.settings
            state.label_limiters = (
                SlidingWindowLimiter({"address": s.label_rate_limit_per_min,
                                      "address_customer": s.label_rate_limit_customer_per_min,
                                      "viewer": s.label_rate_limit_viewer_per_min}),
                SlidingWindowLimiter({"address": s.label_new_sessions_per_hour}, window_s=3600.0),
            )
        return state.label_limiters


def rate_limited(language: str, retry_after: int) -> JSONResponse:
    return envelope("rate_limited", language, headers={"Retry-After": str(retry_after)})


def client_address(request: Request) -> str:
    """The client's address as the reverse proxy saw it, exactly as /api/ask keys its limits. Imported
    at call time: core.agent.api imports this package, so a module-level import would be circular."""
    from core.agent.api import client_address as ask_client_address

    return ask_client_address(request)


@router.post("/api/baskets/label", response_model=LabelResponse)
def post_label(request: Request, response: Response, body: LabelRequest) -> LabelResponse | JSONResponse:
    request.state.language = body.language  # every error from here on is in the body's language
    per_minute, new_sessions = limiters(request)
    address = client_address(request)
    viewer = viewer_of(request, response, refresh=True)
    allowed, retry_after = per_minute.allow({"address": address, "address_customer": f"{address}|{body.customer_id}",
                                             "viewer": viewer})
    if not allowed:
        return rate_limited(body.language, retry_after)
    # The allowlist first, with no database (#101): a customer who is not served gets 404
    # customer_not_found, as on the overview, never tx_ref_not_found.
    with customer_connection(request, body.customer_id) as conn:
        first_answer = not reviews.viewer_established(conn, viewer)
        if first_answer:
            allowed, retry_after = new_sessions.check({"address": address})
            if not allowed:
                return rate_limited(body.language, retry_after)
        try:
            result = label_answer.answer(conn, body.customer_id, request.app.state.settings.demo_today,
                                         body.tx_ref, body.basket, body.language, viewer=viewer)
        except reviews.ReviewNotFound:
            return envelope("tx_ref_not_found", body.language)
        except reviews.BasketNotAllowed:
            return envelope("basket_not_allowed", body.language)
        except reviews.TooManyAnswers:
            return rate_limited(body.language, int(reviews.SESSION_TTL.total_seconds()))
    if first_answer and result["changed"]:
        new_sessions.record({"address": address})  # a session was admitted: count it, nothing else
    if result["changed"]:  # the audit record of every label write (design 7.8): who, which ref, what, when
        label = result["label"] or {}
        log.info("audit label: customer=%s tx_ref=%s basket=%s review_state=%s labelled_at=%s",
                 body.customer_id, body.tx_ref, label.get("basket"), result["review_state"],
                 label.get("labelled_at"))
    return LabelResponse.model_validate(result)
