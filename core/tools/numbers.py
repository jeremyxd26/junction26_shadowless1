"""Builds Number objects and the evidence spec behind each one; shared by every tool.

`transactions()` numbers are computed by `selection.value_of` over the classified rows, so evidence
resolution re-runs exactly the same code. `composite()` numbers are computed from other numbers by
`evidence.compute_formula`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from core.tools import config, evidence, labels
from core.tools.formatting import display
from core.tools.models import Number, Period, Unit
from core.tools.selection import Selection, select, value_of

DEFAULT_UNITS = {
    config.METHODS["total"]: Unit.EUR,
    config.METHODS["basket_total"]: Unit.EUR,
    config.METHODS["n_tx"]: Unit.COUNT,
    config.METHODS["row_count"]: Unit.COUNT,
    config.METHODS["basket_month_avg"]: Unit.EUR_PER_MONTH,
    config.METHODS["spend_month"]: Unit.EUR_PER_MONTH,
    config.METHODS["typical_month"]: Unit.EUR_PER_MONTH,
    config.METHODS["bill_due"]: Unit.EUR,
    config.METHODS["bills_due"]: Unit.EUR,
    config.METHODS["bills_to_date"]: Unit.EUR,
    config.METHODS["daily_pace"]: Unit.EUR_PER_DAY,
}


def json_value(value: Decimal, unit: Unit) -> int | float:
    """A whole count as an integer; anything else, a fractional count too (14.2 a month), as a float."""
    return int(value) if unit is Unit.COUNT and value == value.to_integral_value() else float(value)


def model_number(n: Number | None) -> dict[str, Any] | None:
    """What the model may see of a Number: id, value, unit and label; no evidence ref (R3)."""
    if n is None:
        return None
    return {"id": n.id, "value": n.value, "unit": n.unit.value, "label": n.label}


class NumberBuilder:
    """Collects the specs of every number a tool call produces (written once, at the end)."""

    def __init__(self, ctx, rows) -> None:
        self.ctx = ctx
        self.rows = rows
        self.specs: dict[str, dict[str, Any]] = {}

    def number(self, value: Decimal, unit: Unit, period: Period, method: str, spec: dict, label: str) -> Number:
        ref = evidence.make_ref(spec)
        self.specs[ref] = spec
        return Number(value=json_value(value, unit), unit=unit, period=period,
                      method=method, evidence_ref=ref, label=label,
                      display=display(value, unit, self.ctx.language, method))

    def transactions(self, sel: Selection, method: str, period: Period, label: str, *,
                     unit: Unit | None = None, params: dict[str, Any] | None = None) -> tuple[Number, Decimal]:
        value = value_of(select(self.rows, sel), sel, method, params)
        # The customer's labels these rows were classified with (#68), so resolving the spec later
        # re-classifies with the same labels, whatever the customer answered since.
        label_set = labels.label_set({c.tx.id: c.basket for c in self.rows if c.overridden})
        spec = evidence.transactions_spec(self.ctx.customer_id, self.ctx.as_of, method, sel, value, params,
                                          label_set)
        return self.number(value, unit or DEFAULT_UNITS[method], period, method, spec, label), value

    def composite(self, method: str, formula: str, parts: dict[str, tuple[Number, Decimal]], unit: Unit,
                  period: Period, label: str, *, params: dict[str, Any] | None = None) -> tuple[Number, Decimal]:
        values = {role: v for role, (_, v) in parts.items()}
        value = evidence.compute_formula(formula, values, params)
        spec = evidence.composite_spec(self.ctx.customer_id, self.ctx.as_of, method, formula,
                                       {role: _part(n, v) for role, (n, v) in parts.items()}, value, params)
        return self.number(value, unit, period, method, spec, label), value


def _part(n: Number, value: Decimal) -> str | dict[str, Any]:
    """A composite part: the number's ref, or, for a value the user gave (no ref, #242), the value inline."""
    if n.evidence_ref is not None:
        return n.evidence_ref
    return {"method": n.method, "value": str(value),
            "period": {"start": n.period.start.isoformat(), "end": n.period.end.isoformat()}}
