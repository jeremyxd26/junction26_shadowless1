"""get_savings_plan (#369): the central answer to "How could I save more?".

A small plan of cuts from the user's own data, each from the what-if tool (core/tools/what_if.py), with one
total a month and a year computed here; no model adds numbers (rules in docs/design/metrics.md section 13).

- Levers, in this order, each only when its saving is at least config.SAVINGS_PLAN_MIN_EUR a month and the
  what-if offers a cut (status not `not_offered`):
  1. eating out: Restaurants cut by 20 % (config.SAVINGS_PLAN_FIRST);
  2. the largest other flexible everyday category (config.SAVINGS_PLAN_OTHER_CATEGORIES, by the what-if's
     own monthly baseline) cut by 10 % (config.SAVINGS_PLAN_OTHER_CUT_PCT).
  Different categories never overlap, so nothing is counted twice. Small purchases are no lever: in the data
  they are restaurant visits, which the first lever already covers.
- The total a month is the sum of the levers (composite `sum` of their own refs), the total a year twelve
  times that (composite `scale`). Both are estimates.
- These are savings from cutting below the usual pace: they add to safe to save, never to safe to spend
  (r-w6's invariant, #381). Safe to save a month is shown next to the plan as it is today, never added in.
- The S-Bonus estimate for the default share is a separate extra line, only when it is offered, and never
  part of the total (product owner, #369).
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from core.tools import config, evidence
from core.tools.bonus import get_bonus_estimate
from core.tools.context import NumberRegistry, ToolContext
from core.tools.models import Action, Args, Card, Number, Period, ToolResult, Unit
from core.tools.numbers import NumberBuilder, model_number
from core.tools.safe_to_save import get_safe_to_save
from core.tools.safe_to_spend import NoTransactions
from core.tools.what_if import WhatIfRefused, run_what_if

TOOL = "get_savings_plan"


class GetSavingsPlanArgs(Args):
    """No arguments: the levers and their cut shares are fixed settings (config.SAVINGS_PLAN_*)."""


class Lever(BaseModel):
    key: str            # the category
    category: str       # its label in the request language: "Restaurants", "Lifestyle"
    label: str          # "Restaurants 20% less"
    cut_pct: int
    saving: Number      # the what-if's saving a month, with its own evidence


class SavingsPlanData(BaseModel):
    levers: list[Lever]
    total_month: Number | None      # None when no lever reaches the threshold
    total_year: Number | None
    safe_to_save: Number | None     # shown next to the plan, never added in
    bonus: Number | None            # the S-Bonus extra, never in the total


def _t(key: str, language: str, **kw: Any) -> str:
    return config.label(config.SAVINGS_PLAN_TEXT[key], language).format(**kw)


def _value(n: Number) -> Decimal:
    return Decimal(str(n.value))


def _what_if(ctx: ToolContext, category: str, pct: int):
    """The what-if result of cutting this category, or None when the tool refuses it (no spending)."""
    try:
        return run_what_if(ctx, {"selection": {"kind": "category", "value": category}, "cut_pct": pct}).data
    except WhatIfRefused:
        return None


def pick_other(results: dict[str, Any]) -> str | None:
    """The other category with the highest monthly baseline (ties by name), among those the what-if offers."""
    offered = sorted((-_value(r.baseline_per_month), c) for c, r in results.items()
                     if r is not None and r.status != "not_offered")
    return offered[0][1] if offered else None


def counts(result: Any) -> bool:
    """A lever counts when the what-if offers the cut and saves at least the threshold a month."""
    return result is not None and result.status != "not_offered" and _value(result.saving_per_month) >= \
        config.SAVINGS_PLAN_MIN_EUR


def get_savings_plan(ctx: ToolContext, args: GetSavingsPlanArgs | dict | None = None) -> ToolResult:
    GetSavingsPlanArgs.model_validate(args or {}) if not isinstance(args, GetSavingsPlanArgs) else args
    lang = ctx.language
    first_category, first_pct = config.SAVINGS_PLAN_FIRST
    other_pct = config.SAVINGS_PLAN_OTHER_CUT_PCT
    reg = ctx.numbers.register

    # The composed tools run on a copy of the context with a private number registry (the history, labels
    # and shared reads are the same); only the numbers the plan shows are registered in the answer's.
    private = replace(ctx, numbers=NumberRegistry())

    def shown(n: Number | None) -> Number | None:
        return None if n is None else reg(n.model_copy(update={"id": None}))

    first = _what_if(private, first_category, first_pct)
    others = {c: _what_if(private, c, other_pct) for c in config.SAVINGS_PLAN_OTHER_CATEGORIES}
    other_category = pick_other(others)

    levers: list[Lever] = []
    for category, pct, result in ((first_category, first_pct, first),
                                  (other_category, other_pct, others.get(other_category) if other_category else None)):
        if category is not None and counts(result):
            what = config.label(config.CATEGORY_LABELS[category], lang)
            levers.append(Lever(key=category, category=what, label=_t("lever", lang, what=what, pct=pct),
                                cut_pct=pct, saving=shown(result.saving_per_month)))

    nb = NumberBuilder(ctx, [])
    total_month = total_year = None
    if levers:
        window: Period = levers[0].saving.period
        parts = {f"lever_{i + 1}": (lv.saving, _value(lv.saving)) for i, lv in enumerate(levers)}
        month_n, _ = nb.composite(config.SAVINGS_PLAN_METHODS["total_month"], "sum", parts, Unit.EUR_PER_MONTH,
                                  window, _t("total_month", lang), params={"period": evidence.period_param(window)})
        year_n, _ = nb.composite(config.SAVINGS_PLAN_METHODS["total_year"], "scale",
                                 {"base": (month_n, _value(month_n))}, Unit.EUR_PER_YEAR, window,
                                 _t("total_year", lang),
                                 params={"factor_num": 12, "factor_den": 1, "period": evidence.period_param(window)})
        total_month, total_year = reg(month_n), reg(year_n)

    try:
        safe_to_save = shown(get_safe_to_save(private, {}).data.monthly)
    except NoTransactions:
        safe_to_save = None
    bonus_data = get_bonus_estimate(private, {}).data
    bonus = shown(bonus_data.total_month) if bonus_data.status != "not_offered" else None

    data = SavingsPlanData(levers=levers, total_month=total_month, total_year=total_year,
                           safe_to_save=safe_to_save, bonus=bonus)
    evidence.write(ctx.conn, nb.specs)
    return ToolResult(tool=TOOL, data=data, card=_card(data, lang), notes=[], evidence=list(nb.specs),
                      model_view=_model_view(data))


def _card(data: SavingsPlanData, language: str) -> Card | None:
    """The existing breakdown card: the total a month as the headline, one row per lever, and the S-Bonus
    extra as its own row, labelled as not in the total. No card when no lever reaches the threshold."""
    if data.total_month is None:
        return None
    ref = data.total_month.evidence_ref
    items = [{"key": lv.key, "label": lv.label, "amount": lv.saving.model_dump(), "share": None, "change": None,
              "flags": []} for lv in data.levers]
    if data.bonus is not None:
        items.append({"key": "s_bonus_extra", "label": _t("bonus", language), "amount": data.bonus.model_dump(),
                      "share": None, "change": None, "flags": []})
    return Card(
        card_id="card_" + hashlib.sha256(f"{TOOL}|{ref}".encode()).hexdigest()[:12],
        type="breakdown", title=_t("title", language), subtitle=data.total_month.period.label, evidence_ref=ref,
        estimate={"label": _t("estimate_label", language), "text": _t("estimate_text", language)},
        actions=[Action(type="open_evidence", label=_t("how", language), evidence_ref=ref),
                 Action(type="open_host_screen", target="monthly_saving", label=_t("host_monthly_saving", language))],
        display_hint="list", total=data.total_month, comparison=None, items=items,
    )


def _model_view(data: SavingsPlanData) -> dict[str, Any]:
    """Numbers and labels only (R3). `kind` tells the template which answer to write."""
    return {
        "tool": TOOL,
        "kind": "plan" if data.levers else "none",
        "levers": [{"key": lv.key, "category": lv.category, "cut_pct": lv.cut_pct, "label": lv.label,
                    "saving": model_number(lv.saving)} for lv in data.levers],
        "total_month": model_number(data.total_month),
        "total_year": model_number(data.total_year),
        "safe_to_save": model_number(data.safe_to_save),
        "bonus_extra": model_number(data.bonus),
    }
