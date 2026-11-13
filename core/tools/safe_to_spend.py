"""get_safe_to_spend: what can I safely spend in the next 7 days (metrics.md section 3).

One source of truth: the numbers are read from core/metrics/03_safe_to_spend.sql run for this one
customer (core/tools/metric_sql.py); nothing of the formula is re-implemented here.
- `safe_to_spend` is a composite: the smaller of the balance limit and the budget limit
  (formula `minimum`), so its evidence opens both limits.
- `bills_due` is the very Number get_recurring_bills returns (same value, same evidence ref): the sum
  of the rounded per-bill amounts, so the bills card and this card never disagree. 03 rounds the
  unrounded sum instead; the two can differ by 0.01, which the contract allows for components.
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

from core.tools import bills, config, evidence, metric_sql, periods
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


def get_safe_to_spend(ctx: ToolContext, args: GetSafeToSpendArgs | dict | None = None) -> ToolResult:
    GetSafeToSpendArgs.model_validate(args or {}) if not isinstance(args, GetSafeToSpendArgs) else args
    lang = ctx.language
    notes: list[str] = []

    row = metric_sql.run_one(ctx.conn, config.SAFE_TO_SPEND_FILE, ctx.customer_id, ctx.as_of)
    if row is None:
        raise ValueError("no transactions up to as_of for this customer")

    # Bills due before payday: the same Number as the bills card (one value, one evidence ref).
    bills_result = bills.get_recurring_bills(ctx, {"include_income": False})
    bills_data = bills_result.data
    if bills_data.next_payday != row["next_payday"] or bills_data.salary_status != row["salary_status"]:
        log.warning("payday of get_recurring_bills and 03_safe_to_spend.sql differ for one customer")

    week = Period(start=row["week_start"], end=row["week_end"], label=_t("next_7_days", lang))
    until_payday = bills_data.due_period  # today + 1 .. payday, labelled like the bills card
    today = Period(start=ctx.as_of, end=ctx.as_of, label=periods.period_label(ctx.as_of, ctx.as_of, lang))
    periods_by_key = {"free_until_payday": until_payday, "balance_limit": week, "budget_limit": week,
                      "balance": today, "essentials_reserve": until_payday,
                      "irregular_reserve": until_payday, "cushion": until_payday}

    nb = NumberBuilder(ctx, [])
    reg = ctx.numbers.register
    values: dict[str, Decimal] = {}
    numbers: dict[str, Number] = {}
    settings: dict[str, str] = {}  # 03 defaults (cushion 100 €); stored in each spec so evidence re-runs alike
    for key, column in config.SAFE_TO_SPEND_NUMBERS:
        value = metric_sql.decimal(row[column])
        method = f"{METRIC}.{column}@1"
        spec = evidence.metric_spec(ctx.customer_id, ctx.as_of, method, config.SAFE_TO_SPEND_FILE, column,
                                    settings, value)
        numbers[key] = nb.number(value, Unit.EUR, periods_by_key[key], method, spec, _t(key, lang))
        values[key] = value

    safe_n, safe_value = nb.composite(
        f"{METRIC}.safe_to_spend_7d_eur@1", "minimum",
        {"a": (numbers["balance_limit"], values["balance_limit"]),
         "b": (numbers["budget_limit"], values["budget_limit"])},
        Unit.EUR, week, _t("safe_to_spend", lang))
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

    amounts = {**numbers, "bills_due": bills_data.upcoming_total}
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
        evidence=list(nb.specs) + [r for r in bills_result.evidence if r not in nb.specs],
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
