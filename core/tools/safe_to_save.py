"""get_safe_to_save: what a typical month leaves, and the money beyond what is needed until payday
(metrics.md section 3.1; the `safe_to_save` card of contracts/api.md section 3).

One source of truth: every number is an output column of core/metrics/03_safe_to_spend.sql, read from
the same row as get_safe_to_spend (`safe_to_spend.metric_row`: one run of the file per request, so an
overview with the hero and this card runs it once). Nothing of the formula is re-implemented here; each
number is a `metric` number whose evidence re-runs 03 for the customer.

The card's rules (contract):
- `monthly` is the headline; `stock` is a second line with a one-sentence explanation and no call to
  action (R7).
- `monthly_components`: free month (add) and everyday month (subtract) when free month >= 0; only the
  essentials shortfall (subtract, as a positive amount) when free month < 0.
- `stock_components`: free until payday (add) and everyday until payday (subtract). When free until
  payday is negative the stock is 0 and no components are shown, so no amount is ever negative.
- `reason` only when `monthly` is 0: `essentials_exceed_income` (free month < 0) or
  `largest_everyday_category` (free month >= 0). A sensitive category is never named (R9).
- Free texts carry no digits; every number is a Number object with its display from the formatter.
The customer and as_of come from ctx only (R4, R5); the result is an estimate (R13).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from core.tools import config, evidence, metric_sql, periods, recurring
from core.tools.context import ToolContext
from core.tools.models import Action, Args, Card, Number, Period, ToolResult, Unit
from core.tools.numbers import NumberBuilder, model_number
from core.tools.safe_to_spend import metric_row

TOOL = "get_safe_to_save"
METRIC = "safe_to_spend"
CENT = Decimal("0.01")
log = logging.getLogger(__name__)


class GetSafeToSaveArgs(Args):
    """No arguments: the customer and as_of come from the server-bound context."""


class SaveComponent(BaseModel):
    key: Literal["free_month", "everyday_month", "essentials_shortfall", "free_until_payday", "everyday_until_payday"]
    label: str
    operation: Literal["add", "subtract"]
    amount: Number


class SaveReason(BaseModel):
    kind: Literal["essentials_exceed_income", "largest_everyday_category"]
    category: dict[str, str] | None   # {key, label}; null for the shortfall, and never a sensitive category
    amount: Number
    text: str


class SafeToSaveData(BaseModel):
    monthly: Number
    monthly_components: list[SaveComponent]
    stock: Number
    stock_explanation: str
    stock_components: list[SaveComponent]
    reason: SaveReason | None


def _t(key: str, language: str, **kw) -> str:
    return config.label(config.SAFE_TO_SAVE_TEXT[key], language).format(**kw)


def window(as_of: date) -> tuple[date, date]:
    """03's averaging window: the 6 complete months before the month of as_of + 1 day (win_start, win_end)."""
    first = (as_of + timedelta(days=1)).replace(day=1)
    return periods.add_months(first, -6), first - timedelta(days=1)


def until_payday(ctx: ToolContext, row: dict[str, Any]) -> Period:
    """Today + 1 to 03's payday, labelled like the bills card and the hero's "Free until payday"."""
    payday = row["next_payday"]
    pay = recurring.Payday(date=payday, salary_status=row["salary_status"], days=max((payday - ctx.as_of).days, 1))
    return recurring.due_period(ctx.as_of, pay, ctx.language)


def get_safe_to_save(ctx: ToolContext, args: GetSafeToSaveArgs | dict | None = None) -> ToolResult:
    GetSafeToSaveArgs.model_validate(args or {}) if not isinstance(args, GetSafeToSaveArgs) else args
    settings, row = metric_row(ctx)
    return build(ctx, settings, row)


def build(ctx: ToolContext, settings: dict[str, str], row: dict[str, Any]) -> ToolResult:
    """The tool's result from one row of 03 (separate from the SQL run, so the rules are testable)."""
    lang = ctx.language
    start, end = window(ctx.as_of)
    month = Period(start=start, end=end, label=periods.period_label(start, end, lang))
    stock_period = until_payday(ctx, row)
    nb = NumberBuilder(ctx, [])
    reg = ctx.numbers.register
    units = {key: (column, Unit(unit)) for key, column, unit in config.SAFE_TO_SAVE_NUMBERS}

    def value(column: str) -> Decimal:
        return metric_sql.decimal(row[column])

    def number(key: str, column: str, unit: Unit, label: str) -> Number:
        """A shown number: never negative, with `metric` evidence for 03's column."""
        v = value(column)
        if v < 0:
            raise ValueError(f"safe to save would show a negative amount for {key}")
        period = month if unit is Unit.EUR_PER_MONTH else stock_period
        method = f"{METRIC}.{column}@1"
        spec = evidence.metric_spec(ctx.customer_id, ctx.as_of, method, config.SAFE_TO_SPEND_FILE, column, settings,
                                    v, evidence.period_param(period))
        return reg(nb.number(v, unit, period, method, spec, label))

    def shown(key: str) -> Number:
        column, unit = units[key]
        return number(key, column, unit, _t(key, lang))

    def component(key: str, operation: str) -> SaveComponent:
        return SaveComponent(key=key, label=_t(f"c_{key}", lang), operation=operation, amount=shown(key))

    free_month = value("free_month_eur")
    free_until_payday = value("free_until_payday_eur")
    monthly = shown("monthly")
    # By 03's own reason, which follows the sign of the unrounded free month: a free month between -0.005
    # and 0 rounds to 0.00 but is still a shortfall (review of #191).
    if row.get("save_reason") == "essentials_exceed_income":
        monthly_components = [component("essentials_shortfall", "subtract")]
    else:
        monthly_components = [component("free_month", "add"), component("everyday_month", "subtract")]
    stock = shown("stock")
    stock_components = ([component("free_until_payday", "add"), component("everyday_until_payday", "subtract")]
                        if free_until_payday >= 0 else [])

    reason = None
    kind = row.get("save_reason")
    if kind is not None:
        category = None
        if kind == "essentials_exceed_income":
            amount_label, text = _t("reason_amount_shortfall", lang), _t("reason_essentials_exceed_income", lang)
        elif kind == "largest_everyday_category":
            key = row.get("save_reason_category")
            if key and key not in config.SENSITIVE_CATEGORIES and key in config.CATEGORY_LABELS:
                label = config.label(config.CATEGORY_LABELS[key], lang)
                category = {"key": key, "label": label}
                amount_label = _t("reason_amount_category", lang, category=label)
                text = _t("reason_largest_everyday_category", lang, category=label)
            else:   # a sensitive or unknown category is never named (R9)
                amount_label, text = _t("reason_amount_everyday", lang), _t("reason_everyday_uses_it_up", lang)
        else:
            raise ValueError(f"unknown save_reason {kind!r} in 03_safe_to_spend.sql")
        column, unit = units["reason"]
        amount = number("reason", column, unit, amount_label)
        reason = SaveReason(kind=kind, category=category, amount=amount, text=text)

    _check(row, free_month, free_until_payday)
    data = SafeToSaveData(
        monthly=monthly, monthly_components=monthly_components, stock=stock,
        stock_explanation=_t("stock_explanation", lang), stock_components=stock_components, reason=reason,
    )
    evidence.write(ctx.conn, nb.specs)
    return ToolResult(tool=TOOL, data=data, card=_card(data, lang), notes=[], evidence=list(nb.specs),
                      model_view=_model_view(data))


def _check(row: dict[str, Any], free_month: Decimal, free_until_payday: Decimal) -> None:
    """03's own arithmetic, re-checked on the rounded columns (a warning, never a different number)."""
    monthly = metric_sql.decimal(row["safe_to_save_monthly_eur"])
    everyday = metric_sql.decimal(row["everyday_month_eur"])
    stock = metric_sql.decimal(row["safe_to_save_eur"])
    everyday_until = metric_sql.decimal(row["everyday_until_payday_eur"])
    if abs(monthly - max(free_month - everyday, Decimal(0))) > CENT or \
            abs(stock - max(free_until_payday - everyday_until, Decimal(0))) > CENT or \
            (monthly == 0) != (row.get("save_reason") is not None):
        log.warning("safe to save of 03_safe_to_spend.sql differs from the rule in this module")


def _card(data: SafeToSaveData, language: str) -> Card:
    ref = data.monthly.evidence_ref
    return Card(
        card_id="card_" + hashlib.sha256(f"{TOOL}|{ref}".encode()).hexdigest()[:12],
        type="safe_to_save", title=_t("title", language), subtitle=_t("subtitle", language), evidence_ref=ref,
        estimate={"label": config.label(config.SAFE_TO_SPEND_TEXT["estimate_label"], language),
                  "text": _t("estimate_text", language)},
        actions=[Action(type="open_evidence", label=config.label(config.SAFE_TO_SPEND_TEXT["how"], language),
                        evidence_ref=ref)],
        monthly=data.monthly,
        monthly_components=[c.model_dump() for c in data.monthly_components],
        stock=data.stock,
        stock_explanation=data.stock_explanation,
        stock_components=[c.model_dump() for c in data.stock_components],
        reason=data.reason.model_dump() if data.reason else None,
    )


def _model_view(data: SafeToSaveData) -> dict[str, Any]:
    """Compact view for the model: Numbers by id, value, unit and label; no refs, no customer id (R3).
    The free texts carry no digits."""
    def components(items: list[SaveComponent]) -> list[dict[str, Any]]:
        return [{"key": c.key, "label": c.label, "operation": c.operation, "amount": model_number(c.amount)}
                for c in items]

    return {
        "tool": TOOL,
        "monthly": model_number(data.monthly),
        "monthly_components": components(data.monthly_components),
        "stock": model_number(data.stock),
        "stock_explanation": data.stock_explanation,
        "stock_components": components(data.stock_components),
        "reason": None if data.reason is None else {
            "kind": data.reason.kind,
            "category": data.reason.category["label"] if data.reason.category else None,
            "amount": model_number(data.reason.amount),
            "text": data.reason.text,
        },
    }
