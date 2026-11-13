"""run_what_if: how much would cutting a selection by a percentage save (metrics.md section 4).

One source of truth: the numbers are read from core/metrics/04_what_if.sql run for this one customer
(core/tools/metric_sql.py); each is a `metric` number whose evidence re-runs that file with the same
selection and cut. The baseline is the average of the last 6 complete months with one-offs left out;
regular essentials are never cut (status `not_offered`); unexpected necessities only with a caveat.

Arguments are validated before anything runs: a selection kind from the contract, a category that is
spending (never Health on its own, R9), MCC codes that are not health MCCs, a merchant alias that
exists and is not a health service, and a cut of 1..100 %. The customer and as_of come from ctx only
(R4, R5); the result is an estimate (R13). The model sees aliases, never merchant ids (R3).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from core.tools import aliases, config, evidence, metric_sql, periods
from core.tools.context import ToolContext
from core.tools.models import MERCHANT_ALIAS_PATTERN, Action, Args, Card, Number, Period, ToolResult, Unit
from core.tools.numbers import NumberBuilder, model_number

TOOL = "run_what_if"
METRIC = "what_if"
HEALTH_MCCS = frozenset(config.MCC_GROUPS["health"])
MCC_CODE = re.compile(r"^\d{4}$")


class WhatIfSelection(Args):
    kind: Literal["category", "basket", "mcc", "merchant"]
    value: str

    @model_validator(mode="after")
    def _check(self) -> WhatIfSelection:
        if self.kind == "category":
            if self.value == "Health":
                raise ValueError("Health cannot be a what-if selection (rule R9)")
            if self.value not in config.WHAT_IF_CATEGORIES:
                raise ValueError(f"category {self.value!r} is not a spending category")
        elif self.kind == "basket":
            if self.value not in config.BASKETS:
                raise ValueError(f"unknown basket {self.value!r}")
        elif self.kind == "mcc":
            codes = [c.strip() for c in self.value.split(",") if c.strip()]
            if not codes or any(not MCC_CODE.fullmatch(c) for c in codes):
                raise ValueError("mcc must be one or more 4-digit codes, comma-separated")
            if HEALTH_MCCS & set(codes):
                raise ValueError("health MCCs cannot be a what-if selection (rule R9)")
            self.value = ",".join(sorted(set(codes)))
        elif not re.fullmatch(MERCHANT_ALIAS_PATTERN, self.value):
            raise ValueError("merchant must be an alias such as store_a")
        return self


class RunWhatIfArgs(Args):
    selection: WhatIfSelection
    cut_pct: int = Field(ge=1, le=100)


class Scenario(BaseModel):
    selection: dict[str, str]   # {kind, value}; for a merchant the value is the merchant id (app only)
    cut_pct: Number
    label: str


class WhatIfResult(BaseModel):
    """The POST /api/whatif body without customer_id, as_of, language, estimate and evidence_ref."""

    scenario: Scenario
    status: Literal["estimate", "estimate_with_caveat", "not_offered"]
    baseline_per_month: Number
    saving_per_month: Number
    saving_per_week: Number
    saving_per_year: Number
    one_off_excluded: Number
    regular_excluded: Number
    assumptions: list[str]
    caveats: list[str]


def _t(key: str, language: str, **kw) -> str:
    return config.label(config.WHAT_IF_TEXT[key], language).format(**kw)


def _what(sel: WhatIfSelection, alias_label: str | None, language: str) -> str:
    """What is being cut, in words: 'restaurants', 'everyday spending', 'Grocery store A'."""
    if sel.kind == "category":
        text = config.label(config.CATEGORY_LABELS[sel.value], language)
    elif sel.kind == "basket":
        text = config.label(config.BASKET_LABELS[sel.value], language)
    elif sel.kind == "mcc":
        return _t("mcc", language, codes=sel.value.replace(",", ", "))
    else:
        return alias_label or sel.value
    return text[:1].lower() + text[1:] if language != "fi" else text.lower()


def caveats_for(status: str, language: str) -> list[str]:
    """The caveats a what-if result carries for its status (contracts/api.md section 8.1)."""
    out = [_t("caveat_estimate", language)]
    if status == "estimate_with_caveat":
        out.append(_t("caveat_unexpected", language))
    elif status == "not_offered":
        out.append(_t("caveat_not_offered", language))
    return out


def run_what_if(ctx: ToolContext, args: RunWhatIfArgs | dict) -> ToolResult:
    args = args if isinstance(args, RunWhatIfArgs) else RunWhatIfArgs.model_validate(args)
    lang = ctx.language
    sel = args.selection

    sql_value = sel.value
    alias_label = None
    if sel.kind == "mcc":
        # Beyond the known health MCCs: no code that this customer's own Health transactions use (R9).
        codes = set(sel.value.split(","))
        if any(t.mcc in codes and t.category == "Health" for t in ctx.history()):
            raise ValueError("an MCC used for health spending cannot be a what-if selection (rule R9)")
    if sel.kind == "merchant":
        history = ctx.history()
        alias_map = aliases.build(history, ctx.as_of)
        try:
            merchant_id = alias_map.merchant_id(sel.value)
        except KeyError:
            raise ValueError(f"unknown merchant alias {sel.value!r}") from None
        if any(t.merchant_id == merchant_id and t.category == "Health" for t in history):
            raise ValueError("a health service cannot be a what-if selection (rule R9)")
        sql_value = merchant_id
        alias_label = alias_map.for_merchant(merchant_id).label(lang)

    settings = {"whatif": f"{sel.kind}:{sql_value}", "whatif_pct": str(args.cut_pct)}
    row = metric_sql.run_one(ctx.conn, config.WHAT_IF_FILE, ctx.customer_id, ctx.as_of, settings)
    if row is None:
        # contracts/api.md section 8.1: no spending in the window at all -> 422 invalid_scenario
        raise ValueError("invalid_scenario: the selection has no spending in the last 6 full months")

    window = Period(start=row["period_start"], end=row["period_end"],
                    label=periods.period_label(row["period_start"], row["period_end"], lang))
    what = _what(sel, alias_label, lang)
    nb = NumberBuilder(ctx, [])
    reg = ctx.numbers.register
    numbers: dict[str, Number] = {}
    for key, column, unit in config.WHAT_IF_NUMBERS:
        value = metric_sql.decimal(row[column])
        method = f"{METRIC}.{column}@1"
        spec = evidence.metric_spec(ctx.customer_id, ctx.as_of, method, config.WHAT_IF_FILE, column, settings, value,
                                    evidence.period_param(window))
        label = _t(key, lang, what=what[:1].upper() + what[1:])
        numbers[key] = reg(nb.number(value, Unit(unit), window, method, spec, label))

    cut = reg(Number(value=args.cut_pct, unit=Unit.PERCENT, period=window, method=config.USER_INPUT_METHOD,
                     evidence_ref=None, label=_t("cut", lang),
                     display=f"{args.cut_pct} %" if lang == "fi" else f"{args.cut_pct}%"))
    scenario_label = _t("scenario", lang, pct=args.cut_pct, what=what)
    result = WhatIfResult(
        scenario=Scenario(selection={"kind": sel.kind, "value": sql_value}, cut_pct=cut, label=scenario_label),
        status=row["status"],
        assumptions=[_t("estimate_text", lang, pct=args.cut_pct), _t("assume_rest", lang)],
        caveats=caveats_for(row["status"], lang),
        **numbers,
    )
    evidence.write(ctx.conn, nb.specs)
    return ToolResult(
        tool=TOOL, data=result, card=_card(result, args.cut_pct, lang), notes=[], evidence=list(nb.specs),
        model_view=_model_view(result, sel),
    )


def _card(result: WhatIfResult, cut_pct: int, language: str) -> Card:
    ref = result.saving_per_month.evidence_ref
    return Card(
        card_id="card_" + hashlib.sha256(f"{TOOL}|{ref}".encode()).hexdigest()[:12],
        type="whatif", title=result.scenario.label, subtitle=_t("subtitle", language), evidence_ref=ref,
        estimate={"label": _t("estimate_label", language), "text": _t("estimate_text", language, pct=cut_pct)},
        actions=[Action(type="open_evidence", label=_t("how", language), evidence_ref=ref)],
        result=result.model_dump(mode="json"),
    )


def _model_view(result: WhatIfResult, sel: WhatIfSelection) -> dict[str, Any]:
    """Compact view for the model: aliases instead of merchant ids, no refs, no customer id (R3)."""
    return {
        "tool": TOOL,
        "scenario": result.scenario.label,
        "selection": {"kind": sel.kind, "value": sel.value},   # the alias for a merchant, never its id
        "cut_pct": model_number(result.scenario.cut_pct),
        "status": result.status,
        **{key: model_number(getattr(result, key)) for key, _, _ in config.WHAT_IF_NUMBERS},
        "assumptions": list(result.assumptions),
        "caveats": list(result.caveats),
    }
