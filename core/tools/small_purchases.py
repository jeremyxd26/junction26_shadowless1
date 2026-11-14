"""get_small_purchases (#256): the small everyday purchases nobody notices one by one.

"31 small purchases in three months added up to €156, about €52 a month": a literacy feature (the gap
between how spending feels and what it adds up to). Every number has evidence, and the card leads into
the what-if.

Definition (metrics.md section 12; the reference SQL is core/metrics/08_small_purchases.sql):
- A small purchase is money out (`amount_eur < 0`) in the basket `everyday_spending`, as the baskets
  classify it (core.tools.classify with the customer's labels, so bills, subscriptions, transfers and
  saving are out), in one of config.SMALL_PURCHASE_CATEGORIES, of at most `max_amount` euros.
- A refund is not a purchase and is never counted. It still lowers everyday spending, as in the baskets.
- The period defaults to the last 3 complete months (config.SMALL_PURCHASE_DEFAULT_PERIOD, preset
  `last_3_months` of core/tools/periods.py): one month holds too few small purchases to say anything
  (coordinator, #256, after the persona data).

Numbers, each a Number from the one formatter with the method `small_purchases.<column>@1`:
- `count` and `total_eur`: transactions evidence that lists exactly these purchases (a Selection with
  their ids, as the review card does);
- `avg_eur`: total / count (composite `mean`), only when there is at least one purchase;
- `month_avg_eur`: total / the number of months (composite `scale`), only when the period is two or more whole
  calendar months (the default is); for one month it would only repeat the total (#465);
- `flexible_total_eur`: everyday spending in the period (transactions evidence, refunds netted);
- `share_pct`: the total's share of everyday spending (composite), only when that is above zero;
- per category, largest first: `total_eur` (transactions) and `share_pct` of the small total
  (composite); these are the rows of the existing breakdown card;
- `max_amount_eur`: the limit used, a rule value (composite `rule_value`), so an answer can name it.

With fewer than config.SMALL_PURCHASE_MIN_COUNT purchases the card still lists them, and the model
view says `few`: the answer is a plain "not much here" with the count. The card's action asks the
what-if question for the category with the largest total, with no amount: the user says how much
(issue #142, R1). Merchant ids never leave the server; the categories are the only grouping (R3).
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from core.tools import config, evidence, labels, periods
from core.tools.classify import CTx, classify
from core.tools.context import ToolContext
from core.tools.models import Action, Args, Card, Number, Period, PeriodArg, PeriodPreset, ToolResult, Unit
from core.tools.numbers import NumberBuilder, model_number
from core.tools.selection import Selection

TOOL = "get_small_purchases"
EVERYDAY = "everyday_spending"
CENT = Decimal("0.01")


class GetSmallPurchasesArgs(Args):
    period: PeriodArg = Field(
        default_factory=lambda: PeriodArg(preset=PeriodPreset(config.SMALL_PURCHASE_DEFAULT_PERIOD)))
    # Euros; a float in the declaration so every model reads it as a plain number.
    max_amount: float = Field(default=float(config.SMALL_PURCHASE_MAX_EUR),
                              ge=config.SMALL_PURCHASE_MAX_RANGE[0], le=config.SMALL_PURCHASE_MAX_RANGE[1])


class SmallCategory(BaseModel):
    key: str
    label: str
    amount: Number
    share: Number | None


class SmallPurchasesData(BaseModel):
    period: Period
    max_amount: Number
    count: Number
    total: Number
    average: Number | None
    month_average: Number | None   # only for a period of whole calendar months
    flexible_total: Number
    share: Number | None
    categories: list[SmallCategory]
    few: bool


def _t(key: str, language: str, **kw: Any) -> str:
    return config.label(config.SMALL_PURCHASES_TEXT[key], language).format(**kw)


def limit_of(args: GetSmallPurchasesArgs) -> Decimal:
    """max_amount as euros and cents."""
    return Decimal(str(args.max_amount)).quantize(CENT)


def whole_months(period: Period) -> int | None:
    """The number of calendar months a period covers when it starts on a 1st and ends on a month's last
    day (as 08_small_purchases.sql `small_months` counts them), else None."""
    start, end = period.start, period.end
    if start.day != 1 or (end + timedelta(days=1)).day != 1:
        return None
    return 12 * (end.year - start.year) + end.month - start.month + 1


def small_purchases(rows: list[CTx], period: Period, limit: Decimal) -> list[CTx]:
    """The small purchases of the period, in transaction order (the definition in the docstring)."""
    return [c for c in rows
            if period.start <= c.tx.tx_date <= period.end and c.flow == "spend" and c.basket == EVERYDAY
            and c.tx.category in config.SMALL_PURCHASE_CATEGORIES
            and c.tx.amount_eur < 0 and -c.tx.amount_eur <= limit]


def get_small_purchases(ctx: ToolContext, args: GetSmallPurchasesArgs | dict) -> ToolResult:
    args = args if isinstance(args, GetSmallPurchasesArgs) else GetSmallPurchasesArgs.model_validate(args)
    lang = ctx.language
    notes: list[str] = []
    resolved = periods.resolve(args.period, ctx.as_of, lang)
    period = resolved.period
    if resolved.clamped:
        notes.append(config.label(config.TEXT["note_clamped"], lang).format(label=period.label))

    rows = classify(ctx.history(), ctx.as_of, labels.for_context(ctx))
    limit = limit_of(args)
    found = small_purchases(rows, period, limit)
    nb = NumberBuilder(ctx, rows)
    reg = ctx.numbers.register
    categories = tuple(sorted(config.SMALL_PURCHASE_CATEGORIES))

    def purchases(of: list[CTx], cats: tuple[str, ...] = categories) -> Selection:
        return Selection(direction="out", start=period.start, end=period.end, categories=cats,
                         baskets=(EVERYDAY,), tx_ids=tuple(sorted(c.tx.id for c in of)))

    max_n = nb.composite(config.METHODS["small_max"], "rule_value", {}, Unit.EUR, period, _t("max_amount", lang),
                         params={"value": str(limit)})
    count = nb.transactions(purchases(found), config.METHODS["small_count"], period, _t("count", lang))
    total = nb.transactions(purchases(found), config.METHODS["small_total"], period, _t("total", lang))
    flexible = nb.transactions(Selection(direction="out", start=period.start, end=period.end, baskets=(EVERYDAY,)),
                               config.METHODS["small_flexible"], period, _t("flexible", lang))
    average = share = month_average = None
    if count[1] > 0:
        average = nb.composite(config.METHODS["small_avg"], "mean", {"total": total, "count": count}, Unit.EUR,
                               period, _t("average", lang))
    months = whole_months(period)
    if months and months > 1:   # one month: the average would only repeat the total (#465)
        month_average = nb.composite(config.METHODS["small_month_avg"], "scale", {"base": total},
                                     Unit.EUR_PER_MONTH, period, _t("month_average", lang),
                                     params={"factor_num": 1, "factor_den": months})
    if flexible[1] > 0:
        share = nb.composite(config.METHODS["small_share"], "share_pct", {"part": total, "whole": flexible},
                             Unit.PERCENT, period, _t("share", lang))

    by_category: dict[str, list[CTx]] = {}
    for c in found:
        by_category.setdefault(c.tx.category, []).append(c)
    category_numbers = []
    for key, txs in by_category.items():
        label = config.label(config.CATEGORY_LABELS[key], lang)
        amount = nb.transactions(purchases(txs, (key,)), config.METHODS["small_total"], period, label)
        category_numbers.append((key, label, amount))
    category_numbers.sort(key=lambda k: (-k[2][1], k[0]))          # largest first, then by name
    items = []
    for key, label, amount in category_numbers:
        part_share = None
        if total[1] > 0:
            part_share = reg(nb.composite(config.METHODS["small_share"], "share_pct",
                                          {"part": amount, "whole": total}, Unit.PERCENT, period,
                                          _t("category_share", lang))[0])
        items.append(SmallCategory(key=key, label=label, amount=reg(amount[0]), share=part_share))

    data = SmallPurchasesData(
        period=period, max_amount=reg(max_n[0]), count=reg(count[0]), total=reg(total[0]),
        average=reg(average[0]) if average else None,
        month_average=reg(month_average[0]) if month_average else None, flexible_total=reg(flexible[0]),
        share=reg(share[0]) if share else None, categories=items,
        few=count[1] < config.SMALL_PURCHASE_MIN_COUNT,
    )
    evidence.write(ctx.conn, nb.specs)
    return ToolResult(tool=TOOL, data=data, card=_card(data, lang), notes=notes, evidence=list(nb.specs),
                      model_view=_model_view(data, notes, args.period.preset.value))


def _card(data: SmallPurchasesData, language: str) -> Card:
    ref = data.total.evidence_ref
    actions = [Action(type="open_evidence", label=_t("show", language), evidence_ref=ref)]
    if data.categories:
        largest = data.categories[0].label
        what = largest.lower() if language == "en" else largest
        actions.append(Action(type="ask", label=_t("action_label", language, what=what),
                              prompt=_t("action_prompt", language, what=what)))
    return Card(
        card_id="card_" + hashlib.sha256(f"{TOOL}|{ref}".encode()).hexdigest()[:12],
        type="breakdown", title=_t("title", language), subtitle=data.period.label, evidence_ref=ref,
        estimate=None, actions=actions, display_hint="list", total=data.total, comparison=None,
        items=[{"key": c.key, "label": c.label, "amount": c.amount.model_dump(),
                "share": c.share.model_dump() if c.share else None, "change": None, "flags": []}
               for c in data.categories],
    )


def _model_view(data: SmallPurchasesData, notes: list[str], preset: str) -> dict[str, Any]:
    """The compact projection the model may see: numbers and category labels only, no rows, no merchant
    ids, no customer, no refs (R3). `takeaway` tells the template which sentence to write."""
    return {
        "tool": TOOL,
        "period": data.period.label,
        "period_preset": preset,   # the template names a preset period in words ("in the last three months")
        "max_amount": model_number(data.max_amount),
        "count": model_number(data.count),
        "total": model_number(data.total),
        "average": model_number(data.average),
        "per_month": model_number(data.month_average),
        "share_of_everyday": model_number(data.share),
        "everyday_total": model_number(data.flexible_total),
        "categories": [{"key": c.key, "label": c.label, "amount": model_number(c.amount),
                        "share": model_number(c.share)} for c in data.categories],
        "takeaway": {"kind": "none" if data.count.value == 0 else "few" if data.few else "summary",
                     "largest_category": data.categories[0].label if data.categories else None},
        "notes": list(notes),
    }
