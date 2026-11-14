"""The request model of POST /api/bill/explain (contracts/api.md section 11.1, #243): what a 400 is."""

from datetime import date

import pytest
from pydantic import ValidationError

from core.app.api.schemas import BillExplainRequest, BillFieldsRequest

FIELDS = {"payee": "Esimerkki Remontti Oy", "iban": "FI71 1234 5600 0098 76", "reference": "12344",
          "amount": "145.00", "due_date": "2026-10-20"}


def fields(**kw):
    return BillFieldsRequest.model_validate({**FIELDS, **kw})


def test_a_typed_bill_validates():
    f = fields()
    assert f.due_date == date(2026, 10, 20) and f.amount == "145.00"


@pytest.mark.parametrize("due_date", [0, 20261020, "2026-10-20T00:00:00", "2026-10-20 00:00", "20.10.2026",
                                      "2026-2-1", "2026-02-30", "２０２６-10-20", "", None])
def test_due_date_is_only_yyyy_mm_dd_and_a_real_date(due_date):
    with pytest.raises(ValidationError):
        fields(due_date=due_date)


@pytest.mark.parametrize("amount", ["145.00", "0.01", "100000.00", "100000", "7.5"])
def test_amounts_in_the_bound(amount):
    assert fields(amount=amount).amount == amount


@pytest.mark.parametrize("amount", ["0", "0.00", "100000.01", "1.234", "-1", "１２", "1e3", " 1", "1,00", 145])
def test_amounts_out_of_the_bound_or_form(amount):
    with pytest.raises(ValidationError):
        fields(amount=amount)


def test_unknown_and_over_long_fields_are_refused():
    with pytest.raises(ValidationError):
        fields(note="x")
    with pytest.raises(ValidationError):
        fields(payee="x" * 71)
    with pytest.raises(ValidationError):
        BillExplainRequest.model_validate({"customer_id": "CUST00042", "barcode": "1", "extra": 1})
    with pytest.raises(ValidationError):
        BillExplainRequest.model_validate({"customer_id": "CUST00042", "barcode": "1" * 81})


def test_one_of_barcode_or_fields_is_left_to_the_endpoint():
    """Both or neither validate here: the endpoint answers them with a 422 invalid_bill, not a 400."""
    assert BillExplainRequest.model_validate({"customer_id": "CUST00042"}).fields is None
    both = BillExplainRequest.model_validate({"customer_id": "CUST00042", "barcode": "1", "fields": FIELDS})
    assert both.barcode == "1" and both.fields is not None
