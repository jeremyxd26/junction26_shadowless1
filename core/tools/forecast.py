"""get_balance_forecast: "Will my money last until payday?" (#257, metrics.md section 3.3).

Today's balance, minus the bills that safe to spend counts before payday, each on its expected date,
minus a usual daily spending pace, for every day after today and before payday. An estimate (R13).

Inputs, each a finished Number with evidence:
- the balance: `safe_to_spend.balance_eur@1`, read from the row of 03_safe_to_spend.sql exactly as the
  hero reads it (same spec, so the same ref): the latest balance_after of the customer's account;
- the bills: recurring.bills_due_numbers, the one path of the hero and the bills card, so the total
  `safe_to_spend.bills_due_eur@1` is the hero's own (same ref). For one day, the bills due after today
  up to that day (`balance_forecast.bills_to_date_eur@1`) are the same terms with the factors of those
  days: a once-a-month bill counts on each of its due dates up to the day, a bill paid several times a
  month counts typical month x days / 30.4375. At payday they equal the hero's total (checked);
- the daily pace (`balance_forecast.daily_pace_eur@1`), the one labelled estimate: everyday spending and
  regular essentials, the hero's bill series left out, per day in each of the last three full months
  (metrics.md section 0); the median of the three daily averages.

Outputs (`balance_forecast.balance_eur@1`, composite `balance_forecast`: balance - bills by that day -
pace x days): the balance on the card's days. The lowest projected balance (the earliest day on a tie),
the first day below zero and the day before payday all come from one projection. With outflows only,
the lowest point is the day before payday unless the pace is zero. Bills due on payday itself are in
the hero's total but not in the balance the day before.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel

from core.tools import aliases, config, evidence, labels, metric_sql, periods, recurring
from core.tools.classify import classify, window
from core.tools.context import ToolContext
from core.tools.models import Action, Args, Card, Estimate, Number, Period, PeriodArg, ToolResult, Unit, assumption
from core.tools.numbers import NumberBuilder, model_number
from core.tools.periods import MONTHS_EN_SHORT, add_months, month_end, month_key
from core.tools.safe_to_spend import BillsDueMismatch, NoTransactions, metric_row
from core.tools.selection import Selection, select, value_of

TOOL = "get_balance_forecast"
BALANCE_METHOD = "safe_to_spend.balance_eur@1"   # the hero's balance: 03's balance_eur column
Status = Literal["comfortable", "above_zero", "below_zero"]
Kind = Literal["today", "bills", "below_zero", "lowest", "day_before_payday"]


class GetBalanceForecastArgs(Args):
    """No arguments: the customer, today and payday come from the server-bound context."""


# ---- pure projection ------------------------------------------------------------------------------

@dataclass(frozen=True)
class Day:
    date: date
    days: int          # days after today
    bills: Decimal     # the bills due after today up to this day, rounded once
    balance: Decimal   # balance - bills - pace x days, cents


def project(today: date, payday: date, balance: Decimal, pace: Decimal,
            bills_to: Callable[[date], Decimal]) -> list[Day]:
    """Every day after today and before payday (none when payday is tomorrow), computed from the
    rounded parts with the composite formula itself, so the evidence of each day reconciles."""
    out = []
    for k in range(1, (payday - today).days):
        d = today + timedelta(days=k)
        bills = bills_to(d)
        value = evidence.compute_formula("balance_forecast", {"balance": balance, "bills": bills, "pace": pace},
                                         {"days": k})
        out.append(Day(d, k, bills, value))
    return out


def lowest(days: list[Day]) -> Day | None:
    """The lowest projected balance, the earliest day on a tie; None without days."""
    return min(days, key=lambda d: (d.balance, d.date), default=None)


def first_below_zero(days: list[Day]) -> Day | None:
    return next((d for d in days if d.balance < 0), None)


def factors_on(dues: list[recurring.BillDue], today: date, day: date) -> dict[str, list[str]]:
    """The bills-due factors of the days after today up to `day`, by series key, in the form of
    recurring.bills_due_numbers: a once-a-month bill counts its due dates up to the day, a bill paid
    several times a month the days so far over 30.4375. At payday these are the hero's factors."""
    k = (day - today).days
    out = {}
    for due in dues:
        if due.pro_rata_days:
            num, den = Decimal(min(k, due.pro_rata_days)), recurring.DAYS_PER_MONTH
        else:
            num, den = Decimal(sum(1 for d in due.due_dates if d <= day)), Decimal(1)
        out[due.series.key] = [str(num), str(den)]
    return dict(sorted(out.items()))


def status_of(lowest_balance: Decimal, bills_until_payday: Decimal) -> Status:
    """below_zero when the lowest point is under zero; comfortable when it still covers the bills due
    before payday once more; above_zero in between."""
    if lowest_balance < 0:
        return "below_zero"
    if lowest_balance >= bills_until_payday:
        return "comfortable"
    return "above_zero"


def full_months(start: date, end: date) -> list[str]:
    """The month keys of the calendar months that lie wholly in start..end."""
    out, m = [], start.replace(day=1)
    while m <= end:
        if m >= start and month_end(m) <= end:
            out.append(month_key(m))
        m = add_months(m, 1)
    return out


# ---- the tool -------------------------------------------------------------------------------------

class Step(BaseModel):
    date: date
    kinds: list[Kind]
    label: str           # card text: the short date and what happens that day (it has digits)
    balance: Number


class BalanceForecastData(BaseModel):
    status: Status
    today: date
    next_payday: date
    salary_status: Literal["received_this_month", "upcoming", "late", "no_salary_series"]
    balance_now: Number
    bills_until_payday: Number
    daily_pace: Number
    lowest: Number
    lowest_date: date
    day_before_payday: Number
    first_below_zero: Number | None
    first_below_zero_date: date | None
    steps: list[Step]


def _t(key: str, language: str, **kw: Any) -> str:
    return config.label(config.FORECAST_TEXT[key], language).format(**kw)


def _short(d: date, language: str) -> str:
    return f"{d.day}.{d.month}." if language == "fi" else f"{d.day} {MONTHS_EN_SHORT[d.month - 1]}"


def _day_period(d: date, language: str) -> Period:
    return Period(start=d, end=d, label=periods.period_label(d, d, language))


def _series_label(s: recurring.Series, alias_map: aliases.AliasMap, language: str) -> str:
    """A bill's name as the bills card shows it: an alias for a merchant, never the merchant id."""
    if s.kind == "merchant":
        return alias_map.for_merchant(s.key).label(language)
    return config.label(config.SERIES_LABELS.get(s.key, (s.key, s.key)), language)


def _no_data(language: str) -> ToolResult:
    """No transactions, or no balance to start from: no card and no number, the note says why."""
    note = _t("note_no_data", language)
    return ToolResult(tool=TOOL, data=None, card=None, notes=[note], evidence=[],
                      model_view={"tool": TOOL, "kind": "estimate", "status": "no_data", "notes": [note]})


class NoForecast(Exception):
    """No transactions, or no balance to start from: there is no forecast."""


@dataclass
class Projection:
    """One forecast: its inputs, each a finished Number, and every day after today and before payday. The
    forecast tool and the bill explanation (#421) build the Number of a day through it, so a day has one
    Number and one evidence ref whoever asks. The specs it builds are in `nb.specs`; the caller writes them."""

    language: str
    today: date
    pay: recurring.Payday
    due: recurring.BillsDueNumbers
    dues: list[recurring.BillDue]
    balance: Number
    balance_value: Decimal
    pace: Number
    pace_value: Decimal
    sel_bills: Selection
    nb: NumberBuilder
    days: list[Day]
    history: list

    @property
    def by_date(self) -> dict[date, Day]:
        return {d.date: d for d in self.days}

    def bills_by(self, day: date, label: str, series_keys: tuple[str, ...] | None = None) -> tuple[Number, Decimal]:
        """The bills due after today up to `day` (`balance_forecast.bills_to_date_eur@1`): all the hero's bills,
        or only the given series, with the factors of those days."""
        span = Period(start=self.today + timedelta(days=1), end=day,
                      label=periods.period_label(self.today + timedelta(days=1), day, self.language))
        factors, sel = factors_on(self.dues, self.today, day), self.sel_bills
        if series_keys is not None:
            factors = {k: v for k, v in factors.items() if k in series_keys}
            sel = replace(sel, series_keys=tuple(sorted(series_keys)))
        return self.nb.transactions(sel, config.METHODS["bills_to_date"], span, label,
                                    params={"factors": factors, "period": evidence.period_param(span)})

    def balance_on(self, day: Day, label: str) -> Number:
        """The projected balance on one day (`balance_forecast.balance_eur@1`), with its evidence."""
        bills = self.bills_by(day.date, _t("bills_to_date", self.language))
        day_period = _day_period(day.date, self.language)
        number, value = self.nb.composite(
            config.FORECAST_BALANCE_METHOD, "balance_forecast",
            {"balance": (self.balance, self.balance_value), "bills": bills, "pace": (self.pace, self.pace_value)},
            Unit.EUR, day_period, label, params={"days": day.days, "period": evidence.period_param(day_period)})
        if value != day.balance:
            raise RuntimeError("a forecast day's evidence differs from the projection")
        return number


def projection(ctx: ToolContext) -> Projection:
    """The forecast's inputs and days for the server-bound customer and today. NoForecast without
    transactions or a balance; BillsDueMismatch when the bills due of the two paths differ (as the hero)."""
    lang = ctx.language
    today = ctx.as_of
    try:
        settings, row = metric_row(ctx)   # the hero's row of 03, read once per request
    except NoTransactions:
        raise NoForecast("no transactions up to as_of for this customer") from None
    if row.get("balance_eur") is None:
        raise NoForecast("no balance to start from")

    history = ctx.history()
    rows = classify(history, today, labels.for_context(ctx))
    nb = NumberBuilder(ctx, rows)
    series = recurring.detect(history, today)
    pay = recurring.payday(series, today)
    due = recurring.bills_due_numbers(ctx, nb, series=series, pay=pay)   # the hero's bills, same refs
    if due.total_value != metric_sql.decimal(row["bills_due_eur"]):
        raise BillsDueMismatch("bills due of core.tools.recurring and 03_safe_to_spend.sql differ for one customer")
    dues = [bill_due for _, bill_due, _, _ in due.items]
    bill_keys = tuple(sorted(bill_due.series.key for bill_due in dues))

    # The balance: the hero's Number (same spec as get_safe_to_spend, so the same evidence ref).
    today_period = _day_period(today, lang)
    balance_value = metric_sql.decimal(row["balance_eur"])
    balance_spec = evidence.metric_spec(ctx.customer_id, today, BALANCE_METHOD, config.SAFE_TO_SPEND_FILE,
                                        "balance_eur", settings, balance_value, evidence.period_param(today_period))
    balance = nb.number(balance_value, Unit.EUR, today_period, BALANCE_METHOD, balance_spec, _t("balance_now", lang))

    # The daily pace: everyday spending and essentials without the bills, last three full months.
    window3 = periods.resolve(PeriodArg(preset="last_3_months"), today, lang).period
    sel_pace = Selection(direction="out", start=window3.start, end=window3.end,
                         baskets=tuple(sorted(config.FORECAST_BASKETS)), series_not_in=bill_keys)
    pace, pace_value = nb.transactions(sel_pace, config.METHODS["daily_pace"], window3, _t("daily_pace", lang),
                                       params={"months": full_months(window3.start, window3.end)})

    # The bills due after today up to a day: the hero's terms with the factors of those days.
    win_start, win_end = window(today)
    sel_bills = Selection(direction="out", start=win_start, end=win_end, series_keys=bill_keys)
    bill_rows = select(rows, sel_bills)

    def bills_to(day: date) -> Decimal:
        return value_of(bill_rows, sel_bills, config.METHODS["bills_to_date"],
                        {"factors": factors_on(dues, today, day)})

    if bills_to(pay.date) != due.total_value:
        raise RuntimeError("the forecast's bills up to payday differ from the bills due before payday")

    days = project(today, pay.date, balance_value, pace_value, bills_to)
    return Projection(lang, today, pay, due, dues, balance, balance_value, pace, pace_value, sel_bills, nb, days,
                      history)


def get_balance_forecast(ctx: ToolContext, args: GetBalanceForecastArgs | dict | None = None) -> ToolResult:
    if not isinstance(args, GetBalanceForecastArgs):
        GetBalanceForecastArgs.model_validate(args or {})
    lang = ctx.language
    try:
        p = projection(ctx)
    except NoForecast:
        return _no_data(lang)
    today, pay, due, dues, days, nb = p.today, p.pay, p.due, p.dues, p.days, p.nb
    balance, balance_value, pace, history = p.balance, p.balance_value, p.pace, p.history
    by_date = p.by_date
    reg = ctx.numbers.register
    balance_on = p.balance_on

    # The card's days: today, each day a once-a-month bill falls due, the first day below zero, the
    # lowest point and the day before payday; one row per day.
    low, below = lowest(days), first_below_zero(days)
    last = days[-1] if days else None
    alias_map = aliases.build(history, today)
    kinds: dict[date, list[Kind]] = {today: ["today"]}
    bills_on: dict[date, list[str]] = {}
    for bill_due in dues:
        for d in bill_due.due_dates:
            if d in by_date:
                kinds.setdefault(d, []).append("bills")
                bills_on.setdefault(d, []).append(_series_label(bill_due.series, alias_map, lang))
    for kind, day in (("below_zero", below), ("lowest", low), ("day_before_payday", last)):
        if day is not None:
            kinds.setdefault(day.date, []).append(kind)

    numbers: dict[date, Number] = {today: balance}
    steps = []
    for d in sorted(kinds):
        ks = list(dict.fromkeys(kinds[d]))
        if d != today:
            when = periods.period_label(d, d, lang)
            if "lowest" in ks:
                key = "lowest_day_before_payday" if "day_before_payday" in ks else "lowest"
            elif "below_zero" in ks:
                key = "below_zero"
            elif "day_before_payday" in ks:
                key = "day_before_payday"
            else:
                key = "after_bills"
            numbers[d] = balance_on(by_date[d], _t(key, lang, date=when))
        parts = [_t("row_today", lang)] if "today" in ks else []
        if "bills" in ks:
            parts.append(_t("row_bills", lang, bills=", ".join(dict.fromkeys(bills_on[d]))))
        parts += [_t(f"row_{k}", lang) for k in ("below_zero", "lowest", "day_before_payday") if k in ks]
        steps.append((d, ks, f"{_short(d, lang)} · {', '.join(parts)}"))

    # Ids follow the card: the lowest point (the headline) first, then the rows, the pace, the bills.
    lowest_date = low.date if low is not None else today
    registered = {lowest_date: reg(numbers[lowest_date])}
    for d, _, _ in steps:
        registered.setdefault(d, reg(numbers[d]))
    pace_n, bills_n, balance_n = reg(pace), reg(due.total), registered[today]
    status = status_of(low.balance if low is not None else balance_value, due.total_value)
    # With no day before payday (payday tomorrow) a negative balance is below zero today.
    below_date = below.date if below is not None else (today if balance_value < 0 else None)

    notes = []
    if pay.salary_status == "no_salary_series":
        notes.append(_t("note_no_salary", lang))
    elif pay.salary_status == "late":
        notes.append(_t("note_late_salary", lang))
    if status == "below_zero":
        notes.append(_t("note_below_zero", lang, date=periods.period_label(below_date, below_date, lang)))
    else:
        notes.append(_t(f"note_{status}", lang))
    if any(pay.date in bill_due.due_dates for bill_due in dues):
        notes.append(_t("note_payday_bills", lang))
    notes.append(_t("note_estimate", lang))

    data = BalanceForecastData(
        status=status, today=today, next_payday=pay.date, salary_status=pay.salary_status,
        balance_now=balance_n, bills_until_payday=bills_n, daily_pace=pace_n,
        lowest=registered[lowest_date], lowest_date=lowest_date,
        day_before_payday=registered[last.date] if last is not None else balance_n,
        first_below_zero=registered[below_date] if below_date is not None else None,
        first_below_zero_date=below_date,
        steps=[Step(date=d, kinds=ks, label=label, balance=registered[d]) for d, ks, label in steps],
    )
    evidence.write(ctx.conn, nb.specs)
    return ToolResult(tool=TOOL, data=data, card=_card(data, lang), notes=notes, evidence=list(nb.specs),
                      model_view=_model_view(data, due.due_period, notes))


def _card(data: BalanceForecastData, language: str) -> Card:
    ref = data.lowest.evidence_ref
    actions = [Action(type="open_evidence", label=_t("how", language), evidence_ref=ref)]
    if data.status != "comfortable":   # below zero, or little to spare: try a cut (the what-if flow)
        actions.append(Action(type="ask", label=_t("whatif_label", language), prompt=_t("whatif_prompt", language)))
    return Card(
        card_id="card_" + hashlib.sha256(f"{TOOL}|{ref}".encode()).hexdigest()[:12],
        type="breakdown", title=_t("title", language),
        subtitle=periods.period_label(data.today, data.next_payday - timedelta(days=1), language)
        if data.next_payday - data.today > timedelta(days=1) else periods.period_label(data.today, data.today, language),
        evidence_ref=ref,
        # #380: observed are today's balance and the bills until payday; assumed are the usual daily pace, the
        # bills' usual days and no money coming in before payday
        estimate=Estimate(label=_t("estimate_label", language),
                          text=_t("estimate_text", language, pace=data.daily_pace.display),
                          observed=[data.balance_now, data.bills_until_payday],
                          assumptions=[assumption("forecast.spending_as_usual", language, data.daily_pace),
                                       assumption("forecast.bills_on_usual_days", language),
                                       assumption("forecast.no_income_before_payday", language)]),
        actions=actions,
        display_hint="time_series",
        total=data.lowest,
        comparison=None,
        items=[{"key": s.date.isoformat(), "label": s.label, "amount": s.balance.model_dump(), "share": None,
                "change": None, "flags": []} for s in data.steps],
    )


def _model_view(data: BalanceForecastData, until_payday: Period, notes: list[str]) -> dict[str, Any]:
    """For the model: the lowest point first, then the other summary numbers; dates as ISO fields. No
    rows, refs, merchant ids or customer id (R3); the days of the card stay on the card."""
    distinct = {data.lowest.id}

    def once(n: Number | None) -> dict[str, Any] | None:
        if n is None or n.id in distinct:
            return None
        distinct.add(n.id)
        return model_number(n)

    return {
        "tool": TOOL,
        "kind": "estimate",
        "period": until_payday.label,
        "status": data.status,
        "lowest_balance": model_number(data.lowest),
        "first_below_zero": once(data.first_below_zero),
        "day_before_payday": once(data.day_before_payday),
        "balance_now": once(data.balance_now),
        "bills_until_payday": model_number(data.bills_until_payday),
        "daily_pace": model_number(data.daily_pace),
        "today": data.today.isoformat(),
        "next_payday": data.next_payday.isoformat(),
        "lowest_date": data.lowest_date.isoformat(),
        "first_below_zero_date": data.first_below_zero_date.isoformat() if data.first_below_zero_date else None,
        "salary_status": data.salary_status,
        "notes": list(notes),
    }
