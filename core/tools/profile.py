"""get_spender_profile: "What kind of spender am I?" (metrics.md section 5).

One source of truth: the label, the traits and every feature are read from
core/metrics/05_spender_profile.sql run for this one customer (core/tools/metric_sql.py). Each
feature is a `metric` number whose evidence re-runs that file, except the monthly spending, which is
the very Number of the basket card (`spender_profile.spend_month_eur@1` over the window's spending
rows, same value and evidence ref), so the two cards never disagree.

The label rule is also written out in Python (`profile_key`), only to mark the features that decided
the label and as a consistency check: 05 decides on unrounded values, so the label always comes from
the SQL row. Labels, descriptions and trait notes carry no numbers and no sensitive terms; no feature
uses Health on its own (R9). The customer and as_of come from ctx only (R4, R5).
"""

from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from core.tools import config, evidence, labels, metric_sql, periods
from core.tools.classify import classify
from core.tools.context import ToolContext
from core.tools.models import Action, Args, Card, Number, Period, ToolResult, Unit
from core.tools.numbers import NumberBuilder, model_number
from core.tools.selection import Selection

TOOL = "get_spender_profile"
METRIC = "spender_profile"
log = logging.getLogger(__name__)

# The features that decided each label: the feature of the rule that matched; for `steady`, the
# fallback, the three features whose rules did not match (metrics.md section 5, label table).
DECIDING: dict[str, tuple[str, ...]] = {
    "not_enough_income_data": ("net_income",),
    "stretched": ("keep_rate",),
    "big_ticket": ("one_off_share",),
    "everyday_heavy": ("everyday_share_pct",),
    "saver": ("keep_rate",),
    "steady": ("keep_rate", "one_off_share", "everyday_share_pct"),
}


class GetSpenderProfileArgs(Args):
    """No arguments: the customer and as_of come from the server-bound context, and the window is
    always the last 6 complete months (metrics.md section 0)."""


class ProfileLabel(BaseModel):
    key: str
    label: str
    description: str


class Trait(BaseModel):
    key: str
    label: str
    note: str
    feature: str | None   # the feature the trait rests on (data only; not a card field)


class Feature(BaseModel):
    key: str
    decides_label: bool
    value: Number


class CategoryRef(BaseModel):
    key: str
    label: str


class SpenderProfileData(BaseModel):
    period: Period
    profile: ProfileLabel
    traits: list[Trait]
    features: list[Feature]          # deciding features first, then the order of config.PROFILE_FEATURES
    top_everyday_category: CategoryRef | None
    n_months: int


# ---- pure logic (05_spender_profile.sql, label and keep rate) ---------------------------------------

def keep_rate(net_income_month: Decimal, spend_month: Decimal) -> Decimal | None:
    """05 `h.keep_rate`: (net income - spend) / net income in %, only when net income is positive."""
    if net_income_month <= 0:
        return None
    return 100 * (net_income_month - spend_month) / net_income_month


def profile_key(keep_rate_pct: Decimal | None, one_off_share_pct: Decimal | None,
                everyday_share_pct: Decimal | None) -> str:
    """05's primary label: the first matching rule (metrics.md section 5)."""
    t = config.PROFILE_THRESHOLDS
    if keep_rate_pct is None:
        return "not_enough_income_data"
    if keep_rate_pct < 0:
        return "stretched"
    if (one_off_share_pct or 0) >= t["big_ticket_one_off_share"]:
        return "big_ticket"
    if (everyday_share_pct or 0) >= t["everyday_heavy_share"]:
        return "everyday_heavy"
    if keep_rate_pct >= t["saver_keep_rate"]:
        return "saver"
    return "steady"


def _t(table: dict[str, tuple[str, str]], key: str, language: str, **kw) -> str:
    return config.label(table[key], language).format(**kw)


def _feature_number(nb: NumberBuilder, key: str, value: Decimal, unit: Unit, period: Period, method: str,
                    spec: dict[str, Any], label: str, language: str) -> Number:
    n = nb.number(value, unit, period, method, spec, label)
    if key == "everyday_tx_month":  # a rate with one decimal: keep it (contracts/api.md card.profile)
        text = f"{value:.1f}"
        shown = f"{text.replace('.', ',')} / kk" if language == "fi" else f"{text} a month"
        return n.model_copy(update={"value": float(value), "display": shown})
    if unit is Unit.MONTHS and value == 1 and language != "fi":
        return n.model_copy(update={"display": "1 month"})
    return n


def get_spender_profile(ctx: ToolContext, args: GetSpenderProfileArgs | dict | None = None) -> ToolResult:
    if not isinstance(args, GetSpenderProfileArgs):
        GetSpenderProfileArgs.model_validate(args or {})
    lang = ctx.language
    notes: list[str] = []

    row = metric_sql.run_one(ctx.conn, config.PROFILE_FILE, ctx.customer_id, ctx.as_of)
    if row is None:
        raise ValueError("no transactions up to as_of for this customer")
    start, end = row["period_start"], row["period_end"]
    period = Period(start=start, end=end, label=periods.period_label(start, end, lang))
    n_months = int(row["n_months"])

    history = ctx.history()
    rows = classify(history, ctx.as_of, labels.basket_labels(ctx.conn, ctx.customer_id, ctx.as_of))
    nb = NumberBuilder(ctx, rows)

    numbers: dict[str, Number] = {}
    values: dict[str, Decimal] = {}
    for key, column, unit_value in config.PROFILE_FEATURES:
        if row[column] is None:   # e.g. no keep rate without positive net income, no shares without spending
            continue
        value = metric_sql.decimal(row[column])
        unit = Unit(unit_value)
        method = f"{METRIC}.{column}@1"
        label = _t(config.PROFILE_FEATURE_LABELS, key, lang)
        values[key] = value
        if key == "spend":
            # The basket card's total: the window's spending rows / n_months, a transactions number.
            sel = Selection(direction="out", start=start, end=end)
            n, py_value = nb.transactions(sel, config.METHODS["spend_month"], period, label,
                                          params={"n_months": n_months})
            if py_value == value:
                numbers[key] = n
                continue
            nb.specs.pop(n.evidence_ref, None)
            log.warning("monthly spending of the rows and of 05_spender_profile.sql differ for one customer")
        spec = evidence.metric_spec(ctx.customer_id, ctx.as_of, method, config.PROFILE_FILE, column, {}, value,
                                    evidence.period_param(period))
        numbers[key] = _feature_number(nb, key, value, unit, period, method, spec, label, lang)

    key = row["profile"]
    if key not in config.PROFILE_KEYS:
        raise RuntimeError("05_spender_profile.sql returned an unknown profile key")
    if key != profile_key(values.get("keep_rate"), values.get("one_off_share"), values.get("everyday_share_pct")):
        # 05 compares unrounded values; a rounded column can sit on the other side of a threshold.
        log.warning("profile rule in this module and 05_spender_profile.sql differ for one customer")
    deciding = [k for k in DECIDING[key] if k in numbers]

    reg = ctx.numbers.register
    order = deciding + [k for k, _, _ in config.PROFILE_FEATURES if k in numbers and k not in deciding]
    features = [Feature(key=k, decides_label=k in deciding, value=reg(numbers[k])) for k in order]

    trait_keys = [t for t in config.PROFILE_TRAITS if t in (row["traits"] or [])]
    traits = [Trait(key=t, label=_t(config.TRAIT_LABELS, t, lang), note=_t(config.TRAIT_NOTES, t, lang),
                    feature=config.TRAIT_FEATURES.get(t)) for t in trait_keys]

    top = row["top_everyday_category"]
    top_ref = None
    if top and top in config.CATEGORY_LABELS and top not in config.PEER_SENSITIVE:
        top_ref = CategoryRef(key=top, label=config.label(config.CATEGORY_LABELS[top], lang))

    if key == "not_enough_income_data":
        notes.append(_t(config.PROFILE_TEXT, "note_no_income", lang))
    if "salary_moved_elsewhere" in trait_keys:
        notes.append(_t(config.PROFILE_TEXT, "note_sweep", lang))

    data = SpenderProfileData(
        period=period,
        profile=ProfileLabel(key=key, label=_t(config.PROFILE_LABELS, key, lang),
                             description=_t(config.PROFILE_DESCRIPTIONS, key, lang)),
        traits=traits, features=features, top_everyday_category=top_ref, n_months=n_months,
    )
    evidence.write(ctx.conn, nb.specs)
    return ToolResult(tool=TOOL, data=data, card=_card(data, lang), notes=notes, evidence=list(nb.specs),
                      model_view=_model_view(data, notes))


def _card(data: SpenderProfileData, language: str) -> Card:
    by_key = {f.key: f for f in data.features}
    shown = [f.key for f in data.features if f.decides_label]
    shown += [k for k in config.PROFILE_CARD_FEATURES if k in by_key and k not in shown]
    ref = by_key[shown[0]].value.evidence_ref if shown else None
    return Card(
        card_id="card_" + hashlib.sha256(f"{TOOL}|{data.profile.key}|{ref}".encode()).hexdigest()[:12],
        type="profile", title=_t(config.PROFILE_TEXT, "title", language),
        subtitle=_t(config.PROFILE_TEXT, "subtitle", language, label=data.period.label),
        evidence_ref=ref, estimate=None,
        actions=[Action(type="ask", label=_t(config.PROFILE_TEXT, "action_label", language),
                        prompt=_t(config.PROFILE_TEXT, "action_prompt", language))],
        profile=data.profile.model_dump(),
        traits=[{"key": t.key, "label": t.label, "note": t.note} for t in data.traits],
        features=[{"key": k, "decides_label": by_key[k].decides_label, "value": by_key[k].value.model_dump()}
                  for k in shown],
    )


def _model_view(data: SpenderProfileData, notes: list[str]) -> dict[str, Any]:
    """Compact view for the model: no rows, merchant ids, customer id or evidence refs (R3)."""
    return {
        "tool": TOOL,
        "period": data.period.label,
        "profile": data.profile.model_dump(),
        "traits": [{"key": t.key, "label": t.label, "note": t.note} for t in data.traits],
        "features": [{"key": f.key, "decides_label": f.decides_label, "value": model_number(f.value)}
                     for f in data.features],
        "top_everyday_category": data.top_everyday_category.model_dump() if data.top_everyday_category else None,
        "notes": list(notes),
    }
