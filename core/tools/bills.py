"""get_recurring_bills: recurring bills and income cadence, and the bills due before payday.

Signature and shapes: docs/design/agent-core.md section 6.2 and the `bills` card in contracts/api.md.
Definitions: metrics.md sections 2 and 3 (01_recurring.sql for series and status, 03_safe_to_spend.sql
for payday and bills due). Every number carries one evidence ref (R1, R2); the customer and as_of
come from ctx only (R4, R5).
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

from core.tools import aliases, config, evidence, labels, periods, recurring
from core.tools.classify import classify, window
from core.tools.context import ToolContext
from core.tools.models import Action, Args, Card, Number, Period, ToolResult, Unit
from core.tools.numbers import NumberBuilder, model_number
from core.tools.selection import Selection

TOOL = "get_recurring_bills"


class GetRecurringBillsArgs(Args):
    include_income: bool = True


class BillItem(BaseModel):
    bill_id: str
    label: str
    category: str
    cadence: str = "monthly"
    status: str
    status_label: str
    typical_month: Number
    last_paid: date
    next_expected: date | None
    due_until_payday: Number
    evidence_ref: str | None


class IncomeItem(BaseModel):
    key: str
    label: str
    status: str
    typical_month: Number
    next_expected: date | None


class BillsData(BaseModel):
    window: Period
    bills: list[BillItem]
    income: list[IncomeItem] = Field(default_factory=list)
    upcoming_total: Number
    due_period: Period
    next_payday: date
    salary_status: str


def _t(key: str, language: str, **kw) -> str:
    return config.label(config.BILLS_TEXT[key], language).format(**kw)


def _ordinal(day: int, language: str) -> str:
    if language == "fi":
        return f"{day}. päivä"
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"


def _status_label(s: recurring.Series, language: str) -> str:
    if s.status == "spread":
        word = config.COUNT_WORDS.get(s.tx_per_month)
        if word:
            return _t("status_spread", language, word=config.label(word, language))
        return _t("status_spread_many", language)
    day = _ordinal(s.typical_day, language)
    return {
        "done_this_month": _t("status_done", language, day=day),
        "upcoming": _t("status_upcoming", language, day=day),
        "late": _t("status_late", language, day=day),
        "skipped_this_month": _t("status_skipped", language),
    }[s.status]


def _series_label(s: recurring.Series, alias_map: aliases.AliasMap, language: str) -> str:
    if s.kind == "merchant":
        return alias_map.for_merchant(s.key).label(language)
    return config.label(config.SERIES_LABELS.get(s.key, (s.key, s.key)), language)


def _bill_id(ctx: ToolContext, s: recurring.Series) -> str:
    """Opaque, stable bill id. Merchant series never expose the merchant id."""
    if s.kind == "tx_type":
        return f"bill_{s.key}"
    return "bill_" + hashlib.sha256(f"{ctx.customer_id}|{s.key}".encode()).hexdigest()[:10]


def _short_date(d: date, language: str) -> str:
    if language == "fi":
        return f"{d.day}.{d.month}."
    return f"{d.day} {periods.MONTHS_EN_SHORT[d.month - 1]}"


def get_recurring_bills(ctx: ToolContext, args: GetRecurringBillsArgs | dict | None = None) -> ToolResult:
    args = args if isinstance(args, GetRecurringBillsArgs) else GetRecurringBillsArgs.model_validate(args or {})
    lang = ctx.language
    notes: list[str] = []

    history = ctx.history()
    rows = classify(history, ctx.as_of, labels.basket_labels(ctx.conn, ctx.customer_id, ctx.as_of))
    alias_map = aliases.build(history, ctx.as_of)
    series = recurring.detect(history, ctx.as_of)
    pay = recurring.payday(series, ctx.as_of)
    dues = {d.series.key: d for d in recurring.bills_due(series, ctx.as_of, pay)}

    win_start, win_end = window(ctx.as_of)
    win = Period(start=win_start, end=win_end, label=periods.period_label(win_start, win_end, lang))
    due_label = (_t("until_payday", lang, date=_short_date(pay.date, lang))
                 if pay.salary_status != "no_salary_series" else _t("until_assumed_payday", lang))
    due_period = Period(start=ctx.as_of + timedelta(days=1), end=pay.date, label=due_label)
    if pay.salary_status == "no_salary_series":
        notes.append(_t("note_no_salary", lang))
    if any(s.key == recurring.SWEEP for s in series):
        notes.append(_t("note_sweep", lang))

    nb = NumberBuilder(ctx, rows)
    reg = ctx.numbers.register

    def series_selection(s: recurring.Series) -> Selection:
        return Selection(direction=s.direction, start=win_start, end=win_end, series_key=s.key)

    def typical(s: recurring.Series) -> tuple[Number, Any]:
        return nb.transactions(series_selection(s), config.METHODS["typical_month"], win, _t("typical", lang))

    bills: list[tuple[BillItem, tuple[Number, Any]]] = []
    for s in series:
        if not recurring.is_bill(s) or s.key not in dues:
            continue
        due = dues[s.key]
        typ = typical(s)
        num, den = due.factor
        # From the series' rows, like 03_safe_to_spend.sql: the unrounded typical month times the factor,
        # rounded once. Its evidence is the series' transactions in the window.
        due_n = nb.transactions(series_selection(s), config.METHODS["bill_due"], due_period,
                                _t("due_pro_rata" if s.status == "spread" else "due", lang),
                                params={"factor_num": str(num), "factor_den": str(den)})
        bills.append((BillItem(
            bill_id=_bill_id(ctx, s), label=_series_label(s, alias_map, lang), category=s.category,
            status=s.status, status_label=_status_label(s, lang), typical_month=reg(typ[0]),
            last_paid=s.last_date, next_expected=s.next_expected, due_until_payday=reg(due_n[0]),
            evidence_ref=typ[0].evidence_ref,
        ), due_n))
    bills.sort(key=lambda b: (-b[1][1], -b[0].typical_month.value, b[0].bill_id))

    total = reg(nb.composite(config.METHODS["bills_due"], "sum",
                             {item.bill_id: due for item, due in bills}, Unit.EUR, due_period,
                             _t("title", lang))[0])

    income: list[IncomeItem] = []
    if args.include_income:
        for s in series:
            if s.direction == "in" and s.category in config.INCOME_CATEGORIES:
                income.append(IncomeItem(key=s.key, label=_series_label(s, alias_map, lang), status=s.status,
                                         typical_month=reg(typical(s)[0]), next_expected=s.next_expected))

    data = BillsData(window=win, bills=[b for b, _ in bills], income=income, upcoming_total=total,
                     due_period=due_period, next_payday=pay.date, salary_status=pay.salary_status)
    evidence.write(ctx.conn, nb.specs)
    return ToolResult(tool=TOOL, data=data, card=_card(data, lang), notes=notes, evidence=list(nb.specs),
                      model_view=_model_view(data, notes))


def _card(data: BillsData, language: str) -> Card:
    card_id = "card_" + hashlib.sha256(f"{TOOL}|{data.upcoming_total.evidence_ref}".encode()).hexdigest()[:12]
    estimate = None
    if any(b.status == "spread" for b in data.bills):
        estimate = {"label": _t("estimate_label", language), "text": _t("estimate_text", language)}
    return Card(
        card_id=card_id, type="bills", title=_t("title", language), subtitle=data.due_period.label,
        evidence_ref=data.upcoming_total.evidence_ref, estimate=estimate,
        actions=[Action(type="open_evidence", label=_t("action_label", language),
                        evidence_ref=data.upcoming_total.evidence_ref)],
        total=data.upcoming_total,
        items=[b.model_dump() for b in data.bills],
    )


def _model_view(data: BillsData, notes: list[str]) -> dict[str, Any]:
    """Compact view for the model: no rows, merchant ids, customer id or evidence refs (R3)."""
    return {
        "tool": TOOL,
        "window": data.window.label,
        "due_period": data.due_period.label,
        "next_payday": data.next_payday.isoformat(),
        "salary_status": data.salary_status,
        "upcoming_total": model_number(data.upcoming_total),
        "bills": [
            {"bill_id": b.bill_id, "label": b.label, "status": b.status,
             "typical_month": model_number(b.typical_month), "due_until_payday": model_number(b.due_until_payday),
             "next_expected": b.next_expected.isoformat() if b.next_expected else None}
            for b in data.bills
        ],
        "income": [
            {"key": i.key, "label": i.label, "status": i.status, "typical_month": model_number(i.typical_month),
             "next_expected": i.next_expected.isoformat() if i.next_expected else None}
            for i in data.income
        ],
        "notes": list(notes),
    }
