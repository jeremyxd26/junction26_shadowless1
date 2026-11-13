"""Which digits an answer text may contain: an allowlist by subtraction (R1).

Shared by the eval runner (core/eval/run.py) and the answer pipeline's output validator
(core/agent), so both apply the same rule. Standard library only.

The rule. Remove from the text
  (a) every exact `display` string of a Number object the answer declares, where it stands as a
      whole token: not glued to a letter, digit, currency or percent mark, and not after a dash or a
      minus sign (which would change what the number says); and
  (b) every whole date expression that parses to a real date, month or date range and equals a date
      or a period the tools returned (a date expression followed by € or % is not a date).
If ANY digit remains anywhere (glued to letters, inside an id, after a dash, in any unit), the text
fails. No id shapes or lookbehind tricks are needed: an id, an IBAN or "EUR5000" fails because its
digits are left over.

A date expression needs a year: "15 Oct 2026", "October 15, 2026", "September 2026",
"1–15 Jun 2026", "1 Jun – 15 Aug 2026", "2026-10-15", "15.10.2026", "1.–15.6.2026",
"1.6.–15.8.2026", "syyskuu 2026", "syyskuussa 2026", "15. lokakuuta 2026".

Known limits (documented, not chased): numbers written as words ("twice", "kolme"), and wrong
wording around a correct number ("per year" next to a monthly value, "rose" for a fall). In the
pipeline the unit and sign of the declared Number object guard the second.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

DASHES = "-‒–—−"          # hyphen-minus, figure dash, en dash, em dash, minus sign
SPACES = "   "                       # space, NBSP, NNBSP
DASH_CLASS = re.escape(DASHES)                # for use inside [...]: the hyphen escaped
_D = f"[{DASH_CLASS}]"
_S = f"[{SPACES}]"

MONTHS_EN = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTHS_EN.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
MONTHS_EN["sept"] = 9
MONTHS_FI = {stem: i + 1 for i, stem in enumerate(("tammi", "helmi", "maalis", "huhti", "touko", "kesä", "heinä",
                                                   "elo", "syys", "loka", "marras", "joulu"))}
MON_EN = r"(?P<{g}>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
MON_FI = r"(?P<{g}>tammi|helmi|maalis|huhti|touko|kesä|heinä|elo|syys|loka|marras|joulu)kuu\w*"


def _en(g: str) -> str:
    return MON_EN.format(g=g)


def _fi(g: str) -> str:
    return MON_FI.format(g=g)


# Longest forms first; each match is removed before the next pattern runs.
DATE_PATTERNS = [
    ("date", rf"(?P<y>\d{{4}})-(?P<m>\d{{2}})-(?P<d>\d{{2}})"),
    ("range", rf"(?P<d1>\d{{1,2}})\.(?P<m1>\d{{1,2}})\.{_S}?{_D}{_S}?(?P<d2>\d{{1,2}})\.(?P<m2>\d{{1,2}})\.(?P<y>\d{{4}})"),
    ("range", rf"(?P<d1>\d{{1,2}})\.{_S}?{_D}{_S}?(?P<d2>\d{{1,2}})\.(?P<m>\d{{1,2}})\.(?P<y>\d{{4}})"),
    ("date", rf"(?P<d>\d{{1,2}})\.(?P<m>\d{{1,2}})\.(?P<y>\d{{4}})"),
    ("range", rf"(?P<d1>\d{{1,2}}){_S}+{_en('mn1')}(?:{_S}+(?P<y1>\d{{4}}))?{_S}?{_D}{_S}?(?P<d2>\d{{1,2}}){_S}+{_en('mn2')}{_S}+(?P<y>\d{{4}})"),
    ("range", rf"(?P<d1>\d{{1,2}}){_S}?{_D}{_S}?(?P<d2>\d{{1,2}}){_S}+{_en('mn')}{_S}+(?P<y>\d{{4}})"),
    ("range", rf"(?P<d1>\d{{1,2}})\.{_S}?{_D}{_S}?(?P<d2>\d{{1,2}})\.{_S}*{_fi('mn')}{_S}+(?P<y>\d{{4}})"),
    ("date", rf"(?P<d>\d{{1,2}}){_S}+{_en('mn')},?{_S}+(?P<y>\d{{4}})"),
    ("date", rf"{_en('mn')}{_S}+(?P<d>\d{{1,2}}),{_S}+(?P<y>\d{{4}})"),
    ("date", rf"(?P<d>\d{{1,2}})\.{_S}*{_fi('mn')}{_S}+(?P<y>\d{{4}})"),
    ("month", rf"{_en('mn')}{_S}+(?P<y>\d{{4}})"),
    ("month", rf"{_fi('mn')}{_S}+(?P<y>\d{{4}})"),
]
# Not part of a longer number or word, not after a dash or minus, and not money or a percentage:
# no mark glued before it or one space before it, none glued after it or one space after it.
_BEFORE = rf"(?<![\w€$%.,{DASH_CLASS}])(?<![€$%] )"
_AFTER = r"(?![\w€$%]|[.,]\d| ?[€$%])"
DATE_RX = [(kind, re.compile(_BEFORE + p + _AFTER, re.I)) for kind, p in DATE_PATTERNS]


@dataclass(frozen=True)
class DateSpan:
    text: str
    start: date
    end: date
    returned: bool


def _month(word: str) -> int:
    word = word.lower().rstrip(".")
    if word in MONTHS_EN:
        return MONTHS_EN[word]
    return MONTHS_FI[word]


def _parse(kind: str, m: re.Match) -> tuple[date, date] | None:
    g = m.groupdict()
    try:
        y = int(g["y"])
        if kind == "date":
            month = int(g["m"]) if g.get("m") else _month(g["mn"])
            d = date(y, month, int(g["d"]))
            return d, d
        if kind == "month":
            month = _month(g["mn"])
            return date(y, month, 1), date(y, month, calendar.monthrange(y, month)[1])
        # range
        if g.get("m1"):
            m1, m2 = int(g["m1"]), int(g["m2"])
        elif g.get("mn1"):
            m1, m2 = _month(g["mn1"]), _month(g["mn2"])
        elif g.get("m"):
            m1 = m2 = int(g["m"])
        else:
            m1 = m2 = _month(g["mn"])
        y1 = int(g["y1"]) if g.get("y1") else y
        start, end = date(y1, m1, int(g["d1"])), date(y, m2, int(g["d2"]))
        return (start, end) if start <= end else None
    except (ValueError, KeyError, TypeError):
        return None  # not a real date: its digits stay in the text


def normalise(text: str) -> str:
    """NFKC: look-alike digits (superscript, circled, full-width, ...) become ASCII digits, and NBSP and
    NNBSP become plain spaces. Every text and display is normalised before it is read."""
    return unicodedata.normalize("NFKC", text or "")


def find_dates(text: str, dates: Iterable[date] = (), periods: Iterable[tuple[date, date]] = (), *,
               blank_all: bool = False) -> tuple[list[DateSpan], str]:
    """The date expressions of a text, each marked returned or not, and the text with the returned
    ones blanked out (all of them with blank_all). A date counts as returned if it is one of `dates`
    or a bound of a period; a month or a range only if it equals one of `periods`."""
    text = normalise(text)
    dates = set(dates)
    periods = set(periods)
    bounds = dates | {d for p in periods for d in p}
    chars = list(text)
    spans: list[DateSpan] = []
    kept: dict[int, str] = {}  # position -> text of an expression that was not returned
    for kind, rx in DATE_RX:
        for m in rx.finditer("".join(chars)):
            parsed = _parse(kind, m)
            if parsed is None:
                continue
            start, end = parsed
            returned = (start in bounds) if kind == "date" else ((start, end) in periods)
            spans.append(DateSpan(m.group(0), start, end, returned))
            if not returned and not blank_all:
                kept[m.start()] = m.group(0)
            # Blank the span so a shorter pattern cannot match inside it; kept ones come back below.
            chars[m.start():m.end()] = [" "] * (m.end() - m.start())
    for pos, original in kept.items():
        chars[pos:pos + len(original)] = list(original)
    return spans, "".join(chars)


def remove_displays(text: str, displays: Iterable[str]) -> str:
    """Blank out each display string where it stands as a whole token (longest first): not glued to a
    letter or digit, not after a dash or minus, and with no € or % before or after it (with or
    without one space), so a declared count "1" cannot be reused as "1 €" or "1 %"."""
    text = normalise(text)
    for display in sorted({normalise(d) for d in displays if d}, key=len, reverse=True):
        rx = re.compile(_BEFORE + re.escape(display) + _AFTER)
        text = rx.sub(lambda m: " " * len(m.group(0)), text)
    return text


def shows(text: str, display: str, dates: Iterable[date] = (), periods: Iterable[tuple[date, date]] = ()) -> bool:
    """The display stands in the text as a whole token, outside the returned date expressions."""
    _, rest = find_dates(text, dates, periods)
    return remove_displays(rest, [display]) != normalise(rest)


def leftover_digits(text: str, *, displays: Iterable[str] = (), dates: Iterable[date] = (),
                    periods: Iterable[tuple[date, date]] = ()) -> list[str]:
    """Problems: date expressions that were not returned, then every run of digits that is left after
    removing the declared displays and the returned date expressions. Empty when the text is clean."""
    problems = []
    # Dates first: a declared count such as "30" must not take the day out of "1 Jul – 30 Sep 2026".
    spans, text = find_dates(text, dates, periods)
    text = remove_displays(text, displays)
    for span in spans:
        if not span.returned:
            problems.append(f"the date '{span.text}' was not returned by a tool")
    for m in re.finditer(r"\S*\d\S*", text):
        problems.append(f"digits that are not a declared number or a returned date: '{m.group(0)}'")
    return problems


# ---- reading numbers ------------------------------------------------------------------------------

NUMBER_RX = re.compile(rf"(?P<sign>[{DASH_CLASS}])?{_S}?(?P<pre>€{_S}?)?(?P<num>\d+(?:[{SPACES},.]\d+)*)(?P<post>{_S}?[€%])?")


def parse_number(raw: str, language: str) -> float:
    if language == "fi":
        return float(re.sub(f"[{SPACES}]", "", raw).replace(",", "."))
    return float(raw.replace(",", ""))


def parse_display(display: str, language: str) -> tuple[float, str | None] | None:
    """(signed value, mark) of a display string such as "€1,234.56", "-1 234,56 €", "18,9 %" or "3".
    The mark is "eur", "pct" or None. None when the string is not one number."""
    m = re.fullmatch(rf"{_S}*" + NUMBER_RX.pattern + rf"{_S}*", normalise(display))
    if not m:
        return None
    try:
        value = parse_number(m.group("num"), language)
    except ValueError:
        return None
    marks = (m.group("pre") or "") + (m.group("post") or "")
    mark = "eur" if "€" in marks else "pct" if "%" in marks else None
    return (-value if m.group("sign") else value), mark


def scan_numbers(text: str, language: str) -> list[tuple[float, str | None]]:
    """(value, mark) of every number in a free text, for numbers the user typed in a question."""
    _, text = find_dates(text, blank_all=True)
    out = []
    for m in NUMBER_RX.finditer(text):
        try:
            value = parse_number(m.group("num"), language)
        except ValueError:
            continue
        marks = (m.group("pre") or "") + (m.group("post") or "")
        out.append((value, "eur" if "€" in marks else "pct" if "%" in marks else None))
    return out


UNIT_MARKS = {"eur": {"eur"}, "eur_per_day": {"eur"}, "eur_per_week": {"eur"}, "eur_per_month": {"eur"},
              "eur_per_year": {"eur"}, "percent": {"pct"}, "percentile": {"pct", None}, "count": {None},
              "days": {None}, "months": {None}}


def display_matches(display: str, value: float, unit: str, language: str, tolerance: float = 0.005) -> bool:
    """The display string states this value, with this unit's mark and the right sign."""
    parsed = parse_display(display, language)
    if parsed is None or unit not in UNIT_MARKS:
        return False
    shown, mark = parsed
    return mark in UNIT_MARKS[unit] and abs(shown - float(value)) <= tolerance + 1e-9
