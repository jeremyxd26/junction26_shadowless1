"""get_peer_benchmark: you compared with people of your age band and area (metrics.md section 6).

One source of truth: core/metrics/06_peer_benchmark.sql run for this one customer
(core/tools/metric_sql.py). It reads the precomputed marts when the build for as_of is complete and
otherwise falls back to the customers in the range (here: only this customer, so no group).
- `you` is the customer's own monthly average: the window's rows of the metric / n_months, a
  transactions number whose evidence lists those rows. It is checked against 06's `you_month_eur`.
- The group statistics (median, quartiles, percentile, difference from the median, group size) are
  `peer_aggregate` numbers: their evidence re-runs 06 and shows group statistics only, never another
  customer's rows.
- No group of at least 20 other comparable customers, or a customer whose salary is swept elsewhere:
  `shown = false` with a reason, no statistics and no card.
Health is never benchmarked and is rejected at the argument level (R9). Peer numbers are estimates and
the card says so (R13). The customer and as_of come from ctx only (R4, R5).
"""

from __future__ import annotations

import hashlib
import logging
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, field_validator

from core.tools import baskets, config, evidence, labels, metric_sql, periods
from core.tools.classify import classify
from core.tools.context import ToolContext
from core.tools.models import Action, Args, Card, Number, Period, PeerMetric, ToolResult, Unit
from core.tools.numbers import NumberBuilder, model_number
from core.tools.selection import Selection

TOOL = "get_peer_benchmark"
METRIC = "peer_benchmark"
log = logging.getLogger(__name__)

# Metrics a what-if never cuts (regular essentials, metrics.md section 4): the card offers no
# "spend less" follow-up for them.
NO_CUT_ACTION = frozenset({"regular_essentials", "Housing", "Utilities", "Groceries"})


class PeerPeriod(str, Enum):
    """06 compares monthly averages over the last 6 complete months only (metrics.md section 6)."""

    LAST_6_MONTHS = "last_6_months"


class GetPeerBenchmarkArgs(Args):
    metric: PeerMetric   # total spending, a basket or a category; never Health (R9)
    period: PeerPeriod = PeerPeriod.LAST_6_MONTHS

    @field_validator("metric", mode="before")
    @classmethod
    def _not_sensitive(cls, value: Any) -> Any:
        if isinstance(value, str) and value in config.PEER_SENSITIVE:
            raise ValueError(f"{value} is never benchmarked against other people (rule R9)")
        return value


class PeerGroup(BaseModel):
    level: Literal["age_band+area3", "age_band+city", "age_band", "all"]
    label: str
    size: Number | None          # other comparable customers in the group; only when shown
    comparable: bool


class PeerBenchmarkData(BaseModel):
    metric: str
    metric_label: str
    period: Period
    shown: bool
    reason: Literal["group_too_small", "not_comparable"] | None
    you: Number
    peer_median: Number | None
    peer_p25: Number | None
    peer_p75: Number | None
    percentile: Number | None
    vs_median: Number | None     # None also when the group median is 0
    peer_group: PeerGroup
    peer_source: Literal["marts", "range"]


# ---- pure logic --------------------------------------------------------------------------------------

def peer_status(comparable: bool, peer_n: int, min_n: int) -> tuple[bool, str | None]:
    """06 `shown`: comparable and at least min_n other peers; otherwise the reason it is not shown."""
    if not comparable:
        return False, "not_comparable"
    if peer_n < min_n:
        return False, "group_too_small"
    return True, None


def group_label(level: str, group: str, language: str) -> str:
    """A coarse label for the group: "Age 35-44, postal area 005" (never a customer or a full code)."""
    if level == "all":
        return _t("group_all", language)
    age, _, area = group.partition(" ")
    if level == "age_band+area3":
        return _t("group_age_band+area3", language, age=age, area=area)
    if level == "age_band+city":
        city = config.label(config.CITY_LABELS[area], language) if area in config.CITY_LABELS \
            else _t("group_city_other", language, code=area)
        return _t("group_age_band+city", language, age=age, city=city)
    return _t("group_age_band", language, age=age)


def metric_label(metric: str, language: str) -> str:
    if metric == "spend_total":
        return _t("spend_total", language)
    if metric in config.BASKET_LABELS:
        return config.label(config.BASKET_LABELS[metric], language)
    return config.label(config.CATEGORY_LABELS[metric], language)


def metric_selection(metric: str, period: Period) -> Selection:
    """The customer's own rows of a 06 metric: the spend flow, one basket or one category."""
    if metric == "spend_total":
        return Selection(direction="out", start=period.start, end=period.end)
    if metric in config.BASKETS:
        return Selection(direction="out", start=period.start, end=period.end, baskets=(metric,))
    return Selection(direction="out", start=period.start, end=period.end, categories=(metric,))


def _t(key: str, language: str, **kw) -> str:
    return config.label(config.PEER_TEXT[key], language).format(**kw)


# ---- the tool ----------------------------------------------------------------------------------------

def get_peer_benchmark(ctx: ToolContext, args: GetPeerBenchmarkArgs | dict) -> ToolResult:
    args = args if isinstance(args, GetPeerBenchmarkArgs) else GetPeerBenchmarkArgs.model_validate(args)
    lang = ctx.language
    metric = args.metric.value
    notes: list[str] = []

    # min group size passed explicitly (the documented default), so a session setting can never leak in
    # the customer's labels (#68) as app.tx_labels, so 06 classifies a reviewed purchase like the baskets do
    settings = {"peer_min_n": config.PEER_MIN_N, **labels.metric_settings_for(ctx)}
    rows = [r for r in metric_sql.run(ctx.conn, config.PEER_FILE, ctx.customer_id, ctx.as_of, settings)
            if r.get("customer_id") == ctx.customer_id and r.get("metric") == metric]
    if not rows:
        raise ValueError("no transactions up to as_of for this customer")
    row = rows[0]
    start, end = row["period_start"], row["period_end"]
    period = Period(start=start, end=end, label=periods.period_label(start, end, lang))
    period_param = evidence.period_param(period)
    what = metric_label(metric, lang)

    history = ctx.history()
    nb = NumberBuilder(ctx, classify(history, ctx.as_of, labels.for_context(ctx)))
    reg = ctx.numbers.register

    # ---- you: the customer's own rows ----
    you_value = metric_sql.decimal(row["you_month_eur"])
    n_months = baskets.months_with_history(start, end, history[0].tx_date if history else None)
    you, py_value = nb.transactions(metric_selection(metric, period), config.METHODS["peer_you"], period,
                                    _t("you", lang), unit=Unit.EUR_PER_MONTH, params={"n_months": n_months})
    if py_value != you_value:
        nb.specs.pop(you.evidence_ref, None)
        log.warning("own monthly value of the rows and of 06_peer_benchmark.sql differ for one customer")
        you = _stat(nb, ctx, metric, "you_month_eur", you_value, Unit.EUR_PER_MONTH, period, period_param,
                    settings, _t("you", lang))
    you = reg(you)

    min_n = int(config.PEER_MIN_N)
    shown, reason = peer_status(bool(row["comparable"]), int(row["peer_n"]), min_n)
    if shown != bool(row["shown"]):
        log.warning("peer status rule in this module and 06_peer_benchmark.sql differ for one customer")
        shown = bool(row["shown"])
        reason = None if shown else (reason or "group_too_small")

    stats: dict[str, Number | None] = {k: None for k, _, _ in config.PEER_STATS}
    if shown:
        for key, column, unit_value in config.PEER_STATS:
            if row[column] is None:   # vs_median when the group median is 0
                continue
            stats[key] = reg(_stat(nb, ctx, metric, column, metric_sql.decimal(row[column]), Unit(unit_value),
                                   period, period_param, settings, _t(key, lang)))
    else:
        notes.append(_t(f"reason_{reason}", lang))

    level = row["peer_level"]
    data = PeerBenchmarkData(
        metric=metric, metric_label=what, period=period, shown=shown, reason=reason, you=you,
        peer_median=stats["peer_median"], peer_p25=stats["peer_p25"], peer_p75=stats["peer_p75"],
        percentile=stats["percentile"], vs_median=stats["vs_median"],
        peer_group=PeerGroup(level=level, label=group_label(level, row["peer_group"], lang), size=stats["size"],
                             comparable=bool(row["comparable"])),
        peer_source=row["peer_source"],
    )
    evidence.write(ctx.conn, nb.specs)
    estimate = {"label": _t("estimate_label", lang), "text": _t(f"estimate_{level}", lang)} if shown else None
    return ToolResult(tool=TOOL, data=data, card=_card(data, estimate, lang) if shown else None, notes=notes,
                      evidence=list(nb.specs), model_view=_model_view(data, estimate, notes))


def _stat(nb: NumberBuilder, ctx: ToolContext, metric: str, column: str, value: Decimal, unit: Unit,
          period: Period, period_param: dict[str, str], settings: dict[str, str], label: str) -> Number:
    method = f"{METRIC}.{column}@1"
    spec = evidence.peer_spec(ctx.customer_id, ctx.as_of, method, config.PEER_FILE, metric, column, settings,
                              value, period_param)
    # The display comes from the method-aware formatter (#111) through NumberBuilder: "51st percentile",
    # "1.2% more" / "31.0% less" for the difference from the median, "118" for the group size.
    n = nb.number(value, unit, period, method, spec, label)
    if unit is Unit.PERCENTILE:   # a whole percentile stays an integer, as in contracts/api.md card.peer
        return n.model_copy(update={"value": int(value)})
    return n


def _card(data: PeerBenchmarkData, estimate: dict[str, str], language: str) -> Card:
    ref = data.peer_median.evidence_ref
    if data.metric == "spend_total":
        prompt = _t("action_prompt_total", language)
    else:
        prompt = _t("action_prompt", language, what=data.metric_label.lower() if language == "en" else data.metric_label)
    actions = [] if data.metric in NO_CUT_ACTION else [Action(type="ask", label=_t("action_label", language),
                                                              prompt=prompt)]
    dump = lambda n: n.model_dump() if n is not None else None  # noqa: E731
    return Card(
        card_id="card_" + hashlib.sha256(f"{TOOL}|{data.metric}|{ref}".encode()).hexdigest()[:12],
        type="peer", title=_t("title", language, what=data.metric_label),
        subtitle=_t("subtitle", language, label=data.period.label),
        evidence_ref=ref, estimate=estimate, actions=actions,
        you=dump(data.you), peer_median=dump(data.peer_median), peer_p25=dump(data.peer_p25),
        peer_p75=dump(data.peer_p75), percentile=dump(data.percentile), vs_median=dump(data.vs_median),
        peer_group={"level": data.peer_group.level, "label": data.peer_group.label,
                    "size": dump(data.peer_group.size), "comparable": data.peer_group.comparable},
        note=_t("note", language),
    )


def _model_view(data: PeerBenchmarkData, estimate: dict[str, str] | None, notes: list[str]) -> dict[str, Any]:
    """Compact view for the model: group statistics only; no rows, customer id or evidence refs (R3)."""
    return {
        "tool": TOOL,
        "metric": data.metric,
        "metric_label": data.metric_label,
        "period": data.period.label,
        "shown": data.shown,
        "reason": data.reason,
        "you": model_number(data.you),
        "peer_median": model_number(data.peer_median),
        "peer_p25": model_number(data.peer_p25),
        "peer_p75": model_number(data.peer_p75),
        "percentile": model_number(data.percentile),
        "vs_median": model_number(data.vs_median),
        # No group label: the age band and the postal area stay on the card (#487); the sentence needs only
        # the size and whether the group is comparable.
        "peer_group": {"level": data.peer_group.level, "size": model_number(data.peer_group.size),
                       "comparable": data.peer_group.comparable},
        "estimate": estimate["text"] if estimate else None,
        "notes": list(notes),
    }
