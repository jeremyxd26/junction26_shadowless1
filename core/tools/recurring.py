"""Recurring series, their status, the next payday and the bills due before it. Pure logic.

Python twin, for one customer, of:
- core/metrics/01_recurring.sql: series, months present, typical amount and day, status and next
  expected date (metrics.md section 2);
- core/metrics/03_safe_to_spend.sql: next payday, salary status and the bills due after today up
  to and including payday (metrics.md section 3).
Keep the two in step; the database-backed tests compare this module with both SQL files.
"""

from __future__ import annotations

import calendar
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from core.tools.classify import window
from core.tools.db import Tx
from core.tools.periods import add_months, month_end

MIN_MONTHS = 4             # present in at least 4 of the 6 window months
MERCHANT_MAX_CV = 0.10     # a merchant series needs one stable charge a month
LATE_SALARY_DAY = 26       # late_share_12m: salary on day 26 or later
BILL_GRACE_DAYS = 7        # a bill up to 7 days past its typical day is late, later it is skipped
DAYS_PER_MONTH = Decimal("30.4375")
NO_SALARY_PAYDAY_DAYS = 30
SWEEP = "salary_sweep"
SALARY = "salary"


def series_key(t: Tx) -> str | None:
    """01_recurring.sql `keyed`: a tx_type for non-card flows, the merchant for card purchases."""
    if t.tx_type == "purchase":
        return t.merchant_id
    return t.tx_type


def percentile_disc_half(values: list[int]) -> int:
    """PostgreSQL percentile_disc(0.5): the first value whose cumulative share reaches 0.5."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.5 * len(ordered)) - 1)]


@dataclass(frozen=True)
class Series:
    kind: str                  # "tx_type" | "merchant"
    key: str
    category: str              # the category of its latest transaction
    direction: str             # "in" | "out"
    months_present: int
    tx_per_month: int
    typical_month: Decimal     # unrounded median of monthly totals (percentile_cont)
    cv_month: float | None
    typical_day: int
    last_date: date
    last_amount: Decimal
    last_tx_id: int
    n_tx_this_month: int
    paid_this_month: Decimal
    status: str                # spread | done_this_month | upcoming | late | skipped_this_month
    next_expected: date | None
    late_share_12m: Decimal | None


def _typical_dates(today: date, typical_day: int) -> tuple[date, date, date]:
    """The typical day this month and next month (clamped to the month's end), and this month's end."""
    month_start = today.replace(day=1)
    this_end = month_end(month_start)
    next_start = add_months(month_start, 1)
    next_end = month_end(next_start)
    typ_this = min(month_start + timedelta(days=typical_day - 1), this_end)
    typ_next = min(next_start + timedelta(days=typical_day - 1), next_end)
    return typ_this, typ_next, this_end


def status_and_next(today: date, direction: str, tx_per_month: int, paid_this_month: bool,
                    typical_day: int) -> tuple[str, date | None]:
    """01_recurring.sql `status` and `next_expected_date`."""
    typ_this, typ_next, this_end = _typical_dates(today, typical_day)
    if tx_per_month > 1:
        return "spread", None
    if paid_this_month:
        return "done_this_month", typ_next
    if today <= typ_this:
        return "upcoming", max(typ_this, today + timedelta(days=1))
    if direction == "in":
        return "late", max(this_end, today + timedelta(days=1))
    if (today - typ_this).days <= BILL_GRACE_DAYS:
        return "late", today + timedelta(days=1)
    return "skipped_this_month", typ_next


def detect(history: list[Tx], today: date) -> list[Series]:
    """All recurring series of one customer as of `today` (01_recurring.sql)."""
    win_start, win_end = window(today)
    month_start = today.replace(day=1)
    keyed = [(series_key(t), t) for t in history if t.tx_date <= today and series_key(t) is not None]

    monthly: dict[str, dict[tuple[int, int], list[Tx]]] = defaultdict(lambda: defaultdict(list))
    for key, t in keyed:
        if win_start <= t.tx_date <= win_end:
            monthly[key][(t.tx_date.year, t.tx_date.month)].append(t)

    by_key: dict[str, list[Tx]] = defaultdict(list)
    for key, t in keyed:
        by_key[key].append(t)

    found = []
    for key, months in monthly.items():
        n_tx = [len(ts) for ts in months.values()]
        totals = [sum((abs(t.amount_eur) for t in ts), Decimal("0")) for ts in months.values()]
        first_days = [min(t.tx_date.day for t in ts) for ts in months.values()]
        dirs = [(1 if s > 0 else -1 if s < 0 else 0)
                for s in (sum((t.amount_eur for t in ts), Decimal("0")) for ts in months.values())]
        kind = "merchant" if by_key[key][0].tx_type == "purchase" else "tx_type"
        cv = None
        if len(totals) > 1 and statistics.mean(totals) != 0:
            cv = float(statistics.stdev(totals) / statistics.mean(totals))
        if len(months) < MIN_MONTHS:
            continue
        if kind == "merchant" and not (max(n_tx) == 1 and cv is not None and cv <= MERCHANT_MAX_CV):
            continue

        direction = "in" if sum(dirs) > 0 else "out"
        tx_per_month = percentile_disc_half(n_tx)
        typical_day = percentile_disc_half(first_days)
        all_tx = by_key[key]
        last = max(all_tx, key=lambda t: (t.tx_at, t.id))
        this_month = [t for t in all_tx if month_start <= t.tx_date <= today]
        status, next_expected = status_and_next(today, direction, tx_per_month, bool(this_month), typical_day)
        late_share = None
        if key == SALARY:
            recent = [t for t in all_tx if t.tx_date > today - timedelta(days=365)]
            if recent:
                late_share = Decimal(sum(t.tx_date.day >= LATE_SALARY_DAY for t in recent)) / len(recent)
        found.append(Series(
            kind=kind, key=key, category=last.category, direction=direction,
            months_present=len(months), tx_per_month=tx_per_month,
            typical_month=statistics.median(totals), cv_month=cv, typical_day=typical_day,
            last_date=last.tx_date, last_amount=abs(last.amount_eur), last_tx_id=last.id,
            n_tx_this_month=len(this_month),
            paid_this_month=sum((abs(t.amount_eur) for t in this_month), Decimal("0")),
            status=status, next_expected=next_expected, late_share_12m=late_share,
        ))
    return sorted(found, key=lambda s: (s.direction, s.kind, s.key))


# ---- payday and bills due (03_safe_to_spend.sql) --------------------------------------------------

@dataclass(frozen=True)
class Payday:
    date: date
    salary_status: str   # received_this_month | upcoming | late | no_salary_series
    days: int            # N = payday - today, at least 1


def payday(series: list[Series], today: date) -> Payday:
    salary = next((s for s in series if s.key == SALARY), None)
    if salary is None:
        d = today + timedelta(days=NO_SALARY_PAYDAY_DAYS)
        return Payday(d, "no_salary_series", (d - today).days)
    typ_this, typ_next, this_end = _typical_dates(today, salary.typical_day)
    if salary.n_tx_this_month > 0:
        d, status = typ_next, "received_this_month"
    elif today <= typ_this:
        d, status = max(typ_this, today + timedelta(days=1)), "upcoming"
    else:
        d, status = max(this_end, today + timedelta(days=1)), "late"
    return Payday(d, status, (d - today).days)


@dataclass(frozen=True)
class BillDue:
    """One bill's term of bills_due (03_safe_to_spend.sql `bill_due` / `bills`)."""

    series: Series
    occurrences: int        # once-a-month bill: how many typical dates fall due before payday
    due_dates: tuple[date, ...]
    pro_rata_days: int      # spread bill: N days of typical_month / 30.4375; else 0

    @property
    def factor(self) -> tuple[Decimal, Decimal]:
        """(numerator, denominator) applied to the typical month."""
        if self.pro_rata_days:
            return Decimal(self.pro_rata_days), DAYS_PER_MONTH
        return Decimal(self.occurrences), Decimal(1)


def is_bill(s: Series) -> bool:
    """Bills are recurring outflows except Salary Sweep, a transfer (metrics.md 2.3)."""
    return s.direction == "out" and s.key != SWEEP


def bills_due(series: list[Series], today: date, pay: Payday) -> list[BillDue]:
    out = []
    month_start = today.replace(day=1)
    for s in series:
        if not is_bill(s):
            continue
        if s.tx_per_month > 1:
            out.append(BillDue(s, 0, (), pay.days))
            continue
        if s.tx_per_month != 1:
            continue
        due_dates = []
        for k in range(3):
            m = add_months(month_start, k)
            typical_date = min(m.replace(day=1) + timedelta(days=s.typical_day - 1), month_end(m))
            if k == 0 and s.n_tx_this_month > 0:
                continue  # already paid this month
            if typical_date > today:
                due = typical_date
            elif (today - typical_date).days <= BILL_GRACE_DAYS:
                due = today + timedelta(days=1)  # a few days late: due now
            else:
                continue  # long overdue: taken as skipped
            if due <= pay.date:
                due_dates.append(due)
        out.append(BillDue(s, len(due_dates), tuple(due_dates), 0))
    return out


def days_in_month(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]
