"""get_bonus_estimate: "How much S-Bonus could I get?" as a what-if on the customer's own grocery spending
(#158). Rules and worked examples: docs/domain/s-group-benefits.md section 4; the values (Bonus table
levels, payment benefit and its sources, default share, which table, which category) come only from
core/config/s_group_benefits.yaml, read once at import. A missing or malformed file stops the import with
a message that names the problem.

Inputs:
- G: the customer's own spending a month in the base category of the rules file (Groceries),
  `spender_profile.spend_month_eur@1` for the last 6 complete months, with n_months computed as the
  basket card does (one-offs included). Built through NumberBuilder, so any tool asking the same thing
  gets the same spec and the same evidence ref.
- share_pct: the what-if share of G that would go to S-Group stores, a whole percentage 1..100. When the
  user typed it, it is `user_input@1`; otherwise it is the default share of the rules file, a rule value
  with its own evidence (`bonus_estimate.share_pct@1`).

Outputs (`bonus_estimate.<name>@1`, each a Number with an evidence ref): the level base (share x G), the
Bonus percentage of the level reached, the Bonus a month, the payment benefit a month, their sum a month
and a year. Each derived number is a composite of its inputs and the rule it applies (the table row or
the rate, with the source ids of the rules file), so its evidence resolves and reconciles.

Rounding, as the document's formula: the level and the amounts work on the unrounded s x G and are
rounded once at the end. The level base is shown rounded to cents, but the level is never decided on
the rounded value (399.99 at 50 % is 199.995: the 1.0 % row, not the 1.5 % one).

Status `estimate` (R13), or `not_offered` when s x G is below the lowest row of the table: then the Bonus
is 0, the card and the result say why, and the payment benefit is still shown. The assumptions travel
with every result as fixed texts. No merchant is named, and nothing says where the customer shops.
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
CONFIG_PATH = "core/config/s_group_benefits.yaml"   # relative: the form every message and spec shows
CONFIG_FILE = ROOT / CONFIG_PATH
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
    table: str                                   # what_if_assumptions.bonus_table
    base_category: str                           # what_if_assumptions.base_category
    levels: tuple[tuple[Decimal, Decimal], ...]   # (min monthly purchases EUR, Bonus percent), ascending
    below_lowest_percent: Decimal
    table_sources: tuple[str, ...]
    payment_percent: Decimal
    payment_sources: tuple[str, ...]
    default_share_pct: int

    def _cite(self) -> dict[str, Any]:
        return {"config": CONFIG_PATH, "version": self.version}

    def level_params(self, share_pct: int) -> dict[str, Any]:
        return {"table": self.table, "levels": [[str(m), str(p)] for m, p in self.levels],
                "below_lowest_percent": str(self.below_lowest_percent), "source": list(self.table_sources),
                "share_num": share_pct, "share_den": 100, **self._cite()}

    def rate_params(self, share_pct: int) -> dict[str, Any]:
        return {"percent": str(self.payment_percent), "rule": "payment_benefit.percent",
                "source": list(self.payment_sources), "share_num": share_pct, "share_den": 100, **self._cite()}

    def share_params(self) -> dict[str, Any]:
        return {"value": str(self.default_share_pct), "rule": "what_if_assumptions.default_share", **self._cite()}

    def lowest_params(self) -> dict[str, Any]:
        return {"value": str(self.levels[0][0]), "rule": f"bonus.tables.{self.table}.levels[0]",
                "source": list(self.table_sources), **self._cite()}


def _decimal(value: Any, where: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{where} is not a number: {value!r}")
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{where} is not a number: {value!r}") from None
    if not d.is_finite() or d < 0:
        raise ValueError(f"{where} must be a finite number >= 0: {value!r}")
    return d


def _sources(value: Any, where: str) -> tuple[str, ...]:
    items = value if isinstance(value, list) else [value]
    if not items or not all(isinstance(s, str) and s for s in items):
        raise ValueError(f"{where} must list source ids")
    return tuple(items)


def _shown(path: Path) -> str:
    """The file as a message shows it: relative to the repository when it is inside, else its name."""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def load_rules(path: Path = CONFIG_FILE) -> BonusRules:
    """The rules of the estimate. RuntimeError, naming the file by its relative path, on any problem."""
    shown = _shown(path)
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assumptions = doc["what_if_assumptions"]
        table_name = str(assumptions["bonus_table"])
        base_category = str(assumptions["base_category"])
        if base_category not in config.CATEGORIES:
            raise ValueError(f"base_category {base_category!r} is not a category of the data")
        bonus = doc["bonus"]
        table = bonus["tables"][table_name]
        rows = [(_decimal(r["min_monthly_purchases_eur"], f"{table_name} level min"),
                 _decimal(r["percent"], f"{table_name} level percent")) for r in table["levels"]]
        if not rows:
            raise ValueError(f"the {table_name} table has no levels")
        if [m for m, _ in rows] != sorted({m for m, _ in rows}):
            raise ValueError(f"the {table_name} table's minimums must be strictly ascending")
        if [p for _, p in rows] != sorted(p for _, p in rows):
            raise ValueError(f"the {table_name} table's percentages must not decrease")
        share_pct = _decimal(assumptions["default_share"], "default_share") * 100
        if share_pct != share_pct.to_integral_value() or not 1 <= share_pct <= 100:
            raise ValueError("default_share must be a fraction giving a whole percentage 1..100")
        payment = doc["payment_benefit"]
        return BonusRules(
            version=int(doc["version"]), table=table_name, base_category=base_category, levels=tuple(rows),
            below_lowest_percent=_decimal(bonus["below_lowest_row_percent"], "below_lowest_row_percent"),
            table_sources=_sources(table["source"], f"bonus.tables.{table_name}.source"),
            payment_percent=_decimal(payment["percent"], "payment_benefit.percent"),
            payment_sources=_sources(payment["source"], "payment_benefit.source"),
            default_share_pct=int(share_pct),
        )
    except FileNotFoundError:
        raise RuntimeError(f"S-Bonus rules missing: {shown} not found") from None
    except (yaml.YAMLError, KeyError, TypeError, ValueError, AttributeError) as exc:
        raise RuntimeError(f"S-Bonus rules malformed in {shown}: {type(exc).__name__}: {exc}") from None


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
    """Section 4 of the document, computed exactly as the evidence formulas re-compute it: the level and
    the amounts on the unrounded s x G, each rounded once."""
    g = {"base": grocery_month}
    # shown rounded DOWN to cents, so it never reads as a threshold the unrounded base did not reach
    base = evidence.compute_formula("scale", g, {"factor_num": share_pct, "factor_den": 100, "rounding": "down"})
    percent = evidence.compute_formula("bonus_level", g, rules.level_params(share_pct))
    bonus = evidence.compute_formula("percent_of", {"percent": percent, **g}, {"share_num": share_pct,
                                                                               "share_den": 100})
    payment = evidence.compute_formula("rate_of", g, rules.rate_params(share_pct))
    total = evidence.compute_formula("sum", {"bonus": bonus, "payment_benefit": payment})
    year = money(total * 12)                                                             # scale 12/1
    unrounded = grocery_month * share_pct / 100
    status = "not_offered" if unrounded < rules.levels[0][0] else "estimate"
    return Estimate(base, percent, bonus, payment, total, year, status)


# ---- the tool -----------------------------------------------------------------------------------------

class GetBonusEstimateArgs(Args):
    # The what-if share that would go to S-Group stores; leave it out for the default of the rules file.
    # Strict: a whole number only (`true` is not 1 %, "50" is not 50 %).
    share_pct: int | None = Field(default=None, ge=1, le=100, strict=True)


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
    lowest_level: Number | None      # set when not_offered: the threshold s x G stays below
    reason: str | None
    assumptions: list[str]


def _t(key: str, language: str, **kw: Any) -> str:
    return config.label(config.BONUS_TEXT[key], language).format(**kw)


def get_bonus_estimate(ctx: ToolContext, args: GetBonusEstimateArgs | dict | None = None) -> ToolResult:
    args = args if isinstance(args, GetBonusEstimateArgs) else GetBonusEstimateArgs.model_validate(args or {})
    lang = ctx.language
    typed = args.share_pct is not None
    share_pct = args.share_pct if typed else RULES.default_share_pct
    share_params = {"share_num": share_pct, "share_den": 100}

    # G: the category's month average over the last 6 complete months, as the basket card computes one.
    period = periods.resolve(PeriodArg(preset="last_6_months"), ctx.as_of, lang).period
    history = ctx.history()
    rows = classify(history, ctx.as_of, labels.for_context(ctx))  # the request's labels, read once (#68)
    n_months = months_with_history(period.start, period.end, history[0].tx_date if history else None) \
        if is_whole_months(period.start, period.end) else 1
    nb = NumberBuilder(ctx, rows)
    reg = ctx.numbers.register
    sel = Selection(direction="out", start=period.start, end=period.end, categories=(RULES.base_category,))
    grocery = nb.transactions(sel, config.METHODS["spend_month"], period, _t("grocery_month", lang),
                              params={"n_months": n_months})

    if typed:
        share = Number(value=share_pct, unit=Unit.PERCENT, period=period, method=config.USER_INPUT_METHOD,
                       evidence_ref=None, label=_t("share_typed", lang),
                       display=display(Decimal(share_pct), Unit.PERCENT, lang, config.USER_INPUT_METHOD))
    else:  # the rules file's default: a rule value with its own evidence
        share = nb.composite(M["share_pct"], "rule_value", {}, Unit.PERCENT, period, _t("share_default", lang),
                             params=RULES.share_params())[0]

    level_base = nb.composite(M["level_base_eur"], "scale", {"base": grocery}, Unit.EUR_PER_MONTH, period,
                              _t("level_base", lang),
                              params={"factor_num": share_pct, "factor_den": 100, "rounding": "down"})
    percent = nb.composite(M["bonus_percent"], "bonus_level", {"base": grocery}, Unit.PERCENT, period,
                           _t("bonus_percent", lang), params=RULES.level_params(share_pct))
    bonus = nb.composite(M["bonus_month_eur"], "percent_of", {"percent": percent, "base": grocery},
                         Unit.EUR_PER_MONTH, period, _t("bonus_month", lang), params=share_params)
    payment = nb.composite(M["payment_benefit_month_eur"], "rate_of", {"base": grocery}, Unit.EUR_PER_MONTH,
                           period, _t("payment_benefit_month", lang), params=RULES.rate_params(share_pct))
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
        lowest = nb.composite(M["lowest_level_eur"], "rule_value", {}, Unit.EUR_PER_MONTH, period,
                              _t("lowest_level", lang), params=RULES.lowest_params())[0]
        reason = _t("reason_below_lowest", lang)

    # Number ids (n1, n2, ...) follow the order the card shows them: the share in the subtitle, the
    # total, the secondary numbers (the lowest level after the Bonus level), then the two components.
    shown = {"share": share, "total_month": total[0], "bonus_percent": percent[0], "lowest_level": lowest,
             "total_year": year[0], "level_base": level_base[0], "grocery_month": grocery[0],
             "bonus_month": bonus[0], "payment_benefit_month": payment[0]}
    registered = {key: reg(n) if n is not None else None for key, n in shown.items()}
    data = BonusEstimateData(
        status=check.status,
        scenario=_t("scenario", lang, share=share.display),
        reason=reason,
        assumptions=[_t(key, lang) for key in config.BONUS_ASSUMPTIONS],
        **registered,
    )
    evidence.write(ctx.conn, nb.specs)
    return ToolResult(tool=TOOL, data=data, card=_card(data, lang), notes=[], evidence=list(nb.specs),
                      model_view=_model_view(data))


def _card(data: BonusEstimateData, language: str) -> Card:
    ref = data.total_month.evidence_ref
    # When nothing is offered, the reason comes first: the card says why the Bonus is 0.
    text = " ".join([*([data.reason] if data.reason else []), _t("estimate_text", language), *data.assumptions])
    secondary = [data.bonus_percent, data.total_year, data.level_base, data.grocery_month]
    if data.lowest_level is not None:
        secondary.insert(1, data.lowest_level)
    return Card(
        card_id="card_" + hashlib.sha256(f"{TOOL}|{ref}".encode()).hexdigest()[:12],
        type="metric", title=_t("title", language), subtitle=data.scenario, evidence_ref=ref,
        estimate={"label": _t("estimate_label", language), "text": text},
        actions=[Action(type="open_evidence", label=_t("how", language), evidence_ref=ref)],
        status=None,
        primary=data.total_month,
        secondary=secondary,
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
