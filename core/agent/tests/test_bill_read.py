"""Reading a sample bill (core/bills/read.py, issue #250): the model reads, code checks, the user confirms.

The model's answers are recorded responses replayed by a fake transport through the real Gemini
client (no network, no key). The parser is a stand-in for core/bills/parse.py (#241), written here
against #241's published interface with its own implementation of the checks (IBAN mod 97, the
Finnish 7-3-1 reference check, the version 4 virtual barcode), until #241 is merged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from core.agent.gemini_client import GeminiClient, GeminiError
from core.agent.tests.test_gemini_client import FakeTransport, api_error, text_response
from core.bills.read import (BillReadUnavailable, check_fields, model_fields, parse_amount, parse_due_date,
                             read_bill)

PNG = b"\x89PNG\r\n\x1a\n" + b"sample-bill" * 40
IBAN = "FI2112345600000785"                          # the contract's example account (valid mod 97)
REFERENCE = "1232"                                   # 7-3-1: 1*1 + 2*3 + 3*7 = 28 -> check digit 2
BARCODE = "4" + IBAN[2:] + "000812" + "40" + "000" + REFERENCE.rjust(20, "0") + "261001"


# ---- a stand-in for core/bills/parse.py (#241's interface) ---------------------------------------

class BillFormatError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ParsedBarcode:
    version: int
    iban: str
    amount: Decimal | None
    reference: str
    due_date: date | None


class FakeParser:
    BillFormatError = BillFormatError

    @staticmethod
    def normalise_iban(text: str) -> str:
        t = "".join(text.split()).upper()
        if not t.isascii() or not t.isalnum():
            raise BillFormatError("iban_check")
        return t

    @staticmethod
    def valid_iban(text: str) -> bool:
        t = FakeParser.normalise_iban(text)
        if t.startswith("FI") and len(t) != 18:
            return False
        digits = "".join(str(int(c, 36)) for c in t[4:] + t[:4])
        return int(digits) % 97 == 1

    @staticmethod
    def normalise_reference(text: str) -> str:
        t = "".join(text.split()).upper()
        if not t.isascii() or not t.isalnum():
            raise BillFormatError("reference_check")
        return t if t.startswith("RF") else (t.lstrip("0") or "0")

    @staticmethod
    def valid_reference(text: str) -> bool:
        t = FakeParser.normalise_reference(text)
        if t.startswith("RF"):
            return int("".join(str(int(c, 36)) for c in t[4:] + t[:4])) % 97 == 1
        if not t.isdigit() or len(t) < 2:
            return False
        body, check = t[:-1], int(t[-1])
        total = sum(int(d) * (7, 3, 1)[i % 3] for i, d in enumerate(reversed(body)))
        return (10 - total % 10) % 10 == check

    @staticmethod
    def format_iban(text: str) -> str:
        t = FakeParser.normalise_iban(text)
        return " ".join(t[i:i + 4] for i in range(0, len(t), 4))

    @staticmethod
    def format_reference(text: str) -> str:
        t = FakeParser.normalise_reference(text)
        if t.startswith("RF"):
            return " ".join(t[i:i + 4] for i in range(0, len(t), 4))
        groups = []
        while t:
            groups.insert(0, t[-5:])
            t = t[:-5]
        return " ".join(groups)

    @staticmethod
    def parse_virtual_barcode(text: str) -> ParsedBarcode:
        t = "".join(text.split())
        if len(t) != 54 or not t.isascii() or not t.isdigit():
            raise BillFormatError("barcode_length")
        if t[0] != "4":
            raise BillFormatError("barcode_version")
        iban = "FI" + t[1:17]
        if not FakeParser.valid_iban(iban):
            raise BillFormatError("iban_check")
        euros, cents = int(t[17:23]), t[23:25]
        reference = t[28:48].lstrip("0")
        if not FakeParser.valid_reference(reference):
            raise BillFormatError("reference_check")
        yy, mm, dd = t[48:50], t[50:52], t[52:54]
        due = None if t[48:54] == "000000" else date(2000 + int(yy), int(mm), int(dd))
        amount = None if euros == 0 and cents == "00" else Decimal(f"{euros}.{cents}")
        return ParsedBarcode(4, iban, amount, reference, due)


def model_answer(**fields) -> dict:
    """A recorded model response with these schema fields."""
    return text_response(json.dumps(fields))


def read(answer, language="fi", transport=None):
    transport = transport or FakeTransport(answer)
    client = GeminiClient("gemini-3.8-flash", transport, cache="off", sleep=lambda s: None)
    return read_bill(client, PNG, "image/png", language, parser=FakeParser()), transport


PRINTED = dict(payee="Esimerkki Asunnot Oy", iban="FI21 1234 5600 0007 85", reference="1232",
               amount="812,40", due_date="1.10.2026")


# ---- the four cases of the issue ---------------------------------------------------------------------

def test_a_barcode_bill_read_correctly_is_checked_by_code():
    result, transport = read(model_answer(**PRINTED, barcode=BARCODE))
    f = result["fields"]
    assert len(transport.requests) == 1 and result["needs_confirmation"] is True
    assert f["barcode"]["status"] == "checked" and f["barcode"]["source"] == "barcode"
    assert f["iban"] == {"value": IBAN, "display": "FI21 1234 5600 0007 85", "status": "checked", "source": "barcode",
                         "note": None}
    assert f["reference"]["value"] == "1232" and f["reference"]["status"] == "checked"
    assert f["amount"] == {"value": "812.40", "display": "812,40 €", "status": "checked", "source": "barcode", "note": None}
    assert f["due_date"] == {"value": "2026-10-01", "display": "1.10.2026", "status": "checked", "source": "barcode",
                             "note": None}
    assert f["payee"]["status"] == "unchecked" and f["payee"]["source"] == "printed"
    assert "Number" not in json.dumps(result) and "evidence_ref" not in json.dumps(result)


def test_a_barcode_with_one_misread_iban_digit_is_dropped_and_the_printed_fields_stay_unconfirmed():
    misread = BARCODE[:5] + str((int(BARCODE[5]) + 1) % 10) + BARCODE[6:]
    result, _ = read(model_answer(**PRINTED, barcode=misread))
    f = result["fields"]
    assert f["barcode"] is None
    assert f["iban"]["source"] == "printed" and f["iban"]["status"] == "checked"     # its own check digits pass
    assert f["amount"]["status"] == "unchecked" and f["due_date"]["status"] == "unchecked"


def test_barcode_and_printed_amount_disagree():
    result, _ = read(model_answer(**{**PRINTED, "amount": "821,40"}, barcode=BARCODE), language="en")
    amount = result["fields"]["amount"]
    assert amount["value"] == "812.40" and amount["source"] == "barcode"              # the barcode's value
    assert amount["status"] == "unchecked" and "differ" in amount["note"]


def test_no_barcode_and_a_wrong_reference_check_digit():
    result, _ = read(model_answer(**{**PRINTED, "reference": "1233"}))
    ref = result["fields"]["reference"]
    assert ref["value"] == "1233" and ref["status"] == "unchecked" and "tarkiste" in ref["note"]
    assert result["fields"]["iban"]["status"] == "checked"
    assert result["fields"]["amount"]["status"] == "unchecked" and result["fields"]["barcode"] is None


# ---- the model's answer outside the schema, and the model unavailable ----------------------------

@pytest.mark.parametrize("text", ["not json", "[]", '{"iban": 123}', '{"iban": "x", "note": "pay now"}'])
def test_an_answer_that_does_not_fit_the_schema_is_unavailable(text):
    with pytest.raises(BillReadUnavailable) as exc:
        read(text_response(text))
    assert exc.value.code == "model_unavailable"


@pytest.mark.parametrize("failure", [TimeoutError(), api_error(429), api_error(503), api_error(404),
                                     {"prompt_feedback": {"block_reason": "SAFETY"}}],
                         ids=["timeout", "429", "503", "404", "blocked"])
def test_the_model_unavailable_gives_model_unavailable_with_one_request_at_most(failure):
    transport = FakeTransport(failure)
    with pytest.raises(BillReadUnavailable):
        read(None, transport=transport)
    assert len(transport.requests) == 1                    # no retry, no fallback model


@pytest.mark.parametrize("code", ["disabled", "budget", "rate_limited"])
def test_a_reading_refused_by_the_budget_or_the_switch_sends_nothing(code):
    class Refusing:
        def extract(self, *args, **kwargs):
            raise GeminiError(code)

    with pytest.raises(BillReadUnavailable) as exc:
        read_bill(Refusing(), PNG, "image/png", "en", parser=FakeParser())
    assert exc.value.reason == code


# ---- formats: a field that fails its format is dropped, never repaired --------------------------

@pytest.mark.parametrize("field, value", [
    ("iban", "FI21 1234 5600 0007 8５"),        # a fullwidth digit
    ("iban", "not an account"),
    ("iban", "FI21" + "1" * 40),                 # over the length cap
    ("reference", "12a32"),
    ("amount", "about 800"),
    ("amount", "-812,40"),
    ("due_date", "31.2.2026"),                   # not a real day
    ("due_date", "next Friday"),
    ("due_date", "31 February 2026"),            # not a real day
    ("due_date", "20 Octobre 2026"),             # not an English month
    ("due_date", "October 20, 2026"),            # another order
    ("payee", "Pay at https://pay.example"),
])
def test_a_field_that_fails_its_format_is_dropped(field, value):
    checked = check_fields(model_fields(json.dumps({field: value})), FakeParser(), "en")
    assert checked[field] is None


@pytest.mark.parametrize("text, value", [("812,40", "812.40"), ("€812.40", "812.40"), ("1 234,56 €", "1234.56"),
                                         ("1,234.56", "1234.56"), ("812", "812.00"), ("EUR 60,00", "60.00")])
def test_printed_amounts_in_both_locales(text, value):
    assert f"{parse_amount(text):.2f}" == value


@pytest.mark.parametrize("text", ["20.10.2026", "2026-10-20", "20 October 2026", "20 Oct 2026", "20 october 2026"])
def test_printed_due_dates_in_both_locales(text):
    """The English bill's own form counts too (the accuracy run of #250: sample 4 prints "20 October 2026")."""
    assert parse_due_date(text) == date(2026, 10, 20)


# ---- injection: text in the image tells the model to report another account -------------------------

def fake_explain(confirmed: dict) -> dict:
    """A stand-in for POST /api/bill/explain (#242) until it is merged: the warning signs it raises for
    confirmed fields, and whether it offers the add_to_payments action."""
    signals = []
    if not FakeParser.valid_iban(confirmed["iban"]):
        signals.append("iban_check_failed")
    if not FakeParser.valid_reference(confirmed["reference"]):
        signals.append("reference_check_failed")
    return {"signals": signals, "actions": [] if signals else ["add_to_payments"]}


def test_an_obeyed_injection_with_a_bad_check_digit_shows_unchecked_and_never_reaches_a_payment():
    injected = "FI21 1234 5600 0007 86"          # one digit off: fails mod 97
    result, _ = read(model_answer(**{**PRINTED, "iban": injected}))
    iban = result["fields"]["iban"]
    assert iban["status"] == "unchecked" and iban["note"] and result["needs_confirmation"] is True
    confirmed = {name: f["value"] for name, f in result["fields"].items() if f}      # the user confirms as shown
    explained = fake_explain(confirmed)
    assert "iban_check_failed" in explained["signals"] and "add_to_payments" not in explained["actions"]


def test_an_obeyed_injection_on_a_barcode_bill_loses_to_the_barcode_and_is_flagged():
    other = "FI4950009420028730"                  # structurally valid, not the bill's account
    assert FakeParser.valid_iban(other)
    result, _ = read(model_answer(**{**PRINTED, "iban": other}, barcode=BARCODE), language="en")
    iban = result["fields"]["iban"]
    assert iban["value"] == IBAN and iban["source"] == "barcode"                   # the barcode's account
    assert iban["status"] == "unchecked" and "differ" in iban["note"]


def test_the_residual_risk_a_valid_injected_iban_on_a_bill_without_barcode_is_a_field_to_confirm():
    other = "FI4950009420028730"
    result, _ = read(model_answer(**{**PRINTED, "iban": other}))
    iban = result["fields"]["iban"]
    # Code cannot know the paper: a valid account passes its check digits. It is shown for the user to
    # compare with the bill (needs_confirmation), and it is never an answer or a payment by itself.
    assert iban["value"] == other and iban["status"] == "checked" and result["needs_confirmation"] is True


def test_the_reading_holds_no_model_text_beyond_the_fields():
    answer = text_response(json.dumps({**PRINTED, "barcode": BARCODE}) + "")
    result, _ = read(answer)
    assert set(result) == {"fields", "needs_confirmation", "prompt", "model"}
    assert set(result["fields"]) == {"payee", "iban", "reference", "amount", "due_date", "barcode"}
