"""The customer's answer to a review card: store it, and say which overview numbers moved (#68).

Used by POST /api/baskets/label (contract 0.2.0 section 10). It is not a tool of the AI model: the
app calls the endpoint when the customer taps an option (R6).

One database transaction: the review row is locked, the overview numbers are computed before the
change, the answer is written, and the numbers are computed again. Both sets come from the same
tools as the overview (get_basket_breakdown, get_safe_to_spend), so `before` equals what the overview
showed and `after` equals what it shows next. Each number keeps its own evidence ref: the spec records
the label set it was computed with, so a ref issued before the answer keeps reconciling.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import psycopg

from core.tools import config, evidence, labels, reviews
from core.tools.baskets import get_basket_breakdown
from core.tools.classify import classify
from core.tools.context import NumberRegistry, ToolContext
from core.tools.models import Number
from core.tools.numbers import NumberBuilder
from core.tools.review_card import amount_number, purchase
from core.tools.safe_to_spend import get_safe_to_spend
from core.tools.selection import Selection

BASKET_KEYS = ("unclassified", *config.BASKETS)
CHANGE_ORDER = (*BASKET_KEYS, "irregular_reserve", "safe_to_spend")


def _t(key: str, language: str, **kw: Any) -> str:
    return config.label(config.REVIEW_TEXT[key], language).format(product=config.PRODUCT_NAME, **kw)


def overview_numbers(ctx: ToolContext) -> dict[str, tuple[str, Number]]:
    """The overview numbers an answer can move, by key: the four basket states (monthly averages over
    the last 6 complete months; a state with no purchase is 0), the reserve for unexpected necessities
    and safe to spend."""
    lang = ctx.language
    data = get_basket_breakdown(ctx, {"period": {"preset": "last_6_months"}}).data
    out: dict[str, tuple[str, Number]] = {}
    shown = {b.key: b.amount for b in data.baskets}
    missing = [k for k in BASKET_KEYS if k not in shown]
    if missing:  # a zero with its own evidence, computed like the breakdown's items
        rows = classify(ctx.history(), ctx.as_of, labels.for_context(ctx))
        nb = NumberBuilder(ctx, rows)
        for key in missing:
            sel = Selection(direction="out", start=data.period.start, end=data.period.end, baskets=(key,))
            shown[key], _ = nb.transactions(sel, config.METHODS["basket_month_avg"], data.period,
                                            config.label(config.BASKET_LABELS[key], lang),
                                            params={"n_months": data.n_months})
        evidence.write(ctx.conn, nb.specs)
    for key in BASKET_KEYS:
        label = _t("month_avg", lang, label=config.label(config.BASKET_LABELS[key], lang))
        out[key] = (label, shown[key])
    sts = get_safe_to_spend(ctx, {}).data
    reserve = next(c for c in sts.components if c.key == "irregular_reserve")
    out["irregular_reserve"] = (reserve.label, reserve.amount)
    out["safe_to_spend"] = (config.label(config.SAFE_TO_SPEND_TEXT["safe_to_spend"], lang), sts.safe_to_spend)
    return out


def changes(before: dict[str, tuple[str, Number]], after: dict[str, tuple[str, Number]]) -> list[dict[str, Any]]:
    """The numbers whose value moved, in overview order (a value diff, never a ref diff)."""
    out = []
    for key in CHANGE_ORDER:
        (label, b), (_, a) = before[key], after[key]
        if b.value != a.value:
            out.append({"key": key, "label": label,
                        "before": b.model_dump(mode="json", exclude={"id"}),
                        "after": a.model_dump(mode="json", exclude={"id"})})
    return out


def _timestamp(moment: datetime | None) -> str | None:
    """Contract section 1: ISO 8601 with offset, Helsinki wall clock, whole seconds."""
    if moment is None:
        return None
    return moment.astimezone(reviews.HELSINKI).replace(microsecond=0).isoformat()


def _message(ctx: ToolContext, outcome: reviews.Outcome) -> dict[str, Any]:
    lang = ctx.language
    numbers: dict[str, Any] = {}
    if not outcome.changed:
        text = rendered = _t("unchanged" if outcome.review.basket else "still_pending", lang)
    elif outcome.review.basket == "everyday_spending":
        found = purchase(ctx, outcome.review)
        n1 = amount_number(ToolContext(ctx.customer_id, ctx.as_of, ctx.conn, lang, NumberRegistry(),
                                       _history=ctx.history(), _labels=ctx._labels, viewer=ctx.viewer), *found)
        text = _t("done_everyday_spending", lang, amount="{{" + n1.id + "}}")
        rendered = _t("done_everyday_spending", lang, amount=n1.display)
        numbers[n1.id] = n1.model_dump(mode="json")
    elif outcome.review.basket == "unexpected_necessities":
        text = rendered = _t("done_unexpected_necessities", lang)
    else:
        text = rendered = _t("undone_pending" if outcome.state == reviews.PENDING else "undone_closed", lang)
    return {"text": text, "text_rendered": rendered, "numbers": numbers}


def answer(conn: psycopg.Connection, customer_id: str, as_of: date, tx_ref: str, basket: str | None,
           language: str = "en", now: datetime | None = None, viewer: str | None = None) -> dict[str, Any]:
    """Store the answer to a review and return the response body of contract section 10.

    With a `viewer` (the API, #144) the answer is that viewer's own and every number before and after
    is the viewer's; without one (tools, scripts) it is the shared answer.

    Raises reviews.ReviewNotFound (unknown, foreign or closed ref; also when SPIKE_REVIEWS is off),
    reviews.BasketNotAllowed (a basket key that is not one of the two options) and
    reviews.TooManyAnswers (the viewer's session is full).
    """
    if not reviews.enabled():
        raise reviews.ReviewNotFound(tx_ref)
    now = now or reviews.utcnow()
    with conn.transaction():
        if viewer is not None:
            # A viewer's answer never changes the shared rows that review creation looks at (one open
            # review per 7 days follows created_at only), so it serialises with this viewer alone.
            reviews.lock_viewer(conn, viewer, customer_id)
        else:
            reviews.lock_customer(conn, customer_id)  # the lock review creation takes (one open review)
        review = reviews.find(conn, customer_id, tx_ref, lock=viewer is None, viewer=viewer, now=now)
        outcome = reviews.decide(review, basket, now)
        ctx = ToolContext(customer_id, as_of, conn, language, viewer=viewer)
        moved: list[dict[str, Any]] = []
        if outcome.changed:
            before = overview_numbers(ctx)
            if viewer is not None:
                reviews.save_answer(conn, viewer, outcome.review, now)
            else:
                reviews.save(conn, outcome.review)
            ctx = ToolContext(customer_id, as_of, conn, language, _history=ctx.history(), viewer=viewer)
            moved = changes(before, overview_numbers(ctx))
        message = _message(ctx, outcome)
    label = None
    if outcome.review.basket is not None:
        label = {"basket": outcome.review.basket,
                 "label": config.label(config.BASKET_LABELS[outcome.review.basket], language),
                 "labelled_at": _timestamp(outcome.review.answered_at)}
    return {
        "customer_id": customer_id,
        "as_of": as_of.isoformat(),
        "language": language,
        "tx_ref": tx_ref,
        "label": label,
        "review_state": outcome.state,
        "changed": outcome.changed,
        "message": message,
        "changes": moved,
        "refetch": [f"/api/overview/{customer_id}"],
    }
