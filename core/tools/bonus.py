"""get_bonus_estimate: "How much S-Bonus could I get?" as a what-if on the customer's own grocery spending
(#158). Rules and worked examples: docs/domain/s-group-benefits.md section 4; the values (Bonus table
levels, payment benefit, default share) come only from core/config/s_group_benefits.yaml, read once at
import. A missing or malformed file stops the import with a message that names the problem.

Inputs:
- G: the customer's own Groceries spending a month, `spender_profile.spend_month_eur@1` over the
  category Groceries for the last 6 complete months, with n_months computed as the basket card does
  (one-offs included). Built through NumberBuilder, so any tool asking the same thing gets the same spec
  and the same evidence ref.
- share_pct: the what-if share of G that would go to S-Group stores, a whole percentage 1..100. When the
  user typed it, it is `user_input@1`; otherwise it is the default share of the YAML file.

Outputs (`bonus_estimate.<name>@1`, each a Number with an evidence ref): the level base (share x G), the
Bonus percentage of the level reached, the Bonus a month, the payment benefit a month, their sum a month
and a year. Each derived number is a composite of its inputs and the rule it applies (the table row or
the rate, with the source ids of the YAML file), so its evidence resolves and reconciles.

Status `estimate` (R13), or `not_offered` when the level base is below the lowest row of the table: then
the Bonus is 0 and the reason says so; the payment benefit is still shown. The assumptions travel with
every result as fixed texts. No merchant is named, and nothing says where the customer shops.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from core.tools import config, evidence, labels, periods
from core.tools.baskets import is_whole_months, months_with_history
from core.tools.classify import classify
from core.tools.context import ToolContext
from core.tools.db import ROOT
from core.tools.formatting import display, money
from core.tools.models import Action, Args, Card, Number, PeriodArg, ToolResult, Unit
from core.tools.numbers import NumberBuilder, model_number
from core.tools.selection import Selection

TOOL = "get_bonus_estimate"
CONFIG_FILE = ROOT / "core" / "config" / "s_group_benefits.yaml"
CONFIG_PATH = "core/config/s_group_benefits.yaml"
TABLE = "default"
BASE_CATEGORY = "Groceries"
# Written out, so the method-id scan of core/tests/test_api_contract.py finds every one.
M = {
    "share_pct": "bonus_estimate.share_pct@1",
    "level_base_eur": "bonus_estimate.level_base_eur@1",
    "bonus_percent": "bonus_estimate.bonus_percent@1",
    "bonus_month_eur": "bonus_estimate.bonus_month_eur@1",
    "payment_benefit_month_eur": "bonus_estimate.payment_benefit_month_eur@1",
    "total_month_eur": "bonus_estimate.total_month_eur@1",
    "total_year_eur": "bonus_estimate.total_year_eur@1",
    "lowest_level_eur": "bonus_estimate.lowest_level_eur@1",
}


# ---- the rules, read at import ----------------------------------------------------------------------

@dataclass(frozen=True)
class BonusRules:
    version: int
    table: str
    levels: tuple[tuple[Decimal, Decimal], ...]   # (min monthly purchases EUR, Bonus percent), ascending
    below_lowest_percent: Decimal
    table_sources: tuple[str, ...]
    payment_percent: Decimal
    default_share_pct: int

    def level_params(self) -> dict[str, Any]:
        return {"table": self.table, "levels": [[str(m), str(p)] for m, p in self.levels],
                "below_lowest_percent": str(self.below_lowest_percent), "source": list(self.table_sources),
                "config": CONFIG_PATH, "version": self.version}

    def rate_params(self) -> dict[str, Any]:
        return {"percent": str(self.payment_percent), "rule": "payment_benefit.percent",
                "config": CONFIG_PATH, "version": self.version}


def _decimal(value: Any, where: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{where} is not a number: {value!r}") from None
    if not d.is_finite() or d < 0:
        raise ValueError(f"{where} must be a finite number >= 0: {value!r}")
    return d


def load_rules(path: Path = CONFIG_FILE) -> BonusRules:
    """The default Bonus table, the payment benefit and the default share. RuntimeError on any problem."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        bonus = doc["bonus"]
        table = bonus["tables"][TABLE]
        rows = [(_decimal(r["min_monthly_purchases_eur"], f"{TABLE} level min"),
                 _decimal(r["percent"], f"{TABLE} level percent")) for r in table["levels"]]
        if not rows:
            raise ValueError("the default table has no levels")
        if [m for m, _ in rows] != sorted({m for m, _ in rows}):
            raise ValueError("the default table's minimums must be strictly ascending")
        if [p for _, p in rows] != sorted(p for _, p in rows):
            raise ValueError("the default table's percentages must not decrease")
        share = _decimal(doc["what_if_assumptions"]["default_share"], "default_share")
        share_pct = share * 100
        if share_pct != share_pct.to_integral_value() or not 1 <= share_pct <= 100:
            raise ValueError("default_share must be a fraction giving a whole percentage 1..100")
        sources = table["source"]
        return BonusRules(
            version=int(doc["version"]), table=TABLE, levels=tuple(rows),
            below_lowest_percent=_decimal(bonus["below_lowest_row_percent"], "below_lowest_row_percent"),
            table_sources=tuple(str(s) for s in (sources if isinstance(sources, list) else [sources])),
            payment_percent=_decimal(doc["payment_benefit"]["percent"], "payment_benefit.percent"),
            default_share_pct=int(share_pct),
        )
    except FileNotFoundError:
        raise RuntimeError(f"S-Bonus rules missing: {path} not found") from None
    except (yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"S-Bonus rules malformed in {path}: {type(exc).__name__}: {exc}") from None


RULES = load_rules()


# ---- pure arithmetic (the document's worked examples are its tests) ----------------------------------

@dataclass(frozen=True)
class Estimate:
    level_base: Decimal
    bonus_percent: Decimal
    bonus_month: Decimal
    payment_benefit_month: Decimal
    total_month: Decimal
    total_year: Decimal
    status: Literal["estimate", "not_offered"]


def estimate(grocery_month: Decimal, share_pct: int, rules: BonusRules = RULES) -> Estimate:
    """Section 4 of the document, computed exactly as the evidence formulas re-compute it."""
    base = money(grocery_month * share_pct / 100)                                       # scale
    percent = evidence.compute_formula("bonus_level", {"base": base}, rules.level_params())
    bonus = evidence.compute_formula("percent_of", {"percent": percent, "base": base})
    payment = evidence.compute_formula("rate_of", {"base": base}, rules.rate_params())
    total = evidence.compute_formula("sum", {"bonus": bonus, "payment_benefit": payment})
    year = money(total * 12)                                                             # scale 12/1
    status = "not_offered" if base < rules.levels[0][0] else "estimate"
    return Estimate(base, percent, bonus, payment, total, year, status)


# ---- the tool -----------------------------------------------------------------------------------------

class GetBonusEstimateArgs(Args):
    # The what-if share that would go to S-Group stores; leave it out for the default of the rules file.
    share_pct: int | None = Field(default=None, ge=1, le=100)


class BonusEstimateData(BaseModel):
    status: Literal["estimate", "not_offered"]
    scenario: str
    share: Number
    grocery_month: Number
    level_base: Number
    bonus_percent: Number
    bonus_month: Number
    payment_benefit_month: Number
    total_month: Number
    total_year: Number
    lowest_level: Number | None      # set when not_offered: the threshold the base stays below
    reason: str | None
    assumptions: list[str]


def _t(key: str, language: str, **kw: Any) -> str:
    return config.label(config.BONUS_TEXT[key], language).format(**kw)


def get_bonus_estimate(ctx: ToolContext, args: GetBonusEstimateArgs | dict | None = None) -> ToolResult:
    args = args if isinstance(args, GetBonusEstimateArgs) else GetBonusEstimateArgs.model_validate(args or {})
    lang = ctx.language
    typed = args.share_pct is not None
    share_pct = args.share_pct if typed else RULES.default_share_pct

    # G: the category's month average over the last 6 complete months, as the basket card computes one.
    period = periods.resolve(PeriodArg(preset="last_6_months"), ctx.as_of, lang).period
    history = ctx.history()
    rows = classify(history, ctx.as_of, labels.basket_labels(ctx.conn, ctx.customer_id, ctx.as_of))
    n_months = months_with_history(period.start, period.end, history[0].tx_date if history else None) \
        if is_whole_months(period.start, period.end) else 1
    nb = NumberBuilder(ctx, rows)
    reg = ctx.numbers.register
    sel = Selection(direction="out", start=period.start, end=period.end, categories=(BASE_CATEGORY,))
    grocery = nb.transactions(sel, config.METHODS["spend_month"], period, _t("grocery_month", lang),
                              params={"n_months": n_months})

    share = Number(value=share_pct, unit=Unit.PERCENT, period=period,
                   method=config.USER_INPUT_METHOD if typed else M["share_pct"], evidence_ref=None,
                   label=_t("share_typed" if typed else "share_default", lang),
                   display=display(Decimal(share_pct), Unit.PERCENT, lang))

    level_base = nb.composite(M["level_base_eur"], "scale", {"base": grocery}, Unit.EUR_PER_MONTH, period,
                              _t("level_base", lang), params={"factor_num": share_pct, "factor_den": 100})
    percent = nb.composite(M["bonus_percent"], "bonus_level", {"base": level_base}, Unit.PERCENT, period,
                           _t("bonus_percent", lang), params=RULES.level_params())
    bonus = nb.composite(M["bonus_month_eur"], "percent_of", {"percent": percent, "base": level_base},
                         Unit.EUR_PER_MONTH, period, _t("bonus_month", lang))
    payment = nb.composite(M["payment_benefit_month_eur"], "rate_of", {"base": level_base}, Unit.EUR_PER_MONTH,
                           period, _t("payment_benefit_month", lang), params=RULES.rate_params())
    total = nb.composite(M["total_month_eur"], "sum", {"bonus": bonus, "payment_benefit": payment},
                         Unit.EUR_PER_MONTH, period, _t("total_month", lang))
    year = nb.composite(M["total_year_eur"], "scale", {"base": total}, Unit.EUR_PER_YEAR, period,
                        _t("total_year", lang), params={"factor_num": 12, "factor_den": 1})

    check = estimate(grocery[1], share_pct)
    got = (level_base[1], percent[1], bonus[1], payment[1], total[1], year[1])
    if got != (check.level_base, check.bonus_percent, check.bonus_month, check.payment_benefit_month,
               check.total_month, check.total_year):
        raise RuntimeError("the S-Bonus evidence formulas differ from the estimate")

    lowest = None
    reason = None
    if check.status == "not_offered":
        minimum = RULES.levels[0][0]
        lowest = reg(nb.composite(M["lowest_level_eur"], "rule_value", {}, Unit.EUR_PER_MONTH, period,
                                  _t("lowest_level", lang),
                                  params={"value": str(minimum), "rule": f"bonus.tables.{TABLE}.levels[0]",
                                          **{k: v for k, v in RULES.level_params().items()
                                             if k in ("source", "config", "version")}})[0])
        reason = _t("reason_below_lowest", lang)

    data = BonusEstimateData(
        status=check.status,
        scenario=_t("scenario", lang, share=share.display),
        share=reg(share),
        grocery_month=reg(grocery[0]),
        level_base=reg(level_base[0]),
        bonus_percent=reg(percent[0]),
        bonus_month=reg(bonus[0]),
        payment_benefit_month=reg(payment[0]),
        total_month=reg(total[0]),
        total_year=reg(year[0]),
        lowest_level=lowest,
        reason=reason,
        assumptions=[_t(key, lang) for key in config.BONUS_ASSUMPTIONS],
    )
    evidence.write(ctx.conn, nb.specs)
    return ToolResult(tool=TOOL, data=data, card=_card(data, lang), notes=[], evidence=list(nb.specs),
                      model_view=_model_view(data))


def _card(data: BonusEstimateData, language: str) -> Card:
    ref = data.total_month.evidence_ref
    estimate_text = " ".join([_t("estimate_text", language), *data.assumptions])
    return Card(
        card_id="card_" + hashlib.sha256(f"{TOOL}|{ref}".encode()).hexdigest()[:12],
        type="metric", title=_t("title", language), subtitle=data.scenario, evidence_ref=ref,
        estimate={"label": _t("estimate_label", language), "text": estimate_text},
        actions=[Action(type="open_evidence", label=_t("how", language), evidence_ref=ref)],
        status=None,
        primary=data.total_month,
        secondary=[data.bonus_percent, data.total_year, data.level_base, data.grocery_month],
        comparison=None,
        components=[
            {"key": "bonus", "label": data.bonus_month.label, "operation": "add",
             "amount": data.bonus_month.model_dump()},
            {"key": "payment_benefit", "label": data.payment_benefit_month.label, "operation": "add",
             "amount": data.payment_benefit_month.model_dump()},
        ],
    )


def _model_view(data: BonusEstimateData) -> dict[str, Any]:
    """For the model: numbers by id, the status, the fixed assumptions. No merchant, no rows, no refs,
    nothing about where the customer shops (R3)."""
    return {
        "tool": TOOL,
        "kind": "estimate",
        "status": data.status,
        "share": model_number(data.share),   # the scenario as a number (the card's sentence has digits)
        "grocery_month": model_number(data.grocery_month),
        "level_base": model_number(data.level_base),
        "bonus_percent": model_number(data.bonus_percent),
        "bonus_month": model_number(data.bonus_month),
        "payment_benefit_month": model_number(data.payment_benefit_month),
        "total_month": model_number(data.total_month),
        "total_year": model_number(data.total_year),
        "lowest_level": model_number(data.lowest_level),
        "reason": data.reason,
        "assumptions": list(data.assumptions),
    }
