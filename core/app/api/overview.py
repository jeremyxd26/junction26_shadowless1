"""GET /api/overview/{customer_id} (contracts/api.md section 6), assembled from tool results.

Sections and their tools:
- hero: the safe-to-spend metric card, from HERO_TOOL. It is the one switch for that section: None
  until the tool exists (issue #55), and then the hero is null rather than faked. When #55 lands,
  set HERO_TOOL = core.tools.<module>.get_safe_to_spend.
- cards: the basket breakdown over the last 6 complete months (get_basket_breakdown) and the bills
  before payday (get_recurring_bills).
- insights: none yet (no insight tool exists).
No language model is called. One ToolContext per request, so the customer's transactions are read
once for all tools.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Path, Query, Request

from core.tools.baskets import get_basket_breakdown
from core.tools.bills import get_recurring_bills
from core.tools.context import ToolContext
from core.tools.models import ToolResult

from . import texts
from .deps import CUSTOMER_ID_PATTERN, connection, require_customer
from .personas import persona_by_id
from .schemas import Language, MetricCard, OverviewResponse

router = APIRouter()

# The switch for the hero section: a tool `(ctx, args) -> ToolResult` whose card is a `metric` card.
HERO_TOOL: Callable[[ToolContext, dict], ToolResult] | None = None


def _card(result: ToolResult) -> dict[str, Any]:
    return result.card.model_dump(mode="json")


def build(ctx: ToolContext, hero_tool: Callable | None = None) -> OverviewResponse:
    lang = ctx.language
    persona = persona_by_id(ctx.customer_id)
    greeting = (texts.pick(texts.GREETING, lang).format(name=persona["display_name"]) if persona
                else texts.pick(texts.GREETING_NO_NAME, lang))

    hero = None
    if hero_tool is not None:
        hero = MetricCard.model_validate(_card(hero_tool(ctx, {})))

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
