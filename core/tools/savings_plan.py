"""get_savings_plan (#369): the central answer to "How could I save more?".

A small plan of cuts from the user's own data, each from the what-if tool (core/tools/what_if.py), with one
total a month and a year computed here; no model adds numbers (rules in docs/design/metrics.md section 13).

- Levers, in this order, each only when its saving is at least config.SAVINGS_PLAN_MIN_EUR a month and the
  what-if offers a cut (status not `not_offered`):
  1. eating out: Restaurants cut by 20 % (config.SAVINGS_PLAN_FIRST);
  2. the largest other flexible everyday category (config.SAVINGS_PLAN_OTHER_CATEGORIES without the first
     lever's category, by the what-if's own monthly baseline) cut by 10 % (config.SAVINGS_PLAN_OTHER_CUT_PCT).
  The tool skips the first lever's category when it picks the second, whatever the settings say, so the two
  never overlap and nothing is counted twice. Small purchases are no lever: in the data they are restaurant
  visits, which the first lever already covers.
- The total a month is the sum of the levers (composite `sum` of their own refs, one role per category), the
  total a year twelve times that (composite `scale`). Both are estimates. Each cut share is a rule value
  (`savings_plan.cut_pct@1`), so an answer can cite it as a number instead of bare digits.
- These are savings from cutting below the usual pace: they add to safe to save, never to safe to spend
  (r-w6's invariant, #381). The savings goal set aside first (#391) is named next to the plan, the same
  Number and ref as the safe-to-spend answer cites, in every review state, never added in (#468).
- The S-Bonus is never shown with the plan, never part of the total (product owner, #369): no amount on the
  card or in the model view. When its estimate is offered, its own question ("How much S-Bonus could I
  get?") is the answer's first follow-up, answered with its own Number and evidence (coordinator, #411).
- The card has no digit outside a Number or the period: each row's label says its cut in words.
- When no lever reaches the threshold, the card is the baskets card (where the money goes), next to the
  savings goal (coordinator, #411). A failure of the goal or the S-Bonus leaves them out; the plan still stands.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import replace
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from core.tools import config, evidence
from core.tools.baskets import get_basket_breakdown
from core.tools.bonus import get_bonus_estimate
from core.tools.context import NumberRegistry, ToolContext
from core.tools.models import Action, Args, Card, Estimate, Number, Period, ToolResult, Unit, assumption
from core.tools.numbers import NumberBuilder, model_number
from core.tools.safe_to_spend import get_safe_to_spend
from core.tools.missing import MissingData
from core.tools.what_if import WhatIfRefused, run_what_if

TOOL = "get_savings_plan"
NUMBER_KEYS = {"value", "unit", "period", "method", "evidence_ref", "label", "display"}
log = logging.getLogger(__name__)


class GetSavingsPlanArgs(Args):
    """No arguments: the levers and their cut shares are fixed settings (config.SAVINGS_PLAN_*)."""


class Lever(BaseModel):
    key: str            # the category
    category: str       # its label in the request language: "Restaurants", "Lifestyle"
    label: str          # the card row, in words: "Restaurants, a fifth less" (no digit outside a Number)
    cut_pct: int
    cut: Number         # the cut share as a rule value, so an answer cites it as a token
    cut_words: str | None   # the cut share in words ("a fifth"), or None when the setting has none
    saving: Number      # the what-if's saving a month, with its own evidence


class SavingsPlanData(BaseModel):
    levers: list[Lever]
    total_month: Number | None      # None when no lever reaches the threshold
    total_year: Number | None
    savings_goal: Number | None     # the goal set aside first (#391, #468): named next to the plan, never added in
    follow_up: str | None           # the S-Bonus question, offered when the estimate is (coordinator, #411)


def _t(key: str, language: str, **kw: Any) -> str:
    return config.label(config.SAVINGS_PLAN_TEXT[key], language).format(**kw)


def _value(n: Number) -> Decimal:
    return Decimal(str(n.value))


def _what_if(ctx: ToolContext, category: str, pct: int):
    """The what-if result of cutting this category, or None when the tool refuses it (no spending). The
    structured mode: a category with fewer than 3 purchases is `not_offered`, so it is no lever (#379 part B)."""
    try:
        return run_what_if(ctx, {"selection": {"kind": "category", "value": category}, "cut_pct": pct},
                           too_few="not_offered").data
    except (WhatIfRefused, MissingData):   # a reason, never the end of the plan (#379 part B)
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


def cut_words(pct: int, language: str) -> str | None:
    """A cut share in words ("a fifth", "viidenneksen"), or None when the setting has no words for it."""
    words = config.SAVINGS_PLAN_CUT_WORDS.get(pct)
    return config.label(words, language) if words else None


def role(category: str) -> str:
    """A composite part's role named by its category: "Restaurants" -> "restaurants"."""
    return "".join(ch if ch.isalnum() else "_" for ch in category.lower())


def _decoration(name: str, fn) -> Any:
    """An extra beside the plan (the savings goal, the S-Bonus, the baskets card of the no-lever answer): any
    failure leaves it out and keeps the plan (#411)."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - an extra beside the plan never takes the plan down
        log.warning("savings plan: %s unavailable (%s)", name, type(exc).__name__)
        return None


def _shown_card(card: Card, shown) -> Card:
    """A composed tool's card with each Number registered in the answer's registry (the card's numbers carry
    the answer's ids, like any card of an answer)."""
    def walk(node):
        if isinstance(node, Number):
            return shown(node)
        if isinstance(node, BaseModel):    # a Comparison: its Numbers too
            return node.model_copy(update={k: walk(getattr(node, k)) for k in type(node).model_fields})
        if isinstance(node, dict):
            if NUMBER_KEYS <= set(node):    # a card item's amount, a dumped Number
                return shown(Number.model_validate({**node, "id": None})).model_dump()
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node
    # The card's own fields hold no Number; its type's fields (total, items, comparison) are extras.
    return card.model_copy(update={k: walk(v) for k, v in (card.model_extra or {}).items()})


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
    others = {c: _what_if(private, c, other_pct) for c in config.SAVINGS_PLAN_OTHER_CATEGORIES
              if c != first_category}   # never the first lever's category again: nothing counted twice
    other_category = pick_other(others)

    nb = NumberBuilder(ctx, [])
    levers: list[Lever] = []
    results = []   # each lever's what-if result, for its baseline in the estimate (#503 review)
    for category, pct, result in ((first_category, first_pct, first),
                                  (other_category, other_pct, others.get(other_category) if other_category else None)):
        if category is not None and counts(result):
            what = config.label(config.CATEGORY_LABELS[category], lang)
            saving = shown(result.saving_per_month)
            cut, _ = nb.composite(config.SAVINGS_PLAN_METHODS["cut_pct"], "rule_value", {}, Unit.PERCENT,
                                  saving.period, _t("cut", lang, what=what), params={"value": str(pct)})
            words = cut_words(pct, lang)
            label = _t("lever", lang, what=what, words=words) if words else _t("lever_no_words", lang, what=what)
            levers.append(Lever(key=category, category=what, label=label, cut_pct=pct, cut=reg(cut),
                                cut_words=words, saving=saving))
            results.append(result)

    total_month = total_year = None
    if levers:
        window: Period = levers[0].saving.period
        parts = {role(lv.key): (lv.saving, _value(lv.saving)) for lv in levers}
        month_n, _ = nb.composite(config.SAVINGS_PLAN_METHODS["total_month"], "sum", parts, Unit.EUR_PER_MONTH,
                                  window, _t("total_month", lang), params={"period": evidence.period_param(window)})
        year_n, _ = nb.composite(config.SAVINGS_PLAN_METHODS["total_year"], "scale",
                                 {"base": (month_n, _value(month_n))}, Unit.EUR_PER_YEAR, window,
                                 _t("total_year", lang),
                                 params={"factor_num": 12, "factor_den": 1, "period": evidence.period_param(window)})
        total_month, total_year = reg(month_n), reg(year_n)

    # The savings goal set aside first (#391): the safe-to-spend answer's own Number (the same ref), the same in
    # every review state, so the two answers of one conversation name one monthly figure (#468). It is never
    # added to the plan's total; a goal of 0 is left out.
    goal = _decoration("savings goal", lambda: get_safe_to_spend(private, {}).data.savings_goal)
    savings_goal = shown(goal) if goal is not None and goal.value > 0 else None

    # The S-Bonus is never shown with the plan: no amount on the card or in the model view, so nothing can put
    # it next to the total. When the estimate is offered, its own question is the answer's first follow-up, and
    # that answer has its own Number and evidence (coordinator, #411).
    bonus_offered = _decoration("S-Bonus", lambda: get_bonus_estimate(private, {}).data.status != "not_offered")
    follow_up = _t("bonus_follow_up", lang) if bonus_offered else None

    extra_evidence: list = []
    card = None
    if levers:
        # #380 / #503 review: the estimate observes each lever's baseline (the what-if's own Number and ref). They
        # are registered after every Number above, so no existing id or text token of the answer moves; the plan's
        # answer gains these Numbers on purpose.
        baselines = [shown(r.baseline_per_month) for r in results]
        card = _card(levers, total_month, lang, baselines)
    else:   # no lever: where the money goes, next to the savings goal (coordinator, #411, #468)
        baskets = _decoration("baskets", lambda: get_basket_breakdown(private, dict(config.SAVINGS_PLAN_NONE_BASKETS)))
        if baskets is not None and baskets.card is not None:
            card = _shown_card(baskets.card, shown)
            extra_evidence = list(baskets.evidence)

    data = SavingsPlanData(levers=levers, total_month=total_month, total_year=total_year,
                           savings_goal=savings_goal, follow_up=follow_up)
    evidence.write(ctx.conn, nb.specs)
    return ToolResult(tool=TOOL, data=data, card=card, notes=[], evidence=list(nb.specs) + extra_evidence,
                      model_view=_model_view(data))


def _card(levers: list[Lever], total_month: Number, language: str, baselines: list[Number]) -> Card:
    """The existing breakdown card: the total a month as the headline and one row per lever (each row's key is
    its category, its label in words). No digit outside a Number or the period: no S-Bonus amount, and the
    estimate text is the assumption in words."""
    ref = total_month.evidence_ref
    items = [{"key": lv.key, "label": lv.label, "amount": lv.saving.model_dump(), "share": None, "change": None,
              "flags": []} for lv in levers]
    host_label = config.label(config.SAFE_TO_SAVE_TEXT["host_monthly_saving"], language)   # one label (#267)
    return Card(
        card_id="card_" + hashlib.sha256(f"{TOOL}|{ref}".encode()).hexdigest()[:12],
        type="breakdown", title=_t("title", language), subtitle=total_month.period.label, evidence_ref=ref,
        # #380 / #503 review: observed are the levers' baselines (what_if.baseline_month_eur@1); the savings are
        # baseline x an assumed cut, the estimate itself. Assumed: the coming months, and each lever's cut share.
        estimate=Estimate(label=_t("estimate_label", language), text=_t("estimate_text", language),
                          observed=list(baselines),
                          assumptions=[assumption("savings_plan.next_months_like_last", language),
                                       *(assumption("savings_plan.cuts_as_shown", language, lv.cut) for lv in levers)]),
        actions=[Action(type="open_evidence", label=_t("how", language), evidence_ref=ref),
                 Action(type="open_host_screen", target="monthly_saving", label=host_label)],
        display_hint="list", total=total_month, comparison=None, items=items,
    )


def _model_view(data: SavingsPlanData) -> dict[str, Any]:
    """Numbers and labels only (R3), and no digit outside a Number: each cut share is a Number (a rule value)
    and, when the setting has them, words. No S-Bonus number (coordinator, #411): only its question, which the
    answer offers as its first follow-up. `kind` tells the template which answer to write."""
    return {
        "tool": TOOL,
        "kind": "plan" if data.levers else "none",
        "levers": [{"key": lv.key, "category": lv.category, "cut": model_number(lv.cut), "cut_words": lv.cut_words,
                    "saving": model_number(lv.saving)} for lv in data.levers],
        "total_month": model_number(data.total_month),
        "total_year": model_number(data.total_year),
        "savings_goal": model_number(data.savings_goal),
        "follow_up": data.follow_up,
    }
