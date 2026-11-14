"""The forecast on the bill's due date without a database (#421): the four statuses, the edges of the forecast
window (today, the day before payday, payday, a past date, payday tomorrow), a due date on a weekend, a matched
bill the forecast already counts (never subtracted twice), the chip and the draft, and a forecast that cannot
be computed."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from core.agent.model import PlanInput
from core.agent.rules import RuleModel
from core.tools import bill_explain as be
from core.tools import config
from core.tools.forecast import Day
from core.tools.models import Number, Period, Unit
from core.tools.safe_to_spend import BillsDueMismatch
from core.tools.tests.test_bill_explain_pure import AS_OF, barcode, explain, fake, fields_bill  # noqa: F401
from core.tools.formatting import display

PAYDAY = date(2026, 10, 15)


def eur(value: str, ref: str, method: str, period: Period, lang: str = "en") -> Number:
    return Number(value=float(value), unit=Unit.EUR, period=period, method=method, evidence_ref=ref, label="x",
                  display=display(Decimal(value), Unit.EUR, lang, method))


class Projection:
    """A forecast like forecast.projection's: a balance now, a pace a day and, for the matched series, what the
    forecast subtracts by each day (housing on its expected day; nothing else, to keep the arithmetic plain)."""

    def __init__(self, balance="1640.15", pace="28.40", housing_day=date(2026, 10, 1), housing="836.65",
                 today=AS_OF, payday=PAYDAY, lang="en"):
        self.today, self.lang = today, lang
        self.pay = SimpleNamespace(date=payday)
        self.balance_value, self.pace_value = Decimal(balance), Decimal(pace)
        self.housing_day, self.housing = housing_day, Decimal(housing)
        self.balance = eur(balance, "ev_fc_balance", "safe_to_spend.balance_eur@1",
                           Period(start=today, end=today, label="today"), lang)
        self.dues = [SimpleNamespace(series=SimpleNamespace(kind="tx_type", key="housing_payment"))]
        self.nb = SimpleNamespace(specs={"ev_fc_spec": {"kind": "test"}})
        self.days = []
        for k in range(1, (payday - today).days):
            d = today + timedelta(days=k)
            bills = self.housing if d >= housing_day else Decimal("0")
            self.days.append(Day(d, k, bills, self.balance_value - bills - self.pace_value * k))
        self.asked = []

    @property
    def by_date(self):
        return {d.date: d for d in self.days}

    def balance_on(self, day: Day, label: str) -> Number:
        self.asked.append(day.date)
        return eur(f"{day.balance:.2f}", f"ev_fc_{day.date:%m%d}", "balance_forecast.balance_eur@1",
                   Period(start=day.date, end=day.date, label=str(day.date)), self.lang)

    def bills_by(self, day: date, label: str, series_keys=None):
        value = self.housing if day >= self.housing_day else Decimal("0")
        n = eur(f"{value:.2f}", f"ev_fc_bills_{day:%m%d}", "balance_forecast.bills_to_date_eur@1",
                Period(start=self.today + timedelta(days=1), end=day, label="span"), self.lang)
        return n, value


ROW = {"free_until_payday_eur": Decimal("12441.31"), "balance_limit_7d_eur": Decimal("5806.08")}   # 03 with a bill


def with_forecast(fake, **kw) -> Projection:  # noqa: F811
    p = Projection(**kw)
    fake.projection = lambda ctx: p
    fake.row = ROW
    return p


def unknown(amount: str, due: date):
    return fields_bill(amount=amount, due=due)


# ---- the four statuses -----------------------------------------------------------------------------------

def test_covered_takes_the_forecasts_own_number_for_the_due_date(fake):  # noqa: F811
    p = with_forecast(fake)
    out = explain(unknown("145.00", date(2026, 10, 10)))["forecast"]
    day = p.by_date[date(2026, 10, 10)]
    assert out["status"] == "covered" and p.asked == [date(2026, 10, 10)]
    assert out["before"]["evidence_ref"] == "ev_fc_1010" and out["before"]["value"] == float(day.balance)
    assert out["already_counted"] is None and out["counted"]["method"] == "user_input@1"    # the whole bill
    assert out["after"]["value"] == float(day.balance - Decimal("145.00"))
    assert out["after"]["method"] == "bill.forecast_after_eur@1" and out["shortfall"] is None and out["chip"] is None
    assert out["text"] == f"Your forecast balance on 10 Oct 2026 covers this bill: {out['after']['display']} would be left after it."


def test_tight_below_the_margin(fake):  # noqa: F811
    p = with_forecast(fake)
    before = p.by_date[date(2026, 10, 10)].balance
    amount = before - config.BILL_FORECAST_MARGIN_EUR + Decimal("0.01")       # leaves 99.99
    out = explain(unknown(f"{amount:.2f}", date(2026, 10, 10)))["forecast"]
    assert out["status"] == "tight" and out["after"]["value"] == 99.99
    assert out["text"] == "Your forecast balance on 10 Oct 2026 covers this bill, but only €99.99 would be left after it."


@pytest.mark.parametrize("after,status", [("-0.01", "not_covered"), ("0.00", "tight"), ("99.99", "tight"),
                                          ("100.00", "covered")])
def test_the_status_boundaries(after, status):
    assert be.forecast_status(Decimal(after)) == status


def test_not_covered_names_the_shortfall_and_the_date_and_offers_the_forecast(fake):  # noqa: F811
    p = with_forecast(fake)
    before = p.by_date[date(2026, 10, 10)].balance
    out = explain(unknown(f"{before + Decimal('50.00'):.2f}", date(2026, 10, 10)))
    fc = out["forecast"]
    assert fc["status"] == "not_covered" and fc["after"]["value"] == -50.0
    assert fc["shortfall"]["value"] == 50.0 and fc["shortfall"]["method"] == "bill.forecast_shortfall_eur@1"
    assert fc["text"] == "Your forecast balance on 10 Oct 2026 does not cover this bill: it is €50.00 short."
    assert fc["chip"] == {"type": "ask", "label": "See your balance forecast", "prompt": "Will my money last until payday?"}
    # the status never removes the draft (decision 3)
    assert [a["type"] for a in out["actions"]][0] == "add_to_payments"   # contact_bank (#453) may follow


@pytest.mark.parametrize("lang", ["en", "fi"])
def test_the_texts_never_suggest_borrowing(fake, lang):  # noqa: F811
    """#419: no loan, credit, instalment or overdraft in any forecast sentence."""
    banned = ("loan", "credit", "instalment", "installment", "overdraft", "borrow", "laina", "luotto", "osamaksu",
              "tililimiitti", "lainaa")
    keys = [k for k in config.BILL_TEXT if k.startswith("forecast_")]
    assert {"forecast_covered", "forecast_tight", "forecast_not_covered", "forecast_beyond", "forecast_past"} <= set(keys)
    for key in keys:
        text = config.label(config.BILL_TEXT[key], lang).lower()
        assert not any(word in text for word in banned), key


@pytest.mark.parametrize("prompt,lang", [(config.BILL_TEXT["forecast_prompt"][0], "en"),
                                         (config.BILL_TEXT["forecast_prompt"][1], "fi")])
def test_the_chip_asks_the_forecast_question_the_rules_know(prompt, lang):
    tools = ["get_balance_forecast", "get_safe_to_spend", "get_recurring_bills", "get_spending"]
    request = PlanInput(question=prompt, language=lang, as_of=AS_OF.isoformat(),
                        tools=[{"name": t, "description": "", "parameters_json_schema": {}} for t in tools])
    result = RuleModel().plan(request)
    assert result.recognised and [c.name for c in result.calls][0] == "get_balance_forecast"


# ---- the forecast window ---------------------------------------------------------------------------------

def test_due_today_takes_the_balance_now(fake):  # noqa: F811
    p = with_forecast(fake)
    out = explain(unknown("145.00", AS_OF))["forecast"]
    assert out["before"]["evidence_ref"] == "ev_fc_balance" and p.asked == []
    assert out["after"]["value"] == 1640.15 - 145.0


def test_the_day_before_payday_is_inside_payday_is_outside(fake):  # noqa: F811
    with_forecast(fake)
    inside = explain(unknown("145.00", PAYDAY - timedelta(days=1)))["forecast"]
    assert inside["status"] != "outside_forecast" and inside["before"]["evidence_ref"] == "ev_fc_1014"
    on_payday = explain(unknown("145.00", PAYDAY))["forecast"]
    assert on_payday["status"] == "outside_forecast" and on_payday["before"] is on_payday["after"] is None
    assert on_payday["text"] == ("Due on 15 Oct 2026, beyond your balance forecast, which runs until the day before "
                                 "your payday on 15 Oct 2026.")
    assert on_payday["chip"] is None


def test_a_past_due_date_is_outside_the_forecast(fake):  # noqa: F811
    with_forecast(fake)
    out = explain(unknown("145.00", date(2026, 9, 20)))["forecast"]
    assert out["status"] == "outside_forecast" and out["before"] is None
    assert out["text"] == "The due date 20 Sep 2026 has passed, so your balance forecast does not include it."


def test_payday_tomorrow_leaves_only_today(fake):  # noqa: F811
    with_forecast(fake, payday=AS_OF + timedelta(days=1))
    assert explain(unknown("145.00", AS_OF))["forecast"]["before"]["evidence_ref"] == "ev_fc_balance"
    assert explain(unknown("145.00", AS_OF + timedelta(days=1)))["forecast"]["status"] == "outside_forecast"


@pytest.mark.parametrize("due", [date(2026, 10, 10), date(2026, 10, 11)])   # a Saturday and a Sunday
def test_a_due_date_on_a_weekend_is_that_days_forecast(fake, due):  # noqa: F811
    """The due date as printed, no shift to a banking day: the forecast has every calendar day, and the bills
    due and safe to spend's effect use calendar dates too."""
    assert due.weekday() in (5, 6)
    p = with_forecast(fake)
    out = explain(unknown("145.00", due))["forecast"]
    assert out["before"]["evidence_ref"] == f"ev_fc_{due:%m%d}" and p.asked == [due]
    assert be.forecast_window(due, AS_OF, PAYDAY) is None


def test_the_window_rule():
    assert be.forecast_window(date(2026, 9, 29), AS_OF, PAYDAY) == "past"
    assert be.forecast_window(AS_OF, AS_OF, PAYDAY) is None
    assert be.forecast_window(PAYDAY - timedelta(days=1), AS_OF, PAYDAY) is None
    assert be.forecast_window(PAYDAY, AS_OF, PAYDAY) == "beyond"


# ---- a bill the forecast already counts ------------------------------------------------------------------

def test_a_regular_bill_already_in_the_forecast_is_not_subtracted_twice(fake):  # noqa: F811
    """Housing is expected on 1 Oct, so the forecast for 8 Oct already subtracts 836.65 for it: a housing bill of
    886.65 due 8 Oct takes only the excess of 50.00 from that balance."""
    p = with_forecast(fake)
    bill = be.read_barcode(barcode(euros="000886", cents="65", yymmdd="261008"), "Esimerkki Asunnot Oy")
    out = explain(bill)["forecast"]
    before = p.by_date[date(2026, 10, 8)].balance
    assert out["already_counted"]["value"] == 836.65 and out["already_counted"]["evidence_ref"] == "ev_fc_bills_1008"
    assert out["counted"]["value"] == 50.0 and out["counted"]["method"] == "bill.forecast_counted_eur@1"
    assert out["after"]["value"] == float(before - Decimal("50.00"))
    assert fake.specs[out["counted"]["evidence_ref"]]["formula"] == "excess"


def test_a_regular_bill_due_before_its_usual_day_takes_its_whole_amount(fake):  # noqa: F811
    """Housing expected on 12 Oct: on 8 Oct the forecast has not subtracted it yet, so the whole bill counts
    (safe to spend's `counted`, over the whole time until payday, would be only the excess)."""
    p = with_forecast(fake, housing_day=date(2026, 10, 12))
    bill = be.read_barcode(barcode(euros="000886", cents="65", yymmdd="261008"), "Esimerkki Asunnot Oy")
    out = explain(bill)
    fc = out["forecast"]
    assert fc["already_counted"] is None and fc["counted"]["value"] == 886.65
    assert fc["after"]["value"] == float(p.by_date[date(2026, 10, 8)].balance - Decimal("886.65"))


def test_an_unmatched_bill_has_nothing_already_counted(fake):  # noqa: F811
    with_forecast(fake)
    out = explain(unknown("486.00", date(2026, 10, 2)))["forecast"]
    assert out["already_counted"] is None and out["counted"]["value"] == 486.0


# ---- no forecast ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("failure", ["no_forecast", "mismatch"])
def test_a_forecast_that_cannot_be_computed_gives_a_null_block(fake, failure):  # noqa: F811
    def broken(ctx):
        if failure == "no_forecast":
            raise be.forecast_tool.NoForecast("no balance")
        raise BillsDueMismatch("differ")

    fake.projection, fake.row = broken, ROW
    out = explain(unknown("145.00", date(2026, 10, 10)))
    assert out["forecast"] is None and out["actions"]


@pytest.mark.parametrize("where", ["projection", "balance_on"])
def test_a_failed_consistency_check_of_the_forecast_gives_a_null_block(fake, where, caplog):  # noqa: F811
    """Review of #461: the forecast's own consistency checks (RuntimeError in projection() or balance_on()) never
    take the bill explanation down: the block is null, with a line in the log, and the rest stands."""
    if where == "projection":
        def broken(ctx):
            raise RuntimeError("the forecast's bills up to payday differ from the bills due before payday")
        fake.projection = broken
    else:
        p = with_forecast(fake)

        def bad_day(day, label):
            raise RuntimeError("a forecast day's evidence differs from the projection")
        p.balance_on = bad_day
    fake.row = ROW
    with caplog.at_level("WARNING"):
        out = explain(unknown("145.00", date(2026, 10, 10)))
    assert out["forecast"] is None and out["safe_to_spend"] is not None and out["actions"]
    assert "balance forecast unavailable for a bill" in caplog.text


def test_the_forecasts_numbers_are_written_with_the_bills(fake):  # noqa: F811
    with_forecast(fake)
    explain(unknown("145.00", date(2026, 10, 10)))
    assert "ev_fc_spec" in fake.specs
