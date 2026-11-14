"""Period presets resolved to explicit dates, clamped to [DATA_START, as_of] (R5).

Rules (team-lead decisions for #31; metrics.md section 0 for the month windows):
- Weeks are ISO weeks, Monday to Sunday. this_week = Monday of the as_of week ... as_of;
  last_week = the Monday-to-Sunday week before it.
- this_month = the 1st of the as_of month ... as_of; last_month = the previous calendar month.
- last_N_months = the last N complete calendar months: a month counts if its last day is on or
  before as_of (metrics.md section 0). On 2026-09-30 that includes September; on 2026-09-14 it ends
  on 2026-08-31.
- year_to_date = 1 January of the as_of year ... as_of. custom = the given dates.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from core.tools import config
from core.tools.models import CompareTo, Period, PeriodArg, PeriodPreset

MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December")
MONTHS_EN_SHORT = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MONTHS_FI = ("tammikuu", "helmikuu", "maaliskuu", "huhtikuu", "toukokuu", "kesäkuu", "heinäkuu",
             "elokuu", "syyskuu", "lokakuu", "marraskuu", "joulukuu")

N_MONTHS = {
    PeriodPreset.LAST_3_MONTHS: 3,
    PeriodPreset.LAST_6_MONTHS: 6,
    PeriodPreset.LAST_12_MONTHS: 12,
}


class PeriodOutOfRange(ValueError):
    """The period has no day inside [DATA_START, as_of]. `reason` says which side it misses (#379):
    "period_before_data" (it ends before the data starts) or "period_in_future" (it starts after as_of)."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class Resolved:
    period: Period
    clamped: bool  # True if the requested dates were cut to the data range


def month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def add_months(d: date, months: int) -> date:
    """Shift by whole months; the day is clamped to the target month's length."""
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def shift_range(start: date, end: date, months: int) -> tuple[date, date]:
    """Shift a range by whole months, keeping month ends on month ends."""
    new_start = add_months(start, months)
    new_end = month_end(add_months(end, months)) if end == month_end(end) else add_months(end, months)
    return new_start, new_end


def preset_dates(arg: PeriodArg, as_of: date) -> tuple[date, date]:
    """The unclamped dates of a preset. Every preset rule lives here."""
    p = arg.preset
    if p is PeriodPreset.THIS_WEEK:
        return as_of - timedelta(days=as_of.weekday()), as_of
    if p is PeriodPreset.LAST_WEEK:
        monday = as_of - timedelta(days=as_of.weekday())
        return monday - timedelta(days=7), monday - timedelta(days=1)
    if p is PeriodPreset.THIS_MONTH:
        return as_of.replace(day=1), as_of
    if p is PeriodPreset.LAST_MONTH:
        first_this = as_of.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return last_prev.replace(day=1), last_prev
    if p in N_MONTHS:
        next_month_start = (as_of + timedelta(days=1)).replace(day=1)  # date_trunc('month', today + 1)
        return add_months(next_month_start, -N_MONTHS[p]), next_month_start - timedelta(days=1)
    if p is PeriodPreset.YEAR_TO_DATE:
        return date(as_of.year, 1, 1), as_of
    assert arg.start is not None and arg.end is not None  # validated by PeriodArg
    return arg.start, arg.end


def clamp(start: date, end: date, as_of: date) -> tuple[date, date, bool]:
    new_start, new_end = max(start, config.DATA_START), min(end, as_of)
    if new_start > new_end:
        raise PeriodOutOfRange(f"no data between {start.isoformat()} and {end.isoformat()}",
                               reason="period_before_data" if end < config.DATA_START else "period_in_future")
    return new_start, new_end, (new_start, new_end) != (start, end)


def resolve(arg: PeriodArg, as_of: date, language: str = "en") -> Resolved:
    start, end = preset_dates(arg, as_of)
    start, end, clamped = clamp(start, end, as_of)
    return Resolved(Period(start=start, end=end, label=period_label(start, end, language)), clamped)


def baseline_dates(arg: PeriodArg, start: date, end: date, compare_to: CompareTo) -> tuple[date, date] | None:
    """The comparison period for a resolved period, or None when it is not defined ("typical")."""
    if compare_to is CompareTo.SAME_PERIOD_LAST_YEAR:
        return shift_range(start, end, -12)
    if compare_to is not CompareTo.PREVIOUS_PERIOD:
        return None
    p = arg.preset
    if p in (PeriodPreset.THIS_WEEK, PeriodPreset.LAST_WEEK):
        return start - timedelta(days=7), end - timedelta(days=7)
    if p in (PeriodPreset.THIS_MONTH, PeriodPreset.LAST_MONTH):
        return shift_range(start, end, -1)
    if p in N_MONTHS:
        return shift_range(start, end, -N_MONTHS[p])
    if p is PeriodPreset.YEAR_TO_DATE:
        return shift_range(start, end, -12)
    length = (end - start).days + 1  # custom: the same number of days just before
    return start - timedelta(days=length), start - timedelta(days=1)


# ---- labels ---------------------------------------------------------------------------------------

def _is_full_month(start: date, end: date) -> bool:
    return start.day == 1 and end == month_end(start)


def period_label(start: date, end: date, language: str = "en") -> str:
    if _is_full_month(start, end):
        if language == "fi":
            return f"{MONTHS_FI[start.month - 1]} {start.year}"
        return f"{MONTHS_EN[start.month - 1]} {start.year}"
    if language == "fi":
        if start == end:
            return f"{start.day}.{start.month}.{start.year}"
        if start.year == end.year:
            if start.month == end.month:
                return f"{start.day}.–{end.day}.{end.month}.{end.year}"
            return f"{start.day}.{start.month}.–{end.day}.{end.month}.{end.year}"
        return f"{start.day}.{start.month}.{start.year}–{end.day}.{end.month}.{end.year}"
    s_mon, e_mon = MONTHS_EN_SHORT[start.month - 1], MONTHS_EN_SHORT[end.month - 1]
    if start == end:
        return f"{start.day} {s_mon} {start.year}"
    if start.year == end.year:
        if start.month == end.month:
            return f"{start.day}–{end.day} {e_mon} {end.year}"
        return f"{start.day} {s_mon} – {end.day} {e_mon} {end.year}"
    return f"{start.day} {s_mon} {start.year} – {end.day} {e_mon} {end.year}"


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())
