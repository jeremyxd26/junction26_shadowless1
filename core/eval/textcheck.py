"""Reading numbers, dates and ids out of an answer text, for the eval checks in run.py (R1).

- Date expressions are found first: ISO (2026-10-15), Finnish dotted dates and ranges (15.10.2026,
  1.–15.6.2026, 1.6.–15.8.2026), and dates written with month names in English or Finnish
  ("15 Oct 2026", "1–15 Jun 2026", "September 2026", "October 15, 2026", "syyskuu 2026",
  "15. lokakuuta 2026"). Only the digits inside such an expression may be date parts; a bare "30"
  or "2026" elsewhere is an ordinary number.
- Number tokens carry an explicit sign (hyphen-minus or U+2212 MINUS SIGN, not after a letter or
  digit) and the adjacent unit mark: € before or after the number, or %. English: 1,234.56 and
  12.5%; Finnish: 1 234,56 € and 12,5 % with a space, NBSP or NNBSP as thousands separator.
- Ids (customer, merchant, transaction, evidence, IBAN) are found by their shape, so they are
  reported as ids and not just as stray digits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

SPACES = "   "
DASH = r"\s?[–\-]\s?"
MONTHS_EN = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
             "october", "november", "december")
MONTH_EN = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|"
            r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?")
MONTH_FI = r"(?:tammi|helmi|maalis|huhti|touko|kesä|heinä|elo|syys|loka|marras|joulu)kuu\w*"

DATE_EXPRESSIONS = [re.compile(p, re.I) for p in (
    r"\b\d{4}-\d{2}-\d{2}\b",                                                   # 2026-10-15
    rf"\b\d{{1,2}}\.\d{{1,2}}\.{DASH}\d{{1,2}}\.\d{{1,2}}\.\d{{4}}\b",            # 1.6.–15.8.2026
    rf"\b\d{{1,2}}\.{DASH}\d{{1,2}}\.\d{{1,2}}\.\d{{4}}\b",                       # 1.–15.6.2026
    r"\b\d{1,2}\.\d{1,2}\.\d{4}\b",                                             # 15.10.2026
    rf"\b\d{{1,2}}\s+{MONTH_EN}(?:\s+\d{{4}})?{DASH}\d{{1,2}}\s+{MONTH_EN}\s+\d{{4}}\b",  # 1 Jun – 15 Aug 2026
    rf"\b\d{{1,2}}{DASH}\d{{1,2}}\s+{MONTH_EN}(?:\s+\d{{4}})?\b",               # 1–15 Jun 2026
    rf"\b\d{{1,2}}\s+{MONTH_EN}(?:,?\s+\d{{4}})?\b",                            # 15 Oct 2026, 15 October
    rf"\b{MONTH_EN}\s+\d{{1,2}},\s+\d{{4}}\b",                                  # October 15, 2026
    rf"\b{MONTH_EN}\s+\d{{4}}\b",                                               # September 2026
    rf"\b{MONTH_EN}\s+\d{{1,2}}\b(?![.,]\d)",                                   # October 15
    rf"(?:\b\d{{1,2}}\.{DASH})?\b\d{{1,2}}\.\s*{MONTH_FI}(?:\s+\d{{4}})?",       # 1.–15. kesäkuuta 2026
    rf"\b{MONTH_FI}\s+\d{{4}}\b",                                               # syyskuu 2026
)]

ID_PATTERN = re.compile(
    r"\b(?:CUST\d+|MRC-[A-Z]+-\d+|M\d{3,}|tx_\d+|ev_[0-9a-z]{6,}|ans_\w+|conv_\w+|card_\w+|FI\d{2}(?:\s?\d{4}){3,4}\d{0,2})\b",
    re.I)

NUMBER = {
    "en": re.compile(r"(?<![\w.,])(?P<sign>[-−])?(?P<pre>€\s?)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
                     r"(?P<post>\s?[€%])?"),
    "fi": re.compile(rf"(?<![\w.,])(?P<sign>[-−])?(?P<pre>€[{SPACES}]?)?"
                     rf"(?P<num>\d{{1,3}}(?:[{SPACES}]\d{{3}})+(?:,\d+)?|\d+(?:,\d+)?)(?P<post>[{SPACES}]?[€%])?"),
}


@dataclass(frozen=True)
class Token:
    value: float          # signed when the text has an explicit minus
    decimals: int
    mark: str | None      # "eur", "pct" or None
    explicit_minus: bool
    raw: str


def find_ids(text: str) -> list[str]:
    return [m.group(0) for m in ID_PATTERN.finditer(text)]


def date_expressions(text: str) -> tuple[list[tuple[str, list[int]]], str]:
    """(expressions with the integers inside them, the text with the expressions blanked out)."""
    found = []
    for rx in DATE_EXPRESSIONS:
        def take(m: re.Match) -> str:
            found.append((m.group(0), [int(d) for d in re.findall(r"\d+", m.group(0))]))
            return " " * len(m.group(0))
        text = rx.sub(take, text)
    return found, text


def numbers(text: str, lang: str) -> list[Token]:
    out = []
    for m in NUMBER[lang].finditer(text):
        raw = m.group("num")
        if lang == "en":
            raw = raw.replace(",", "")
        else:
            raw = re.sub(f"[{SPACES}]", "", raw).replace(",", ".")
        value = float(raw)
        minus = bool(m.group("sign"))
        pre, post = (m.group("pre") or "").strip(), (m.group("post") or "").strip()
        mark = "eur" if "€" in (pre + post) else "pct" if post == "%" else None
        out.append(Token(-value if minus else value, len(raw.split(".")[1]) if "." in raw else 0, mark, minus,
                         m.group(0)))
    return out


def date_parts(dates) -> set[int]:
    parts: set[int] = set()
    for d in dates:
        if isinstance(d, str):
            d = date.fromisoformat(d)
        parts |= {d.day, d.month, d.year}
    return parts


UNIT_MARK = {"eur": "eur", "eur_per_day": "eur", "eur_per_week": "eur", "eur_per_month": "eur",
             "eur_per_year": "eur", "percent": "pct", "percentile": None, "count": None, "days": None,
             "months": None}


def token_is(token: Token, value: float, unit: str, tol: float) -> bool:
    """The token states this value in this unit: the right mark, the right sign, within tolerance.
    A token without a minus may state a negative change by its size ("€12.34 less")."""
    if token.mark != UNIT_MARK[unit]:
        return False
    if token.explicit_minus and value >= 0:
        return False
    target = value if token.explicit_minus else abs(value)
    return abs(token.value - target) <= tol + 1e-9
