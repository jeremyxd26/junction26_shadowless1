"""The forecast on a bill's due date against the database (#421): the four demo personas, one customer at a time,
labels off (conftest). Skipped without DATABASE_URL. Read only, except the evidence specs every tool writes.

The block's balance before is the balance forecast's own Number for the due date (value, display and evidence
ref), every number of the block opens in the evidence view and reconciles, and a bill already among the
forecast's bills takes only its excess."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from core.app.api import evidence as evidence_api
from core.app.api.schemas import BillExplainResponse
from core.tools import bill_explain as be
from core.tools import evidence
from core.tools.context import ToolContext
from core.tools.forecast import get_balance_forecast

AS_OF = date(2026, 9, 30)
PERSONAS = ("CUST00349", "CUST00493", "CUST00849", "CUST00860")
REMONTTI = ("Esimerkki Remontti Oy", "FI71 1234 5600 0098 76", "12344")      # no regular bill of anyone
ENERGIA = ("Esimerkki Energia Oy", "FI21 1234 5600 0007 85", "1232")         # a utilities payee (sample 2)


def ctx(conn, customer_id: str, lang: str = "en") -> ToolContext:
    return ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn, language=lang)


def explain(conn, customer_id: str, bill, lang: str = "en") -> dict:
    out = be.explain_bill(ctx(conn, customer_id, lang), bill)
    BillExplainResponse.model_validate({"customer_id": customer_id, "as_of": AS_OF, "language": lang, **out})
    return out


def d(number: dict) -> Decimal:
    return Decimal(str(number["value"]))


def opens_and_reconciles(conn, customer_id: str, number: dict, lang: str = "en") -> None:
    res = evidence.resolve(conn, number["evidence_ref"], customer_id)
    assert res.reconciles is True, number["method"]
    view = evidence_api.build(conn, res, customer_id, lang)
    assert (view.number.value, view.number.display) == (number["value"], number["display"]), number["method"]


@pytest.mark.parametrize("customer_id", PERSONAS)
def test_the_balance_before_is_the_forecasts_own_number_on_its_days(conn, customer_id):
    """For each day of the forecast card (today, a bills day, the lowest point), a bill due that day starts from
    the forecast's Number for that day: the same value, display and evidence ref."""
    steps = get_balance_forecast(ctx(conn, customer_id), {}).data.steps
    assert len(steps) >= 2
    for step in steps:
        fc = explain(conn, customer_id, be.read_fields(*REMONTTI, "100.00", step.date))["forecast"]
        before = fc["before"]
        assert (before["value"], before["display"], before["evidence_ref"]) == (
            step.balance.value, step.balance.display, step.balance.evidence_ref), step.date
        assert fc["already_counted"] is None and d(fc["counted"]) == Decimal("100.00")
        assert d(fc["after"]) == d(before) - Decimal("100.00")
        opens_and_reconciles(conn, customer_id, fc["after"])


@pytest.mark.parametrize("customer_id", PERSONAS)
def test_a_utilities_bill_takes_only_its_excess_and_every_number_reconciles(conn, customer_id):
    """Sample 2 (EUR 312.70 to a utilities payee, due 13 Oct): utilities is spread over the month, so the
    forecast already subtracts part of it by 13 Oct; the bill takes only the excess over that part."""
    fc = explain(conn, customer_id, be.read_fields(*ENERGIA, "312.70", date(2026, 10, 13)))["forecast"]
    already, counted = d(fc["already_counted"]), d(fc["counted"])
    assert fc["already_counted"]["method"] == "balance_forecast.bills_to_date_eur@1" and already > 0
    assert counted == max(Decimal("312.70") - already, Decimal("0"))
    assert d(fc["after"]) == d(fc["before"]) - counted
    for key in ("before", "already_counted", "counted", "after"):
        opens_and_reconciles(conn, customer_id, fc[key])


@pytest.mark.parametrize("lang", ["en", "fi"])
def test_the_tight_persona_on_her_lowest_day(conn, lang):
    """CUST00849's forecast is lowest on 14 Oct (641.43): EUR 600 leaves 41.43 (tight), EUR 700 is 58.57 short
    (not covered, with the chip); the draft stays in both."""
    tight = explain(conn, "CUST00849", be.read_fields(*REMONTTI, "600.00", date(2026, 10, 14)), lang)
    assert tight["forecast"]["status"] == "tight" and d(tight["forecast"]["after"]) == Decimal("41.43")
    short = explain(conn, "CUST00849", be.read_fields(*REMONTTI, "700.00", date(2026, 10, 14)), lang)
    fc = short["forecast"]
    assert fc["status"] == "not_covered" and d(fc["shortfall"]) == Decimal("58.57") and fc["chip"]["type"] == "ask"
    assert fc["shortfall"]["display"] in fc["text"]
    opens_and_reconciles(conn, "CUST00849", fc["shortfall"], lang)
    assert [a["type"] for a in short["actions"]][0] == "add_to_payments"   # contact_bank (#453) may follow


def test_a_bill_due_after_payday_is_outside_the_forecast(conn):
    fc = explain(conn, "CUST00860", be.read_fields(*REMONTTI, "100.00", date(2026, 10, 20)))["forecast"]
    assert fc["status"] == "outside_forecast" and fc["before"] is None and fc["after"] is None
