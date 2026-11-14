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

from core.tools import aliases, config, evidence, labels, periods
from core.tools.classify import classify
from core.tools.context import ToolContext
from core.tools.missing import MissingData
from core.tools.models import (
    Action, Args, Card, CompareTo, Comparison, Direction, Filter, GroupBy, Number, Period, PeriodArg,
    Tone, ToolResult, Unit,
)
from core.tools.numbers import NumberBuilder
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


_Numbers = NumberBuilder  # shared builder (core/tools/numbers.py)


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


def top_categories(rows: list, language: str, n: int = 5) -> list[dict[str, str]]:
    """The customer's largest spending categories in the whole data, Health never among them (R9): chips."""
    sums: dict[str, Decimal] = defaultdict(Decimal)
    for c in rows:
        if c.tx.category != "Health" and c.out_eur > 0:
            sums[c.tx.category] += c.out_eur
    ranked = sorted(sums, key=lambda k: (-sums[k], k))[:n]
    return [{"key": k, "label": config.label(config.CATEGORY_LABELS[k], language) if k in config.CATEGORY_LABELS else k}
            for k in ranked]




def filter_names(categories, mcc_groups, baskets, merchant: str | None, language: str) -> list[str]:
    """The labels of a filter's parts, each once: categories, groups and baskets in that order, each sorted as the
    selection sorts them, then a merchant's alias. The parts after the first are lower-cased whole ("home & tech",
    "electronics and home"); an alias keeps its case (review of #496)."""
    known = list(dict.fromkeys(
        [config.label(config.CATEGORY_LABELS[c], language) for c in categories if c in config.CATEGORY_LABELS]
        + [config.label(config.MCC_GROUP_LABELS[g], language) for g in mcc_groups if g in config.MCC_GROUP_LABELS]
        + [config.label(config.BASKET_LABELS[b], language) for b in baskets if b in config.BASKET_LABELS]))
    names = known + ([merchant] if merchant else [])
    return [n if i == 0 or i >= len(known) else n.lower() for i, n in enumerate(names)]


def join_names(names: list[str], language: str) -> str:
    """"Housing and restaurants", "Housing, restaurants and travel", "Asuminen ja ravintolat". When a part itself
    contains the joiner, the last one is "sekä" in Finnish and a serial comma in English, so the list stays
    readable: "Koti ja tekniikka sekä ostokset ja vapaa-aika", "Electronics and home, and taxi" (#501)."""
    if len(names) <= 1:
        return "".join(names)
    word = " ja " if language == "fi" else " and "
    last = (" sekä " if language == "fi" else ", and ") if any(word in f" {n} " for n in names) else word
    return ", ".join(names[:-1]) + last + names[-1]


def filter_dims(categories, mcc_groups, baskets, merchant: str | None, language: str) -> list[tuple[str, list[str]]]:
    """The filter by dimension, each label once and sorted as the selection sorts them: categories, MCC groups,
    baskets, then a merchant's alias. Within a dimension the parts are a union; across dimensions the selection is
    an intersection (core/tools/selection.py), #501."""
    dims = []
    for kind, keys, table in (("categories", categories, config.CATEGORY_LABELS),
                              ("mcc_groups", mcc_groups, config.MCC_GROUP_LABELS),
                              ("baskets", baskets, config.BASKET_LABELS)):
        names = list(dict.fromkeys(config.label(table[k], language) for k in keys if k in table))
        if names:
            dims.append((kind, names))
    if merchant:
        dims.append(("merchant", [merchant]))
    return dims


def render_filter(dims: list[tuple[str, list[str]]], language: str, sentence: bool = False) -> str | None:
    """A filter by dimension in words, for the label (the Number, the card, the evidence title) or for a sentence.

    Within one dimension the parts are a union ("Housing and restaurants"). Across dimensions the selection is an
    intersection (#501, review of #528):
    - an MCC group with categories is a part of them: the group first, the categories in brackets, "Taxi
      (Transportation)", "Taksi (Liikenne)";
    - a group named like a category is that category's card purchases, alone or with its category: "Restaurants
      (card purchases)", "Ravintolat (korttiostot)", never the category's own label (config.CARD_PURCHASE_GROUPS);
    - a basket: "Housing within everyday spending"; in Finnish in the brackets too, "Asuminen (arjen kulutus)";
    - a merchant: "Restaurants at Grocery store A", "Ravintolat kauppiaalla Ruokakauppa A".
    FILTER_LABEL_CAP parts or more of one dimension are counted, with no digit: "Spending in several categories",
    "Kulutus useassa luokassa". In a label the parts after the first are lower-cased (a bracketed category keeps its
    capital); in a sentence every known label is lower-cased in English, and in Finnish all but the first, which
    follows "luokassa"/"luokissa" ("luokissa Asuminen ja ravintolat (arjen kulutus)"). An alias keeps its case."""
    named = {kind: list(names) for kind, names in dims if names}
    if not named:
        return None
    fi = language == "fi"
    text_of = lambda key: config.label(config.TEXT[key], language)  # noqa: E731

    def union(kind: str, names: list[str], cap_first: bool, long_count: bool) -> str:
        if len(names) >= config.FILTER_LABEL_CAP:
            what = text_of(f"filter_many_{kind}")
            return text_of("filter_many").format(what=what) if long_count else what
        return join_names([n if cap_first and i == 0 else n.lower() for i, n in enumerate(names)], language)

    cats, groups, bsk, merchant = (named.get(k) for k in ("categories", "mcc_groups", "baskets", "merchant"))
    brackets: list[str] = []
    card, carded = text_of("filter_card_purchases"), card_group_names(language)
    if groups and set(groups) <= carded and (not cats or {n.lower() for n in groups} == {n.lower() for n in cats}):
        # a group named like a category holds only that category's card purchases (an MCC is set only on a card
        # purchase): a smaller sum, so never the category's own label, alone or with its category (review of #528)
        lead_kind, lead = "mcc_groups", groups
        brackets.append(card)
    elif groups:
        # among other groups, or within other categories, each such group says it itself: "Restaurants (card
        # purchases) and taxi"
        lead_kind, lead = "mcc_groups", [f"{n} ({card})" if n in carded else n for n in groups]
        if cats:
            if lead[-1].endswith(f" ({card})") and len(lead) < config.FILTER_LABEL_CAP:   # listed, not counted
                # one bracket, never two in a row: "Restaurants (card purchases, Housing)" (#567)
                lead[-1] = lead[-1][:-len(f" ({card})")]
                brackets.append(card)
            brackets.append(union("categories", cats, cap_first=not sentence, long_count=False))
    else:
        lead_kind = next(k for k in ("categories", "baskets", "merchant") if k in named)
        lead = named[lead_kind]
    counted = lead_kind != "merchant" and len(lead) >= config.FILTER_LABEL_CAP
    if lead_kind == "merchant":
        text = ("kauppiaalla " if fi and sentence else "") + lead[0]
    else:
        text = union(lead_kind, lead, cap_first=fi or not sentence, long_count=not sentence)
        if fi and sentence and not counted:
            text = ("luokassa " if len(lead) == 1 else "luokissa ") + text
    if bsk and lead_kind != "baskets":
        within = union("baskets", bsk, cap_first=False, long_count=False)
        if fi:
            brackets.append(within)
    if brackets:
        text += " (" + ", ".join(brackets) + ")"
    if bsk and lead_kind != "baskets" and not fi:
        text += text_of("filter_within") + within
    if merchant and lead_kind != "merchant":
        text += text_of("filter_at") + merchant[0]
    return text


def card_group_names(language: str) -> set[str]:
    """The labels of the MCC groups named like a category (config.CARD_PURCHASE_GROUPS) in the request language."""
    return {config.label(config.MCC_GROUP_LABELS[g], language) for g in config.CARD_PURCHASE_GROUPS}


def group_label(key: str, language: str) -> str:
    """One MCC group's label, as the filter label writes it: a group named like a category is that category's card
    purchases, "Restaurants (card purchases)", "Ravintolat (korttiostot)"; the others by name, "Taxi" (#528)."""
    name = config.label(config.MCC_GROUP_LABELS[key], language)
    return f"{name} ({_text('filter_card_purchases', language)})" if key in config.CARD_PURCHASE_GROUPS else name


def filter_label(categories, mcc_groups, baskets, merchant: str | None, language: str) -> str | None:
    """A filter in words, every part named (#399), across dimensions an intersection (#501): render_filter. None
    without a filter: a filtered sum is never labelled as all spending. The tool and the evidence view name one
    filter the same way."""
    return render_filter(filter_dims(categories, mcc_groups, baskets, merchant, language), language)


def _filter_keys(args: GetSpendingArgs, alias_map: aliases.AliasMap, language: str):
    f = args.filter or Filter()
    merchant = (alias_map.for_merchant(alias_map.merchant_id(f.merchant)).label(language)
                if f.merchant is not None else None)
    return (sorted({c.value for c in f.categories or []}), sorted({g.value for g in f.mcc_groups or []}),
            sorted({b.value for b in f.baskets or []}), merchant)


def _filter_names_of(args: GetSpendingArgs, alias_map: aliases.AliasMap, language: str) -> list[str]:
    return filter_names(*_filter_keys(args, alias_map, language), language)


def _filter_dims_of(args: GetSpendingArgs, alias_map: aliases.AliasMap, language: str) -> list[tuple[str, list[str]]]:
    return filter_dims(*_filter_keys(args, alias_map, language), language)


def _total_label(args: GetSpendingArgs, alias_map: aliases.AliasMap, language: str) -> str:
    label = filter_label(*_filter_keys(args, alias_map, language), language)
    return label or _text("spending" if args.direction is Direction.OUT else "income", language)


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
        return key, group_label(key, language)   # "Restaurants (card purchases)" beside "Taxi" (#528)
    if by == "month":
        start = date.fromisoformat(key + "-01")
        end = periods.month_end(start)
        return key, periods.period_label(max(start, period.start), min(end, period.end), language)
    monday = date.fromisoformat(key)
    sunday = monday + timedelta(days=6)
    return key, periods.period_label(max(monday, period.start), min(sunday, period.end), language)


def _tone(change: Decimal, sel: Selection) -> Tone:
    """Colour hint only; metrics.md does not define tone for plain sums, so this is our rule:
    more spending is worse, more income is better, anything else (saving, transfers) is neutral."""
    if change == 0:
        return Tone.NEUTRAL
    if sel.direction == "out" and set(sel.categories) <= config.SPEND_CATEGORIES:
        return Tone.WORSE if change > 0 else Tone.BETTER
    if sel.direction == "in" and set(sel.categories) <= config.INCOME_CATEGORIES:
        return Tone.BETTER if change > 0 else Tone.WORSE
    return Tone.NEUTRAL


def _model_number(n: Number | None) -> dict[str, Any] | None:
    if n is None:
        return None
    return {"id": n.id, "value": n.value, "unit": n.unit.value, "label": n.label}


def get_spending(ctx: ToolContext, args: GetSpendingArgs | dict) -> ToolResult:
    args = args if isinstance(args, GetSpendingArgs) else GetSpendingArgs.model_validate(args)
    lang = ctx.language
    notes: list[str] = []

    try:
        resolved = periods.resolve(args.period, ctx.as_of, lang)
    except periods.PeriodOutOfRange as exc:
        # The answer names the customer's own first month of data, not the dataset's (#379).
        history = ctx.history()
        first = history[0].tx_date.isoformat() if history else None
        raise periods.PeriodOutOfRange(str(exc), reason=exc.reason, first=first, last=ctx.as_of.isoformat()) from None
    period = resolved.period
    if resolved.clamped:
        notes.append(_text("note_clamped", lang, label=period.label))

    history = ctx.history()
    rows = classify(history, ctx.as_of, labels.for_context(ctx))
    alias_map = aliases.build(history, ctx.as_of)
    base = _base_selection(args, period, alias_map)
    nb = _Numbers(ctx, rows)
    reg = ctx.numbers.register

    total_label = _total_label(args, alias_map, lang)
    total, total_value = nb.transactions(base, config.METHODS["total"], period, total_label)
    tx_count, n_value = nb.transactions(base, config.METHODS["n_tx"], period, _text("transactions", lang))
    if args.filter is not None and n_value == 0 and not select(rows, base.with_period(config.DATA_START, ctx.as_of)):
        # Never in the whole data (#379): what is missing, and the customer's own largest categories.
        raise MissingData("category_absent", what=total_label, top=top_categories(rows, lang))
    total, tx_count = reg(total), reg(tx_count)
    # the note is about a monthly habit, so only over the what-if window or longer, never a single month (#534)
    months = (period.end.year - period.start.year) * 12 + period.end.month - period.start.month + 1
    too_few = args.filter is not None and 0 < n_value < config.TOO_FEW_TRANSACTIONS and months >= config.WINDOW_MONTHS
    if n_value == 0:
        notes.append(_text("note_empty", lang))
    elif too_few:
        notes.append(_text("note_too_few", lang))   # the numbers are shown, marked (#379)

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
                                    tone=_tone(change[1], base), label=vs)

    # ---- groups ----
    groups: list[SpendingGroup] = []
    group_counts: list[int] = []   # per group, in group order: how many transactions its amount adds up
    if args.group_by is not GroupBy.NONE:
        by = args.group_by.value
        if by == "basket" and base.direction == "in":
            raise ValueError("group_by 'basket' applies to spending only (direction 'out')")
        sums: dict[str, Decimal] = defaultdict(Decimal)
        counts: dict[str, int] = defaultdict(int)   # transactions per group, for the model view (#301)
        for c in select(rows, base):
            sums[group_key(c, by)] += amount(c, base.direction)
            counts[group_key(c, by)] += 1
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
            # A month or week bucket has no counterpart in the baseline period, so no per-group change.
            if base_sel is not None and baseline_period is not None and by not in TIME_GROUPINGS:
                b_gsel = gsel.with_period(baseline_period.start, baseline_period.end)
                b_amount = nb.transactions(b_gsel, config.METHODS["total"], baseline_period,
                                           f"{label}, {baseline_period.label}")
                change_n = reg(nb.composite(config.METHODS["change"], "difference",
                                            {"current": amount_n, "baseline": b_amount},
                                            Unit.EUR, period, change_label)[0])
            groups.append(SpendingGroup(key=public_key, label=label, amount=reg(amount_n[0]),
                                        share=share, change=change_n))
            group_counts.append(sum(counts[k] for k in rest) if key == "other" else counts[key])

    data = SpendingData(period=period, total=total, tx_count=tx_count, comparison=comparison, groups=groups)
    evidence.write(ctx.conn, nb.specs)
    return ToolResult(
        tool=TOOL,
        data=data,
        card=_card(args, data, lang),
        notes=notes,
        evidence=list(nb.specs),
        model_view=_model_view(data, base.direction, notes, group_counts, _filter_names_of(args, alias_map, lang),
                               _filter_dims_of(args, alias_map, lang)),
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


def _model_view(data: SpendingData, direction: str, notes: list[str], counts: list[int] | None = None,
                filter_names: list[str] | None = None,
                filter_dims: list[tuple[str, list[str]]] | None = None) -> dict[str, Any]:
    """The compact projection the model may see: no rows, no merchant ids, no customer, no refs (R3).

    A group's amount is the total of all its transactions in the period. The view says so, and gives
    the number of transactions it adds up (#301): a merchant's total of two purchases was read as
    "your largest visit". The count is context for the wording only. It has no id, so the answer
    cannot cite it."""
    counts = counts if counts is not None else [None] * len(data.groups)
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
        # what the total's label names (#399): each part once, as the sentence names it ("luokissa" for two or more)
        "filter_parts": len(filter_names or []),
        "filter_labels": list(filter_names or []),
        # the same filter by dimension (#501): a union inside one, an intersection across them
        "filter_dims": [{"kind": kind, "labels": list(names)} for kind, names in filter_dims or []],
        "tx_count": _model_number(data.tx_count),
        "comparison": comparison,
        "groups": [
            {"key": g.key, "label": g.label, "amount": _model_number(g.amount),
             "amount_is": "total_for_period", "transactions": n,
             "share": _model_number(g.share), "change": _model_number(g.change), "flags": g.flags}
            for g, n in zip(data.groups, counts)
        ],
        "notes": list(notes),
    }
