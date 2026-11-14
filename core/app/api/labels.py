"""POST /api/baskets/label (contracts/api.md section 10, #68): the customer's answer to a review card.

The app calls it when the customer taps an option; it is not a tool of the AI model (R6). The work is
done by core.tools.label_answer in one database transaction; this module maps its outcomes to the
contract's responses:
- 404 tx_ref_not_found for an unknown ref, the ref of a closed (expired) review and another customer's
  ref alike, so nobody can probe for refs (R4);
- 422 basket_not_allowed for a basket key that is not one of the review's two options;
- 400 invalid_request for a malformed body, including a basket value that is not a basket key.
Error messages follow the request's `language`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.tools import label_answer, reviews
from core.tools.cache import TOOL_CACHE

from .deps import customer_connection
from .errors import envelope
from .schemas import LabelRequest, LabelResponse

log = logging.getLogger("uvicorn.error")
router = APIRouter()


@router.post("/api/baskets/label", response_model=LabelResponse)
def post_label(request: Request, body: LabelRequest) -> LabelResponse | JSONResponse:
    request.state.language = body.language  # every error from here on is in the body's language
    # The allowlist first, with no database (#101): a customer who is not served gets 404
    # customer_not_found, as on the overview, never tx_ref_not_found.
    with customer_connection(request, body.customer_id) as conn:
        try:
            result = label_answer.answer(conn, body.customer_id, request.app.state.settings.demo_today,
                                         body.tx_ref, body.basket, body.language)
        except reviews.ReviewNotFound:
            return envelope("tx_ref_not_found", body.language)
        except reviews.BasketNotAllowed:
            return envelope("basket_not_allowed", body.language)
    if result["changed"]:
        # Memory hygiene for the tool cache (#86): the new label set is in every key, so the customer's
        # old entries can never be served again; dropping them only frees memory. The write itself never
        # goes through the cache.
        TOOL_CACHE.invalidate_customer(body.customer_id)
    if result["changed"]:  # the audit record of every label write (design 7.8): who, which ref, what, when
        label = result["label"] or {}
        log.info("audit label: customer=%s tx_ref=%s basket=%s review_state=%s labelled_at=%s",
                 body.customer_id, body.tx_ref, label.get("basket"), result["review_state"],
                 label.get("labelled_at"))
    return LabelResponse.model_validate(result)
