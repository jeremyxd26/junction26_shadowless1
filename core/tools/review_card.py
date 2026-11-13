"""The `review` card: the coach asks about one spending spike (contract 0.2.0 section 3, design 7.8).

Built by the server, never by the model: the question and option texts are fixed templates
(config.REVIEW_TEXT). The card carries an opaque `tx_ref` and a merchant alias, never a transaction
or merchant id. Its amount is a `spending.total` Number over exactly that purchase, with evidence.
"""

from __future__ import annotations

from typing import Any

from core.tools import aliases, config, evidence, labels, periods
from core.tools.classify import CTx, classify
from core.tools.context import ToolContext
from core.tools.formatting import display
from core.tools.models import Number, Period, Unit
from core.tools.numbers import NumberBuilder
from core.tools.reviews import ANSWER_BASKETS, Review
from core.tools.selection import Selection

CARD_ID = "card_review_01"  # a response holds at most one review card


def _t(key: str, language: str, **kw: Any) -> str:
    return config.label(config.REVIEW_TEXT[key], language).format(product=config.PRODUCT_NAME, **kw)


def long_date(d, language: str) -> str:
    if language == "fi":
        return f"{d.day}.{d.month}.{d.year}"
    return f"{d.day} {periods.MONTHS_EN[d.month - 1]} {d.year}"


def purchase(ctx: ToolContext, review: Review) -> tuple[CTx, list[CTx]] | None:
    """The reviewed purchase as classified now (with the customer's labels), and all classified rows."""
    rows = classify(ctx.history(), ctx.as_of, labels.for_context(ctx))
    row = next((c for c in rows if c.tx.id == review.tx_id), None)
    return (row, rows) if row is not None else None


def amount_number(ctx: ToolContext, row: CTx, rows: list[CTx]) -> Number:
    """The purchase amount: spending.total over exactly this transaction, registered and with evidence."""
    t = row.tx
    category = config.label(config.CATEGORY_LABELS.get(t.category, (t.category, t.category)), ctx.language)
    period = Period(start=t.tx_date, end=t.tx_date, label=periods.period_label(t.tx_date, t.tx_date, ctx.language))
    sel = Selection(direction="out", start=t.tx_date, end=t.tx_date, categories=(t.category,), tx_ids=(t.id,))
    nb = NumberBuilder(ctx, rows)
    number, _ = nb.transactions(sel, config.METHODS["total"], period, _t("amount", ctx.language, category=category))
    evidence.write(ctx.conn, nb.specs)
    return ctx.numbers.register(number)


def build(ctx: ToolContext, review: Review) -> dict[str, Any] | None:
    """The review card for a pending (or answered) review, or None if its purchase is not in the history."""
    found = purchase(ctx, review)
    if found is None:
        return None
    row, rows = found
    t, lang = row.tx, ctx.language
    amount = amount_number(ctx, row, rows)
    category = config.label(config.CATEGORY_LABELS.get(t.category, (t.category, t.category)), lang)
    merchant = None
    if t.merchant_id is not None:
        alias = aliases.build(ctx.history(), ctx.as_of).for_merchant(t.merchant_id)
        merchant = {"alias": alias.key, "label": alias.label(lang)}
    basket = row.basket
    pair = config.REVIEW_TEXT
    question = {
        q: _t("question", q, amount=display(row.out_eur, Unit.EUR, q), date=long_date(t.tx_date, q),
              category=config.label(config.CATEGORY_LABELS.get(t.category, (t.category, t.category)), q))
        for q in ("en", "fi")
    }
    return {
        "card_id": CARD_ID,
        "type": "review",
        "title": _t("title", lang),
        "subtitle": f"{category}, {long_date(t.tx_date, lang)}",
        "evidence_ref": amount.evidence_ref,
        "estimate": None,
        "tx_ref": review.tx_ref,
        "date": t.tx_date.isoformat(),
        "category": t.category,
        "merchant": merchant,
        "amount": amount.model_dump(mode="json"),
        "current_basket": {"key": basket, "label": config.label(config.BASKET_LABELS[basket], lang)},
        "question": question,
        "options": [
            {"basket": b,
             "label": {"en": pair[f"option_{b}"][0], "fi": pair[f"option_{b}"][1]},
             "effect": {"en": _t(f"effect_{b}", "en"), "fi": _t(f"effect_{b}", "fi")}}
            for b in ANSWER_BASKETS
        ],
        "why": _t("why", lang),
        "actions": [{"type": "open_evidence", "label": _t("see_purchase", lang), "evidence_ref": amount.evidence_ref}],
    }
