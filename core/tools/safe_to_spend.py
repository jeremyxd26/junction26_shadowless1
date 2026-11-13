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
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from core.tools import config, evidence, labels, metric_sql, periods, recurring
from core.tools.classify import classify
from core.tools.context import ToolContext
from core.tools.models import Action, Args, Card, Number, Period, ToolResult, Unit
from core.tools.numbers import NumberBuilder, model_number

TOOL = "get_safe_to_spend"
METRIC = "safe_to_spend"
log = logging.getLogger(__name__)


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


def get_safe_to_spend(ctx: ToolContext, args: GetSafeToSpendArgs | dict | None = None) -> ToolResult:
    GetSafeToSpendArgs.model_validate(args or {}) if not isinstance(args, GetSafeToSpendArgs) else args
    lang = ctx.language
    notes: list[str] = []

    # The cushion is passed explicitly (the documented default), so a session setting can never leak in
    # and every evidence spec records it.
    settings = {"cushion_eur": config.SAFE_TO_SPEND_CUSHION_EUR}
    row = metric_sql.run_one(ctx.conn, config.SAFE_TO_SPEND_FILE, ctx.customer_id, ctx.as_of, settings)
    if row is None:
        raise NoTransactions("no transactions up to as_of for this customer")

    # Bills due before payday: only through the shared function (one value, one ref with the bills card).
    history = ctx.history()
    rows = classify(history, ctx.as_of, labels.basket_labels(ctx.conn, ctx.customer_id, ctx.as_of))
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

    safe_n, safe_value = nb.composite(
        f"{METRIC}.safe_to_spend_7d_eur@1", "minimum",
        {"a": (numbers["balance_limit"], values["balance_limit"]),
         "b": (numbers["budget_limit"], values["budget_limit"])},
        Unit.EUR, week, _t("safe_to_spend", lang), params={"period": evidence.period_param(week)})
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
        period=week, safe_to_spend=reg(safe_n), free_until_payday=reg(numbers["free_until_payday"]),
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


def _card(data: SafeToSpendData, language: str) -> Card:
    ref = data.safe_to_spend.evidence_ref
    return Card(
        card_id="card_" + hashlib.sha256(f"{TOOL}|{ref}".encode()).hexdigest()[:12],
        type="metric", title=_t("title", language), subtitle=data.period.label,
        evidence_ref=ref,
        estimate={"label": _t("estimate_label", language), "text": _t("estimate_text", language)},
        actions=[Action(type="open_evidence", label=_t("how", language), evidence_ref=ref)],
        status=data.status,
        primary=data.safe_to_spend,
        secondary=[data.free_until_payday, data.balance_limit, data.budget_limit],
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
        "components": [{"key": c.key, "label": c.label, "operation": c.operation, "amount": model_number(c.amount)}
                       for c in data.components],
        "next_payday": data.next_payday.isoformat(),
        "salary_status": data.salary_status,
        "notes": list(notes),
    }
