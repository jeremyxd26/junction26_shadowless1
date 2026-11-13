"""get_spending: spending or income by filter and period, optionally grouped and compared.

Signature and result shape: docs/design/agent-core.md section 6.2. Every number is a Number with
its own evidence ref (R1, R2); the customer and as_of come from ctx only (R4, R5).
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from core.tools import aliases, config, evidence, periods
from core.tools.classify import classify
from core.tools.context import ToolContext
from core.tools.formatting import display, money
from core.tools.models import (
    Action, Args, Card, CompareTo, Comparison, Direction, Filter, GroupBy, Number, Period, PeriodArg,
    Tone, ToolResult, Unit,
)
from core.tools.selection import NONE_KEY, Selection, amount, group_key, select

TOOL = "get_spending"
TIME_GROUPINGS = ("month", "week")


class GetSpendingArgs(Args):
    period: PeriodArg
    filter: Filter | None = None
    direction: Direction = Direction.OUT
    group_by: GroupBy = GroupBy.NONE
    compare_to: CompareTo = CompareTo.NONE
    top_n: int = Field(default=5, ge=1, le=10)


class SpendingGroup(BaseModel):
    key: str
    label: str
    amount: Number
    share: Number | None
    change: Number | None
    flags: list[str] = Field(default_factory=list)  # one_off / habit: not defined in metrics.md yet


class SpendingData(BaseModel):
    period: Period
    total: Number
    tx_count: Number
    comparison: Comparison | None
    groups: list[SpendingGroup]


class _Numbers:
    """Builds Number objects and collects the evidence spec behind each one."""

    def __init__(self, ctx: ToolContext, rows) -> None:
        self.ctx = ctx
        self.rows = rows
        self.specs: dict[str, dict[str, Any]] = {}

    def _number(self, value: Decimal, unit: Unit, period: Period, method: str, spec: dict, label: str) -> Number:
        ref = evidence.make_ref(spec)
        self.specs[ref] = spec
        return Number(value=float(value), unit=unit, period=period, method=method, evidence_ref=ref,
                      label=label, display=display(value, unit, self.ctx.language))

    def transactions(self, sel: Selection, method: str, period: Period, label: str) -> tuple[Number, Decimal]:
        picked = select(self.rows, sel)
        if method == config.METHODS["total"]:
            value = money(sum((c.out_eur if sel.direction == "out" else c.in_eur for c in picked), Decimal("0")))
            unit = Unit.EUR
        else:
            value = Decimal(len(picked))
            unit = Unit.COUNT
        spec = evidence.transactions_spec(self.ctx.customer_id, self.ctx.as_of, method, sel, value)
        return self._number(value, unit, period, method, spec, label), value

    def composite(self, method: str, formula: str, parts: dict[str, tuple[Number, Decimal]], unit: Unit,
                  period: Period, label: str) -> tuple[Number, Decimal]:
        values = {role: v for role, (_, v) in parts.items()}
        value = evidence.compute_formula(formula, values)
        spec = evidence.composite_spec(self.ctx.customer_id, self.ctx.as_of, method, formula,
                                       {role: n.evidence_ref for role, (n, _) in parts.items()}, value)
        return self._number(value, unit, period, method, spec, label), value


def _text(key: str, language: str, **kw) -> str:
    return config.label(config.TEXT[key], language).format(**kw)


def _base_selection(args: GetSpendingArgs, period: Period, alias_map: aliases.AliasMap) -> Selection:
    f = args.filter or Filter()
    direction = args.direction.value
    categories = tuple(sorted({c.value for c in f.categories or []}))
    allowed = config.OUT_CATEGORIES if direction == "out" else config.IN_CATEGORIES
    wrong = [c for c in categories if c not in allowed]
    if wrong:
        raise ValueError(f"categories {wrong} do not fit direction {direction!r}")
    baskets = tuple(sorted({b.value for b in f.baskets or []}))
    if baskets and direction == "in":
        raise ValueError("baskets apply to spending only (direction 'out')")
    merchant_id = None
    if f.merchant is not None:
        try:
            merchant_id = alias_map.merchant_id(f.merchant)
        except KeyError:
            raise ValueError(f"unknown merchant alias {f.merchant!r}") from None
    return Selection(direction=direction, start=period.start, end=period.end, categories=categories,
                     baskets=baskets, mcc_groups=tuple(sorted({g.value for g in f.mcc_groups or []})),
                     merchant_id=merchant_id)


def _total_label(args: GetSpendingArgs, alias_map: aliases.AliasMap, language: str) -> str:
    f = args.filter or Filter()
    parts = [bool(f.categories), bool(f.baskets), bool(f.mcc_groups), f.merchant is not None]
    if sum(parts) == 1:
        if f.categories and len(f.categories) == 1:
            return config.label(config.CATEGORY_LABELS[f.categories[0].value], language)
        if f.mcc_groups and len(f.mcc_groups) == 1:
            return config.label(config.MCC_GROUP_LABELS[f.mcc_groups[0].value], language)
        if f.baskets and len(f.baskets) == 1:
            return config.label(config.BASKET_LABELS[f.baskets[0].value], language)
        if f.merchant is not None:
            return alias_map.for_merchant(alias_map.merchant_id(f.merchant)).label(language)
    return _text("spending" if args.direction is Direction.OUT else "income", language)


def _group_label(by: str, key: str, period: Period, alias_map: aliases.AliasMap, language: str) -> tuple[str, str]:
    """(public key, label) of a group. Merchant ids never leave the server: they become aliases."""
    if by == "category":
        return key, config.label(config.CATEGORY_LABELS[key], language)
    if by == "basket":
        return key, config.label(config.BASKET_LABELS.get(key, config.BASKET_LABELS["unclassified"]), language)
    if by == "merchant":
        if key == NONE_KEY:
            return "no_merchant", _text("no_merchant", language)
        alias = alias_map.for_merchant(key)
        return alias.key, alias.label(language)
    if by == "mcc_group":
        if key == NONE_KEY:
            return "no_mcc_group", _text("no_mcc_group", language)
        return key, config.label(config.MCC_GROUP_LABELS[key], language)
    if by == "month":
        start = date.fromisoformat(key + "-01")
        end = periods.month_end(start)
        return key, periods.period_label(max(start, period.start), min(end, period.end), language)
    monday = date.fromisoformat(key)
    sunday = monday + timedelta(days=6)
    return key, periods.period_label(max(monday, period.start), min(sunday, period.end), language)


def _tone(change: Decimal, direction: str) -> Tone:
    if change == 0:
        return Tone.NEUTRAL
    more_is_better = direction == "in"
    return Tone.BETTER if (change > 0) == more_is_better else Tone.WORSE


def _model_number(n: Number | None) -> dict[str, Any] | None:
    if n is None:
        return None
    return {"id": n.id, "value": n.value, "unit": n.unit.value, "label": n.label}


def get_spending(ctx: ToolContext, args: GetSpendingArgs | dict) -> ToolResult:
    args = args if isinstance(args, GetSpendingArgs) else GetSpendingArgs.model_validate(args)
    lang = ctx.language
    notes: list[str] = []

    resolved = periods.resolve(args.period, ctx.as_of, lang)
    period = resolved.period
    if resolved.clamped:
        notes.append(_text("note_clamped", lang, label=period.label))

    history = ctx.history()
    rows = classify(history, ctx.as_of)
    alias_map = aliases.build(history, ctx.as_of)
    base = _base_selection(args, period, alias_map)
    nb = _Numbers(ctx, rows)
    reg = ctx.numbers.register

    total_label = _total_label(args, alias_map, lang)
    total, total_value = nb.transactions(base, config.METHODS["total"], period, total_label)
    tx_count, n_value = nb.transactions(base, config.METHODS["n_tx"], period, _text("transactions", lang))
    total, tx_count = reg(total), reg(tx_count)
    if n_value == 0:
        notes.append(_text("note_empty", lang))

    # ---- comparison ----
    comparison = None
    base_sel = None
    baseline_period = None
    if args.compare_to is CompareTo.TYPICAL:
        notes.append(_text("note_typical", lang))
    elif args.compare_to is not CompareTo.NONE:
        b_start, b_end = periods.baseline_dates(args.period, period.start, period.end, args.compare_to)
        if b_start < config.DATA_START:
            notes.append(_text("note_no_baseline", lang, start=periods.period_label(
                config.DATA_START, config.DATA_START, lang)))
        else:
            baseline_period = Period(start=b_start, end=b_end, label=periods.period_label(b_start, b_end, lang))
            base_sel = base.with_period(b_start, b_end)
            vs = _text("vs", lang, label=baseline_period.label)
            change_label = _text("change_vs", lang, label=baseline_period.label)
            baseline = nb.transactions(base_sel, config.METHODS["total"], baseline_period, baseline_period.label)
            change = nb.composite(config.METHODS["change"], "difference",
                                  {"current": (total, total_value), "baseline": baseline}, Unit.EUR, period, change_label)
            change_pct = None
            if baseline[1] != 0:
                change_pct = reg(nb.composite(config.METHODS["change_pct"], "pct_change",
                                              {"current": (total, total_value), "baseline": baseline},
                                              Unit.PERCENT, period, change_label)[0])
            comparison = Comparison(baseline=reg(baseline[0]), change=reg(change[0]), change_pct=change_pct,
                                    tone=_tone(change[1], base.direction), label=vs)

    # ---- groups ----
    groups: list[SpendingGroup] = []
    if args.group_by is not GroupBy.NONE:
        by = args.group_by.value
        if by == "basket" and base.direction == "in":
            raise ValueError("group_by 'basket' applies to spending only (direction 'out')")
        sums: dict[str, Decimal] = defaultdict(Decimal)
        for c in select(rows, base):
            sums[group_key(c, by)] += amount(c, base.direction)
        if by in TIME_GROUPINGS:
            keys, rest = sorted(sums), []
        else:
            ranked = sorted(sums, key=lambda k: (-sums[k], k))
            keys, rest = ranked[:args.top_n], ranked[args.top_n:]
        selections = [(k, base.with_group(by, key=k)) for k in keys]
        if rest:
            selections.append(("other", base.with_group(by, not_in=tuple(keys))))
        change_label = _text("change_vs", lang, label=baseline_period.label) if baseline_period else ""
        for key, gsel in selections:
            if key == "other":
                public_key, label = "other", _text("everything_else", lang)
            else:
                public_key, label = _group_label(by, key, period, alias_map, lang)
            amount_n = nb.transactions(gsel, config.METHODS["total"], period, label)
            share = None
            if total_value != 0:
                share = reg(nb.composite(config.METHODS["share_pct"], "share_pct",
                                         {"part": amount_n, "whole": (total, total_value)},
                                         Unit.PERCENT, period, _text("share", lang))[0])
            change_n = None
            if base_sel is not None and baseline_period is not None:
                b_gsel = gsel.with_period(baseline_period.start, baseline_period.end)
                b_amount = nb.transactions(b_gsel, config.METHODS["total"], baseline_period,
                                           f"{label}, {baseline_period.label}")
                change_n = reg(nb.composite(config.METHODS["change"], "difference",
                                            {"current": amount_n, "baseline": b_amount},
                                            Unit.EUR, period, change_label)[0])
            groups.append(SpendingGroup(key=public_key, label=label, amount=reg(amount_n[0]),
                                        share=share, change=change_n))

    data = SpendingData(period=period, total=total, tx_count=tx_count, comparison=comparison, groups=groups)
    evidence.write(ctx.conn, nb.specs)
    return ToolResult(
        tool=TOOL,
        data=data,
        card=_card(args, data, lang),
        notes=notes,
        evidence=list(nb.specs),
        model_view=_model_view(data, base.direction, notes),
    )


def _card(args: GetSpendingArgs, data: SpendingData, language: str) -> Card:
    card_id = "card_" + hashlib.sha256(f"{TOOL}|{data.total.evidence_ref}|{args.group_by.value}".encode()).hexdigest()[:12]
    common = dict(
        card_id=card_id, title=data.total.label, subtitle=data.period.label,
        evidence_ref=data.total.evidence_ref, estimate=None,
        actions=[Action(type="open_evidence", label="Näytä tapahtumat" if language == "fi" else "Show transactions",
                        evidence_ref=data.total.evidence_ref)],
    )
    if not data.groups:
        return Card(type="metric", primary=data.total, secondary=[data.tx_count],
                    comparison=data.comparison, components=[], **common)
    return Card(type="breakdown",
                display_hint="time_series" if args.group_by.value in TIME_GROUPINGS else "list",
                total=data.total, comparison=data.comparison,
                items=[g.model_dump() for g in data.groups], **common)


def _model_view(data: SpendingData, direction: str, notes: list[str]) -> dict[str, Any]:
    """The compact projection the model may see: no rows, no merchant ids, no customer, no refs (R3)."""
    comparison = None
    if data.comparison is not None:
        comparison = {
            "label": data.comparison.label,
            "baseline": _model_number(data.comparison.baseline),
            "change": _model_number(data.comparison.change),
            "change_pct": _model_number(data.comparison.change_pct),
            "tone": data.comparison.tone.value,
        }
    return {
        "tool": TOOL,
        "period": data.period.label,
        "direction": direction,
        "total": _model_number(data.total),
        "tx_count": _model_number(data.tx_count),
        "comparison": comparison,
        "groups": [
            {"key": g.key, "label": g.label, "amount": _model_number(g.amount), "share": _model_number(g.share),
             "change": _model_number(g.change), "flags": g.flags}
            for g in data.groups
        ],
        "notes": list(notes),
    }
