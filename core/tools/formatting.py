"""Rounding and localised `display` strings for Number objects (contracts/api.md 2.1)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from core.tools.models import Unit

CENT = Decimal("0.01")
TENTH = Decimal("0.1")


def money(value: Decimal) -> Decimal:
    """Round to cents, half away from zero (like PostgreSQL round on numeric)."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def pct(value: Decimal) -> Decimal:
    return value.quantize(TENTH, rounding=ROUND_HALF_UP)


def _group(digits: str, sep: str) -> str:
    out = []
    while len(digits) > 3:
        out.insert(0, digits[-3:])
        digits = digits[:-3]
    out.insert(0, digits)
    return sep.join(out)


def display(value: Decimal, unit: Unit, language: str = "en") -> str:
    """`€1,234.56` / `1 234,56 €`, `18.9%` / `18,9 %`, counts as integers. No plus sign."""
    negative = value < 0
    magnitude = abs(value)
    sign = "-" if negative else ""
    if unit is Unit.COUNT:
        return f"{sign}{int(magnitude)}"
    if unit in (Unit.PERCENT, Unit.PERCENTILE):
        text = f"{pct(magnitude):.1f}"
        return f"{sign}{text.replace('.', ',')} %" if language == "fi" else f"{sign}{text}%"
    whole, frac = f"{money(magnitude):.2f}".split(".")
    if language == "fi":
        return f"{sign}{_group(whole, ' ')},{frac} €"
    return f"{sign}€{_group(whole, ',')}.{frac}"
