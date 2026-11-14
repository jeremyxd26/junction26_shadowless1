"""get_balance_forecast (#257) without a database: the projection, its edges, the pace method, the card
against the API schema and a template answer the validator accepts."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.tools import config, evidence, forecast, recurring
from core.tools.classify import CTx
from core.tools.context import ToolContext
from core.tools.db import Tx
from core.tools.formatting import money
from core.tools.forecast import (GetBalanceForecastArgs, factors_on, first_below_zero, full_months, lowest, project,
                                 status_of)
from core.tools.safe_to_spend import NoTransactions
from core.tools.selection import Selection, select, value_of

TODAY = date(2026, 9, 30)
PAY = recurring.Payday(date(2026, 10, 15), "received_this_month", 15)


@pytest.fixture(autouse=True)
def no_review_reads(monkeypatch):
    monkeypatch.setenv("SPIKE_REVIEWS", "off")


def series(key, typical_day, typical="600.00", tx_per_month=1, n_tx_this_month=0):
    return recurring.Series(
        kind="tx_type", key=key, category="Housing", direction="out", months_present=6, tx_per_month=tx_per_month,
        typical_month=Decimal(typical), cv_month=0.0, typical_day=typical_day, last_date=date(2026, 9, 1),
        last_amount=Decimal(typical), last_tx_id=1, n_tx_this_month=n_tx_this_month, paid_this_month=Decimal(0),
        status="upcoming", next_expected=None, late_share_12m=None)


def bills_to_for(dues):
    """The bills due up to a day as the bills-due method computes them: unrounded terms, rounded once."""
    def bills_to(day):
        total = Decimal(0)
        for key, (num, den) in factors_on(dues, TODAY, day).items():
            s = next(d.series for d in dues if d.series.key == key)
            total += s.typical_month * Decimal(num) / Decimal(den)
        return money(total)
    return bills_to


def no_bills(day):
    return Decimal("0.00")


# ---- the projection -------------------------------------------------------------------------------

def test_without_bills_the_balance_falls_by_the_pace_each_day():
    days = project(TODAY, PAY.date, Decimal("1000.00"), Decimal("10.00"), no_bills)
    assert [d.date for d in days] == [TODAY + timedelta(days=k) for k in range(1, 15)]   # 1..14 Oct
    assert (days[0].balance, days[-1].balance) == (Decimal("990.00"), Decimal("860.00"))
    assert lowest(days) is days[-1] and first_below_zero(days) is None
    assert status_of(days[-1].balance, Decimal("0.00")) == "comfortable"


def test_a_bill_on_the_demo_date_is_subtracted_from_tomorrow():
    """A bill whose typical day is today and is not paid yet is due tomorrow (03's rule), so the forecast
    takes it from the first day on."""
    dues = recurring.bills_due([series("housing_payment", typical_day=30, typical="613.93")], TODAY, PAY)
    assert dues[0].due_dates == (date(2026, 10, 1),)
    days = project(TODAY, PAY.date, Decimal("1902.64"), Decimal("42.99"), bills_to_for(dues))
    assert days[0].bills == Decimal("613.93") and days[0].balance == Decimal("1245.72")
    assert days[-1].balance == Decimal("1902.64") - Decimal("613.93") - Decimal("42.99") * 14


def test_payday_tomorrow_leaves_no_day_between():
    assert project(TODAY, TODAY + timedelta(days=1), Decimal("500.00"), Decimal("10.00"), no_bills) == []
    assert lowest([]) is None and first_below_zero([]) is None


def test_the_lowest_point_on_the_first_day_and_on_the_last_day():
    dues = recurring.bills_due([series("housing_payment", typical_day=1, typical="300.00", n_tx_this_month=1)],
                               TODAY, PAY)                       # next month's date: 1 Oct
    flat = project(TODAY, PAY.date, Decimal("1000.00"), Decimal("0.00"), bills_to_for(dues))
    assert lowest(flat).date == date(2026, 10, 1)                # a tie from the first day on: the earliest
    falling = project(TODAY, PAY.date, Decimal("1000.00"), Decimal("5.00"), bills_to_for(dues))
    assert lowest(falling).date == date(2026, 10, 14)            # the day before payday


def test_the_first_day_below_zero_and_the_status():
    days = project(TODAY, PAY.date, Decimal("100.00"), Decimal("30.00"), no_bills)
    below = first_below_zero(days)
    assert below.date == date(2026, 10, 4) and below.balance == Decimal("-20.00")
    assert status_of(lowest(days).balance, Decimal("50.00")) == "below_zero"
    assert status_of(Decimal("49.99"), Decimal("50.00")) == "above_zero"
    assert status_of(Decimal("50.00"), Decimal("50.00")) == "comfortable"


def test_at_payday_the_factors_are_the_bills_due_factors():
    dues = recurring.bills_due([series("housing_payment", typical_day=3, n_tx_this_month=1),
                                series("utilities_payment", typical_day=10, typical="98.74", tx_per_month=3)],
                               TODAY, PAY)
    expected = {d.series.key: [str(d.factor[0]), str(d.factor[1])] for d in dues}
    assert factors_on(dues, TODAY, PAY.date) == expected
    assert factors_on(dues, TODAY, date(2026, 10, 2)) == {"housing_payment": ["0", "1"],
                                                         "utilities_payment": ["2", "30.4375"]}


def test_a_bill_due_on_payday_is_in_the_total_but_not_the_day_before():
    dues = recurring.bills_due([series("housing_payment", typical_day=15, typical="700.00", n_tx_this_month=1)],
                               TODAY, PAY)
    bills_to = bills_to_for(dues)
    assert dues[0].due_dates == (PAY.date,)
    assert bills_to(PAY.date - timedelta(days=1)) == Decimal("0.00") and bills_to(PAY.date) == Decimal("700.00")


def test_full_months():
    assert full_months(date(2026, 7, 1), date(2026, 9, 30)) == ["2026-07", "2026-08", "2026-09"]
    assert full_months(date(2026, 7, 15), date(2026, 9, 30)) == ["2026-08", "2026-09"]


# ---- the pace method, the selection and the formula -------------------------------------------------

def ctx_row(i, d, amount, basket="everyday_spending", tx_type="purchase", category="Groceries"):
    t = Tx(i, d, datetime.combine(d, datetime.min.time()), category, tx_type, "MRC-GRO-0001" if tx_type == "purchase"
           else None, None, Decimal(amount))
    return CTx(t, "spend", False, False, basket, None)


def test_the_daily_pace_is_the_median_of_three_monthly_daily_averages():
    rows = [ctx_row(1, date(2026, 7, 5), "-310.00"),                         # 10.00 a day in July
            ctx_row(2, date(2026, 8, 5), "-620.00", basket="regular_essentials"),   # 20.00 a day in August
            ctx_row(3, date(2026, 9, 5), "-90.00"),                          # 3.00 a day in September
            ctx_row(4, date(2026, 8, 3), "-800.00", basket="regular_essentials", tx_type="housing_payment",
                    category="Housing"),                                    # a bill: left out
            ctx_row(5, date(2026, 8, 9), "-500.00", basket="unexpected_necessities")]   # not usual spending
    sel = Selection(direction="out", start=date(2026, 7, 1), end=date(2026, 9, 30),
                    baskets=tuple(sorted(config.FORECAST_BASKETS)), series_not_in=("housing_payment",))
    value = value_of(select(rows, sel), sel, config.METHODS["daily_pace"], {"months": ["2026-07", "2026-08", "2026-09"]})
    assert value == Decimal("10.00")


def test_series_not_in_is_in_the_spec_only_when_set():
    plain = Selection(direction="out", start=TODAY, end=TODAY)
    assert "series_not_in" not in plain.to_spec()                 # other numbers keep their refs
    sel = Selection(direction="out", start=TODAY, end=TODAY, series_not_in=("housing_payment",))
    assert sel.to_spec()["series_not_in"] == ["housing_payment"]
    assert Selection.from_spec(sel.to_spec()) == sel and Selection.from_spec(plain.to_spec()) == plain


def test_the_forecast_formula():
    values = {"balance": Decimal("1000.00"), "bills": Decimal("100.50"), "pace": Decimal("10.25")}
    assert evidence.compute_formula("balance_forecast", values, {"days": 3}) == Decimal("868.75")
    assert evidence.FORMULAS["balance_forecast"] == ("balance", "bills", "pace")


# ---- the tool's edges --------------------------------------------------------------------------------

def test_no_transactions_or_no_balance_gives_a_note_and_no_card(monkeypatch):
    def none(ctx):
        raise NoTransactions("no transactions")

    for fake in (none, lambda ctx: ({}, {"balance_eur": None})):
        monkeypatch.setattr(forecast, "metric_row", fake)
        result = forecast.get_balance_forecast(ToolContext(customer_id="CUST00860", as_of=TODAY, conn=None), {})
        assert result.card is None and result.data is None and result.evidence == []
        assert result.model_view["status"] == "no_data" and "cannot be estimated" in result.notes[0]


def test_the_arguments_take_nothing():
    GetBalanceForecastArgs.model_validate({})
    with pytest.raises(ValidationError):
        GetBalanceForecastArgs.model_validate({"customer_id": "CUST00001"})


# ---- a whole run on a synthetic customer: the card, the model view, a template answer --------------

def tx(i, d, category, amount, tx_type="purchase", merchant=None, mcc=None):
    return Tx(i, d, datetime.combine(d, datetime.min.time()), category, tx_type, merchant, mcc, Decimal(amount))


def synthetic_history():
    """Salary on the 15th, rent on the 6th, utilities three times a month, groceries every other day."""
    h, i = [], 0
    for m in range(4, 10):
        for d, cat, amount, kind in ((15, "Salary", "2500.00", "salary"), (6, "Housing", "-613.93", "housing_payment"),
                                     (5, "Utilities", "-30.00", "utilities_payment"),
                                     (15, "Utilities", "-35.00", "utilities_payment"),
                                     (25, "Utilities", "-33.74", "utilities_payment")):
            i += 1
            h.append(tx(i, date(2026, m, d), cat, amount, kind))
        for d in range(1, 29, 2):
            i += 1
            h.append(tx(i, date(2026, m, d), "Groceries", "-40.00", merchant="MRC-GRO-0001", mcc="5411"))
    return sorted(h, key=lambda t: (t.tx_date, t.id))


@pytest.mark.parametrize("lang", ["en", "fi"])
def test_a_whole_run_gives_a_breakdown_card_and_an_answer_the_validator_accepts(monkeypatch, lang):
    from core.agent import template, validator
    from core.app.api.schemas import BreakdownCard
    from core.tools import labels
    from core.tools.classify import classify
    from core.tools.numbers import NumberBuilder

    history = synthetic_history()
    probe = ToolContext(customer_id="CUST00849", as_of=TODAY, conn=None)
    probe._history = history
    bills_total = recurring.bills_due_numbers(
        probe, NumberBuilder(probe, classify(history, TODAY, labels.for_context(probe)))).total_value
    monkeypatch.setattr(forecast, "metric_row", lambda ctx: ({"cushion_eur": "50"},
                                                             {"balance_eur": "900.00", "bills_due_eur": str(bills_total)}))
    monkeypatch.setattr(evidence, "write", lambda conn, specs: None)   # no database
    ctx = ToolContext(customer_id="CUST00849", as_of=TODAY, conn=None, language=lang)
    ctx._history = history
    result = forecast.get_balance_forecast(ctx, {})
    data, card, view = result.data, result.card, result.model_view

    assert data.status == "below_zero" and data.first_below_zero_date is not None
    assert data.bills_until_payday.value == float(bills_total)
    BreakdownCard.model_validate(card.model_dump(mode="json"))       # the contract's breakdown card
    items = card.model_dump(mode="json")["items"]
    assert [i["key"] for i in items] == sorted(i["key"] for i in items) and "regular_essentials" not in str(items)
    assert items[0]["amount"]["value"] == 900.0 and card.total.id == data.lowest.id
    assert card.estimate and data.daily_pace.display in card.estimate.text
    assert [a.type for a in card.actions] == ["open_evidence", "ask"]   # below zero: the what-if question
    assert "evidence_ref" not in str(view) and "CUST" not in str(view)
    assert list(view).index("lowest_balance") < list(view).index("balance_now")   # the lowest point leads

    numbers = list(ctx.numbers.all().values())
    allowed = validator.allowed_from(numbers, [view], TODAY)
    draft = template.template_draft([view], [], lang, allowed)
    assert draft["cited"][0] == data.lowest.id                       # the answer leads with the lowest point
    assert validator.check_text(draft["text"], allowed) == []
    assert any(str(data.first_below_zero_date.day) in s for s in result.notes)   # the date said plainly


def test_payday_tomorrow_with_a_negative_balance_is_below_zero_today(monkeypatch):
    """Review of #337: no day lies before payday, so the first day below zero is today (no crash)."""
    from core.tools import labels
    from core.tools.classify import classify
    from core.tools.numbers import NumberBuilder

    today = date(2026, 10, 14)                    # salary on the 15th, not yet paid: payday tomorrow
    history = synthetic_history()
    probe = ToolContext(customer_id="CUST00849", as_of=today, conn=None)
    probe._history = history
    bills_total = recurring.bills_due_numbers(
        probe, NumberBuilder(probe, classify(history, today, labels.for_context(probe)))).total_value
    monkeypatch.setattr(forecast, "metric_row", lambda ctx: ({}, {"balance_eur": "-50.00", "bills_due_eur": str(bills_total)}))
    monkeypatch.setattr(evidence, "write", lambda conn, specs: None)
    for lang in ("en", "fi"):
        ctx = ToolContext(customer_id="CUST00849", as_of=today, conn=None, language=lang)
        ctx._history = history
        result = forecast.get_balance_forecast(ctx, {})
        data = result.data
        assert data.next_payday == date(2026, 10, 15) and data.steps[-1].date == today and len(data.steps) == 1
        assert data.status == "below_zero" and data.first_below_zero_date == today
        assert data.lowest.value == data.day_before_payday.value == data.balance_now.value == -50.0
        assert any(("14 Oct 2026" if lang == "en" else "14.10.2026") in note for note in result.notes)


def test_the_lowest_point_recomputed_by_hand(monkeypatch):
    """The synthetic customer's lowest point from its own amounts, without the tool's helpers: rent
    613.93 on 6 Oct, utilities 98.74 a month spread (x 14 / 30.4375), groceries 14 x 40.00 a month
    (median daily average of July, August, September = 560 / 31), 14 days to 14 Oct."""
    from core.tools import labels
    from core.tools.classify import classify
    from core.tools.numbers import NumberBuilder

    history = synthetic_history()
    probe = ToolContext(customer_id="CUST00849", as_of=TODAY, conn=None)
    probe._history = history
    bills_total = recurring.bills_due_numbers(
        probe, NumberBuilder(probe, classify(history, TODAY, labels.for_context(probe)))).total_value
    monkeypatch.setattr(forecast, "metric_row", lambda ctx: ({}, {"balance_eur": "900.00", "bills_due_eur": str(bills_total)}))
    monkeypatch.setattr(evidence, "write", lambda conn, specs: None)
    ctx = ToolContext(customer_id="CUST00849", as_of=TODAY, conn=None)
    ctx._history = history
    data = forecast.get_balance_forecast(ctx, {}).data

    pace = money(Decimal(560) / 31)                                               # 18.06
    bills_by_14_oct = money(Decimal("613.93") + Decimal("98.74") * 14 / Decimal("30.4375"))   # 659.35
    lowest_by_hand = Decimal("900.00") - bills_by_14_oct - pace * 14              # -12.19
    assert (data.daily_pace.value, data.lowest.value) == (float(pace), float(lowest_by_hand))
    assert data.lowest_date == data.first_below_zero_date == date(2026, 10, 14)
    assert data.bills_until_payday.value == float(money(Decimal("613.93") + Decimal("98.74") * 15 / Decimal("30.4375")))
