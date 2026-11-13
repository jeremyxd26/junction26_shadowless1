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

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.tools import label_answer, reviews

from .deps import connection, require_customer
from .errors import ApiError, envelope
from .schemas import LabelRequest, LabelResponse

router = APIRouter()


@router.post("/api/baskets/label", response_model=LabelResponse)
def post_label(request: Request, body: LabelRequest) -> LabelResponse | JSONResponse:
    with connection(request) as conn:
        try:
            require_customer(conn, body.customer_id)
        except ApiError as exc:
            return envelope(exc.code, body.language)
        try:
            result = label_answer.answer(conn, body.customer_id, request.app.state.settings.demo_today,
                                         body.tx_ref, body.basket, body.language)
        except reviews.ReviewNotFound:
            return envelope("tx_ref_not_found", body.language)
        except reviews.BasketNotAllowed:
            return envelope("basket_not_allowed", body.language)
    return LabelResponse.model_validate(result)
