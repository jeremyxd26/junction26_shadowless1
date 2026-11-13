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


RATE_SUFFIX = {  # contracts/api.md example: "€1,180.21 a month"
    Unit.EUR_PER_DAY: (" a day", " / pv"),
    Unit.EUR_PER_WEEK: (" a week", " / vk"),
    Unit.EUR_PER_MONTH: (" a month", " / kk"),
    Unit.EUR_PER_YEAR: (" a year", " / v"),
}
COUNT_SUFFIX = {Unit.DAYS: (" days", " pv"), Unit.MONTHS: (" months", " kk")}


def display(value: Decimal, unit: Unit, language: str = "en") -> str:
    """`€1,234.56` / `1 234,56 €`, `€1,180.21 a month` / `1 180,21 € / kk`, `18.9%` / `18,9 %`,
    counts as integers, days and months with their unit. No plus sign."""
    negative = value < 0
    magnitude = abs(value)
    sign = "-" if negative else ""
    fi = language == "fi"
    if unit is Unit.COUNT:
        return f"{sign}{int(magnitude)}"
    if unit in COUNT_SUFFIX:
        return f"{sign}{int(magnitude)}{COUNT_SUFFIX[unit][1 if fi else 0]}"
    if unit in (Unit.PERCENT, Unit.PERCENTILE):
        text = f"{pct(magnitude):.1f}"
        return f"{sign}{text.replace('.', ',')} %" if fi else f"{sign}{text}%"
    whole, frac = f"{money(magnitude):.2f}".split(".")
    suffix = RATE_SUFFIX.get(unit, ("", ""))[1 if fi else 0]
    if fi:
        return f"{sign}{_group(whole, ' ')},{frac} €{suffix}"
    return f"{sign}€{_group(whole, ',')}.{frac}{suffix}"
