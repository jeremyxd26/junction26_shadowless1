"""POST /api/bill/explain (contracts/api.md section 11, #242): a bill explained with the customer's own data.

No language model is called and nothing is stored (core/tools/bill_explain.py).
- The request model refuses an unknown field, an over-long text, an amount outside (0, 100000.00] or with
  more than two decimals, and a due date that is not `YYYY-MM-DD`: a 400 `invalid_request`.
- The customer goes through the persona allowlist first, with no database (`deps.require_served`).
- Exactly one of `barcode` and `fields`; both or neither, or `payee` beside `fields`, and a barcode that
  cannot be used are a 422 `invalid_bill` whose body adds `reason`, and whose `message` is that reason's
  sentence in the body's language, so the app can fall back to the fields form.
- A typed IBAN or reference that fails its check, or a due date in the past, is not an error: the
  response says so in `checks`, `signals` and `warnings`.
- Error messages are in the body's `language` (contract section 1), through `request.state.language`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from core.tools import config
from core.tools.bill_explain import BillRefused, explain_bill, read_barcode, read_fields
from core.tools.context import ToolContext

from .deps import customer_connection, require_served
from .schemas import BillExplainRequest, BillExplainResponse
from .viewer import viewer_of

router = APIRouter()


def refusal(reason: str, language: str) -> JSONResponse:
    """The 422 invalid_bill of contracts/api.md section 11.1: the envelope plus `reason`."""
    body = {"error": {"code": "invalid_bill", "message": config.label(config.BILL_REFUSAL_TEXT[reason], language),
                      "retryable": False, "reason": reason}}
    return JSONResponse(body, status_code=422)


@router.post("/api/bill/explain", response_model=BillExplainResponse)
def post_bill_explain(request: Request, response: Response,
                      body: BillExplainRequest) -> BillExplainResponse | JSONResponse:
    request.state.language = body.language  # every error from here on is in the body's language
    require_served(request, body.customer_id)  # the persona allowlist first, no database (#101)
    if (body.barcode is None) == (body.fields is None):
        return refusal("one_of_barcode_or_fields", body.language)
    if body.fields is not None and body.payee is not None:
        return refusal("payee_with_fields", body.language)
    try:
        if body.barcode is not None:
            bill = read_barcode(body.barcode, body.payee)
        else:
            f = body.fields
            bill = read_fields(f.payee, f.iban, f.reference, f.amount, f.due_date)
    except BillRefused as exc:
        return refusal(exc.reason, body.language)
    with customer_connection(request, body.customer_id) as conn:
        # The viewer's labels (#144), as on the overview and in /api/whatif: after a viewer answers a spike
        # review, the bill's "safe to spend" before and after are that viewer's, the same as their hero.
        ctx = ToolContext(customer_id=body.customer_id, as_of=request.app.state.settings.demo_today, conn=conn,
                          language=body.language, viewer=viewer_of(request, response))
        out = explain_bill(ctx, bill)
    return BillExplainResponse.model_validate(
        {"customer_id": body.customer_id, "as_of": ctx.as_of, "language": body.language, **out})
