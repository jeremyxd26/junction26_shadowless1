"""POST /api/whatif (contracts/api.md section 8), built from run_what_if. No language model is called.

- The request is validated first: unknown fields are ignored, but a bad customer id, a selection kind
  outside the contract, an empty value or a cut that is not a whole number from 1 to 100 is a 400.
- A merchant selection carries the merchant id from a card (section 8.1); the tool works with the
  customer's own aliases, so the id is mapped to its alias here. An alias is accepted as it is.
- Everything the tool refuses about the selection is a 422 `invalid_scenario`, with the contract's
  fixed message and no detail, one identical body for every reason (so Health cannot be told apart):
  - Health or another sensitive selection (R9);
  - a category that is not spending, an unknown basket, a malformed MCC;
  - a merchant this customer has not used;
  - a selection with no spending in the window.
  Only the tool's refusal type (`WhatIfRefused`) and the argument validation are mapped; any other
  error of the tool is a bug and stays a 500.
- A cut of regular essentials is not an error: the tool returns the status `not_offered`.
- Error messages are in the body's `language` (contract section 1), through `request.state.language`.
- The labels are the viewer's (#144, core.app.api.viewer), as on the overview: after a viewer answers a
  spike review, their what-if starts from the same state as their hero; other viewers are unaffected.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Request, Response
from pydantic import ValidationError

from core.tools import aliases
from core.tools.context import ToolContext
from core.tools.models import MERCHANT_ALIAS_PATTERN
from core.tools.what_if import RunWhatIfArgs, WhatIfRefused, run_what_if

from .deps import customer_connection
from .errors import ApiError
from .schemas import WhatIfRequest, WhatIfResponse
from .viewer import viewer_of

router = APIRouter()


def build(ctx: ToolContext, body: WhatIfRequest) -> WhatIfResponse:
    sel = body.scenario.selection
    value = sel.value
    if sel.kind == "merchant" and not re.fullmatch(MERCHANT_ALIAS_PATTERN, value):
        try:
            value = aliases.build(ctx.history(), ctx.as_of).for_merchant(value).key
        except KeyError:
            raise ApiError("invalid_scenario") from None
    try:
        args = RunWhatIfArgs.model_validate(
            {"selection": {"kind": sel.kind, "value": value}, "cut_pct": body.scenario.cut_pct})
    except ValidationError:
        raise ApiError("invalid_scenario") from None
    try:
        result = run_what_if(ctx, args)
    except WhatIfRefused:  # the tool's refusals: R9, unknown alias, no spending in the window
        raise ApiError("invalid_scenario") from None
    card = result.card
    return WhatIfResponse.model_validate({
        "customer_id": ctx.customer_id,
        "as_of": ctx.as_of,
        "language": ctx.language,
        **result.data.model_dump(mode="json"),
        "estimate": card.estimate.model_dump(mode="json") if card.estimate else None,
        "evidence_ref": card.evidence_ref,
    })


@router.post("/api/whatif", response_model=WhatIfResponse)
def post_whatif(request: Request, response: Response, body: WhatIfRequest) -> WhatIfResponse:
    request.state.language = body.language  # every error from here on is in the body's language
    with customer_connection(request, body.customer_id) as conn:   # allowlist first, no database (#101)
        ctx = ToolContext(customer_id=body.customer_id, as_of=request.app.state.settings.demo_today, conn=conn,
                          language=body.language, viewer=viewer_of(request, response))  # #144: this viewer's answers
        return build(ctx, body)
