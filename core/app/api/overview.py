"""GET /api/overview/{customer_id} (contracts/api.md section 6), assembled from tool results.

Sections and their tools:
- hero: the safe-to-spend metric card, from HERO_TOOL = get_safe_to_spend (#55, switched on in #79):
  safe to spend in the next 7 days with its components, status and estimate text; null when the tool
  fails for a known reason (HERO_KNOWN_FAILURES).
- safe_to_save: the safe_to_save card, from SAVE_TOOL = get_safe_to_save (#165); null on a known failure.
  It reads the same row of 03_safe_to_spend.sql as the hero (safe_to_spend.metric_row, cached on the
  request's ToolContext), so the overview runs the file once.
- cards: the basket breakdown over the last 6 complete months (get_basket_breakdown) and the bills
  before payday (get_recurring_bills).
- insights: none yet (no insight tool exists).
No language model is called. One ToolContext per request, so the customer's transactions are read
once for all tools. The tools go through the tool cache (#86, core/tools/cache.py): cached results
come back at once; the others run in parallel on up to two pool connections, and their numbers are
registered in a fixed order, so ids never depend on which tool finished first.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Path, Query, Request, Response

from core.tools import review_card
from core.tools import reviews as spike_reviews
from core.tools.baskets import GetBasketBreakdownArgs, get_basket_breakdown
from core.tools.bills import GetRecurringBillsArgs, get_recurring_bills
from core.tools.cache import TOOL_CACHE, Connector, apply
from core.tools.context import ToolContext
from core.tools.models import ToolResult
from core.tools.safe_to_save import GetSafeToSaveArgs, get_safe_to_save
from core.tools.safe_to_spend import BillsDueMismatch, GetSafeToSpendArgs, NoTransactions, get_safe_to_spend

from . import texts
from .deps import CUSTOMER_ID_PATTERN, customer_connection
from .personas import persona_by_id
from .schemas import Language, MetricCard, OverviewResponse, SafeToSaveCard
from .viewer import viewer_of

router = APIRouter()

# The hero section's tool: `(ctx, args) -> ToolResult` whose card is a `metric` card.
HERO_TOOL: Callable[[ToolContext, dict], ToolResult] = get_safe_to_spend
# The tool's known failures: the hero is null instead of a 500 for the whole overview. Anything else is
# a bug and stays a 500.
HERO_KNOWN_FAILURES = (BillsDueMismatch, NoTransactions)
# The safe_to_save card's tool and its known failure (no transactions up to as_of): then the card is null.
SAVE_TOOL: Callable[[ToolContext, dict], ToolResult] = get_safe_to_save
SAVE_KNOWN_FAILURES = (NoTransactions,)
log = logging.getLogger("uvicorn.error")
# The overview's tools by function, with their cache name and argument model (#86). A tool that is not
# listed here (a test stub) is called directly.
CACHEABLE: dict[Callable, tuple[str, type]] = {
    get_safe_to_spend: ("get_safe_to_spend", GetSafeToSpendArgs),
    get_safe_to_save: ("get_safe_to_save", GetSafeToSaveArgs),
    get_basket_breakdown: ("get_basket_breakdown", GetBasketBreakdownArgs),
    get_recurring_bills: ("get_recurring_bills", GetRecurringBillsArgs),
}
SECOND_CONNECTION_TIMEOUT_S = 0.05   # take a second connection only if one is free at once


def _card(result: ToolResult) -> dict[str, Any]:
    return result.card.model_dump(mode="json")


def _results(ctx: ToolContext, calls: list[tuple[Callable, dict]],
             extra_connection: Connector | None) -> list[ToolResult | Exception]:
    """Each call's result, or its exception, in call order (one call can fail alone). The tools listed in
    CACHEABLE go through the tool cache; any other tool (a test stub, a tool added later) is called
    directly, after them, so a new tool never takes the others off the cache."""
    out: list[ToolResult | Exception | None] = [None] * len(calls)
    cached = [i for i, (fn, _) in enumerate(calls) if fn in CACHEABLE]
    if cached:
        known = [(CACHEABLE[calls[i][0]][0], CACHEABLE[calls[i][0]][1], calls[i][0], calls[i][1]) for i in cached]
        for i, p in zip(cached, TOOL_CACHE.prepare_many(known, ctx, extra_connection)):
            out[i] = p if isinstance(p, Exception) else apply(p.entry, ctx)
    for i, (fn, args) in enumerate(calls):
        if out[i] is None:
            try:
                out[i] = fn(ctx, args)
            except Exception as exc:  # noqa: BLE001 - the caller decides, like the cached path
                out[i] = exc
    return out  # type: ignore[return-value]


def build(ctx: ToolContext, hero_tool: Callable | None = None, save_tool: Callable | None = None,
          extra_connection: Connector | None = None) -> OverviewResponse:
    lang = ctx.language
    persona = persona_by_id(ctx.customer_id)
    greeting = (texts.pick(texts.GREETING, lang).format(name=persona["display_name"]) if persona
                else texts.pick(texts.GREETING_NO_NAME, lang))

    # The pending spike review (#68), found or created before any number is computed, so the hero and
    # the cards already show its purchase as `unclassified`. Creating it is the only write of this GET
    # (contract section 6); nothing is created when SPIKE_REVIEWS is off. The reviews it reads become
    # the context's labels, so no tool of this request reads them again, and the tool cache's label key
    # (#86) is made from them. The review card itself never goes through the cache.
    pending = spike_reviews.ensure_pending_for(ctx)
    review = review_card.build(ctx, pending) if pending is not None else None

    # The order puts the hero and the safe-to-save card in the same lane of the cache's parallel misses
    # (positions 0 and 2), so the one row of 03_safe_to_spend.sql they share runs once even when cold.
    hero_result, baskets_result, save_result, bills_result = _results(ctx, [
        (hero_tool or HERO_TOOL, {}),
        (get_basket_breakdown, {"period": {"preset": "last_6_months"}}),
        (save_tool or SAVE_TOOL, {}),
        (get_recurring_bills, {"include_income": False}),
    ], extra_connection)

    if isinstance(hero_result, HERO_KNOWN_FAILURES):
        # Safe to spend cannot be computed for a known reason: the hero is null and the rest of the
        # overview stays intact (coordinator decision on #106; contract 0.2.2). The log names the class only.
        log.warning("hero unavailable (%s)", type(hero_result).__name__)
        hero = None
    elif isinstance(hero_result, Exception):
        raise hero_result   # anything else is a bug and stays a 500
    else:
        hero = MetricCard.model_validate(_card(hero_result))

    if isinstance(save_result, SAVE_KNOWN_FAILURES):
        log.warning("safe to save unavailable (%s)", type(save_result).__name__)
        safe_to_save = None
    elif isinstance(save_result, Exception):
        raise save_result
    else:
        safe_to_save = SafeToSaveCard.model_validate(_card(save_result))

    for result in (baskets_result, bills_result):
        if isinstance(result, Exception):
            raise result
    cards = [_card(baskets_result), _card(bills_result)]
    # `reviews` (at most one pending review card, #68) is a top-level field, not an entry of `cards`.
    reviews: list[dict[str, Any]] = [review] if review is not None else []
    insights: list[dict[str, Any]] = []  # EXTENSION POINT: insight tools (habit_trend, one_off, ...)

    return OverviewResponse.model_validate({
        "customer_id": ctx.customer_id,
        "as_of": ctx.as_of,
        "language": lang,
        "greeting": greeting,
        "ai_disclosure": texts.pick(texts.AI_DISCLOSURE, lang),
        "hero": hero,
        "safe_to_save": safe_to_save,
        "cards": cards,
        "reviews": reviews,
        "insights": insights,
        "suggested_questions": [texts.pick(q, lang) for q in texts.SUGGESTED_QUESTIONS],
    })


@router.get("/api/overview/{customer_id}", response_model=OverviewResponse)
def get_overview(
    request: Request,
    response: Response,
    customer_id: str = Path(pattern=CUSTOMER_ID_PATTERN),
    lang: Language = Query("en"),
) -> OverviewResponse:
    pool = request.app.state.pool
    with customer_connection(request, customer_id) as conn:   # allowlist first, no database (#101)
        ctx = ToolContext(customer_id=customer_id, as_of=request.app.state.settings.demo_today, conn=conn,
                          language=lang, viewer=viewer_of(request, response))  # #144: this viewer's answers
        return build(ctx, HERO_TOOL, SAVE_TOOL, lambda: pool.connection(timeout=SECOND_CONNECTION_TIMEOUT_S))
