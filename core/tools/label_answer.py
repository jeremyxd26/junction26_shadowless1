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

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg

from core.tools import config, evidence, labels, reviews
from core.tools.baskets import get_basket_breakdown
from core.tools.classify import classify
from core.tools.context import NumberRegistry, ToolContext
from core.tools.models import Number
from core.tools.numbers import NumberBuilder
from core.tools.review_card import amount_number, purchase
from core.tools.safe_to_save import get_safe_to_save
from core.tools.safe_to_spend import NoTransactions, binding_limit, get_safe_to_spend
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
    # #382: the limits say why safe to spend did not move; safe to save is the overview's second headline.
    out["balance_limit"] = (sts.balance_limit.label, sts.balance_limit)
    out["budget_limit"] = (sts.budget_limit.label, sts.budget_limit)
    try:
        save = get_safe_to_save(ctx, {}).data
        out["safe_to_save"] = (save.monthly.label, save.monthly)
    except NoTransactions:  # the overview shows no safe-to-save card either
        pass
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


EFFECT_KEYS = ("safe_to_spend", "safe_to_save", "irregular_reserve")


def _e(key: str, language: str) -> str:
    return config.label(config.LABEL_EFFECT_TEXT[key], language)


def effect_text(before: dict[str, tuple[str, Number]], after: dict[str, tuple[str, Number]], basket: str | None,
                state: str, amount: str, token: Any, language: str) -> str:
    """The effect of an answer from the real difference (#382): two sentences at most, three numbers.

    `token(key, side)` gives the {{nK}} token of a number, `amount` the purchase's token. Safe to spend
    moved: from what to what, and where the purchase went. It did not: where the purchase went, then
    either what safe to save did, or why safe to spend stays (which limit binds, by the formula)."""
    def value(side: dict, key: str) -> float | None:
        return side[key][1].value if key in side else None

    reserve_grew = (value(after, "irregular_reserve") or 0) > (value(before, "irregular_reserve") or 0)
    if basket == "unexpected_necessities":
        why = _e("why_unexpected_reserve" if reserve_grew else "why_unexpected", language)
    elif basket == "everyday_spending":
        why = _e("why_everyday", language)
    else:
        why = _e("why_pending" if state == reviews.PENDING else "why_closed", language)
    if value(before, "safe_to_spend") != value(after, "safe_to_spend"):
        return _e("moved", language).format(before=token("safe_to_spend", "before"),
                                            after=token("safe_to_spend", "after"), amount=amount, why=why)
    first = _e("basket", language).format(amount=amount, why=why)
    if "safe_to_save" in before and value(before, "safe_to_save") != value(after, "safe_to_save"):
        second = _e("save_moved", language).format(before=token("safe_to_save", "before"),
                                                   after=token("safe_to_save", "after"))
    else:
        limits = after if "balance_limit" in after else before
        binding = binding_limit(Decimal(str(value(limits, "balance_limit"))),
                                Decimal(str(value(limits, "budget_limit"))))
        second = _e("same_balance" if binding == "balance" else "same_budget", language)
    return f"{first} {second}"


def effect(ctx: ToolContext, outcome: reviews.Outcome, before: dict[str, tuple[str, Number]],
           after: dict[str, tuple[str, Number]]) -> dict[str, Any]:
    """`effect` of the response (#382): the headline numbers before and after (safe to spend, safe to
    save, the reserve, the basket the purchase moved into), each a Number with its evidence ref as the
    overview shows it, and the text built from their real difference, with tokens of these numbers."""
    lang = ctx.language
    grown = [k for k in BASKET_KEYS if after[k][1].value > before[k][1].value]
    into = outcome.review.basket if outcome.review.basket in BASKET_KEYS else (grown[0] if grown else "unclassified")
    keys = [k for k in (*EFFECT_KEYS, into) if k in before and k in after]
    registry = NumberRegistry()
    pairs = {k: (registry.register(before[k][1].model_copy(update={"id": None})),
                 registry.register(after[k][1].model_copy(update={"id": None}))) for k in keys}
    found = purchase(ctx, outcome.review)
    amount = registry.register(amount_number(
        ToolContext(ctx.customer_id, ctx.as_of, ctx.conn, lang, NumberRegistry(), _history=ctx.history(),
                    _labels=ctx._labels, viewer=ctx.viewer), *found).model_copy(update={"id": None})) if found else None

    def token(key: str, side: str) -> str:
        return "{{" + pairs[key][0 if side == "before" else 1].id + "}}"

    this_purchase = "Tämä ostos" if lang == "fi" else "This purchase"   # only if the row is gone
    text = effect_text(before, after, outcome.review.basket, outcome.state,
                       "{{" + amount.id + "}}" if amount else this_purchase, token, lang)
    numbers = {n.id: n for n in registry.all().values()}
    cited = {m for m in re.findall(r"\{\{(n\d+)\}\}", text)}
    rendered = re.sub(r"\{\{(n\d+)\}\}", lambda m: numbers[m.group(1)].display, text)
    return {
        "items": [{"key": k, "label": before[k][0], "before": pairs[k][0].model_dump(mode="json"),
                   "after": pairs[k][1].model_dump(mode="json")} for k in keys],
        "text": text,
        "text_rendered": rendered,
        "numbers": {i: numbers[i].model_dump(mode="json") for i in sorted(cited, key=lambda s: int(s[1:]))},
    }


def _timestamp(moment: datetime | None) -> str | None:
    """Contract section 1: ISO 8601 with offset, Helsinki wall clock, whole seconds."""
    if moment is None:
        return None
    return moment.astimezone(reviews.HELSINKI).replace(microsecond=0).isoformat()


def _message(ctx: ToolContext, outcome: reviews.Outcome) -> dict[str, Any]:
    """The message of an answer that changed nothing; an answer that changes something carries its effect."""
    text = _t("unchanged" if outcome.review.basket else "still_pending", ctx.language)
    return {"text": text, "text_rendered": text, "numbers": {}}


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
        effect_body = None
        if outcome.changed:
            before = overview_numbers(ctx)
            if viewer is not None:
                reviews.save_answer(conn, viewer, outcome.review, now)
            else:
                reviews.save(conn, outcome.review)
            ctx = ToolContext(customer_id, as_of, conn, language, _history=ctx.history(), viewer=viewer)
            after = overview_numbers(ctx)
            moved = changes(before, after)
            effect_body = effect(ctx, outcome, before, after)
        # #382: after an answer the confirmation is the real effect, never a fixed promise.
        message = ({k: effect_body[k] for k in ("text", "text_rendered", "numbers")} if effect_body
                   else _message(ctx, outcome))
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
        "effect": effect_body,
        "refetch": [f"/api/overview/{customer_id}"],
    }
