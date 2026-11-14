"""Make the sample bills of the demo gallery (#249): core/bills/samples/sample_N.png and sample_N.pdf
for N = 1..4, and core/bills/samples/samples.json, the answer key.

Development tool only; the service never runs it. It needs Pillow, a development dependency that is
not in core/requirements.txt:

    pip install pillow==13.0.0
    python scripts/make_sample_bills.py          # from the repository root
    python scripts/make_sample_bills.py --font REGULAR.ttf --bold-font BOLD.ttf

Pillow's built-in font has no ä, ö or €, so a TrueType font of the system is used: Arial on Windows
(the committed files were made with it), DejaVu Sans on Linux, Arial on macOS, or the files given.
The output is the same on every run with the same fonts and Pillow version (fixed PDF dates, no
randomness); another font changes only the pixels, never a value.

Everything on the bills is synthetic: fictional companies (the names agreed with #242's table of
known payees), a fictional payer and addresses with the postal code 00000, which does not exist. No
brand, logo, phone number or business id. The IBANs are test values: their bank part is 0000, and no
Finnish monetary institution code begins with 0 (Finance Finland, Finnish Monetary Institution Codes
and BICs, 16.3.2026), so they belong to no account. Check digits are found with the validators of
core/bills/parse.py (#241), and every barcode is parsed back before anything is written.

The four bills tell the demo story for CUST00860 (Sanna) on the demo date 2026-09-30, with her
recurring bills as the bills card shows them: Housing, usually EUR 836.65 a month around the 3rd, and
Utilities, usually EUR 186.40 a month in about three payments; payday 15 October. The warning signs
are those of contracts/api.md section 11.2 (0.3.0): `amount_above_usual` at 150% of the matched
bill's typical month, `short_term` for a due date fewer than 7 days after the demo date.
  1. A regular bill at its usual amount: no warning sign.
  2. The same kind of bill, a regular home bill, clearly higher than usual: `amount_above_usual`.
  3. A payee that is not a regular bill, with a 3-day payment term: `new_payee` and `short_term`.
  4. A reference number with a wrong check digit and no barcode (in English): `reference_check_failed`.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.bills.parse import (  # noqa: E402
    format_iban, format_reference, parse_virtual_barcode, valid_iban, valid_reference,
)

OUT = ROOT / "core" / "bills" / "samples"
AS_OF = date(2026, 9, 30)
WIDTH, HEIGHT = 1200, 1697          # A4 at about 145 dpi
DPI = 145.0
PAYER = ("Sanna Esimerkki", "Esimerkkitie 1 A 2", "00000 ESIMERKKILÄ")
FIXED = datetime(2026, 9, 30, 12, 0, 0).timetuple()   # the PDF dates, so a re-run gives the same file

# ---- values, checked by the parser of #241 -------------------------------------------------------------


def iban_for(bban: str) -> str:
    return next(i for i in (f"FI{cc:02d}{bban}" for cc in range(2, 99)) if valid_iban(i))


def national_for(stem: str) -> str:
    return next(r for r in (f"{stem}{d}" for d in range(10)) if valid_reference(r))


def rf_for(body: str) -> str:
    return next(r for r in (f"RF{cc:02d}{body}" for cc in range(2, 99)) if valid_reference(r))


def wrong_check_digit(reference: str) -> str:
    wrong = reference[:-1] + str((int(reference[-1]) + 3) % 10)
    assert not valid_reference(wrong)
    return wrong


def barcode_for(iban: str, amount: Decimal, reference: str, due: date) -> str:
    """Bank Bar Code Guide 5.3, sections 9 and 10: version 4 for a national reference, 5 for RF."""
    euros, cents = divmod(int(amount * 100), 100)
    if reference.startswith("RF"):
        digits = f"5{iban[2:]}{euros:06d}{cents:02d}{reference[2:4]}{reference[4:].rjust(21, '0')}"
    else:
        digits = f"4{iban[2:]}{euros:06d}{cents:02d}000{reference.rjust(20, '0')}"
    digits += due.strftime("%y%m%d")
    parsed = parse_virtual_barcode(digits)
    assert (parsed.iban, parsed.amount, parsed.reference, parsed.due_date) == (iban, amount, reference, due)
    return digits


SAMPLES = [
    {
        "sample_id": "sample_1", "language": "fi", "colour": (15, 110, 110),
        "title": {"en": "Rent bill", "fi": "Vuokralasku"},
        "story": "A regular bill at its usual amount.",
        "signals": [],
        "payee": "Esimerkki Asunnot Oy", "payee_address": ("Esimerkkikatu 10", "00000 ESIMERKKILÄ"),
        "heading": "LASKU", "iban": iban_for("00000000001001"), "reference": national_for("10452110"),
        "invoice_date": date(2026, 9, 24), "due_date": date(2026, 10, 8), "invoice_no": "2026-1048",
        "customer_no": "104521", "terms": "14 päivää netto",
        "rows": [("Vuokra 10/2026, asunto A 2", "796.65"), ("Vesimaksu, ennakko 10/2026 (2 henkilöä)", "40.00")],
        "note": "Maksathan laskun viitenumerolla. Kiitos!",
        "barcode": True,
    },
    {
        "sample_id": "sample_2", "language": "fi", "colour": (154, 91, 0),
        "title": {"en": "Electricity bill", "fi": "Sähkölasku"},
        "story": "The same kind of bill, a regular home bill, clearly higher than usual.",
        "signals": ["amount_above_usual"],
        "payee": "Esimerkki Energia Oy", "payee_address": ("Esimerkkiväylä 3", "00000 ESIMERKKILÄ"),
        "heading": "SÄHKÖLASKU", "iban": iban_for("00000000001002"), "reference": national_for("33004170926"),
        "invoice_date": date(2026, 9, 29), "due_date": date(2026, 10, 13), "invoice_no": "7731-0926",
        "customer_no": "3300417", "terms": "14 päivää netto",
        "rows": [("Sähköenergia 1.7.–31.8.2026, 1 512 kWh × 13,90 snt", "210.17"),
                 ("Perusmaksu 3 kk × 4,90 €", "14.70"),
                 ("Tasaus: arvioitua suurempi kulutus 1.4.–30.6.2026", "87.83")],
        "note": "Hinnat sisältävät arvonlisäveron. Tasauslasku: kulutus oli arviota suurempi.",
        "barcode": True,
    },
    {
        "sample_id": "sample_3", "language": "fi", "colour": (68, 78, 92),
        "title": {"en": "Repair company bill", "fi": "Remonttiyrityksen lasku"},
        "story": "A payee that is not among the regular bills, with a short payment term.",
        "signals": ["new_payee", "short_term"],
        "payee": "Esimerkki Remontti Oy", "payee_address": ("Esimerkkipolku 7", "00000 ESIMERKKILÄ"),
        "heading": "LASKU", "iban": iban_for("00000000001003"), "reference": rf_for("4720260929"),
        "invoice_date": date(2026, 9, 29), "due_date": date(2026, 10, 2), "invoice_no": "R-0929-17",
        "customer_no": "88213", "terms": "3 päivää netto",
        "rows": [("Kylpyhuoneen kosteusmittaus 29.9.2026", "189.00"),
                 ("Tiivistyskorjaus, työ 3 h × 65,00 €", "195.00"), ("Tarvikkeet", "102.00")],
        "note": "Huom. lyhyt maksuaika.",
        "barcode": True,
    },
    {
        "sample_id": "sample_4", "language": "en", "colour": (29, 79, 145),
        "title": {"en": "Water bill (in English)", "fi": "Vesilasku (englanniksi)"},
        "story": "A reference number with a wrong check digit and no barcode.",
        "signals": ["reference_check_failed"],
        "payee": "Esimerkki Vesi Oy", "payee_address": ("Esimerkkiranta 2", "00000 ESIMERKKILÄ"),
        "heading": "INVOICE", "iban": iban_for("00000000001004"),
        "reference": wrong_check_digit(national_for("5519032")),
        "invoice_date": date(2026, 9, 22), "due_date": date(2026, 10, 20), "invoice_no": "W-2026-3391",
        "customer_no": "551903", "terms": "28 days net",
        "rows": [("Water 1 Jun – 31 Aug 2026, 9 m³ × €2.95", "26.55"), ("Basic charge, 3 months × €5.40", "16.20")],
        "note": "Please pay with the reference number.",
        "barcode": False,
    },
]

# ---- drawing --------------------------------------------------------------------------------------------

INK, MUTED, RULE = (25, 28, 33), (95, 101, 110), (200, 204, 210)
FI_LABELS = {
    "invoice_date": "Laskun päivä", "invoice_no": "Laskun numero", "customer_no": "Asiakasnumero",
    "terms": "Maksuehto", "due_date": "Eräpäivä", "interest": "Viivästyskorko", "reminder": "Huomautusaika",
    "interest_value": "korkolain mukaan", "reminder_value": "8 päivää", "item": "Selite", "sum": "Määrä",
    "total": "Yhteensä", "payer": "Maksaja",
}
EN_LABELS = {
    "invoice_date": "Invoice date", "invoice_no": "Invoice number", "customer_no": "Customer number",
    "terms": "Payment terms", "due_date": "Due date (eräpäivä)", "interest": "Penalty interest (viivästyskorko)",
    "reminder": "Complaints within", "interest_value": "under the Interest Act", "reminder_value": "8 days",
    "item": "Description", "sum": "Amount", "total": "Total", "payer": "Bill to",
}


FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
]
FONTS: dict[bool, str] = {}


def choose_fonts(regular: str | None, bold: str | None) -> None:
    if regular:
        FONTS.update({False: regular, True: bold or regular})
        return
    for reg, bld in FONT_CANDIDATES:
        if Path(reg).is_file() and Path(bld).is_file():
            FONTS.update({False: reg, True: bld})
            return
    sys.exit("no TrueType font with ä, ö and € found; pass --font and --bold-font")


@functools.lru_cache(maxsize=None)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONTS[bold], size)


def money(value: str, language: str) -> str:
    whole, cents = f"{Decimal(value):.2f}".split(".")
    grouped = f"{int(whole):,}"
    return f"{grouped.replace(',', ' ')},{cents} €" if language == "fi" else f"€{grouped}.{cents}"


def day(d: date, language: str) -> str:
    return f"{d.day}.{d.month}.{d.year}" if language == "fi" else f"{d.day} {d.strftime('%B')} {d.year}"


class Page:
    def __init__(self) -> None:
        self.img = Image.new("RGB", (WIDTH, HEIGHT), "white")
        self.draw = ImageDraw.Draw(self.img)

    def text(self, xy, s, size=26, fill=INK, bold=False, anchor="la") -> None:
        self.draw.multiline_text(xy, s, font=font(size, bold), fill=fill, anchor=anchor, spacing=4) if "\n" in s \
            else self.draw.text(xy, s, font=font(size, bold), fill=fill, anchor=anchor)

    def line(self, x0, y0, x1, y1, fill=RULE, width=2) -> None:
        self.draw.line((x0, y0, x1, y1), fill=fill, width=width)

    def box(self, x0, y0, x1, y1, outline=INK, width=2) -> None:
        self.draw.rectangle((x0, y0, x1, y1), outline=outline, width=width)


def render(s: dict) -> Image.Image:
    lang = s["language"]
    L = FI_LABELS if lang == "fi" else EN_LABELS
    p = Page()
    total = f"{sum(Decimal(v) for _, v in s['rows']):.2f}"

    # header
    p.draw.rectangle((0, 0, WIDTH, 14), fill=s["colour"])
    p.text((70, 60), s["payee"], size=46, fill=s["colour"], bold=True)
    p.text((70, 120), ", ".join(s["payee_address"]), size=22, fill=MUTED)
    p.text((1130, 60), s["heading"], size=46, bold=True, anchor="ra")

    # payer and invoice details
    p.text((70, 220), L["payer"], size=20, fill=MUTED)
    for i, row in enumerate(PAYER):
        p.text((70, 252 + i * 36), row, size=28)
    details = [
        ("invoice_date", day(s["invoice_date"], lang)), ("invoice_no", s["invoice_no"]),
        ("customer_no", s["customer_no"]), ("terms", s["terms"]), ("due_date", day(s["due_date"], lang)),
        ("interest", L["interest_value"]), ("reminder", L["reminder_value"]),
    ]
    for i, (key, value) in enumerate(details):
        y = 220 + i * 40
        p.text((560, y), L[key], size=22, fill=MUTED)
        p.text((1130, y), value, size=24, bold=key == "due_date", anchor="ra")

    # rows and total
    y = 560
    p.text((70, y), L["item"], size=22, fill=MUTED)
    p.text((1130, y), L["sum"], size=22, fill=MUTED, anchor="ra")
    p.line(70, y + 38, 1130, y + 38, fill=INK)
    for i, (label, value) in enumerate(s["rows"]):
        ry = y + 60 + i * 48
        p.text((70, ry), label, size=26)
        p.text((1130, ry), money(value, lang), size=26, anchor="ra")
    ty = y + 60 + len(s["rows"]) * 48 + 10
    p.line(70, ty, 1130, ty, fill=INK)
    p.text((70, ty + 22), L["total"], size=30, bold=True)
    p.text((1130, ty + 22), money(total, lang), size=34, bold=True, anchor="ra")
    p.text((70, ty + 100), s["note"], size=24, fill=MUTED)

    # the payment slip
    form_top = 1110
    p.line(40, form_top - 30, WIDTH - 40, form_top - 30, fill=MUTED, width=1)
    if lang == "fi":
        p.text((70, form_top - 20), "TILISIIRTO  GIRERING", size=22, bold=True)
        labels = ("Saajan tilinumero\nMottagarens kontonummer", "Saaja\nMottagare",
                  "Maksajan nimi ja osoite\nBetalarens namn och adress",
                  "Viitenumero\nRef.nr", "Eräpäivä\nFörfallodag", "Euro")
    else:
        p.text((70, form_top - 20), "BANK TRANSFER", size=22, bold=True)
        labels = ("Payee's account\n(IBAN)", "Payee", "Payer", "Reference number\n(viitenumero)",
                  "Due date\n(eräpäivä)", "Amount\nEUR")
    top = form_top + 20
    bottom = top + 440
    p.box(60, top, 1140, bottom)
    p.line(60, top + 90, 1140, top + 90, fill=INK)          # under the account row
    p.line(60, top + 180, 1140, top + 180, fill=INK)        # under the payee row
    p.line(330, top, 330, bottom, fill=INK)                 # label column
    p.line(60, top + 320, 1140, top + 320, fill=INK)        # reference / due date / amount row
    for x in (650, 890, 990):
        p.line(x, top + 320, x, bottom, fill=INK)
    rows = [(top + 12, labels[0], format_iban(s["iban"])), (top + 102, labels[1], s["payee"])]
    for ly, label, value in rows:
        p.text((72, ly), label, size=18, fill=MUTED)
        p.text((350, ly + 22), value, size=30, bold=True)
    p.text((72, top + 192), labels[2], size=18, fill=MUTED)
    for i, row in enumerate(PAYER):
        p.text((350, top + 192 + i * 36), row, size=26)
    p.text((72, top + 332), labels[3], size=18, fill=MUTED)
    p.text((345, top + 380), format_reference(s["reference"]), size=28, bold=True)
    p.text((662, top + 332), labels[4], size=18, fill=MUTED)
    p.text((662, top + 380), day(s["due_date"], lang), size=26, bold=True)
    p.text((902, top + 332), labels[5], size=18, fill=MUTED)
    p.text((1125, top + 380), money(total, lang).replace(" €", "").replace("€", ""), size=30, bold=True,
           anchor="ra")

    if s["barcode_digits"]:
        p.text((70, bottom + 28), "Virtuaaliviivakoodi", size=20, fill=MUTED)
        p.text((70, bottom + 58), s["barcode_digits"], size=28)
    return p.img


# ---- output ---------------------------------------------------------------------------------------------


def main() -> None:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--font", help="a regular TrueType font with ä, ö and €")
    args.add_argument("--bold-font", help="its bold face")
    opts = args.parse_args()
    choose_fonts(opts.font, opts.bold_font)
    OUT.mkdir(parents=True, exist_ok=True)
    key = {
        "about": ("Synthetic sample bills of the demo gallery (#249), made by scripts/make_sample_bills.py. "
                  "`truth` is the answer key for tests and for checking a reading (#250); the service never "
                  "returns it as a reading result. `signals` are the warning signs of contracts/api.md "
                  "section 11.2 each bill should raise for the customer on the date below."),
        "customer_id": "CUST00860",
        "as_of": AS_OF.isoformat(),
        "samples": [],
    }
    for s in SAMPLES:
        amount = sum(Decimal(v) for _, v in s["rows"])
        s["barcode_digits"] = barcode_for(s["iban"], amount, s["reference"], s["due_date"]) if s["barcode"] else None
        img = render(s)
        png, pdf = OUT / f"{s['sample_id']}.png", OUT / f"{s['sample_id']}.pdf"
        img.quantize(colors=64, dither=Image.Dither.NONE).save(png, optimize=True)
        img.save(pdf, "PDF", resolution=DPI, title=s["title"]["en"], author="Synthetic demo data",
                 creationDate=FIXED, modDate=FIXED)
        key["samples"].append({
            "sample_id": s["sample_id"],
            "title": s["title"],
            "language": s["language"],
            "files": {"png": png.name, "pdf": pdf.name},
            "story": s["story"],
            "signals": s["signals"],
            "checks": {"iban": "pass" if valid_iban(s["iban"]) else "fail",
                       "reference": "pass" if valid_reference(s["reference"]) else "fail",
                       "barcode": "pass" if s["barcode_digits"] else "absent"},
            "truth": {
                "payee": s["payee"],
                "iban": s["iban"],
                "reference": s["reference"],
                "amount": f"{amount:.2f}",
                "due_date": s["due_date"].isoformat(),
                "invoice_date": s["invoice_date"].isoformat(),
                "barcode": s["barcode_digits"],
            },
        })
        print(f"{png.name}  {hashlib.sha256(png.read_bytes()).hexdigest()[:12]}  {s['payee']}  "
              f"{amount:.2f}  {s['due_date']}  {', '.join(s['signals']) or 'no warning sign'}")
    (OUT / "samples.json").write_text(json.dumps(key, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("samples.json written")


if __name__ == "__main__":
    main()
