"""POST /api/baskets/label (contracts/api.md section 10, #68): the customer's answer to a review card.

The app calls it when the customer taps an option; it is not a tool of the AI model (R6). The work is
done by core.tools.label_answer in one database transaction; this module maps its outcomes to the
contract's responses:
- 404 tx_ref_not_found for an unknown ref, the ref of a closed (expired) review and another customer's
  ref alike, so nobody can probe for refs (R4);
- 422 basket_not_allowed for a basket key that is not one of the review's two options;
- 400 invalid_request for a malformed body, including a basket value that is not a basket key;
- 429 rate_limited, with Retry-After (#144): per client address and per customer, sliding one-minute
  windows (LABEL_RATE_LIMIT_PER_MIN, LABEL_RATE_LIMIT_CUSTOMER_PER_MIN), checked before any database
  work; also when the viewer's session holds too many answers.
Error messages follow the request's `language`.

Viewer sessions (#144): the answer belongs to the viewer of the request's cookie (core.app.api.viewer).
A request without one gets a new cookie with the response, and the answer is stored under it, so it
never changes what other viewers see. The audit line never contains the session.
"""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from core.app.ratelimit import SlidingWindowLimiter, client_address
from core.tools import label_answer, reviews

from .deps import customer_connection
from .errors import envelope
from .schemas import LabelRequest, LabelResponse
from .viewer import viewer_of

log = logging.getLogger("uvicorn.error")
router = APIRouter()
_limiter_lock = threading.Lock()


def limiter(request: Request) -> SlidingWindowLimiter:
    """The label endpoint's limiter, one per app, built from its settings on first use."""
    state = request.app.state
    with _limiter_lock:
        if getattr(state, "label_limiter", None) is None:
            s = state.settings
            state.label_limiter = SlidingWindowLimiter({"address": s.label_rate_limit_per_min,
                                                        "customer": s.label_rate_limit_customer_per_min})
        return state.label_limiter


def rate_limited(language: str, retry_after: int) -> JSONResponse:
    return envelope("rate_limited", language, headers={"Retry-After": str(retry_after)})


@router.post("/api/baskets/label", response_model=LabelResponse)
def post_label(request: Request, response: Response, body: LabelRequest) -> LabelResponse | JSONResponse:
    request.state.language = body.language  # every error from here on is in the body's language
    allowed, retry_after = limiter(request).allow({"address": client_address(request),
                                                   "customer": body.customer_id})
    if not allowed:
        return rate_limited(body.language, retry_after)
    viewer = viewer_of(request, response)
    # The allowlist first, with no database (#101): a customer who is not served gets 404
    # customer_not_found, as on the overview, never tx_ref_not_found.
    with customer_connection(request, body.customer_id) as conn:
        try:
            result = label_answer.answer(conn, body.customer_id, request.app.state.settings.demo_today,
                                         body.tx_ref, body.basket, body.language, viewer=viewer)
        except reviews.ReviewNotFound:
            return envelope("tx_ref_not_found", body.language)
        except reviews.BasketNotAllowed:
            return envelope("basket_not_allowed", body.language)
        except reviews.TooManyAnswers:
            return rate_limited(body.language, int(reviews.SESSION_TTL.total_seconds()))
    if result["changed"]:  # the audit record of every label write (design 7.8): who, which ref, what, when
        label = result["label"] or {}
        log.info("audit label: customer=%s tx_ref=%s basket=%s review_state=%s labelled_at=%s",
                 body.customer_id, body.tx_ref, label.get("basket"), result["review_state"],
                 label.get("labelled_at"))
    return LabelResponse.model_validate(result)
