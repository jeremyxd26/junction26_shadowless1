"""The machine-readable payment data of a Finnish invoice, read and checked by code alone (#241).

The virtual barcode (virtuaaliviivakoodi), the reference number (viitenumero) and the IBAN. No
database, no network, no model: a number taken from an invoice is either parsed and checked here or
typed and confirmed by the user.

Sources, all published by Finance Finland (www.finanssiala.fi):
- [BBG] Bank Bar Code Guide, version 5.3 (8 November 2012, corrected 21 October 2019):
  section 9 (symbol version 4), section 10 (symbol version 5), section 12 (example) and section 13
  (test invoices of both versions, used as test vectors).
- [REF] Forming a Finnish Reference Number (1 November 2009): the check digit.
- [CTG] Credit Transfer Guidelines, section 2.3 (account number) and section 2.9 (reference number).
- [RF] Structure of the RF Creditor Reference (ISO 11649) (October 2023), and Kansainvälisen
  viitenumeron (ISO 11649) rakenne ja tarkisteen laskenta (1 November 2009), page 3: the RF check digits.
- [IBAN] International Bank Account Number (IBAN) and Bank Identifier Code (BIC) in payment
  (5 July 2015), sections 1.1 and 1.2: the structure and the check of ISO 13616 as described there.

The virtual barcode is the 54 data digits of the bank bar code [BBG sections 9 and 10, "54"]; the
Code 128 start character, check character and stop character belong to the printed symbol only.

    version 4: version (1) "4" | IBAN without "FI" (16) | euros (6) | cents (2) | reserve (3) "000"
               | national reference with leading zeros (20) | due date YYMMDD (6)
    version 5: version (1) "5" | IBAN without "FI" (16) | euros (6) | cents (2)
               | RF reference without "RF" (23): its two check digits, then zeros, then the rest
               | due date YYMMDD (6)

- Amount: euros and cents of 00000000 mean that no amount is given: the payer chooses it, or it is
  above 999 999.99 [BBG section 9, "Euros"]. Then `amount` is None.
- Due date: 000000 means no due date [BBG section 9, "Due Date"]; then `due_date` is None. Otherwise
  it must be a real calendar date. Century rule: YY is the year 2000 + YY. The guide states no rule
  in words; its test invoices encode 31.1.2010 as 100131 and 24.12.2099 as 991224 [BBG sections 12,
  13.1 and 13.2], so 00 to 99 are the years 2000 to 2099.
- The IBAN of a barcode is always Finnish [BBG section 2: only for IBANs that begin with "FI"].
- Version 4 has 000 in its reserve field [BBG section 9, "Reserve"]. Any other value means the
  digits do not follow the layout of version 4, and the code is `barcode_version`.
- Version 5 reference field [BBG section 10]: "RF" and zeros after position 2 are removed when it is
  read, so RF04 9991 is 04000000000000000009991. An all-zero field is printed when the RF reference
  has letters; it carries no reference, and the code is `reference_check`.

Check digits:
- National reference [REF; CTG section 2.9]: 4 to 20 digits (at least three digits and the check
  digit, at most 19 + 1), leading zeros not counted. The digits are multiplied from right to left by
  7, 3, 1, 7, 3, 1, ...; the sum is subtracted from the next full ten; the difference is the check
  digit, and a difference of 10 gives 0.
- RF reference [RF]: "RF", two check digits, then 1 to 21 letters A-Z or digits (25 characters at
  most). Move the first four characters to the end, replace letters by numbers (A = 10 ... Z = 35);
  the number modulo 97 must be 1 (ISO/IEC 7064 MOD 97-10, the algorithm of the IBAN). Check digits
  are formed as 98 minus a remainder, so they lie between 02 and 98; 00, 01 and 99 are rejected.
  The RF part is not required to be a valid national reference (the RF calculation guide's own
  example RF712348231 is valid while 2348231 is not).
- IBAN [IBAN sections 1.1 and 1.2]: country code (two letters), two check digits, then letters or
  digits; the same rearrangement and modulo 97 test, check digits 02 to 98. At most 34 characters:
  the upper bound of ISO 13616 itself, which [IBAN] does not restate; it also keeps the arithmetic
  bounded. A Finnish IBAN is "FI", two check digits and 14 digits: 18 characters [IBAN section 1.1;
  CTG section 2.3]. Other countries' lengths are not checked.

Input: a space, a non-breaking space (U+00A0, U+202F) and a line break (CR, LF) are ignored wherever
they are. Anything else that is not an ASCII digit, or an ASCII letter where the format allows one,
is an error and is never dropped: a tab, a hyphen, and Unicode digits such as fullwidth or
Arabic-Indic ones are rejected, not converted. Letters may be lower case; they are upper-cased only
after this check.

What raises: `parse_virtual_barcode` raises BillFormatError with one of CODES and never returns an
unchecked field. `normalise_*` and `format_*` raise only for characters a format cannot contain (or
for empty input), with the code `iban_check` or `reference_check`; they do not check the check
digits, so a reference with a wrong check digit can still be shown. `valid_*` never raise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

__all__ = [
    "CODES", "BillFormatError", "ParsedBarcode", "parse_virtual_barcode", "normalise_iban", "valid_iban",
    "normalise_reference", "valid_reference", "format_iban", "format_reference",
]

CODES = ("barcode_length", "barcode_version", "barcode_chars", "iban_check", "reference_check", "due_date")

IGNORED = frozenset(" \u00a0\u202f\r\n")
_DIGITS = frozenset("0123456789")
_LETTERS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")
_ALNUM = _DIGITS | _LETTERS

BARCODE_LENGTH = 54
_IBAN = re.compile(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{1,30}")       # at most 34 characters
_FI_IBAN = re.compile(r"FI[0-9]{16}")
_NATIONAL = re.compile(r"[1-9][0-9]{3,19}")                  # 4 to 20 digits, no leading zero
_RF = re.compile(r"RF[0-9]{2}[A-Z0-9]{1,21}")
_WEIGHTS = (7, 3, 1)


class BillFormatError(ValueError):
    """A barcode, IBAN or reference that cannot be accepted; `code` is one of CODES."""

    code: str

    def __init__(self, code: str, message: str) -> None:
        assert code in CODES, code
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ParsedBarcode:
    version: int                 # 4 or 5
    iban: str                    # normalised, "FI" + 16 digits, no spaces
    amount: Decimal | None       # None when the barcode carries 0 (amount not given)
    reference: str               # normalised: national digits without leading zeros, or "RF.."
    due_date: date | None        # None when the barcode carries 000000


def _compact(text: str) -> str:
    return "".join(ch for ch in text if ch not in IGNORED)


def _mod97(text: str) -> int:
    """The number of an upper-case ASCII letters-and-digits string (A = 10 ... Z = 35), modulo 97."""
    return int("".join(str(ord(ch) - 55) if ch in _LETTERS else ch for ch in text)) % 97


def _mod97_valid(text: str) -> bool:
    """[IBAN 1.2; RF]: check digits 02 to 98, and the first four characters moved to the end give 1."""
    return 2 <= int(text[2:4]) <= 98 and _mod97(text[4:] + text[:4]) == 1


def _national_check_digit(stem: str) -> int:
    total = sum(int(d) * _WEIGHTS[i % 3] for i, d in enumerate(reversed(stem)))
    return (10 - total % 10) % 10


# ---- IBAN ---------------------------------------------------------------------------------------------

def normalise_iban(text: str) -> str:
    """No spaces, upper case. Raises BillFormatError("iban_check") for any other character."""
    s = _compact(text)
    if not s or any(ch not in _ALNUM for ch in s):
        raise BillFormatError("iban_check", "an IBAN has only the letters A-Z and the digits 0-9")
    return s.upper()


def valid_iban(text: str) -> bool:
    """Any country by modulo 97; a Finnish IBAN must also be "FI" and 16 digits."""
    try:
        s = normalise_iban(text)
    except BillFormatError:
        return False
    if not _IBAN.fullmatch(s) or (s.startswith("FI") and not _FI_IBAN.fullmatch(s)):
        return False
    return _mod97_valid(s)


def format_iban(text: str) -> str:
    """Groups of four from the left, as printed on a credit transfer form [IBAN 1.3.1]."""
    s = normalise_iban(text)
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4))


# ---- reference number -----------------------------------------------------------------------------------

def normalise_reference(text: str) -> str:
    """A national reference: its digits without leading zeros. An RF reference: "RF" and the rest as
    typed, upper case, no spaces. Raises BillFormatError("reference_check") for any other character or
    when nothing is left."""
    s = _compact(text)
    if s[:2] in ("RF", "Rf", "rF", "rf"):
        if any(ch not in _ALNUM for ch in s):
            raise BillFormatError("reference_check", "an RF reference has only the letters A-Z and the digits 0-9")
        return s.upper()
    if any(ch not in _DIGITS for ch in s):
        raise BillFormatError("reference_check", "a national reference has only the digits 0-9")
    s = s.lstrip("0")
    if not s:
        raise BillFormatError("reference_check", "no reference number")
    return s


def valid_reference(text: str) -> bool:
    """A national reference (4 to 20 digits, weights 7, 3, 1) or an RF reference (modulo 97)."""
    try:
        s = normalise_reference(text)
    except BillFormatError:
        return False
    if s.startswith("RF"):
        return bool(_RF.fullmatch(s)) and _mod97_valid(s)
    return bool(_NATIONAL.fullmatch(s)) and _national_check_digit(s[:-1]) == int(s[-1])


def format_reference(text: str) -> str:
    """National: groups of five from the right [CTG 2.9]. RF: groups of four from the left [RF]."""
    s = normalise_reference(text)
    if s.startswith("RF"):
        return " ".join(s[i:i + 4] for i in range(0, len(s), 4))
    head = len(s) % 5
    return " ".join(([s[:head]] if head else []) + [s[i:i + 5] for i in range(head, len(s), 5)])


# ---- virtual barcode --------------------------------------------------------------------------------------

def parse_virtual_barcode(text: str) -> ParsedBarcode:
    """The fields of a version 4 or 5 virtual barcode, every one checked; raises BillFormatError."""
    s = _compact(text)
    if any(ch not in _DIGITS for ch in s):
        raise BillFormatError("barcode_chars", "a virtual barcode has only the digits 0-9")
    if len(s) != BARCODE_LENGTH:
        raise BillFormatError("barcode_length", f"a virtual barcode has {BARCODE_LENGTH} digits")
    version = int(s[0])
    if version not in (4, 5):
        raise BillFormatError("barcode_version", "only versions 4 and 5 of the virtual barcode exist")

    iban = "FI" + s[1:17]
    if not valid_iban(iban):
        raise BillFormatError("iban_check", "the account number of the barcode fails its check")

    euros, cents = s[17:23], s[23:25]
    amount = None if euros + cents == "00000000" else Decimal(f"{int(euros)}.{cents}")

    if version == 4:
        if s[25:28] != "000":
            raise BillFormatError("barcode_version", "version 4 has 000 in its reserve field")
        reference = s[28:48].lstrip("0")
    else:
        field = s[25:48]
        rest = field[2:].lstrip("0")
        reference = "RF" + field[:2] + rest if rest else ""
    if not reference or not valid_reference(reference):
        raise BillFormatError("reference_check", "the reference number of the barcode fails its check")

    due_date = None
    if s[48:54] != "000000":
        try:
            due_date = date(2000 + int(s[48:50]), int(s[50:52]), int(s[52:54]))
        except ValueError:
            raise BillFormatError("due_date", "the due date of the barcode is not a calendar date") from None

    return ParsedBarcode(version=version, iban=iban, amount=amount, reference=reference, due_date=due_date)
