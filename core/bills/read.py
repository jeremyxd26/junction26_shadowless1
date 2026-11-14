"""Reading a sample bill (issue #250): a language model reads the image, code checks what it read,
and the user confirms. Contract: contracts/api.md section 11.4 (0.3.0, #243).

1. One request through the Gemini adapter (GeminiClient.extract): the image, the prompt
   core/agent/prompts/bill_read.md, no tools, and a response constrained to READ_SCHEMA, which has
   six optional strings. Nothing else from the output is used.
2. The image is untrusted. Only the schema's fields leave the model step. Each is length-capped and
   must pass the parser of #241 or a strict format check. A field that fails its format is dropped,
   never repaired, and no field ever goes into a later prompt.
3. Code decides (issue #250, decision 3, as settled on the issue):
   - A barcode that parses supplies iban, reference, amount and due date (status checked, source
     barcode). A printed value that disagrees with the barcode marks that field unchecked, with a note.
   - Without a usable barcode, an IBAN or reference that passes its check digit is checked. One that
     fails its check digit is kept as unchecked, with the reason; one that fails its format is dropped.
     Amount, due date and payee are always unchecked.
4. The response holds no Number objects, and needs_confirmation is always true. Only fields the user
   confirmed go on to POST /api/bill/explain (#242).
The parser is passed in (core.bills.parse of #241 by default), so the checks are tested on their own.
"""

from __future__ import annotations

import importlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from core.agent.gemini import Prompt, load_prompt
from core.agent.gemini_client import GeminiError
from core.tools.formatting import display
from core.tools.models import Unit

READ_FIELDS = ("payee", "iban", "reference", "amount", "due_date", "barcode")
MAX_LENGTH = {"payee": 70, "iban": 42, "reference": 35, "amount": 20, "due_date": 20, "barcode": 70}
READ_SCHEMA = {
    "type": "object",
    "properties": {
        "payee": {"type": "string", "description": "The payee's name as printed."},
        "iban": {"type": "string", "description": "The payee's IBAN, copied exactly."},
        "reference": {"type": "string", "description": "The reference number (viitenumero or RF), copied exactly."},
        "amount": {"type": "string", "description": "The amount to pay, copied exactly as printed."},
        "due_date": {"type": "string", "description": "The due date (eräpäivä), copied exactly as printed."},
        "barcode": {"type": "string", "description": "The 54-digit virtual barcode, digits only."},
    },
    "additionalProperties": False,
}
READ_REQUEST = "Read the bill in the image and fill the fields you can read."
_SPACES = re.compile(r"[  \t\r\n]")
_IBAN_SHAPE = re.compile(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}")
_REFERENCE_SHAPE = re.compile(r"RF[0-9]{2}[A-Z0-9]{1,21}|[0-9]{2,20}")
_BARCODE_SHAPE = re.compile(r"[0-9]{54}")
_AMOUNT = re.compile(r"(?:€|EUR)?\s*([0-9][0-9  .,]*?)\s*(?:€|EUR|eur|e)?")
_DATE_FI = re.compile(r"([0-9]{1,2})\.([0-9]{1,2})\.([0-9]{4})")
_DATE_ISO = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
# An English bill prints its dates with the month's name ("20 October 2026", "20 Oct 2026"): found by the
# accuracy run of #250, where the model copied sample 4's due date exactly and the check dropped it.
_DATE_EN = re.compile(r"([0-9]{1,2}) ([A-Za-z]{3,9}) ([0-9]{4})")
_MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                "november", "december")
_PAYEE = re.compile(r"[^\W_][\w .,&'’()/+\-]*", re.UNICODE)
MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
NOTES = {
    "differs": {
        "iban": ("The IBAN in the barcode and the printed IBAN differ.", "Viivakoodin ja laskuun painetun tilinumeron välillä on ero."),
        "reference": ("The reference in the barcode and the printed reference differ.", "Viivakoodin ja laskuun painetun viitenumeron välillä on ero."),
        "amount": ("The amount in the barcode and the printed amount differ.", "Viivakoodin ja laskuun painetun summan välillä on ero."),
        "due_date": ("The due date in the barcode and the printed due date differ.", "Viivakoodin ja laskuun painetun eräpäivän välillä on ero."),
    },
    "check": {
        "iban": ("The IBAN's check digits do not match: compare it with the bill.", "Tilinumeron tarkisteet eivät täsmää: vertaa laskuun."),
        "reference": ("The reference number's check digit does not match: compare it with the bill.", "Viitenumeron tarkiste ei täsmää: vertaa laskuun."),
    },
}


class BillReadUnavailable(RuntimeError):
    """The reading cannot use the model, or its answer does not fit the schema: 503 model_unavailable.
    `reason` is a short code, never model text."""

    code = "model_unavailable"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Field:
    value: str
    display: str
    status: str                     # checked | unchecked
    source: str                     # barcode | printed
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"value": self.value, "display": self.display, "status": self.status, "source": self.source,
                "note": self.note}


def _pick(pair: tuple[str, str], language: str) -> str:
    return pair[1] if language == "fi" else pair[0]


# ---- step 2: only the schema's fields, each capped -------------------------------------------------

def model_fields(text: str) -> dict[str, str]:
    """The model's answer as {field: text}: a JSON object with only the schema's keys and string values.
    Anything else does not fit the schema (BillReadUnavailable). An empty value, a value over its
    length cap or one with control or format characters is dropped."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        raise BillReadUnavailable("not_json") from None
    if not isinstance(data, dict) or set(data) - set(READ_FIELDS) or any(not isinstance(v, str) for v in data.values()):
        raise BillReadUnavailable("schema")
    out = {}
    for name, value in data.items():
        value = unicodedata.normalize("NFC", value).strip()
        if not value or len(value) > MAX_LENGTH[name]:
            continue
        if any(unicodedata.category(ch) in ("Cc", "Cf") and ch not in "\t\r\n" for ch in value):
            continue
        out[name] = value
    return out


# ---- strict formats ------------------------------------------------------------------------------------

def parse_amount(text: str) -> Decimal | None:
    """A printed amount ("812,40", "€812.40", "1 234,56 €") as a Decimal, or None. ASCII digits only;
    exactly two decimals when there are decimals; never negative."""
    m = _AMOUNT.fullmatch(text.strip())
    if not m:
        return None
    number = m.group(1).strip()
    decimals = "00"
    if len(number) >= 3 and number[-3] in ".," and number[-2:].isdigit():
        number, decimals = number[:-3], number[-2:]
    whole = re.sub(r"[  .,]", "", number)
    groups = re.split(r"[  .,]", number)
    if not whole.isascii() or not whole.isdigit() or (len(groups) > 1 and any(len(g) != 3 for g in groups[1:])):
        return None
    value = Decimal(f"{int(whole)}.{decimals}")
    return value if value < Decimal("10000000") else None


def parse_due_date(text: str) -> date | None:
    """A printed due date ("1.10.2026", "01.10.2026", "2026-10-01", "1 October 2026", "1 Oct 2026") as a
    date, or None (not a real day, or another form)."""
    text = text.strip()
    m = _DATE_FI.fullmatch(text)
    en = _DATE_EN.fullmatch(text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    elif en:
        name = en.group(2).lower()
        months = [i for i, full in enumerate(_MONTH_NAMES, start=1) if name in (full, full[:3])]
        if not months:
            return None
        d, mo, y = int(en.group(1)), months[0], int(en.group(3))
    else:
        m = _DATE_ISO.fullmatch(text)
        if not m:
            return None
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def format_date(d: date, language: str) -> str:
    return f"{d.day}.{d.month}.{d.year}" if language == "fi" else f"{d.day} {MONTHS_EN[d.month - 1]} {d.year}"


def _compact(text: str) -> str:
    return _SPACES.sub("", text)


def _iban(text: str, parser: Any) -> str | None:
    """The IBAN normalised by the parser when it is IBAN-shaped (ASCII letters and digits), else None."""
    raw = _compact(text)
    if not raw.isascii():
        return None
    try:
        iban = parser.normalise_iban(raw)
    except parser.BillFormatError:
        return None
    return iban if _IBAN_SHAPE.fullmatch(iban) else None


def _reference(text: str, parser: Any) -> str | None:
    raw = _compact(text)
    if not raw.isascii():
        return None
    try:
        reference = parser.normalise_reference(raw)
    except parser.BillFormatError:
        return None
    return reference if _REFERENCE_SHAPE.fullmatch(reference) else None


# ---- step 3: code decides --------------------------------------------------------------------------------

def check_fields(fields: dict[str, str], parser: Any, language: str) -> dict[str, Field | None]:
    """The checked reading: every field of READ_FIELDS as a Field or None (not read, or failed its format)."""
    out: dict[str, Field | None] = {name: None for name in READ_FIELDS}

    payee = fields.get("payee")
    if payee and _PAYEE.fullmatch(payee) and not re.search(r"https?:|www\.|@", payee, re.I):
        out["payee"] = Field(payee, payee, "unchecked", "printed")

    printed_iban = _iban(fields["iban"], parser) if "iban" in fields else None
    printed_reference = _reference(fields["reference"], parser) if "reference" in fields else None
    printed_amount = parse_amount(fields["amount"]) if "amount" in fields else None
    printed_due = parse_due_date(fields["due_date"]) if "due_date" in fields else None

    barcode = None
    raw_barcode = _compact(fields.get("barcode", ""))
    if _BARCODE_SHAPE.fullmatch(raw_barcode):
        try:
            barcode = parser.parse_virtual_barcode(raw_barcode)
        except parser.BillFormatError:
            barcode = None              # a misread digit fails its check: the barcode is dropped

    def amount_field(value: Decimal, status: str, source: str, note: str | None = None) -> Field:
        return Field(f"{value:.2f}", display(value, Unit.EUR, language), status, source, note)

    def date_field(value: date, status: str, source: str, note: str | None = None) -> Field:
        return Field(value.isoformat(), format_date(value, language), status, source, note)

    def differs(name: str, read: Any, from_barcode: Any) -> tuple[str, str | None]:
        if read is not None and read != from_barcode:
            return "unchecked", _pick(NOTES["differs"][name], language)
        return "checked", None

    if barcode is not None:
        out["barcode"] = Field(raw_barcode, raw_barcode, "checked", "barcode")
        status, note = differs("iban", printed_iban, barcode.iban)
        out["iban"] = Field(barcode.iban, parser.format_iban(barcode.iban), status, "barcode", note)
        status, note = differs("reference", printed_reference, barcode.reference)
        out["reference"] = Field(barcode.reference, parser.format_reference(barcode.reference), status, "barcode", note)
        if barcode.amount is not None:
            status, note = differs("amount", printed_amount, barcode.amount)
            out["amount"] = amount_field(barcode.amount, status, "barcode", note)
        elif printed_amount is not None:
            out["amount"] = amount_field(printed_amount, "unchecked", "printed")
        if barcode.due_date is not None:
            status, note = differs("due_date", printed_due, barcode.due_date)
            out["due_date"] = date_field(barcode.due_date, status, "barcode", note)
        elif printed_due is not None:
            out["due_date"] = date_field(printed_due, "unchecked", "printed")
        return out

    if printed_iban is not None:
        ok = parser.valid_iban(printed_iban)
        out["iban"] = Field(printed_iban, parser.format_iban(printed_iban), "checked" if ok else "unchecked",
                            "printed", None if ok else _pick(NOTES["check"]["iban"], language))
    if printed_reference is not None:
        ok = parser.valid_reference(printed_reference)
        out["reference"] = Field(printed_reference, parser.format_reference(printed_reference),
                                 "checked" if ok else "unchecked", "printed",
                                 None if ok else _pick(NOTES["check"]["reference"], language))
    if printed_amount is not None:
        out["amount"] = amount_field(printed_amount, "unchecked", "printed")
    if printed_due is not None:
        out["due_date"] = date_field(printed_due, "unchecked", "printed")
    return out


# ---- step 1 and the whole reading ----------------------------------------------------------------------

def read_bill(client: Any, image: bytes, mime_type: str, language: str, *, parser: Any | None = None,
              prompt: Prompt | None = None) -> dict[str, Any]:
    """Read one bill image: {fields, needs_confirmation, prompt, model}. Raises BillReadUnavailable when
    the model may not be used, fails, is blocked, or answers outside the schema (503 model_unavailable)."""
    parser = parser or importlib.import_module("core.bills.parse")
    prompt = prompt or load_prompt("bill_read")
    try:
        reply = client.extract(prompt.text, READ_REQUEST, image, mime_type, READ_SCHEMA)
    except GeminiError as exc:
        raise BillReadUnavailable(exc.code) from None
    if reply.blocked:
        raise BillReadUnavailable("blocked")
    fields = check_fields(model_fields(reply.text), parser, language)
    return {"fields": {name: (f.as_dict() if f else None) for name, f in fields.items()},
            "needs_confirmation": True, "prompt": prompt.version, "model": reply.model}
