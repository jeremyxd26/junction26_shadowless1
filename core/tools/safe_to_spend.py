"""get_safe_to_spend: what can I safely spend in the next 7 days (metrics.md section 3).

One source of truth: the numbers are read from core/metrics/03_safe_to_spend.sql run for this one
customer (core/tools/metric_sql.py); nothing of the formula is re-implemented here.
- `safe_to_spend` is a composite: the smaller of the balance limit and the budget limit
  (formula `minimum`), so its evidence opens both limits.
- `bills_due` comes only from recurring.bills_due_numbers, the one shared path that get_recurring_bills
  uses too: one value and one evidence ref for both cards. Its value is computed like `bills_due_eur`
  in 03 (the unrounded terms summed, rounded once; team-lead decision "metrics wins"), so it equals
  03's column to the cent; the per-bill items of the bills card are rounded each.
- Every other component and limit is a `metric` number whose evidence re-runs 03 for the customer.
The customer and as_of come from ctx only (R4, R5); the result is an estimate (R13).
"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from core.tools import config, evidence, labels, metric_sql, periods, recurring
from core.tools.classify import classify
from core.tools.context import ToolContext
from core.tools.models import Action, Args, Card, Estimate, Number, Period, ToolResult, Unit, assumption
from core.tools.numbers import NumberBuilder, model_number

TOOL = "get_safe_to_spend"
METRIC = "safe_to_spend"
log = logging.getLogger(__name__)


# The savings goal (#391) is not an argument (#447): until the app has a control for it, neither the model
# planner, the rules nor an endpoint can set it. A plan that passes it is rejected as an unknown argument
# and the default goal holds. The class docstring is part of the planner's declaration, so it stays silent.
class GetSafeToSpendArgs(Args):
    """No arguments: the customer and as_of come from the server-bound context."""


class Component(BaseModel):
    key: Literal["balance", "bills_due", "essentials_reserve", "irregular_reserve", "cushion"]
    label: str
    operation: Literal["add", "subtract"]
    amount: Number


class SafeToSpendData(BaseModel):
    period: Period
    safe_to_spend: Number
    savings_goal: Number          # set aside first each month (#391); inside the budget limit
    usual_week: Number            # the usual everyday pace a week
    free_until_payday: Number
    balance_limit: Number
    budget_limit: Number
    binding_limit: Literal["balance", "budget"]
    components: list[Component]
    status: Literal["ok", "below_usual", "nothing_free"]
    next_payday: date
    salary_status: Literal["received_this_month", "upcoming", "late", "no_salary_series"]


# ---- pure logic (03_safe_to_spend.sql `binding_limit` and `status`), used as a consistency check ----

def binding_limit(balance_limit: Decimal, budget_limit: Decimal) -> str:
    """03: 'balance' when the balance limit is the smaller one or equal, else 'budget'."""
    return "balance" if balance_limit <= budget_limit else "budget"


def status_of(safe_to_spend: Decimal, usual_everyday_7d: Decimal) -> str:
    """03: nothing_free at 0, below_usual under the usual everyday spending of 7 days, else ok."""
    if safe_to_spend <= 0:
        return "nothing_free"
    if safe_to_spend < usual_everyday_7d:
        return "below_usual"
    return "ok"


def _t(key: str, language: str, **kw) -> str:
    return config.label(config.SAFE_TO_SPEND_TEXT[key], language).format(**kw)


class BillsDueMismatch(RuntimeError):
    """Internal error: the shared bills-due Number and 03's bills_due_eur differ (they must be equal)."""


class NoTransactions(ValueError):
    """The customer has no transactions up to as_of, so there is nothing to compute (a ValueError, so
    callers that caught ValueError before keep working)."""


def settings_for(ctx: ToolContext, savings_goal: Decimal | None = None) -> dict[str, str]:
    """The settings of 03_safe_to_spend.sql for this context, in one place for every tool that reads it.
    The cushion is passed explicitly (the documented default), so a session setting can never leak in
    and every evidence spec records it. The customer's labels (#68) go in as app.tx_labels, so the metric
    SQL classifies a reviewed purchase like the tools do, and every evidence spec records them; without
    labels metric_settings_for adds nothing, so specs and refs stay as they were. The hero and the
    safe-to-save card read the same row through metric_row, so they can never disagree."""
    settings = {"cushion_eur": config.SAFE_TO_SPEND_CUSHION_EUR, **labels.metric_settings_for(ctx)}
    if savings_goal is not None:   # only when given, so the default specs carry no setting (#391)
        settings["savings_goal_eur"] = f"{savings_goal:.2f}"   # metric_sql.TYPED_SETTINGS: two decimals
    return settings


def row_key(ctx: ToolContext, settings: dict[str, str]) -> tuple:
    """The key of 03's row in ctx.shared: the file, the customer, as_of and the settings (labels included)."""
    return (config.SAFE_TO_SPEND_FILE, ctx.customer_id, ctx.as_of, tuple(sorted(settings.items())))


def metric_row(ctx: ToolContext, savings_goal: Decimal | None = None) -> tuple[dict[str, str], dict[str, Any]]:
    """The settings and the one row of 03_safe_to_spend.sql for this customer, read once per context:
    the safe-to-spend and the safe-to-save tools of one request share it (#165). NoTransactions when
    03 returns no row."""
    settings = settings_for(ctx, savings_goal)
    key = row_key(ctx, settings)
    if key not in ctx.shared:
        # The answer pipeline runs tools in parallel lanes on copies of one context that share `shared`:
        # one lock per key, stored in `shared` itself (dict.setdefault is atomic), so a second lane waits
        # for the first lane's row instead of running the file again (#217).
        with ctx.shared.setdefault(("lock", key), threading.Lock()):
            if key not in ctx.shared:
                ctx.shared[key] = metric_sql.run_one(ctx.conn, config.SAFE_TO_SPEND_FILE, ctx.customer_id,
                                                     ctx.as_of, settings)
    row = ctx.shared[key]
    if row is None:
        raise NoTransactions("no transactions up to as_of for this customer")
    return settings, row


def month_period(ctx: ToolContext) -> Period:
    """03's averaging window, the 6 complete months the monthly figures describe."""
    first = (ctx.as_of + timedelta(days=1)).replace(day=1)
    start, end = periods.add_months(first, -6), first - timedelta(days=1)
    return Period(start=start, end=end, label=periods.period_label(start, end, ctx.language))


def weekly_numbers(ctx: ToolContext, nb: NumberBuilder, settings: dict[str, str],
                   row: dict[str, Any]) -> dict[str, tuple[Number, Decimal]]:
    """The weekly figure as one builder makes it for every tool (the same specs, so the same refs): the
    balance and budget limits, the savings goal (#391), the usual everyday pace a week, and safe to spend,
    the smaller limit, whose evidence lists the goal."""
    lang = ctx.language
    week = Period(start=row["week_start"], end=row["week_end"], label=_t("next_7_days", lang))
    month = month_period(ctx)
    out: dict[str, tuple[Number, Decimal]] = {}
    for key, column, period, unit in (("balance_limit", "balance_limit_7d_eur", week, Unit.EUR),
                                      ("budget_limit", "budget_limit_7d_eur", week, Unit.EUR),
                                      ("savings_goal", "savings_goal_eur", month, Unit.EUR_PER_MONTH),
                                      ("everyday_month", "everyday_month_eur", month, Unit.EUR_PER_MONTH)):
        value = metric_sql.decimal(row[column])
        method = f"{METRIC}.{column}@1"
        spec = evidence.metric_spec(ctx.customer_id, ctx.as_of, method, config.SAFE_TO_SPEND_FILE, column, settings,
                                    value, evidence.period_param(period))
        label = (config.label(config.SAFE_TO_SAVE_TEXT["everyday_month"], lang) if key == "everyday_month"
                 else _t(key, lang))
        out[key] = (nb.number(value, unit, period, method, spec, label), value)
    out["usual_week"] = nb.composite(config.USUAL_WEEK_METHOD, "scale", {"base": out["everyday_month"]},
                                     Unit.EUR_PER_WEEK, month, _t("usual_week", lang),
                                     params={"factor_num": 7, "factor_den": "30.4375"})
    out["safe_to_spend"] = nb.composite(
        f"{METRIC}.safe_to_spend_7d_eur@1", "minimum_after_goal",
        {"a": out["balance_limit"], "b": out["budget_limit"], "goal": out["savings_goal"]},
        Unit.EUR, week, _t("safe_to_spend", lang), params={"period": evidence.period_param(week)})
    return out


def get_safe_to_spend(ctx: ToolContext, args: GetSafeToSpendArgs | dict | None = None, *,
                      savings_goal: Decimal | None = None) -> ToolResult:
    """`savings_goal`: a monthly goal in place of the default, a Python-level parameter only (tests, a later
    API field; #447). Its bounds are checked with the typed setting (metric_sql: 0 to 100,000, two decimals)."""
    args = args if isinstance(args, GetSafeToSpendArgs) else GetSafeToSpendArgs.model_validate(args or {})
    lang = ctx.language
    notes: list[str] = []

    settings, row = metric_row(ctx, savings_goal)

    # Bills due before payday: only through the shared function (one value, one ref with the bills card).
    history = ctx.history()
    rows = classify(history, ctx.as_of, labels.for_context(ctx))
    nb = NumberBuilder(ctx, rows)
    reg = ctx.numbers.register
    due = recurring.bills_due_numbers(ctx, nb)
    if due.payday.date != row["next_payday"] or due.payday.salary_status != row["salary_status"]:
        log.warning("payday of core.tools.recurring and 03_safe_to_spend.sql differ for one customer")
    # One number, one value ("metrics wins"): the card never shows a bills total that 03 does not
    # compute, because free until payday and the limits are 03's and subtract 03's bills_due_eur.
    if due.total_value != metric_sql.decimal(row["bills_due_eur"]):
        raise BillsDueMismatch("bills due of core.tools.recurring and 03_safe_to_spend.sql differ for one customer")

    week = Period(start=row["week_start"], end=row["week_end"], label=_t("next_7_days", lang))
    until_payday = due.due_period  # today + 1 .. payday, labelled like the bills card
    today = Period(start=ctx.as_of, end=ctx.as_of, label=periods.period_label(ctx.as_of, ctx.as_of, lang))
    periods_by_key = {"free_until_payday": until_payday, "balance_limit": week, "budget_limit": week,
                      "balance": today, "essentials_reserve": until_payday,
                      "irregular_reserve": until_payday, "cushion": until_payday}

    values: dict[str, Decimal] = {}
    numbers: dict[str, Number] = {}
    for key, column in config.SAFE_TO_SPEND_NUMBERS:
        value = metric_sql.decimal(row[column])
        method = f"{METRIC}.{column}@1"
        spec = evidence.metric_spec(ctx.customer_id, ctx.as_of, method, config.SAFE_TO_SPEND_FILE, column,
                                    settings, value, evidence.period_param(periods_by_key[key]))
        numbers[key] = nb.number(value, Unit.EUR, periods_by_key[key], method, spec, _t(key, lang))
        values[key] = value

    weekly = weekly_numbers(ctx, nb, settings, row)   # the same limit specs as the loop above, plus the goal
    safe_n, safe_value = weekly["safe_to_spend"]
    if safe_value != metric_sql.decimal(row["safe_to_spend_7d_eur"]):  # min of rounded = rounded min
        raise RuntimeError("safe to spend does not equal the smaller limit")

    binding = row["binding_limit"]
    status = row["status"]
    usual = metric_sql.decimal(row["usual_everyday_7d_eur"])
    if binding != binding_limit(values["balance_limit"], values["budget_limit"]) or \
            status != status_of(safe_value, usual):
        log.warning("binding limit or status of 03_safe_to_spend.sql differs from the rule in this module")

    if row["salary_status"] == "no_salary_series":
        notes.append(_t("note_no_salary", lang))
    elif row["salary_status"] == "late":
        notes.append(_t("note_late_salary", lang))

    amounts = {**numbers, "bills_due": due.total}
    components = [
        Component(key=key, label=_t(f"c_{key}", lang), operation="add" if key == "balance" else "subtract",
                  amount=reg(amounts[key]))
        for key in config.SAFE_TO_SPEND_COMPONENTS
    ]
    data = SafeToSpendData(
        period=week, safe_to_spend=reg(safe_n), savings_goal=reg(weekly["savings_goal"][0]),
        usual_week=reg(weekly["usual_week"][0]), free_until_payday=reg(numbers["free_until_payday"]),
        balance_limit=reg(numbers["balance_limit"]), budget_limit=reg(numbers["budget_limit"]),
        binding_limit=binding, components=components, status=status,
        next_payday=row["next_payday"], salary_status=row["salary_status"],
    )
    evidence.write(ctx.conn, nb.specs)
    return ToolResult(
        tool=TOOL, data=data, card=_card(data, lang), notes=notes,
        evidence=list(nb.specs),
        model_view=_model_view(data, notes),
    )


def card_subtitle(period: Period, language: str) -> str:
    """The week's dates, written like every other period label (core/tools/periods.py), e.g. "1–7 Oct
    2026" / "1.–7.10.2026" (contracts/api.md section 6: the subtitle carries the period). It has digits,
    so it stays a card text and is never put into answer text; the Numbers keep the label "Next 7 days"."""
    return periods.period_label(period.start, period.end, language)


def _estimate(data: SafeToSpendData, language: str) -> Estimate:
    """#380: both limbs of safe to spend, from the card's own Numbers (no new Number). The balance limb observes
    the balance and the bills due before payday and assumes the usual essentials, the reserve for unexpected costs,
    the cushion and the bills on their usual days; the budget limb (#503 review: it binds for every persona) is the
    card's budget limit, from a typical month that repeats, after the monthly amount for saving is put aside."""
    amount = {c.key: c.amount for c in data.components}
    return Estimate(
        label=_t("estimate_label", language), text=_t("estimate_text", language),
        observed=[amount[key] for key in ("balance", "bills_due") if key in amount] + [data.budget_limit],
        assumptions=[assumption("safe_to_spend.spending_as_usual", language, amount.get("essentials_reserve")),
                     assumption("safe_to_spend.reserve_for_unexpected", language, amount.get("irregular_reserve")),
                     assumption("safe_to_spend.cushion", language, amount.get("cushion")),
                     assumption("safe_to_spend.bills_on_usual_days", language),
                     assumption("safe_to_spend.budget_from_usual_month", language),
                     assumption("safe_to_spend.savings_goal_first", language, data.savings_goal)])


def _card(data: SafeToSpendData, language: str) -> Card:
    ref = data.safe_to_spend.evidence_ref
    return Card(
        card_id="card_" + hashlib.sha256(f"{TOOL}|{ref}".encode()).hexdigest()[:12],
        type="metric", title=_t("title", language), subtitle=card_subtitle(data.period, language),
        evidence_ref=ref,
        estimate=_estimate(data, language),
        actions=[Action(type="open_evidence", label=_t("how", language), evidence_ref=ref)],
        status=data.status,
        primary=data.safe_to_spend,
        secondary=[data.free_until_payday, data.balance_limit, data.budget_limit, data.savings_goal],
        comparison=None,
        components=[c.model_dump() for c in data.components],
    )


def _model_view(data: SafeToSpendData, notes: list[str]) -> dict[str, Any]:
    """Compact view for the model: no rows, merchant ids, customer id or evidence refs (R3)."""
    return {
        "tool": TOOL,
        "period": data.period.label,
        "safe_to_spend": model_number(data.safe_to_spend),
        "status": data.status,
        "binding_limit": data.binding_limit,
        "free_until_payday": model_number(data.free_until_payday),
        "balance_limit": model_number(data.balance_limit),
        "budget_limit": model_number(data.budget_limit),
        "savings_goal": model_number(data.savings_goal),
        "usual_week": model_number(data.usual_week),
        "components": [{"key": c.key, "label": c.label, "operation": c.operation, "amount": model_number(c.amount)}
                       for c in data.components],
        "next_payday": data.next_payday.isoformat(),
        "salary_status": data.salary_status,
        "notes": list(notes),
    }
