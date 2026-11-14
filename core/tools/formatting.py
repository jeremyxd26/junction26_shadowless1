"""Rounding and localised `display` strings for Number objects (contracts/api.md 2.1).

`display` is the one source of every display string: tools (through NumberBuilder), the evidence
endpoint and the answer-text check all call it, with the number's method id where the form depends
on it. The forms (issue #111):

| Case | English | Finnish |
|---|---|---|
| money and rates | `€1,234.56`, `€1,180.21 a month` | `1 234,56 €`, `1 180,21 € / kk` |
| percent | `18.9%` | `18,9 %` |
| percentile (rounded to a whole number) | `72nd percentile` | `72. persentiili` |
| `peer_benchmark.vs_median_pct@1` | `32.3% more`, `31.0% less`, `0.0%` | `32,3 % enemmän`, `31,0 % vähemmän` |
| count | `118`, `4,120`, a fraction with one decimal: `15.2` | `118`, `4 120`, `15,2` |
| `spender_profile.everyday_tx_month@1` | `14.2 a month` | `14,2 / kk` |
| days, months | `1 day`, `12 days`, `1 month` | `1 pv`, `12 pv`, `1 kk` |
| `user_input@1` and `bonus_estimate.share_pct@1` percent, whole | `20%` | `20 %` |

No plus sign is ever added. A negative value shows a minus, unless it rounds to zero (`€0.00`, never
`-€0.00`); a display with a direction word shows the magnitude without a minus.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from core.tools.models import Unit

CENT = Decimal("0.01")
TENTH = Decimal("0.1")
ONE = Decimal("1")

VS_MEDIAN_METHOD = "peer_benchmark.vs_median_pct@1"
PER_MONTH_COUNT_METHODS = frozenset({"spender_profile.everyday_tx_month@1"})
USER_INPUT_METHOD = "user_input@1"
# Percentages that are whole by construction and read as typed: the user's own input, and the default
# what-if share of the S-Bonus estimate (#158), which stands where a typed share would.
WHOLE_PERCENT_METHODS = frozenset({USER_INPUT_METHOD, "bonus_estimate.share_pct@1"})


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
COUNT_SUFFIX = {Unit.DAYS: ((" day", " days"), " pv"), Unit.MONTHS: ((" month", " months"), " kk")}
DIRECTION = {"more": (" more", " enemmän"), "less": (" less", " vähemmän")}
ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def ordinal_en(n: int) -> str:
    """1st, 2nd, 3rd, 4th, 11th, 12th, 13th, 21st, 22nd, 23rd, 100th, 101st, 111th."""
    suffix = "th" if 11 <= n % 100 <= 13 else ORDINAL_SUFFIX.get(n % 10, "th")
    return f"{n}{suffix}"


def _decimal(text: str, fi: bool) -> str:
    return text.replace(".", ",") if fi else text


def _count(magnitude: Decimal, fi: bool) -> str:
    """A whole count as an integer, a fraction with one decimal (half up); thousands grouped like money
    (`4,120` / `4 120`, as the contract's `card.stores` shows)."""
    text = str(int(magnitude)) if magnitude == magnitude.to_integral_value() else f"{pct(magnitude):.1f}"
    whole, _, frac = text.partition(".")
    grouped = _group(whole, " " if fi else ",")
    return f"{grouped},{frac}" if fi and frac else f"{grouped}.{frac}" if frac else grouped


def _percent(text: str, fi: bool) -> str:
    return f"{_decimal(text, fi)} %" if fi else f"{text}%"


def display(value: Decimal, unit: Unit, language: str = "en", method: str | None = None) -> str:
    """The display string of a Number with this value, unit and method (see the module docstring).

    A value that is not a Decimal goes through its shortest text first (`2.675` stays 2.675 and shows
    `€2.68`; `Decimal(2.675)` would be 2.67499…). A percentile outside 0..100 is a bug upstream and
    raises ValueError instead of showing "-1st" or "101st percentile"."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    fi = language == "fi"
    negative = value < 0
    magnitude = abs(value)

    if unit is Unit.PERCENTILE:
        n = int(magnitude.quantize(ONE, rounding=ROUND_HALF_UP))
        if (negative and n) or n > 100:
            raise ValueError(f"a percentile is between 0 and 100, not {value}")
        return f"{n}. persentiili" if fi else f"{ordinal_en(n)} percentile"

    if method == VS_MEDIAN_METHOD and unit is Unit.PERCENT:
        rounded = pct(magnitude)
        text = _percent(f"{rounded:.1f}", fi)
        if rounded == 0:
            return text
        return text + DIRECTION["less" if negative else "more"][1 if fi else 0]

    if unit is Unit.COUNT:
        text = _count(magnitude, fi)
        sign = "-" if negative and text not in ("0", "0.0", "0,0") else ""
        out = sign + text
        if method in PER_MONTH_COUNT_METHODS:
            out += " / kk" if fi else " a month"
        return out

    if unit in COUNT_SUFFIX:
        n = int(magnitude)
        sign = "-" if negative and n else ""
        en_forms, fi_suffix = COUNT_SUFFIX[unit]
        return f"{sign}{n}{fi_suffix if fi else en_forms[0 if n == 1 else 1]}"

    if unit is Unit.PERCENT:
        if method in WHOLE_PERCENT_METHODS and magnitude == magnitude.to_integral_value():
            text = str(int(magnitude))
        else:
            text = f"{pct(magnitude):.1f}"
        sign = "-" if negative and pct(magnitude) != 0 else ""
        return sign + _percent(text, fi)

    rounded = money(magnitude)
    sign = "-" if negative and rounded != 0 else ""
    whole, frac = f"{rounded:.2f}".split(".")
    suffix = RATE_SUFFIX.get(unit, ("", ""))[1 if fi else 0]
    if fi:
        return f"{sign}{_group(whole, ' ')},{frac} €{suffix}"
    return f"{sign}€{_group(whole, ',')}.{frac}{suffix}"
