"""Period presets, edges and comparison periods. No database."""

from datetime import date

import pytest

from core.tools.models import CompareTo, PeriodArg
from core.tools.periods import PeriodOutOfRange, baseline_dates, period_label, resolve

AS_OF = date(2026, 9, 30)  # a Wednesday, the last day of a month


def dates(preset, as_of=AS_OF, **kw):
    p = resolve(PeriodArg(preset=preset, **kw), as_of).period
    return p.start, p.end


@pytest.mark.parametrize("preset, expected", [
    ("this_week", (date(2026, 9, 28), date(2026, 9, 30))),       # Monday .. as_of
    ("last_week", (date(2026, 9, 21), date(2026, 9, 27))),       # previous Mon..Sun
    ("this_month", (date(2026, 9, 1), date(2026, 9, 30))),
    ("last_month", (date(2026, 8, 1), date(2026, 8, 31))),
    ("last_3_months", (date(2026, 7, 1), date(2026, 9, 30))),    # September is complete on the 30th
    ("last_6_months", (date(2026, 4, 1), date(2026, 9, 30))),    # metrics.md section 0 window
    ("last_12_months", (date(2025, 10, 1), date(2026, 9, 30))),
    ("year_to_date", (date(2026, 1, 1), date(2026, 9, 30))),
])
def test_presets_on_month_end(preset, expected):
    assert dates(preset) == expected


@pytest.mark.parametrize("preset, expected", [
    ("this_week", (date(2026, 9, 14), date(2026, 9, 14))),       # as_of is a Monday
    ("last_week", (date(2026, 9, 7), date(2026, 9, 13))),
    ("this_month", (date(2026, 9, 1), date(2026, 9, 14))),
    ("last_month", (date(2026, 8, 1), date(2026, 8, 31))),
    ("last_3_months", (date(2026, 6, 1), date(2026, 8, 31))),    # September not complete yet
    ("last_6_months", (date(2026, 3, 1), date(2026, 8, 31))),    # metrics.md: 2026-03-01 .. 2026-08-31
])
def test_presets_mid_month_on_a_monday(preset, expected):
    assert dates(preset, as_of=date(2026, 9, 14)) == expected


def test_week_edges_sunday_and_year_turn():
    assert dates("this_week", as_of=date(2026, 9, 27)) == (date(2026, 9, 21), date(2026, 9, 27))  # Sunday
    assert dates("last_week", as_of=date(2026, 1, 1)) == (date(2025, 12, 22), date(2025, 12, 28))


def test_last_month_in_january_and_after_short_month():
    assert dates("last_month", as_of=date(2026, 1, 15)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert dates("last_month", as_of=date(2026, 3, 31)) == (date(2026, 2, 1), date(2026, 2, 28))


def test_clamped_to_data_start_and_as_of():
    r = resolve(PeriodArg(preset="last_12_months"), date(2025, 3, 31))
    assert (r.period.start, r.period.end, r.clamped) == (date(2024, 10, 1), date(2025, 3, 31), True)
    r = resolve(PeriodArg(preset="custom", start=date(2026, 9, 1), end=date(2026, 12, 31)), AS_OF)
    assert (r.period.start, r.period.end, r.clamped) == (date(2026, 9, 1), date(2026, 9, 30), True)


def test_period_entirely_after_as_of_is_refused():
    with pytest.raises(PeriodOutOfRange):
        resolve(PeriodArg(preset="custom", start=date(2026, 10, 1), end=date(2026, 10, 31)), AS_OF)


def test_custom_needs_ordered_dates_and_presets_take_none():
    with pytest.raises(ValueError):
        PeriodArg(preset="custom", start=date(2026, 9, 2), end=date(2026, 9, 1))
    with pytest.raises(ValueError):
        PeriodArg(preset="custom", start=date(2026, 9, 1))
    with pytest.raises(ValueError):
        PeriodArg(preset="last_month", start=date(2026, 9, 1))


@pytest.mark.parametrize("preset, compare, expected", [
    ("last_month", "previous_period", (date(2026, 7, 1), date(2026, 7, 31))),
    ("this_month", "previous_period", (date(2026, 8, 1), date(2026, 8, 31))),
    ("last_3_months", "previous_period", (date(2026, 4, 1), date(2026, 6, 30))),
    ("last_week", "previous_period", (date(2026, 9, 14), date(2026, 9, 20))),
    ("last_month", "same_period_last_year", (date(2025, 8, 1), date(2025, 8, 31))),
    ("year_to_date", "previous_period", (date(2025, 1, 1), date(2025, 9, 30))),
])
def test_baseline_periods(preset, compare, expected):
    arg = PeriodArg(preset=preset)
    p = resolve(arg, AS_OF).period
    assert baseline_dates(arg, p.start, p.end, CompareTo(compare)) == expected


def test_baseline_month_to_date_and_custom():
    arg = PeriodArg(preset="this_month")
    p = resolve(arg, date(2026, 9, 14)).period
    assert baseline_dates(arg, p.start, p.end, CompareTo.PREVIOUS_PERIOD) == (date(2026, 8, 1), date(2026, 8, 14))
    arg = PeriodArg(preset="custom", start=date(2026, 9, 11), end=date(2026, 9, 20))
    assert baseline_dates(arg, arg.start, arg.end, CompareTo.PREVIOUS_PERIOD) == (date(2026, 9, 1), date(2026, 9, 10))
    assert baseline_dates(arg, arg.start, arg.end, CompareTo.TYPICAL) is None


def test_labels():
    assert period_label(date(2026, 8, 1), date(2026, 8, 31)) == "August 2026"
    assert period_label(date(2026, 8, 1), date(2026, 8, 31), "fi") == "elokuu 2026"
    assert period_label(date(2026, 7, 1), date(2026, 9, 30)) == "1 Jul – 30 Sep 2026"
    assert period_label(date(2026, 7, 1), date(2026, 9, 30), "fi") == "1.7.–30.9.2026"
    assert period_label(date(2026, 9, 21), date(2026, 9, 27)) == "21–27 Sep 2026"
