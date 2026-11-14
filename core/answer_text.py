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
fails.
A declared display is valid only if it equals what the server's formatter (core/tools/formatting)
writes for the object's value and unit, in English or Finnish (display_matches). No id shapes or lookbehind tricks are needed: an id, an IBAN or "EUR5000" fails because its
digits are left over.

A date expression needs a year: "15 Oct 2026", "October 15, 2026", "September 2026",
"1–15 Jun 2026", "1 Jun – 15 Aug 2026", "2026-10-15", "15.10.2026", "1.–15.6.2026",
"1.6.–15.8.2026", "1.10.2024–31.1.2025", "syyskuu 2026", "syyskuussa 2026", "15. lokakuuta 2026".

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
# After a day ("15. lokakuuta 2026") the month is in lower case; "10. Heinäkuussa" starts a new sentence.
MON_FI_LOWER = "(?-i:" + MON_FI + ")"


def _en(g: str) -> str:
    return MON_EN.format(g=g)


def _fi(g: str) -> str:
    return MON_FI.format(g=g)


def _fi_lower(g: str) -> str:
    return MON_FI_LOWER.format(g=g)


# Longest forms first; each match is removed before the next pattern runs.
DATE_PATTERNS = [
    ("date", rf"(?P<y>\d{{4}})-(?P<m>\d{{2}})-(?P<d>\d{{2}})"),
    ("range", rf"(?P<d1>\d{{1,2}})\.(?P<m1>\d{{1,2}})\.(?P<y1>\d{{4}}){_S}?{_D}{_S}?(?P<d2>\d{{1,2}})\.(?P<m2>\d{{1,2}})\.(?P<y>\d{{4}})"),
    ("range", rf"(?P<d1>\d{{1,2}})\.(?P<m1>\d{{1,2}})\.{_S}?{_D}{_S}?(?P<d2>\d{{1,2}})\.(?P<m2>\d{{1,2}})\.(?P<y>\d{{4}})"),
    ("range", rf"(?P<d1>\d{{1,2}})\.{_S}?{_D}{_S}?(?P<d2>\d{{1,2}})\.(?P<m>\d{{1,2}})\.(?P<y>\d{{4}})"),
    ("date", rf"(?P<d>\d{{1,2}})\.(?P<m>\d{{1,2}})\.(?P<y>\d{{4}})"),
    ("range", rf"(?P<d1>\d{{1,2}}){_S}+{_en('mn1')}(?:{_S}+(?P<y1>\d{{4}}))?{_S}?{_D}{_S}?(?P<d2>\d{{1,2}}){_S}+{_en('mn2')}{_S}+(?P<y>\d{{4}})"),
    ("range", rf"(?P<d1>\d{{1,2}}){_S}+{_en('mn1')}(?:{_S}+(?P<y1>\d{{4}}))?{_S}+and{_S}+(?P<d2>\d{{1,2}}){_S}+{_en('mn2')}{_S}+(?P<y>\d{{4}})"),
    ("range", rf"(?P<d1>\d{{1,2}}){_S}?{_D}{_S}?(?P<d2>\d{{1,2}}){_S}+{_en('mn')}{_S}+(?P<y>\d{{4}})"),
    ("range", rf"(?P<d1>\d{{1,2}})\.{_S}?{_D}{_S}?(?P<d2>\d{{1,2}})\.{_S}*{_fi_lower('mn')}{_S}+(?P<y>\d{{4}})"),
    ("date", rf"(?P<d>\d{{1,2}}){_S}+{_en('mn')},?{_S}+(?P<y>\d{{4}})"),
    ("date", rf"{_en('mn')}{_S}+(?P<d>\d{{1,2}}),{_S}+(?P<y>\d{{4}})"),
    ("date", rf"(?P<d>\d{{1,2}})\.{_S}*{_fi_lower('mn')}{_S}+(?P<y>\d{{4}})"),
    ("month", rf"{_en('mn')}{_S}+(?P<y>\d{{4}})"),
    ("month", rf"{_fi('mn')}{_S}+(?P<y>\d{{4}})"),
]
# Not part of a longer number or word, not after a dash or minus, and not money or a percentage:
# - before: no letter, digit, mark or dash glued to it, and no LEADING mark with one space ("€ 30",
#   "× 3"). A closing mark that follows an amount ("180,26 € 15.10.2026") is not leading: the
#   currency sign is then itself preceded by a digit and an optional space.
# - after: no letter, digit or mark glued to it, and no mark or unit word after one space
#   ("1 €", "1 %", "1 ‰", "1 ×", "1 euro", "1 EUR", "1 e", "1 USD", "1 cent", "1 senttiä", "1 percent",
#   "1 pct", "1 prosenttia", "1 x").
# Marks: currency, percent, per mille, the multiplication sign, "#" and "+" (PR #104 review).
MARKS = "€$%‰×#+"
_LEADING_MARK = rf"(?<!(?<!\d)(?<!\d )[{re.escape(MARKS)}] )"
_BEFORE = rf"(?<![\w{re.escape(MARKS)}.,{DASH_CLASS}]){_LEADING_MARK}"
_UNIT_WORD = r"(?i:eur\b|euro\w*|usd\b|e\b|x\b|cents?\b|sentti\w*|percent\w*|per cent|pct\b|prosent\w*)"
_AFTER = rf"(?![\w{re.escape(MARKS)}]|[.,]\d| ?[{re.escape(MARKS)}]| {_UNIT_WORD})"
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


# One main takeaway and at most one more short sentence (Renat's answer-length rule, #288): the rest
# stays on the cards and behind the chips. Shared by the pipeline (a longer model draft is rejected) and
# the eval (an answered outcome over it fails). The introduction and the decline texts are exempt.
MAX_SENTENCES = 2
MAX_SHORT_WORDS = 35
MAX_NUMBERS = 3
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
# Abbreviations whose dot ends no sentence ("approx. {{n1}}", "esim. ruoka").
_ABBREVIATION = re.compile(r"\b(approx|e\.g|i\.e|incl|esim|mm|n|ns|yms|jne|vs|etc)\.", re.I)


# Sentti never suggests borrowing (#419): a loan, credit, a credit card as a way to pay, instalments,
# financing, "buy now, pay later" or an overdraft, in a suggesting sense. Naming them is fine (the credit
# decision decline says "loan"; a repayment bill keeps its label); proposing them is not.
# A negation in the same clause turns a borrowing word into a statement: "I can't recommend taking a loan",
# "I would not use a credit card", "Älä ota lainaa" (review of #437). Also used by the cut-suggestion check.
NEGATION = re.compile(
    r"\b(?:not|never|cannot|no\s+need|no\s+reason\s+to|avoid\w*|instead\s+of|rather\s+than|ei|älä|älkää|en|et|eivät"
    r"|emme|ette"
    r"|ilman)\b|n['’]t\b|\bnothing\s+to\b", re.I)
# A negation that still suggests: "Why not take out a loan?", "Don't hesitate to use your credit card", "It's
# not a bad idea to…" (review of #437).
SUGGESTING_NEGATION = re.compile(
    r"\bwhy\s+not\b|\bdon['’]?t\s+(?:hesitate|forget|be\s+afraid)\b|\bnever\s+hesitate\b"
    r"|\bnot\s+(?:a\s+)?(?:bad|terrible|crazy)\s+(?:idea|option|choice|move)\b|\bnothing\s+wrong\s+with\b"
    r"|\bno\s+reason\s+not\s+to\b|\bno\s+reason\s+to\s+(?:hesitate|wait|delay)\b|\bmiksi\s+et\b|\bmiksei\b|\bälä\s+(?:epäröi|unohda|pelkää)\b"
    r"|\bei\s+(?:ole\s+)?(?:huono|hullu)\s+(?:idea|ajatus|vaihtoehto)\b"
    r"|\bcan['’]?t\s+go\s+wrong\b|\bcannot\s+go\s+wrong\b|\bwhy\s+(?:you\s+)?wouldn['’]?t\b|\bdon['’]?t\s+see\s+why\b",
    re.I)
# A borrowing question quoted back before a decline ("You asked whether to take a loan; I can't advise on
# that", "Kysyit, kannattaako ottaa lainaa; en voi neuvoa"): with a negation anywhere in the sentence, such a
# frame makes the words a quote, not a suggestion. A bare "if" is no frame: "If you do not have enough,
# consider a loan" suggests (review of #437).
QUOTING_FRAME = re.compile(
    r"\bwhether\b|\basked\b|\bask(?:ing)?\s+(?:about|if|whether)\b|\bquestion\s+(?:about|of|whether)\b"
    r"|\bkannattaako\b|\bkysyit\b|\bkysymy\w*|\bpitäisikö\b", re.I)
# The borrowing words as the subject of a negated predicate: "Taking a loan is not something I suggest".
_NEGATED_PREDICATE = re.compile(
    r"[^.!?;:,]*?\b(?:(?:is|are|was|would\s+be)\s+(?:not|never)|isn['’]t|aren['’]t|wasn['’]t|ei\s+ole)\b", re.I)
# A sentence that quotes the question back ("You asked whether to take a loan.") takes its decline from the
# next sentence ("I can't recommend that.") (review of #437).
_QUOTED_BACK = re.compile(r"\s*(?:you\s+asked|kysyit)\b", re.I)


def negated(clause: str) -> bool:
    """A clause with a negation that makes it a statement ("I can't recommend a loan"), not one that still
    suggests ("why not take a loan?")."""
    return bool(NEGATION.search(clause)) and not SUGGESTING_NEGATION.search(clause)


_CLAUSE_START = re.compile(r"[.!?;:,]|\b(?:but|so|mutta|joten|vaan)\b", re.I)
_CREDIT_DATA = r"(?!\s+(?:cards?|statements?|bills?|numbers?|purchases?|spending|transactions?|repayments?|payments?|fees?|interest|debt|balance|limits?))"
_BORROW_NOUN = (r"(?:(?:small|personal|short-term|quick|payday|consumer|cheap)\s+)?"
                r"(?:loans?|credit(?:\s+cards?|\s+line)?|overdraft\w*|instal{1,2}ment\s+plans?|instal{1,2}ments|financing)")
BORROWING_SUGGESTION = re.compile(
    r"\b(?:take|taking|get|getting|use|apply\s+for|applying\s+for|consider|try|open|opening|suggest|suggesting"
    r"|recommend|recommending"
    r"|(?:consider|try|start|recommend|suggest|by|keep|think\s+about)\s+using)\s+(?:out\s+)?"
    r"(?:a\s+|an\s+|your\s+|some\s+|the\s+)?" + _BORROW_NOUN + r"\b" + _CREDIT_DATA +
    r"|\b(?:an?\s+|your\s+|the\s+)?" + _BORROW_NOUN + r"\s+(?:could|can|would|might|may|will)\s+(?:\w+\s+)?"
    r"(?:cover|help|bridge|fill|tide|fund|pay\s+for|get\s+you|solve|ease|spread)\b"
    r"|\b" + _BORROW_NOUN + r"\s+(?:is|are|would\s+be|could\s+be|might\s+be|may\s+be)\s+(?:an?\s+|one\s+|another\s+"
    r"|your\s+|the\s+)?(?:\w+\s+)?(?:option|choice|way|solution|idea|route|answer|alternative)\b"
    r"|\b(?:loans?|credit|overdraft\w*|financing)\s+(?:is|are)\s+available\b"
    r"|\boffers?\s+(?:you\s+)?(?:an?\s+|some\s+)?(?:\w+\s+)?(?:loans?|credit|overdraft\w*|financing|instal{1,2}ments?)\b"
    + _CREDIT_DATA +
    r"|\bborrow(?:ing)?\b(?!\s+(?:decisions?|costs?))"
    r"|\bpay\s+(?:for\s+it\s+|it\s+|this\s+)?later\b(?!\s+(?:purchases?|services?|payments?|transactions?|bills?"
    r"|charges?|costs?))|\bpay\s+(?:for\s+it\s+|it\s+|this\s+)?in\s+instal{1,2}ments\b"
    r"|\bbuy\s+now,?\s+pay\s+later\b|\bbnpl\b|\bput\s+it\s+on\s+(?:a|your)\s+credit\s+card\b"
    r"|\bfinanc(?:e|ing)\s+(?:it|this|that|the\s+\w+)\b"
    r"|\b(?:ota|ottaa|otat|ottamalla|ottaisi\w*|hae|hakea|haet|hakisi\w*|käytä|käyttää|käytät|käyttäisi\w*"
    r"|harkitse|harkita)\s+(?:\w+\s+)?"
    r"(?:laina|lainaa|lainan|luottoa|luoton|luottokorttia|tililuottoa|osamaksu\w*|pikavippi\w*|rahoitusta"
    r"|kulutusluottoa)\b"
    r"|\blainaa\s+(?:rahaa|\w+(?:lta|ltä))\b"
    r"|\bosamaksulla\b|\bluottokortilla\b|\b(?:tili)?luotolla\b|\blainalla\b|\blainarahalla\b"
    r"|\bmaksa\s+myöhemmin\b|\blainaamalla\b|\blainata\b", re.I)


def _a_statement(text: str, m: re.Match) -> bool:
    """The borrowing words at `m` are a statement, not a suggestion (review of #437):
    - a negation in the same clause before them ("I can't recommend taking a loan", "Älä ota lainaa");
    - a quoting frame before them and a negation anywhere in the sentence ("You asked whether to take a loan;
      I can't advise on that", "En voi neuvoa, kannattaako ottaa lainaa");
    - they are the subject of a negated predicate ("Taking a loan is not something I suggest").
    A negation that still suggests ("why not", "can't go wrong") never makes a statement."""
    ends = [e.end() for e in _SENTENCE_END.finditer(text, 0, m.start())]
    sentence_start = ends[-1] if ends else 0
    after = _SENTENCE_END.search(text, m.end())
    sentence_end = after.end() if after else len(text)
    sentence = text[sentence_start:sentence_end]
    starts = [c.end() for c in _CLAUSE_START.finditer(text, sentence_start, m.start())]
    if negated(text[starts[-1] if starts else sentence_start:m.end()]):
        return True
    if QUOTING_FRAME.search(text, sentence_start, m.start()) and negated(sentence):
        return True
    if _QUOTED_BACK.match(sentence):
        following = _SENTENCE_END.search(text, sentence_end)
        if negated(text[sentence_end:following.end() if following else len(text)]):
            return True
    return bool(_NEGATED_PREDICATE.match(text, m.end(), sentence_end)) and not SUGGESTING_NEGATION.search(sentence)


def borrowing_suggestion(text: str, labels: Iterable[str] = ()) -> str | None:
    """The words in which a text suggests borrowing, or None. Labels from the user's own data (a
    category or bill such as "Loan repayment") are taken out first; a negation or a quoted-back question
    makes the words a statement (`_a_statement`, review of #437)."""
    for label in sorted((x for x in labels if x), key=len, reverse=True):
        text = re.sub(re.escape(label), " ", text, flags=re.I)
    for m in BORROWING_SUGGESTION.finditer(text):
        if not _a_statement(text, m):
            return m.group(0).strip()
    return None


def length_problems(text: str, numbers: int, displays: Iterable[str] = ()) -> list[str]:
    """Why a text breaks the answer-length rule, or []. `numbers` is how many numbers it states; each
    display (or a {{nK}} token) counts as one word, and so does each date or period ("1 Apr – 30 Sep
    2026" names one thing, so it is one word, and its dots end no sentence)."""
    plain = re.sub(r"\{\{n\d+\}\}", "NUM", text)   # one word; "N." would read as an abbreviation
    for d in sorted((d for d in displays if d), key=len, reverse=True):
        plain = plain.replace(d, "NUM")
    spans, blanked = find_dates(plain, blank_all=True)
    if spans:
        chars = list(blanked)
        for span in spans:   # one word in the place of each blanked expression
            at = normalise(plain).find(span.text)
            if at >= 0:
                n = min(4, len(span.text))
                chars[at:at + n] = list("DATE"[:n])
        plain = "".join(chars)
    plain = _ABBREVIATION.sub(lambda m: m.group(1).replace(".", ""), plain)
    problems = []
    sentences = len([s for s in _SENTENCE_END.split(plain) if s.strip()])
    if sentences > MAX_SENTENCES:
        problems.append(f"too long: {sentences} sentences, at most {MAX_SENTENCES}")
    words = len(plain.split())
    if words > MAX_SHORT_WORDS:
        problems.append(f"too long: {words} words, at most {MAX_SHORT_WORDS}")
    if numbers > MAX_NUMBERS:
        problems.append(f"too many numbers: {numbers}, at most {MAX_NUMBERS}; the cards show the rest")
    return problems


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


def formatted(value, unit: str, language: str, method: str | None = None) -> str:
    """What the server's formatter (core/tools/formatting.display) writes for this value, unit and
    method: the method decides some forms ("20%" for a typed cut, "32.3% more" for the peer gap)."""
    from decimal import Decimal

    from core.tools.formatting import display
    from core.tools.models import Unit

    return display(Decimal(str(value)), Unit(unit), language, method)


def _same(a: str, b: str) -> bool:
    # NFKC turns NBSP and NNBSP into spaces; the minus sign U+2212 is the same sign as a hyphen-minus.
    return normalise(a).replace("\u2212", "-") == normalise(b).replace("\u2212", "-")


def same_value(a, b, unit: str, method: str | None = None) -> bool:
    """Two values are the same number for the user: counts, days and months exactly; money and
    percentages when the formatter shows them the same for this method (no tolerance on the raw
    value, so 45.915, shown as 45.92, is not 45.91)."""
    if unit in ("count", "days", "months"):
        return float(a) == float(b)
    try:
        return formatted(a, unit, "en", method) == formatted(b, unit, "en", method)
    except (ValueError, ArithmeticError):
        return False


def display_matches(display: str, value: float, unit: str, language: str, method: str | None = None) -> bool:
    """A declared Number object's display is valid only if it EQUALS what the server's formatter
    writes for its value, unit and method in the answer's own language. A display is never free text, so
    no suffix or unit word is parsed: "1 euro" on a count or "€45.91 a year" on a monthly value never
    match, and "20.0%" for a cut the user typed (method user_input@1, shown as "20%") does not either.
    The language is required and only its form counts: "4,120" is 4120 in English but reads as 4.12 in
    Finnish, so a Finnish answer must say "4 120" (review of #128)."""
    if unit not in UNIT_MARKS or language not in ("en", "fi"):
        return False
    try:
        return _same(display or "", formatted(value, unit, language, method))
    except (ValueError, ArithmeticError):
        return False
