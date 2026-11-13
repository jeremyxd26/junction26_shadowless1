"""get_basket_breakdown: spending split into the three baskets ("Where did my money go?").

Signature and shapes: docs/design/agent-core.md section 6.2 and the `breakdown` card in
contracts/api.md. Definitions: metrics.md section 1 and 02_baskets.sql (rules, month averages, shares);
the total per month is spender_profile.spend_month_eur (05_spender_profile.sql).

Amounts (team-lead decision for #46):
- A period of whole calendar months: monthly averages, `baskets.month_avg_eur@1` = period total /
  n_months, where n_months is the number of the period's months in which the customer has history
  (02_baskets.sql `months`). The total is `spender_profile.spend_month_eur@1`.
- Any other period: period totals, `baskets.total_eur@1`, and the total is `spending.total@1`.
Shares are always `baskets.share_pct@1` from the period totals. Every category inside a basket is
listed, never a top-N, so Health only appears as one line of a full breakdown (R9).
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from core.tools import config, evidence, labels, periods
from core.tools.classify import classify
from core.tools.context import ToolContext
from core.tools.models import Action, Args, Card, Number, Period, PeriodArg, ToolResult, Unit
from core.tools.numbers import NumberBuilder, model_number
from core.tools.selection import Selection, amount, select

TOOL = "get_basket_breakdown"


class GetBasketBreakdownArgs(Args):
    period: PeriodArg


class CategoryAmount(BaseModel):
    key: str
    label: str
    amount: Number


class BasketItem(BaseModel):
    key: str
    label: str
    amount: Number
    share: Number | None
    categories: list[CategoryAmount]


class BasketsData(BaseModel):
    period: Period
    monthly_average: bool
    n_months: int | None
    total: Number
    baskets: list[BasketItem]
    overrides_applied: list[dict[str, Any]] = Field(default_factory=list)  # customer labels: none yet


def _t(key: str, language: str, **kw) -> str:
    return config.label(config.BASKET_TEXT[key], language).format(**kw)


def is_whole_months(start: date, end: date) -> bool:
    return start.day == 1 and end == periods.month_end(end)


def months_with_history(start: date, end: date, first_tx: date | None) -> int:
    """Months of [start, end] from the customer's first transaction month on, at least 1
    (02_baskets.sql `months`: GREATEST(1, LEAST(6, months since the first transaction)))."""
    first = start if first_tx is None else max(start, first_tx.replace(day=1))
    months = (end.year - first.year) * 12 + (end.month - first.month) + 1
    return max(1, months)


def get_basket_breakdown(ctx: ToolContext, args: GetBasketBreakdownArgs | dict) -> ToolResult:
    args = args if isinstance(args, GetBasketBreakdownArgs) else GetBasketBreakdownArgs.model_validate(args)
    lang = ctx.language
    notes: list[str] = []

    resolved = periods.resolve(args.period, ctx.as_of, lang)
    period = resolved.period
    if resolved.clamped:
        notes.append(config.label(config.TEXT["note_clamped"], lang).format(label=period.label))

    history = ctx.history()
    rows = classify(history, ctx.as_of, labels.basket_labels(ctx.conn, ctx.customer_id, ctx.as_of))
    base = Selection(direction="out", start=period.start, end=period.end)
    spend_rows = select(rows, base)
    if not spend_rows:
        notes.append(config.label(config.TEXT["note_empty"], lang))

    monthly = is_whole_months(period.start, period.end)
    n_months = months_with_history(period.start, period.end, history[0].tx_date if history else None) if monthly else None
    params = {"n_months": n_months} if monthly else None

    nb = NumberBuilder(ctx, rows)
    reg = ctx.numbers.register

    def shown(sel: Selection, label: str) -> tuple[Number, Decimal]:
        """The amount the card shows: a monthly average, or the period total."""
        if monthly:
            return nb.transactions(sel, config.METHODS["basket_month_avg"], period, label, params=params)
        return nb.transactions(sel, config.METHODS["basket_total"], period, label)

    total_label = _t("total", lang)
    period_total = nb.transactions(base, config.METHODS["total"], period, total_label)
    if monthly:
        total = nb.transactions(base, config.METHODS["spend_month"], period, total_label, params=params)
    else:
        total = period_total

    per_basket: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for c in spend_rows:
        per_basket[c.basket][c.tx.category] += amount(c, "out")
    keys = list(config.BASKETS) + sorted(k for k in per_basket if k not in config.BASKETS)

    items = []
    for key in keys:
        if key not in config.BASKETS and key not in per_basket:
            continue
        label = config.label(config.BASKET_LABELS.get(key, config.BASKET_LABELS["unclassified"]), lang)
        bsel = Selection(direction="out", start=period.start, end=period.end, baskets=(key,))
        basket_total = nb.transactions(bsel, config.METHODS["basket_total"], period, label)
        shown_amount = shown(bsel, label)
        share = None
        if period_total[1] != 0:
            share = reg(nb.composite(config.METHODS["basket_share"], "share_pct",
                                     {"part": basket_total, "whole": period_total}, Unit.PERCENT, period,
                                     _t("share", lang))[0])
        cats = per_basket.get(key, {})
        categories = []
        for cat in sorted(cats, key=lambda c: (-cats[c], c)):
            csel = Selection(direction="out", start=period.start, end=period.end, categories=(cat,), baskets=(key,))
            clabel = config.label(config.CATEGORY_LABELS[cat], lang)
            categories.append(CategoryAmount(key=cat, label=clabel, amount=reg(shown(csel, clabel)[0])))
        items.append(BasketItem(key=key, label=label, amount=reg(shown_amount[0]), share=share, categories=categories))

    data = BasketsData(period=period, monthly_average=monthly, n_months=n_months, total=reg(total[0]), baskets=items)
    evidence.write(ctx.conn, nb.specs)
    return ToolResult(tool=TOOL, data=data, card=_card(data, lang), notes=notes, evidence=list(nb.specs),
                      model_view=_model_view(data, notes))


def _card(data: BasketsData, language: str) -> Card:
    card_id = "card_" + hashlib.sha256(f"{TOOL}|{data.total.evidence_ref}".encode()).hexdigest()[:12]
    title = _t("title_monthly" if data.monthly_average else "title_period", language)
    subtitle = _t("subtitle_monthly", language, label=data.period.label) if data.monthly_average else data.period.label
    return Card(
        card_id=card_id, type="breakdown", title=title, subtitle=subtitle, evidence_ref=data.total.evidence_ref,
        estimate=None,
        actions=[Action(type="ask", label=_t("action_label", language), prompt=_t("action_prompt", language))],
        display_hint="stacked_bar", total=data.total, comparison=None,
        items=[{"key": b.key, "label": b.label, "amount": b.amount.model_dump(),
                "share": b.share.model_dump() if b.share else None, "change": None, "flags": []}
               for b in data.baskets],
    )


def _model_view(data: BasketsData, notes: list[str]) -> dict[str, Any]:
    """Compact view for the model: no rows, merchant ids, customer id or evidence refs (R3)."""
    return {
        "tool": TOOL,
        "period": data.period.label,
        "monthly_average": data.monthly_average,
        "total": model_number(data.total),
        "baskets": [
            {"key": b.key, "label": b.label, "amount": model_number(b.amount), "share": model_number(b.share),
             "categories": [{"key": c.key, "label": c.label, "amount": model_number(c.amount)} for c in b.categories]}
            for b in data.baskets
        ],
        "notes": list(notes),
    }
