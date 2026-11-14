"""The bill parser (#241): vectors from the cited Finance Finland documents, and everything else built
by an independent second implementation in this file (never by the functions under test)."""

from __future__ import annotations

import dataclasses
import itertools
import random
import string
from datetime import date
from decimal import Decimal

import pytest

from core.bills.parse import (
    CODES, BillFormatError, ParsedBarcode, format_iban, format_reference, normalise_iban, normalise_reference,
    parse_virtual_barcode, valid_iban, valid_reference,
)

# ---- the second implementation ---------------------------------------------------------------------------
# Written from the same documents, in another shape: the remainder modulo 97 is taken piecewise, seven
# digits at a time, and the 7-3-1 check digit is "the next full ten minus the sum", as the reference
# guide words it. The module under test does neither.

_VALUE = {ch: str(n) for n, ch in enumerate(string.ascii_uppercase, start=10)}


def mod97(text: str) -> int:
    digits = "".join(_VALUE.get(ch, ch) for ch in text)
    rem = 0
    for i in range(0, len(digits), 7):
        rem = int(f"{rem}{digits[i:i + 7]}") % 97
    return rem


def iban_of(country: str, bban: str) -> str:
    return f"{country}{98 - mod97(bban + country + '00'):02d}{bban}"


def rf_of(body: str) -> str:
    return f"RF{98 - mod97(body + 'RF00'):02d}{body}"


def national_of(stem: str) -> str:
    total = sum(int(d) * w for d, w in zip(reversed(stem), itertools.cycle((7, 3, 1))))
    diff = (total // 10 + 1) * 10 - total
    return stem + str(0 if diff == 10 else diff)


def barcode(version: int, iban: str, cents: int, reference: str, due: date | None, reserve: str = "000") -> str:
    """The 54 digits laid out as in the Bank Bar Code Guide, sections 9 and 10."""
    euros, rest = divmod(cents, 100)
    if version == 5:
        ref = reference[2:4] + reference[4:].rjust(21, "0")
    else:
        ref = reserve + reference.rjust(20, "0")
    return f"{version}{iban[2:]}{euros:06d}{rest:02d}{ref}{'000000' if due is None else due.strftime('%y%m%d')}"


def code128_check(digits: str) -> int:
    """Check digit 2 of the printed symbol (guide section 12): start 105 and the value pairs, weights 1, 1, 2..."""
    pairs = [int(digits[i:i + 2]) for i in range(0, len(digits), 2)]
    return (105 + sum(n * p for n, p in enumerate(pairs, start=1))) % 103


# ---- the guide's test invoices (Bank Bar Code Guide 5.3, sections 13.1 and 13.2) -----------------------
# digits as listed, then the plain-text fields above each one, then the printed Code 128 check digit.

GUIDE = [
    ("479440520200360820048831500000000868516259619897100612", 4, "FI79 4405 2020 0360 82", "4883.15",
     "86851 62596 19897", date(2010, 6, 12), 40),
    ("458101710000001220004829900000000559582243294671120131", 4, "FI58 1017 1000 0001 22", "482.99",
     "55958 22432 94671", date(2012, 1, 31), 55),
    ("402500046400013020006938000000069875672083435364110724", 4, "FI02 5000 4640 0013 02", "693.80",
     "69 87567 20834 35364", date(2011, 7, 24), 14),
    ("415660100015306410074445400000007758474790647489191219", 4, "FI15 6601 0001 5306 41", "7444.54",
     "7 75847 47906 47489", date(2019, 12, 19), 63),
    ("416800014000502670009358500000078777679656628687000000", 4, "FI16 8000 1400 0502 67", "935.85",
     "78 77767 96566 28687", None, 30),
    ("473313130010000580000000000000000000000000868624130809", 4, "FI73 3131 3001 0000 58", None,
     "8 68624", date(2013, 8, 9), 68),
    ("483330100011007751500002000092125374252539897737160525", 4, "FI83 3301 0001 1007 75", "150000.20",
     "92125 37425 25398 97737", date(2016, 5, 25), 45),
    ("439363630020924920000010300000000000000590738390230311", 4, "FI39 3636 3002 0924 92", "1.03",
     "5907 38390", date(2023, 3, 11), 9),
    ("492393900010033910000000200000000000000001357914991224", 4, "FI92 3939 0001 0033 91", "0.02",
     "13 57914", date(2099, 12, 24), 30),
    ("579440520200360820048831509000000868516259619897100612", 5, "FI79 4405 2020 0360 82", "4883.15",
     "RF09 8685 1625 9619 897", date(2010, 6, 12), 74),
    ("558101710000001220004829906000000559582243294671100131", 5, "FI58 1017 1000 0001 22", "482.99",
     "RF06 5595 8224 3294 671", date(2010, 1, 31), 31),
    ("502500046400013020006938061000000000698756720839110724", 5, "FI02 5000 4640 0013 02", "693.80",
     "RF61 6987 5672 0839", date(2011, 7, 24), 59),
    ("515660100015306410074445484000007758474790647489191219", 5, "FI15 6601 0001 5306 41", "7444.54",
     "RF84 7758 4747 9064 7489", date(2019, 12, 19), 16),
    ("516800014000502670009358560000078777679656628687000000", 5, "FI16 8000 1400 0502 67", "935.85",
     "RF60 7877 7679 6566 2868 7", None, 15),
    ("573313130010000580000000010000000000000000868624130809", 5, "FI73 3131 3001 0000 58", None,
     "RF10 8686 24", date(2013, 8, 9), 91),
    ("583330100011007751500002071092125374252539897737160525", 5, "FI83 3301 0001 1007 75", "150000.20",
     "RF71 9212 5374 2525 3989 7737", date(2016, 5, 25), 80),
    ("539363630020924920000010366000000000000590738390230311", 5, "FI39 3636 3002 0924 92", "1.03",
     "RF66 5907 3839 0", date(2023, 3, 11), 10),
    ("592393900010033910000000295000000000000001357914991224", 5, "FI92 3939 0001 0033 91", "0.02",
     "RF95 1357 914", date(2099, 12, 24), 33),
]
# Version 5 invoice no. 3 was corrected in 2019 (the guide's version history). Its digits agree with its
# plain-text fields, but the Code 128 check digit printed next to them (59) does not; the digits give 34.
# That check digit belongs to the printed symbol, not to the 54 digits, so only this assertion skips it.
CHECK_ERRATUM = "502500046400013020006938061000000000698756720839110724"


@pytest.mark.parametrize("digits,version,iban,amount,reference,due,_", GUIDE, ids=[f"v{g[1]}-{n % 9 + 1}" for n, g in enumerate(GUIDE)])
def test_the_guide_test_invoices(digits, version, iban, amount, reference, due, _):
    got = parse_virtual_barcode(digits)
    assert got == ParsedBarcode(version=version, iban=iban.replace(" ", ""),
                                amount=None if amount is None else Decimal(amount),
                                reference=reference.replace(" ", ""), due_date=due)
    assert (format_iban(got.iban), format_reference(got.reference)) == (iban, reference)   # as printed
    cents = 0 if amount is None else int(Decimal(amount) * 100)
    assert barcode(version, got.iban, cents, got.reference, due) == digits                 # the other way round


def test_the_guide_digits_are_transcribed_exactly():
    """Each listed string reproduces the guide's printed Code 128 check digit (one erratum, see above)."""
    for digits, *_, check in GUIDE:
        assert len(digits) == 54
        if digits != CHECK_ERRATUM:
            assert code128_check(digits) == check, digits
    assert code128_check(CHECK_ERRATUM) == 34


def test_the_section_12_example_with_its_spaces():
    got = parse_virtual_barcode("5 5810171000000122 00048299 06000000559582243294671 100131")
    assert (got.version, got.iban, got.amount, got.reference, got.due_date) == (
        5, "FI5810171000000122", Decimal("482.99"), "RF06559582243294671", date(2010, 1, 31))


# ---- examples from the reference, RF and IBAN documents ---------------------------------------------------

def test_reference_examples_from_the_documents():
    # Forming a Finnish Reference Number: stem 123456 -> 1234561; Credit Transfer Guidelines 2.9.
    assert national_of("123456") == "1234561"
    for text in ("1234561", "12 34561", "00000000000001234561"):
        assert valid_reference(text) and normalise_reference(text) == "1234561"
    assert format_reference("00000000000001234561") == "12 34561"
    # RF calculation guide, page 3: 2348236 -> RF33 2348 236, and the check of RF712348231.
    assert rf_of("2348236") == "RF332348236"
    for text in ("RF332348236", "RF33 2348 236", "RF712348231"):
        assert valid_reference(text)
    assert format_reference("RF332348236") == "RF33 2348 236"
    assert valid_reference("2348236") and not valid_reference("2348231")   # RF does not need the national check
    # Structure of the RF Creditor Reference: letters allowed; Bank Bar Code Guide 10: RF04 9991.
    for text in ("RF54 1234", "RF98 REF1 234", "RF04 9991"):
        assert valid_reference(text)
    assert normalise_reference("RF98 REF1 234") == "RF98REF1234"


def test_iban_examples_from_the_documents():
    # IBAN and BIC in payment 1.2 and 1.3; Credit Transfer Guidelines 2.3.
    for text in ("FI2112345600000785", "FI21 1234 5600 0007 85", "FI5542345670000081", "FI7536363001154921",
                 "SE3550000000054910000003", "DK5000400440116243", "DE89370400440532013000", "NL39RABO0300065264"):
        assert valid_iban(text), text
    assert format_iban("FI5542345670000081") == "FI55 4234 5670 0000 81"
    # IBAN and BIC 1.3.1 prints the electronic format with one zero missing (17 characters): not a Finnish IBAN.
    assert not valid_iban("FI211234560000785")


# ---- generated vectors ----------------------------------------------------------------------------------

RNG = random.Random(241)


def random_digits(n: int) -> str:
    return "".join(RNG.choice(string.digits) for _ in range(n))


NATIONALS = [national_of(str(RNG.randint(1, 9)) + random_digits(RNG.randint(2, 18))) for _ in range(150)]
RF_DIGITS = [rf_of(str(RNG.randint(1, 9)) + random_digits(RNG.randint(0, 20))) for _ in range(100)]
RF_ALNUM = [rf_of("".join(RNG.choice(string.ascii_uppercase + string.digits) for _ in range(RNG.randint(1, 21))))
            for _ in range(100)]
FI_IBANS = [iban_of("FI", random_digits(14)) for _ in range(150)]
OTHER_IBANS = [iban_of(RNG.choice(["DE", "SE", "NL", "EE", "GB"]),
                       "".join(RNG.choice(string.ascii_uppercase + string.digits) for _ in range(RNG.randint(10, 30))))
               for _ in range(100)]


def test_generated_references_and_ibans_are_valid():
    assert all(valid_reference(r) for r in NATIONALS + RF_DIGITS + RF_ALNUM)
    assert all(valid_iban(i) for i in FI_IBANS + OTHER_IBANS)
    assert all(normalise_reference(r) == r for r in NATIONALS + RF_DIGITS + RF_ALNUM)


def test_generated_barcodes_round_trip():
    for n in range(300):
        version = 4 if n % 2 else 5
        iban = FI_IBANS[n % len(FI_IBANS)]
        reference = NATIONALS[n % len(NATIONALS)] if version == 4 else RF_DIGITS[n % len(RF_DIGITS)]
        cents = RNG.choice([0, 1, 99, 100, RNG.randint(1, 99_999_999)])
        due = None if n % 7 == 0 else date.fromordinal(RNG.randint(date(2000, 1, 1).toordinal(),
                                                                    date(2099, 12, 31).toordinal()))
        got = parse_virtual_barcode(barcode(version, iban, cents, reference, due))
        assert got == ParsedBarcode(version, iban, None if cents == 0 else Decimal(cents) / 100, reference, due)


def test_changing_any_single_digit_invalidates():
    """Every digit position of a valid IBAN or reference, every other digit: never valid."""
    def mutations(text: str):
        for i, ch in enumerate(text):
            if ch in string.digits:
                for d in string.digits.replace(ch, ""):
                    yield text[:i] + d + text[i + 1:]

    ibans = ["FI2112345600000785", "FI7536363001154921", "DE89370400440532013000", "NL39RABO0300065264"]
    references = ["1234561", "2348236", "92125374252539897737", "RF332348236", "RF98REF1234", "RF7192125374252539897737"]
    for text in ibans + FI_IBANS[:40] + OTHER_IBANS[:20]:
        assert not any(valid_iban(m) for m in mutations(text)), text
    for text in references + NATIONALS[:40] + RF_DIGITS[:20] + RF_ALNUM[:20]:
        assert not any(valid_reference(m) for m in mutations(text)), text


def test_check_digits_outside_02_to_98_are_rejected():
    """98 minus a remainder is 02..98: 00, 01 and 99 pass the bare modulo test for some numbers, never the check."""
    found = {}
    for n in itertools.count():
        bban = f"{n:014d}"
        check = int(iban_of("FI", bban)[2:4])
        if check in (2, 97, 98):
            found.setdefault(check, bban)
        if len(found) == 3:
            break
    for check, alias in ((2, "99"), (97, "00"), (98, "01")):
        twin = f"FI{alias}{found[check]}"
        assert mod97(twin[4:] + twin[:4]) == 1 and not valid_iban(twin)
    body = next(b for b in (str(n) for n in itertools.count(1)) if rf_of(b)[2:4] == "02")
    assert valid_reference(f"RF02{body}") and not valid_reference(f"RF99{body}")


# ---- every error code -------------------------------------------------------------------------------------

V4 = GUIDE[0][0]
V5 = GUIDE[9][0]
IBAN4 = "FI7944052020036082"


def code_of(text: str) -> str:
    with pytest.raises(BillFormatError) as err:
        parse_virtual_barcode(text)
    return err.value.code


def test_the_codes_are_the_interface():
    assert CODES == ("barcode_length", "barcode_version", "barcode_chars", "iban_check", "reference_check", "due_date")
    err = BillFormatError("due_date", "x")
    assert isinstance(err, ValueError) and err.code == "due_date"


@pytest.mark.parametrize("bad", ["X", "４", "٤", "\t", "-", "."])
def test_barcode_chars(bad):
    assert code_of(V4[:10] + bad + V4[11:]) == "barcode_chars"          # replaced, never dropped
    assert code_of(V4[:10] + bad + V4[10:]) == "barcode_chars"          # inserted, never dropped


def test_barcode_length():
    assert code_of(V4[:-1]) == "barcode_length"
    assert code_of(V4 + "0") == "barcode_length"
    assert code_of("") == "barcode_length"
    assert code_of(" \n ") == "barcode_length"


def test_barcode_version():
    for version in "0123689":
        assert code_of(version + V4[1:]) == "barcode_version"
    reserve = barcode(4, IBAN4, 488315, "868516259619897", date(2010, 6, 12), reserve="001")
    assert code_of(reserve) == "barcode_version"                         # version 4 has 000 in the reserve


def test_iban_check():
    flipped = V4[:5] + str((int(V4[5]) + 1) % 10) + V4[6:]
    assert code_of(flipped) == "iban_check"
    assert code_of(barcode(4, "FI" + "0" * 16, 100, "1234561", None)) == "iban_check"   # never zero


def test_reference_check():
    assert code_of(V4[:47] + str((int(V4[47]) + 1) % 10) + V4[48:]) == "reference_check"   # national check digit
    assert code_of(V5[:25] + "10" + V5[27:]) == "reference_check"                         # RF check digits
    assert code_of(barcode(4, IBAN4, 100, "0", None)) == "reference_check"                # all zeros
    assert code_of(barcode(4, IBAN4, 100, national_of("12"), None)) == "reference_check"  # 3 digits: too short
    zero_filled = V5[:25] + "0" * 23 + V5[48:]                                           # an RF with letters
    assert code_of(zero_filled) == "reference_check"
    assert code_of(V5[:25] + "09" + "0" * 21 + V5[48:]) == "reference_check"             # check digits only


@pytest.mark.parametrize("due", ["990231", "991301", "990100", "000100", "000001", "230229"])
def test_due_date(due):
    assert code_of(V4[:48] + due) == "due_date"


def test_amount_zero_date_zero_leading_zeros_and_rf():
    got = parse_virtual_barcode(barcode(4, IBAN4, 0, "0000" + "1234561", None))
    assert (got.amount, got.due_date, got.reference) == (None, None, "1234561")
    leap = parse_virtual_barcode(V4[:48] + "240229")
    assert leap.due_date == date(2024, 2, 29) and leap.amount == Decimal("4883.15")
    assert all(parse_virtual_barcode(g[0]).amount.as_tuple().exponent == -2 for g in GUIDE if g[3])   # cents kept
    rf = parse_virtual_barcode(barcode(5, IBAN4, 1, "RF049991", date(2026, 10, 15)))
    assert (rf.amount, rf.reference, rf.due_date) == (Decimal("0.01"), "RF049991", date(2026, 10, 15))


def test_the_result_is_frozen():
    got = parse_virtual_barcode(V4)
    with pytest.raises(dataclasses.FrozenInstanceError):
        got.amount = Decimal("1")


# ---- input handling ------------------------------------------------------------------------------------

def test_spaces_non_breaking_spaces_and_line_breaks_are_ignored():
    spaced = "\u00a0".join([V4[:1], V4[1:17]]) + " " + V4[17:25] + "\u202f" + V4[25:48] + "\r\n" + V4[48:] + "\n"
    assert parse_virtual_barcode(spaced) == parse_virtual_barcode(V4)
    assert valid_iban("FI21\u00a01234 5600\n0007\r\n85") and valid_reference(" 12\u00a034561\n")
    assert normalise_iban(" fi21 1234 5600 0007 85 ") == "FI2112345600000785"     # lower case is upper-cased


@pytest.mark.parametrize("bad", ["\t", "-", ".", "\u2003", "\u200b"])
def test_other_characters_are_errors_not_dropped(bad):
    iban = "FI21" + bad + "12345600000785"
    assert not valid_iban(iban)
    with pytest.raises(BillFormatError) as err:
        normalise_iban(iban)
    assert err.value.code == "iban_check"
    assert not valid_reference("12" + bad + "34561") and not valid_reference("RF33" + bad + "2348236")
    with pytest.raises(BillFormatError) as err:
        normalise_reference("12" + bad + "34561")
    assert err.value.code == "reference_check"


@pytest.mark.parametrize("digit", ["２", "٢", "۲", "२", "²"])
def test_unicode_digits_are_rejected_not_converted(digit):
    assert not valid_iban("FI" + digit + "112345600000785")
    assert not valid_reference("1" + digit + "34561") and not valid_reference("RF33" + digit + "348236")
    assert code_of(V4[:30] + digit + V4[31:]) == "barcode_chars"


def test_letters_that_only_look_ascii_are_rejected():
    assert not valid_iban("\ufb012112345600000785")                     # the "fi" ligature, upper-cases to "FI"
    assert not valid_reference("\u0280F332348236")                       # a small-capital R
    assert valid_iban("fi2112345600000785") and normalise_reference("rf33 2348 236") == "RF332348236"


def test_normalise_and_format_do_not_need_a_valid_check_digit():
    """A reference with a wrong check digit can still be shown (only valid_* and the parser check it)."""
    assert valid_reference("1234561") and not valid_reference("1234562")
    assert format_reference("1234562") == "12 34562" and normalise_reference("0001234562") == "1234562"
    assert format_iban("FI2112345600000786") == "FI21 1234 5600 0007 86"
    assert normalise_reference("RF 0400 0099 91") == "RF0400009991"     # a typed RF stays as typed
    assert valid_reference("RF0400009991")
    for text in ("", "0000", "  "):
        with pytest.raises(BillFormatError):
            normalise_reference(text)
        assert not valid_reference(text)
    with pytest.raises(BillFormatError):
        normalise_iban("")


def test_huge_input_is_refused_not_crashed():
    """valid_* never raise: a pasted wall of digits is longer than any IBAN or reference."""
    assert not valid_iban("FI21" + "1" * 5000) and not valid_reference("1" * 5000)
    assert not valid_reference("RF33" + "1" * 5000)
    assert code_of("4" * 5000) == "barcode_length"
