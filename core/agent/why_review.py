"""The purchase behind "why is my safe to spend lower?" (#575): when a spike review is pending, or was answered
"Needed", the why-answer (#552) says what that purchase does to safe to spend.

The effect is a real before/after pair, read only: safe to spend with the label set the answer used, against the
same label set with that one purchase answered the other way (pending: as "Needed"; "Needed": back to pending).
The other side runs get_safe_to_spend on its own connection inside a transaction that is always rolled back, so
nothing it computes is written: the evidence specs of its numbers and anything else vanish with the rollback. Only
"moved or not" is used; none of its numbers is cited.

The purchase's amount is the review card's own Number (core.tools.review_card.build, the card the pipeline shows),
registered in the answer's registry. Its evidence ref is content-addressed: the card wrote that row when it was
shown (the overview, the pending card of an answer, or the card the "Needed" answer was given on), so the card
built here, inside the same rolled-back transaction, writes nothing and its ref still opens.

No review, a review answered "Not needed" (everyday spending) or a closed one: no effect, and the why-answer is
#552's unchanged.
"""

from __future__ import annotations

import dataclasses
import logging
from decimal import Decimal
from typing import Any

from core.tools import reviews
from core.tools.context import NumberRegistry
from core.tools.safe_to_spend import get_safe_to_spend

log = logging.getLogger(__name__)

NEEDED = "unexpected_necessities"


def _value(node: Any) -> Decimal | None:
    try:
        return Decimal(str(node["value"]))
    except (KeyError, TypeError, ValueError, ArithmeticError):
        return None


def _answered_needed(conn: Any, ctx: Any, labels: dict[int, str]) -> Any:
    """The review this viewer answered "Needed" whose label the answer used, or None (the latest if several)."""
    found = [r for r in reviews.load_reviews(conn, ctx.customer_id, ctx.as_of, ctx.viewer, reviews.utcnow())
             if r.basket == NEEDED and labels.get(r.tx_id) == NEEDED]
    return max(found, key=lambda r: r.answered_at or r.created_at) if found else None


def with_effect(data: Any, labels_steps: Any, ctx: Any, pending: Any, view: dict[str, Any]) -> dict[str, Any]:
    """The view with its `review_effect` when it is safe to spend's and a review moved or would move it, else the view
    itself. A copy: the original may be the tool cache's result."""
    if not isinstance(view, dict) or view.get("tool") != "get_safe_to_spend":
        return view
    found = effect(data, labels_steps, ctx, pending, view)
    return {**view, "review_effect": found} if found else view


def effect(data: Any, labels_steps: Any, ctx: Any, pending: Any, view: dict[str, Any]) -> dict[str, Any] | None:
    """{"state": "pending" | "needed", "moved": bool, "amount": {"id": ...}} for the why-answer's safe-to-spend view,
    or None. `data` is the pipeline's data access, `labels_steps` its LabelSteps (the card builder)."""
    labels = ctx._labels or {}
    current = _value(view.get("safe_to_spend") or {})
    if labels_steps is None or not labels or current is None:
        return None
    try:
        with data.connection() as conn:
            with conn.transaction(force_rollback=True):   # everything below is rolled back
                if pending is not None and labels.get(pending.tx_id) == reviews.UNCLASSIFIED:
                    review, state, flipped = pending, "pending", NEEDED
                else:
                    review = _answered_needed(conn, ctx, labels)
                    if review is None:
                        return None
                    state, flipped = "needed", reviews.UNCLASSIFIED
                other_ctx = dataclasses.replace(ctx, conn=conn, numbers=NumberRegistry(),
                                                _labels={**labels, review.tx_id: flipped}, labels_key=None)
                other = _value({"value": get_safe_to_spend(other_ctx, {}).data.safe_to_spend.value})
                card = labels_steps.card(dataclasses.replace(ctx, conn=conn), review)
    except Exception as exc:  # noqa: BLE001 - the why-answer stands without the review sentence
        log.warning("why-answer review effect skipped (%s)", type(exc).__name__)
        return None
    amount_id = ((card or {}).get("amount") or {}).get("id")
    if other is None or not amount_id:
        return None
    # pending: would "Needed" lower it (other < current)? "Needed": did it lower it (current < other)? A rise has no
    # text: then no sentence.
    lower, same = (other < current, other == current) if state == "pending" else (current < other, current == other)
    if not (lower or same):
        return None
    return {"state": state, "moved": lower, "amount": {"id": amount_id}}
