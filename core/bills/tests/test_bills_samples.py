"""The sample bills of the gallery (#249): every true field passes or fails the validators of
core/bills/parse.py exactly as the bill's story says, and every barcode parses to the same fields.

The warning signs follow contracts/api.md section 11.2 (0.3.0). `new_payee` uses the fictional payee
names agreed for #242's table; `amount_above_usual` uses Sanna's typical months as the bills card
shows them, which test_the_usual_amounts_are_sannas_own checks against the database.
"""

from __future__ import annotations

import os
import re
import struct
from datetime import date
from decimal import Decimal

import pytest

from core.bills import gallery
from core.bills.parse import parse_virtual_barcode, valid_iban, valid_reference

KEY = gallery.answer_key()
SAMPLES = {s["sample_id"]: s for s in KEY["samples"]}
AS_OF = date.fromisoformat(KEY["as_of"])
KNOWN_PAYEES = {"Esimerkki Asunnot Oy": "housing_payment", "Esimerkki Energia Oy": "utilities_payment",
                "Esimerkki Vesi Oy": "utilities_payment"}
TYPICAL_MONTH = {"housing_payment": Decimal("836.65"), "utilities_payment": Decimal("186.40")}  # 2026-09-30


def expected_signals(truth: dict) -> list[str]:
    """Section 11.2's rules, written out here for the four bills."""
    out = []
    if not valid_iban(truth["iban"]):
        out.append("iban_check_failed")
    if not valid_reference(truth["reference"]):
        out.append("reference_check_failed")
    bill = KNOWN_PAYEES.get(truth["payee"])
    if bill is None:
        out.append("new_payee")
    amount = Decimal(truth["amount"])
    usual = TYPICAL_MONTH[bill] * Decimal("1.5") if bill else max(TYPICAL_MONTH.values())
    if (amount >= usual) if bill else (amount > usual):
        out.append("amount_above_usual")
    if 0 <= (date.fromisoformat(truth["due_date"]) - AS_OF).days < 7:
        out.append("short_term")
    return sorted(out)


def test_four_samples_three_finnish_one_english():
    assert list(SAMPLES) == ["sample_1", "sample_2", "sample_3", "sample_4"]
    assert [s["language"] for s in SAMPLES.values()] == ["fi", "fi", "fi", "en"]
    assert (KEY["customer_id"], KEY["as_of"]) == ("CUST00860", "2026-09-30")
    assert all(set(s["title"]) == {"en", "fi"} for s in SAMPLES.values())


@pytest.mark.parametrize("sample_id", ["sample_1", "sample_2", "sample_3", "sample_4"])
def test_the_fields_pass_or_fail_as_the_story_says(sample_id):
    s = SAMPLES[sample_id]
    t = s["truth"]
    assert s["checks"]["iban"] == ("pass" if valid_iban(t["iban"]) else "fail")
    assert s["checks"]["reference"] == ("pass" if valid_reference(t["reference"]) else "fail")
    assert s["signals"] == expected_signals(t)
    if t["barcode"] is None:
        assert s["checks"]["barcode"] == "absent"
    else:
        got = parse_virtual_barcode(t["barcode"])
        assert s["checks"]["barcode"] == "pass"
        assert (got.iban, got.amount, got.reference, got.due_date) == (
            t["iban"], Decimal(t["amount"]), t["reference"], date.fromisoformat(t["due_date"]))


def test_the_story():
    """1 usual, 2 clearly higher, 3 an unknown payee with a short term, 4 a wrong check digit and no barcode."""
    s1, s2, s3, s4 = (SAMPLES[f"sample_{n}"]["truth"] for n in range(1, 5))
    assert Decimal(s1["amount"]) == TYPICAL_MONTH["housing_payment"] and SAMPLES["sample_1"]["signals"] == []
    assert SAMPLES["sample_2"]["signals"] == ["amount_above_usual"]
    assert SAMPLES["sample_3"]["signals"] == ["new_payee", "short_term"]
    assert (date.fromisoformat(s3["due_date"]) - date.fromisoformat(s3["invoice_date"])).days <= 7
    assert s3["reference"].startswith("RF") and s3["barcode"].startswith("5")      # version 5, RF
    assert s1["barcode"].startswith("4") and s2["barcode"].startswith("4")         # version 4, national
    assert SAMPLES["sample_4"]["signals"] == ["reference_check_failed"] and s4["barcode"] is None
    assert valid_reference(s4["reference"][:-1] + next(
        d for d in "0123456789" if valid_reference(s4["reference"][:-1] + d)))      # only the check digit is wrong


def test_synthetic_values_only():
    for s in SAMPLES.values():
        t = s["truth"]
        assert t["payee"].startswith("Esimerkki ")
        assert t["iban"].startswith("FI") and t["iban"][4:8] == "0000"   # no Finnish bank code begins with 0
    assert len({s["truth"]["iban"] for s in SAMPLES.values()}) == 4


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR"
    return struct.unpack(">II", data[16:24])


def test_the_files_exist_png_about_1200_wide_and_one_page_pdfs():
    for s in SAMPLES.values():
        png = (gallery.SAMPLES_DIR / s["files"]["png"]).read_bytes()
        width, height = png_size(png)
        assert width == 1200 and height > width
        pdf = (gallery.SAMPLES_DIR / s["files"]["pdf"]).read_bytes()
        assert pdf.startswith(b"%PDF-") and len(re.findall(rb"/Type\s*/Page(?!s)", pdf)) == 1


def test_the_gallery_view_has_no_true_fields():
    view = gallery.gallery()
    assert [g.sample_id for g in view] == list(SAMPLES)
    for g in view:
        assert set(vars(g)) == {"sample_id", "title", "language", "png", "version"}
        assert len(g.version) == 12 and gallery.image(g.png.name) is g
    assert gallery.image("samples.json") is None and gallery.image("../samples.json") is None


# ---- against the database (skipped without DATABASE_URL) -------------------------------------------------

def test_the_usual_amounts_are_sannas_own(monkeypatch):
    """The typical months above are Sanna's, as her bills card shows them on the demo date (read-only)."""
    from core.tools import db
    from core.tools.bills import get_recurring_bills
    from core.tools.context import ToolContext

    if not os.environ.get("DATABASE_URL") and db.database_url(required=False) is None:
        pytest.skip("DATABASE_URL is not set")
    monkeypatch.setenv("SPIKE_REVIEWS", "off")
    import psycopg

    with psycopg.connect(db.database_url(), application_name="core-tests-sample-bills") as conn:
        conn.execute("SET statement_timeout = '60s'")
        try:
            ctx = ToolContext(customer_id=KEY["customer_id"], as_of=AS_OF, conn=conn, language="en")
            items = get_recurring_bills(ctx, {"include_income": False}).card.model_dump(mode="json")["items"]
        finally:
            conn.rollback()   # the evidence rows the tool writes are not kept
    typical = {i["bill_id"].removeprefix("bill_"): Decimal(str(i["typical_month"]["value"])) for i in items}
    assert {k: typical[k] for k in TYPICAL_MONTH} == TYPICAL_MONTH
