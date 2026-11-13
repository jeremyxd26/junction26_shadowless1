"""GET /api/overview/{customer_id} (contracts/api.md section 6), assembled from tool results.

Sections and their tools:
- hero: the safe-to-spend metric card, from HERO_TOOL = get_safe_to_spend (#55, switched on in #79):
  safe to spend in the next 7 days with its components, status and estimate text; null when the tool
  fails for a known reason (HERO_KNOWN_FAILURES).
- cards: the basket breakdown over the last 6 complete months (get_basket_breakdown) and the bills
  before payday (get_recurring_bills).
- insights: none yet (no insight tool exists).
No language model is called. One ToolContext per request, so the customer's transactions are read
once for all tools.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Path, Query, Request

from core.tools.baskets import get_basket_breakdown
from core.tools.bills import get_recurring_bills
from core.tools.context import ToolContext
from core.tools.models import ToolResult
from core.tools.safe_to_spend import BillsDueMismatch, NoTransactions, get_safe_to_spend

from . import texts
from .deps import CUSTOMER_ID_PATTERN, connection, require_customer
from .personas import persona_by_id
from .schemas import Language, MetricCard, OverviewResponse

router = APIRouter()

# The hero section's tool: `(ctx, args) -> ToolResult` whose card is a `metric` card.
HERO_TOOL: Callable[[ToolContext, dict], ToolResult] = get_safe_to_spend
# The tool's known failures: the hero is null instead of a 500 for the whole overview. Anything else is
# a bug and stays a 500.
HERO_KNOWN_FAILURES = (BillsDueMismatch, NoTransactions)
log = logging.getLogger("uvicorn.error")


def _card(result: ToolResult) -> dict[str, Any]:
    return result.card.model_dump(mode="json")


def build(ctx: ToolContext, hero_tool: Callable | None = None) -> OverviewResponse:
    lang = ctx.language
    persona = persona_by_id(ctx.customer_id)
    greeting = (texts.pick(texts.GREETING, lang).format(name=persona["display_name"]) if persona
                else texts.pick(texts.GREETING_NO_NAME, lang))

    try:
        hero = MetricCard.model_validate(_card((hero_tool or HERO_TOOL)(ctx, {})))
    except HERO_KNOWN_FAILURES as exc:
        # Safe to spend cannot be computed for a known reason: the hero is null and the rest of the
        # overview stays intact (coordinator decision on #106; contract 0.2.2). The log names the class only.
        log.warning("hero unavailable (%s)", type(exc).__name__)
        hero = None

    cards = [
        _card(get_basket_breakdown(ctx, {"period": {"preset": "last_6_months"}})),
        _card(get_recurring_bills(ctx, {"include_income": False})),
    ]
    # EXTENSION POINT (contract 0.2.0, section 6): `reviews` (at most one pending review card, #68)
    # and `safe_to_save` (a safe_to_save card, #53/#55) are top-level fields, not entries of `cards`.
    # `reviews` is [] until #68 fills it; `safe_to_save` is added once its tool exists.
    reviews: list[dict[str, Any]] = []
    insights: list[dict[str, Any]] = []  # EXTENSION POINT: insight tools (habit_trend, one_off, ...)

    return OverviewResponse.model_validate({
        "customer_id": ctx.customer_id,
        "as_of": ctx.as_of,
        "language": lang,
        "greeting": greeting,
        "ai_disclosure": texts.pick(texts.AI_DISCLOSURE, lang),
        "hero": hero,
        "cards": cards,
        "reviews": reviews,
        "insights": insights,
        "suggested_questions": [texts.pick(q, lang) for q in texts.SUGGESTED_QUESTIONS],
    })


@router.get("/api/overview/{customer_id}", response_model=OverviewResponse)
def get_overview(
    request: Request,
    customer_id: str = Path(pattern=CUSTOMER_ID_PATTERN),
    lang: Language = Query("en"),
) -> OverviewResponse:
    with connection(request) as conn:
        require_customer(conn, customer_id)
        ctx = ToolContext(customer_id=customer_id, as_of=request.app.state.settings.demo_today, conn=conn,
                          language=lang)
        return build(ctx, HERO_TOOL)
