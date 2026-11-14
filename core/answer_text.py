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


# The answer-length rule (Renat's decision of 14 Nov 12:10, #572, after #288's two sentences): the main takeaway
# first, then at most two more short sentences; a why/how answer and a general money answer may have four. The rest
# stays on the cards and behind the chips. Shared by the pipeline (a longer model draft is rejected) and the eval (an
# answered outcome over it fails). The introduction and the decline texts are exempt.
MAX_SENTENCES = 3
MAX_SENTENCES_LONG = 4                   # kind "why" or "general"
MAX_SHORT_WORDS = 55
MAX_LONG_WORDS = 75
MAX_NUMBERS = 3
LONG_KINDS = ("why", "general")
# The templates keep their own budget (#288): two short sentences and about 35 words, so no template answer changes
# with this rule (#572); a template that fits a line only when it stays within it asks with kind "template".
MAX_TEMPLATE_SENTENCES = 2
MAX_TEMPLATE_WORDS = 35
# A why or how question ("why is it lower?", "how does an e-invoice work?", "miksi…", "miten…"); "how much" and
# "how many" ask an amount, so they stay ordinary.
WHY_HOW = re.compile(r"\bwhy\b|\bhow come\b|\bhow (?!much\b|many\b|long\b)\w+|\bmiksi\b|\bmiten\b|\bminkä takia\b",
                     re.I)


def answer_kind(question: str, general: bool = False) -> str:
    """The length rule's kind of an answer: "general" (a general money answer, #572), "why" (a why or how question)
    or "ordinary"."""
    if general:
        return "general"
    return "why" if WHY_HOW.search(question or "") else "ordinary"


# A general money answer (#572) has no tool data, so it states no number of any kind: no digit (the validator's
# R1 check), and none of these either. "one" and "yksi" stay ("one way is to…"); every larger count, a share, a
# percentage and a Roman numeral is a figure the answer has no source for ("three months of costs", "VI months",
# "half your income", "kolme kuukautta").
_GENERAL_NUMBER_WORD = re.compile(
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen"
    r"|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundreds?|thousands?|millions?"
    r"|billions?|dozens?|half|halves|quarters?|thirds?|fourths?|fifths?|tenths?|percent\w*|per\s+cent|percentage"
    # ordinals and multiples (review of #618): "a sixth", "the twelfth", "twice", "double", "tenfold"; never the idioms
    # "think twice" and "double-check"
    r"|sixths?|sevenths?|eighths?|ninths?|elevenths?|twelfths?|(?:thir|four|fif|six|seven|eigh|nine)teenths?"
    r"|twentieths?|thirtieths?|fortieths?|fiftieths?|hundredths?|thousandths?|(?<!think )twice|thrice"
    r"|double(?!-?check)\w*|triple\w*|quadruple\w*|(?:two|three|four|five|six|ten|hundred|thousand)fold"
    r"|kaksi|kahde\w*|kolme\w*|kolmen|neljä\w*|neljän|viisi|viide\w*|kuusi|kuude\w*|seitsemä\w*|kahdeksa\w*"
    r"|yhdeksä\w*|\w*kymmen\w*|\w+toista|sata\w*|sadan|tuha\w*|miljoon\w*|miljardi\w*|puolet|puolikas\w*|puoli"
    r"|neljännes\w*|kolmannes\w*|prosent\w*|tusina\w*|pari"
    # multiples and colloquial counts (review of #618, pass 3): "doubling", "treble", "tuplasti", "kaks", "viis"
    r"|doubl(?:ing|ed|es)|trebl\w*|tupla\w*|kaks|viis|tenner|fiver|nil"
    # "a couple of months", "a pair of", "puolen vuoden", "puoleen tuloista", "kolmas osa" (closing review of #618)
    r"|(?:a\s+)?couple\s+of|couple\s+(?:is|are|will|would|of|weeks?|months?|days?|years?)|a\s+pair\s+of|pairs\s+of"
    r"|puolen|puoleen|(?:kolmas|neljäs|viides|kymmenes)\s+osa\w*"
    # compounds ("kaksisataa", "viisituhatta"), shares ("kolmasosa") and multiples ("kaksinkertainen") (review of #618)
    r"|(?:kaksi|kolme|neljä|viisi|kuusi|seitsemän|kahdeksan|yhdeksän)(?:sata|tuhat)\w*"
    r"|(?:kolmas|neljäs|viides|kuudes|seitsemäs|kahdeksas|yhdeksäs|kymmenes|sadas)osa\w*"
    r"|(?:kaksin|kolmin|nelin|viisin|kuusin|kymmenen|sata|tuhat)kertai\w*)\b", re.I)
# A number word joined to the next word ("twentyfive", "threemonth", "fiftyfifty"): the long English number words with
# no word boundary after them (closing review of #618); the short ones (two, six, ten) keep it ("often", "tenant")
_NUMBER_PREFIX = re.compile(r"\b(?:three|four|five|seven|eight|nine|eleven|twelve|twenty|thirty|forty|fifty|sixty"
                            r"|seventy|eighty|ninety|hundred|thousand|million|billion|dozen)[a-z]", re.I)
# The same words hidden inside a run with the spaces and hyphens taken out ("tw enty", "T-W-E-N-T-Y"): only the long
# ones that are part of no ordinary word ("forty" and "eighty" are left out: "comfort you", "weighty")
_JOINED_NUMBER = re.compile(r"twenty|thirty|fifty|sixty|seventy|ninety|hundred|thousand|million|billion|percent"
                            r"|kymmen|prosent", re.I)
# Every Roman numeral (XVI, XXV, L, MM), case-sensitive, never the pronoun "I" (review of #618); in lowercase only the
# common ones of two letters or more made of i, v and x ("xii", "vi"), never an English word ("mix")
_ROMAN_NUMERAL = re.compile(r"\b(?!I\b)(?=[MDCLXVI]+\b)M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})\b"
                            r"|\b(?=[ivx]{2,}\b)x{0,3}(?:ix|iv|v?i{0,3})\b")
# A product, a bank or an investment in a general answer: no product is advised (#572 B5, B6; R7). An emergency or
# rainy-day fund is a buffer, not a product; "a share of your income" and "take stock" are plain words. "Your bank"
# stays: an e-invoice arrives in the online bank.
_GENERAL_PRODUCT = re.compile(
    r"\b(?:invest\w*|(?:index|mutual|investment|equity|bond|hedge|pension)\s+funds?|stock\s*markets?|stocks"
    r"|shares\s+in|equit(?:y|ies)|etfs?|bonds?|crypto\w*|bitcoin|sijoit\w*|rahasto\w*|osake\w*|krypto\w*"
    r"|joukkovelkakirj\w*|nordea|osuuspankki|danske|s-?pankki|s-?mobiili|handelsbanken|aktia|säästöpankki"
    r"|saastopankki|revolut|n26|holvi|klarna|apple\s*pay|google\s*pay|mobile\s*pay"
    # products described, not named (review of #618)
    r"|(?:high-interest\s+|high\s+interest\s+)?savings\s+accounts?|deposit\s+accounts?|(?:fixed|term|time)\s+deposits?"
    r"|money\s+market\w*|pension\s+(?:savings|plans?|insurance)|retirement\s+(?:accounts?|funds?|plans?)"
    r"|insurance\s+polic\w*|gold|real\s+estate|robo-?advis\w*|paypal|localtapiola|s-?bonus|netflix|spotify|viaplay"
    r"|säästötil\w*|saastotil\w*|talletu\w*|määräaikai\w*|kulta|kultaa|kullan|kultaan|eläkesäästö\w*"
    r"|eläkevakuutu\w*|sijoitusasun\w*"
    # banks, payment brands and apps by name, and an app at all (closing review of #618)
    r"|op-?ryhmä\w*|pop\s+pankki|oma\s+säästöpankki|ålandsbanken|alandsbanken|bank\s+norwegian|resurs|siirto|pivo"
    r"|mastercard|american\s+express|amex|nordnet|seligson|evli|mandatum|lähitapiola|lahitapiola|fennia"
    r"|apps?|sovellu\w*)\b|\bOP\b"
    # product stems anywhere in a word ("indeksirahasto", "osakesäästötili", "matkavakuutus")
    r"|\w*(?:rahasto|osake|osakk|sijoit|talletu|säästötil|saastotil|eläkesääst|elakesaast|vakuutu|joukkovelkakir"
    r"|krypto|crypto|bitcoin)\w*", re.I)
# Health in a general answer: health stays out (R9; #572). "A healthy buffer" and "financial health" are plain words.
_GENERAL_HEALTH = re.compile(
    r"(?<!financial )\bhealth\b|\bhealth\s*care\b|\b(?:medicine\w*|medication\w*|doctors?|pharmac\w*|therap\w*"
    r"|dentist\w*|hospital\w*|tervey\w*|lääk\w*|apteek\w*|hammaslääk\w*|terapi\w*|sairaala\w*"
    # mental health (review of #618); "that sounds stressful" is empathy, not advice, so stress itself stays
    r"|anxi\w*|meditat\w*|mental\w*|well-?being|addict\w*|treatment\w*|depress\w*|ahdistu\w*"
    r"|rentoutu\w*|mielenterve\w*|riippuvuu\w*|masennu\w*)\b", re.I)
# Other people's money in a general answer (R5; review of #618): "your partner's account", "lend money to your sister"
_GENERAL_OTHERS = re.compile(
    r"\b(?:partner|spouse|husband|wife|friend|neighbou?r|sister|brother|parent|colleague|cousin)s?'?s?\s+"
    r"(?:account|balance|spending|money|salary|income|earnings|card|bank)\w*|\blend\s+(?:some\s+)?money\b"
    r"|\bask\s+(?:a\s+|your\s+)?(?:friend|neighbou?r|colleague)\w*\s+what\s+they\s+(?:earn|spend|make)"
    r"|\bwhat\s+(?:your|the)\s+neighbou?r\w*\s+spend|\bnaapuri\w*|\b(?:puolisosi|ystäväsi|siskosi|veljesi|"
    r"kumppanisi)\s+(?:tili|saldo|palk|kulu|raha)\w*", re.I)
# A link, an address, a handle or a function name: an answer names none (#572 C4, C5; review of #618)
_GENERAL_LINK = re.compile(
    r"https?://|\bwww\.|\b[\w-]+\.(?:com|fi|org|net|io|xyz|ly|co|app|info|biz|eu|se|de|uk|me|ai)\b(?:/\S*)?"
    r"|\b[\w.+-]+@[\w-]+\.\w+|(?<![\w.])@\w+|\b[a-z]+_[a-z_]+\b|\b[a-z]+[A-Z][A-Za-z]+\b"
    r"|\bget\s+safe\s+to\s+spend\b|\banswer\s+in\s+words\b")
# Judging the user or joking about their spending (#572 E1, E2): "bad with money", "irresponsible", "haha", an emoji.
# "No need to feel ashamed" and "vältä tuhlaamasta ruokaa" are plain words (review of #618).
_GENERAL_JUDGING = re.compile(
    r"\b(?:bad|terrible|awful|hopeless|useless)\s+(?:with|at)\s+(?:money|saving|budget\w*|managing\b[\w\s]*)\b"
    r"|\birresponsib\w*|\blazy\b|\bstupid\w*|\bfoolish\w*|\bdumb\b|\bcareless\w*|\breckless\w*|\bwasteful\w*"
    r"|\bwaste\w*\s+(?:your\s+)?money\b|\bspendthrift\w*|\bwallet\s+is\s+crying|\bclowns?\b|\bhilarious\b"
    r"|\bha(?:ha)+\b|\blol\b|\broast\w*|\bshame\s+on\s+you\b"
    r"|\bhuono\w*\s+rahan|\btuhlaat\b|\btuhlari\w*|\btuhlaavai\w*|\btuhlaajat?\b|\btyhm\w*|\btyper\w*|\bholtito\w*"
    r"|\blaiska\w*|\bvastuuto\w*|\bnolo\w*|[\U0001F300-\U0001FAFF\u2600-\u27BF]", re.I)
# Borrowing in any form in a general answer, and in the question that may take the general route (#572 B3, B7, D8;
# review of #618): never a suggestion and never a mention ("Take a car loan.", "A payday lender can bridge the gap",
# "Pikavippi auttaa palkkaan asti", "Osamaksu jakaa kulun", "Käytä tilinylitysoikeutta").
# The stems match anywhere in a word ("pikalaina", "opintolaina", "tililuotto", "korttivelka", "rahoitus"), and a mention
# is rejected even when negated ("Avoid relying on borrowing"): the coordinator's default (closing review of #618).
# "Debt" is borrowing too, so English and Finnish are alike ("velka" was rejected, "debt" was not).
GENERAL_BORROWING = re.compile(
    r"\w*(?:loan|credit|overdraft|borrow|instal{1,2}ment|mortgag|debt|bnpl)\w*|\bfinanc(?:ing|ed)\b"
    r"|\blend(?:er|ers|ing|s)?\b|\b(?:payday|cash|salary|pay|paycheck|wage)\s+advances?\b"
    r"|\badvance\s+on\s+(?:your|my|the)\s+(?:pay|salary|paycheck|wages?)\b|\bbuy\s+now,?\s+pay\s+later\b"
    r"|\w*(?:laina|lainoj|luotto|luoto|luoton|velka|velan|velat|velko|vippi|vipin|vipp|rahoitu|osamaks|tilinylit)\w*"
    r"|\bmaksa\s+myöhemmin\b", re.I)

# ---- The output side as classes (review of #618, pass 3): positive checks on the draft and its folded copies --------
# Borrowing as a class, beyond the stems above: paying or settling later or bit by bit, a purchase split into payments,
# an account in the red or below zero, an advance, a pawn shop, a tab, money asked from someone until payday, what one
# owes; Finnish maksa myöhemmin / vasta, erissä / erään, miinukselle, pakkaselle, ennakko, pantti, maksuaika. Accents
# are folded in one copy, so the Finnish forms are written without them. Draft side only: the question gate keeps
# GENERAL_BORROWING.
_GENERAL_BORROWING_CLASS = re.compile(
    r"\b(?:pay|settle|sort|deal|cover|repay|clear|handle|hoida|maksa|kuittaa|suorita)\w*(?:\s+\w+){0,3}?\s+(?:later"
    r"|next\s+(?:week|month|year|payday)|afterwards|over\s+time|bit\s+by\s+bit|slowly|in\s+(?:parts|pieces|chunks"
    r"|stages|portions|instal\w*)|myohemmin|ensi\s+(?:kuussa|viikolla)|jalkikateen|perasta|osissa)\b"
    r"|\bbuy(?:ing)?[\s-]+(?:it\s+)?now\b|\bpay(?:ing)?\s+(?:it\s+|them\s+)?(?:later|off)\b|\brepay\w*|\bdefer\w*"
    r"|\b(?:split|spread|divide|break)\w*(?:\s+\w+){0,3}?\s+(?:into|over|across)(?:\s+\w+){0,2}?\s+(?:payments?"
    r"|instal\w*|parts|pieces|chunks|months|portions)\b|\b(?:monthly|several|multiple|smaller|equal)\s+(?:payments"
    r"|instal\w*)\b|\bin(?:to)?\s+the\s+red\b|\boverdr[ae]w\w*|\bbelow\s+zero\b|\bnegative\s+balance\b"
    r"|\b(?:an?|the|cash|salary|pay|payday|wage)\s+advances?\b|\badvance\s+on\b|\bpawn\w*|\bquick\s+cash\b"
    r"|\bfast\s+cash\b|\b(?:a|the|your)\s+tab\b|\brun\s+up\b|\bfront\s+you\b|\b(?:owe|owed|owing|iou)\b"
    r"|\bconsolidat\w*|\broll\w*(?:\s+\w+){0,2}?\s+over\b"
    r"|\b(?:ask|beg)\w*(?:\s+\w+){0,3}?\s+(?:for\s+)?(?:some\s+|a\s+bit\s+of\s+|a\s+little\s+)?(?:money|cash|funds"
    r"|help)\b|\bpyyda\w*(?:\s+\w+){0,2}?\s+rahaa\b"
    r"|\b(?:erissa|eraan|erina|eriin|kuukausierissa|kuukausieriin)\b|\bmiinukse\w*|\bpakkase(?:lle|lla)\b"
    r"|\w*ennakko(?:a|ja|n|t|na|sta|lla|lle)?\b|\bpant(?:ti|ata|taa|taamalla)\w*|\bmaksua(?:ika|ikaa|jan|jalla)\w*"
    r"|\bviivekor\w*|\w*ylitysoik\w*", re.I)
# A financial product recommended without a name: interest or yield, or a verb of getting or using one with a product
# noun ("Open an account that pays more.", "Get travel insurance.", "Try online banking.", "Avaa korkeakorkoinen
# tili.", "Käytä verkkopankkia."). Keeping money in an account is a habit, so "keep" and "siirrä" are no such verb.
_GENERAL_PRODUCT_CLASS = re.compile(
    r"\binterest\b(?!\s+in\b)|\bhigh[\s-]*(?:interest|yield)\w*|\bkorko\w*|\w*korkoi\w*|\bindex\s+\w+"
    r"|\b(?:savings|pension)\s+plans?\b|\bdividend\w*"
    r"|\b(?:open|get|take\s+out|sign\s+up\s+for|apply\s+for|switch\s+to|buy|use|try|choose|pick|consider"
    r"|look\s+into|download|install|set\s+up)\b(?:\s+[\w-]+){0,4}?\s+(?:accounts?|cards?|insurance|polic(?:y|ies)"
    r"|wallets?|stocks?|shares|propert(?:y|ies)|funds?|apps?|applications?|banking|deposits?)\b"
    r"|\b(?:avaa|hanki|ota|vaihda|valitse|kayta|lataa|asenna|osta|harkitse)\w*(?:\s+\w+){0,3}?\s+\w*(?:tili|tilin"
    r"|tilia|kortti|kortin|korttia|vakuutu\w*|sovellu\w*|osake\w*|osakke\w*|asunto\w*|lompako\w*|pankki\w*"
    r"|mobiilimaksu\w*)\b|\w*sovellu\w*", re.I)
# A brand or a shop written in lowercase, or at the start of a sentence, where the proper-noun check cannot see it
_GENERAL_BRAND = re.compile(
    r"\b(?:wolt|lidl|amazon|visa|monzo|swedbank|seb|prisma|k-?market|k-?ruoka|k-?citymarket|s-?market|alepa|tokmanni"
    r"|ikea|zalando|foodora|ebay|etsy|temu|shein)\b", re.I)
# Proper nouns: a capitalised word that does not start a sentence, or a word with a capital after its first letter,
# names a bank, a brand, a shop or a product; only these may stand in a general answer (and the pronoun "I", and the
# names of the two languages and the country: "In Finnish, a budget is called budjetti.").
_PROPER_NOUN_ALLOWED = re.compile(r"(?:I(?:['’](?:m|ll|ve|d))?|Sentt?i\w*|S-[Pp]ank\w*|S-mobiil\w*|English|Finnish"
                                  r"|Finland|Finns?|Suom\w*)")
_WORD = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*")


def _proper_nouns(text: str) -> list[str]:
    """The capitalised words of a draft that are not sentence-initial, and any word with a capital after its first
    letter ("SEB", "iPhone", "MobilePay"), except the allowed names (review of #618, pass 3)."""
    found = []
    for sentence in SENTENCE_BREAK.split(text):
        words = _WORD.findall(sentence)
        for i, word in enumerate(words):
            if _PROPER_NOUN_ALLOWED.fullmatch(word):
                continue
            inner_capital = any(ch.isupper() for ch in word[1:].replace("-", ""))
            if inner_capital or (i > 0 and word[0].isupper()):
                found.append(word)
    return found


# A statement about the user's own money: the general route reads no data, so it never asserts the user's state
# ("You are saving enough.", "Your buffer is fine.", "You can afford it.", "Puskurisi on kunnossa.", "Sinulla on varaa
# tähän."). Second person as the subject of a main clause with a state, a sufficiency or a judgement; "if you are
# unsure", "when you're ready", "kun säästät" and "jos sinulla on" are conditions, not claims.
_NOT_A_CLAIM = (r"(?<!\bif )(?<!\bwhen )(?<!\bwhenever )(?<!\bwhether )(?<!\bunless )(?<!\bwhile )(?<!\bonce )"
                r"(?<!\buntil )(?<!\bso )(?<!\bthat )(?<!\bcase )(?<!\blong as )(?<!\bbefore )(?<!\bafter )"
                r"(?<!\bwhat )(?<!\bhow )(?<!\bhow much )(?<!\bkun )(?<!\bjos )(?<!\bjotta )")
_GENERAL_OWN_STATE = re.compile(
    _NOT_A_CLAIM + r"\byou(?:['’]re|\s+are|\s+were|['’]ve\s+been|\s+have\s+been)\b(?!\s+not\s+alone\b)"
    r"|" + _NOT_A_CLAIM + r"\byou(?:\s+\w+)?(?:\s+have|['’]ve|\s+got)\s+(?!to\b)(?:\w+\s+){0,2}?(?:enough|plenty"
    r"|a\s+healthy|a\s+good|a\s+solid|a\s+big|room|too|more\s+than|saved|spent|done|covered)\b"
    r"|" + _NOT_A_CLAIM + r"\byou\s+(?:can|could|can['’]t|cannot)\s+(?:\w+\s+)?afford\b"
    r"|\byou\s+(?:\w+\s+)?(?:spend|earn|save|owe|make|pay|manage)\w*\s+(?:\w+\s+){0,2}?(?:too|enough|well|a\s+lot"
    r"|more\s+than|less\s+than|plenty|little|fine|great)\b"
    r"|" + _NOT_A_CLAIM + r"\byou\s+(?:should|need\s+to|must|ought\s+to|have\s+to|can|could)\s+(?:\w+\s+)?"
    r"(?:save|spend|cut|earn)\s+"
    r"(?:\w+\s+)?(?:more|less|back|down)\b"
    r"|\byou\s+(?:don['’]t|do\s+not|won['’]t|will\s+not)\s+need\s+(?:a\s+|any\s+)?(?:bigger|larger|smaller|more"
    r"|less|extra)\b"
    r"|(?:\b(?:based\s+on|given|judging\s+by|looking\s+at)|(?:^|(?<=[.!?] ))with)\s+your\s+(?:own\s+)?(?:income"
    r"|spending|salary|savings|buffer|budget|situation|money|finances|bills|expenses|balance|habits|earnings)\b"
    # "your buffer is fine", never the embedded question "how steady your income is" or "how your spending looks"
    r"|(?<!\bhow )(?<!\bwhere )(?<!\bwhat )(?<!\bwhether )(?<!\bif )\byours?\b(?:\s+(?:own|current|monthly|total"
    r"|overall|food|grocery|emergency|regular|present))*\s+(?:buffer|savings?|spending|money|finances|balance|income"
    r"|salary|budget|bills|expenses|costs|situation|account|habits|cash|wallet|fund|position|cushion|earnings)"
    r"(?:\s+(?:on|for)\s+\w+)?\s+(?:is|are|was|were|looks?|seems?|sounds?|appears?|feels?|isn['’]t|aren['’]t|covers?"
    r"|should\s+(?:cover|be\s+(?:enough|fine|ok|okay|big|large|sufficient))|will\s+(?:cover|be)|can\s+cover)\b"
    r"(?=\s+\w)|\byours\s+(?:is|are|looks?|seems?|should)\b"
    r"|\b(?:people|others|someone|anyone)\s+(?:in\s+your\s+(?:situation|position|shoes)|like\s+you)\b"
    # Finnish, accents folded: säästät / kulutat ... tarpeeksi / liikaa, "puskurisi on", "sinulla on", "olet"
    r"|" + _NOT_A_CLAIM + r"\b(?:saastat|kulutat|kaytat|tienaat|ansaitset|maksat|tuhlaat|parjaat|et\s+(?:saasta"
    r"|kuluta|kayta|tienaa|ansaitse|maksa|parjaa))\b(?:\s+\w+){0,3}?\s+(?:jo\s+)?(?:tarpeeksi|riittavasti|liikaa"
    r"|liian|hyvin|paljon|vahan|enemman|vahemman|kuin)\b"
    r"|\b(?:puskuri|saasto|raha|tili|saldo|tulo|meno|kulu|kulutukse|taloute|tilantee|budjetti|palkka|lasku"
    r"|varallisuute)\w*si\s+(?:\w+\s+)?(?:on|ovat|oli|olivat|nayttaa|nayttavat|vaikuttaa|vaikuttavat|riittaa"
    r"|riittavat|kattaa|kattavat)\b"
    r"|" + _NOT_A_CLAIM + r"\bsinulla\s+(?:on|oli|ei\s+ole)\b"
    r"|\bsinun\s+(?:pitaisi|kannattaisi|tulisi|taytyy|pitaa)\s+(?:\w+\s+)?(?:saastaa|kuluttaa|kayttaa|vahentaa)"
    r"(?:\s+\w+)?\s+(?:enemman|vahemman)\b"
    r"|" + _NOT_A_CLAIM + r"\bolet\b", re.I)
# A draft that says it could not work the question out (composer.md's line for empty <data>) is no answer in words
GENERAL_NON_ANSWER = re.compile(
    r"\bI\s+(?:could\s*not|couldn['’]t|cannot|can['’]t|can\s+not|was\s+unable\s+to|am\s+unable\s+to"
    r"|wasn['’]t\s+able\s+to|don['’]t\s+have|do\s+not\s+have)\b|\bunable\s+to\s+(?:work|figure|calculat|comput"
    r"|answer)\w*|\ben\s+(?:pystynyt|pysty|voinut|voi|osannut|osaa|onnistunut|loytanyt)\b"
    r"|\bei\s+(?:onnistunut|voitu|loytynyt)\b", re.I)
# The language of a general answer (reviews of #618): a positive check, so a language nobody listed is caught too.
# Every letter is of the asked language's alphabet (English: a to z, é; Finnish: a to z, å, ä, ö, é), every sentence
# reads as that language (an English one has an English word, a Finnish one a Finnish word or ending), and no sentence
# carries the other language ("Kannattaa pitää budjetti, to be safe."). The list of other languages' words stays as
# one more signal.
_LETTERS = {"en": set("abcdefghijklmnopqrstuvwxyzé"), "fi": set("abcdefghijklmnopqrstuvwxyzåäöé")}
_ENGLISH_COMMON = re.compile(
    r"\b(?:the|a|an|is|are|was|be|been|to|of|and|or|in|on|at|by|for|with|from|as|it|its|you|your|yours|this|that"
    r"|these|those|they|them|their|we|our|can|could|will|would|should|may|might|do|does|did|not|no|if|so|than|then"
    r"|when|what|how|why|which|who|more|less|most|some|any|each|every|all|one|first|next|also|just|only|before|after"
    r"|until|while|because|keep|set|plan|save|saving|savings|spend|spending|start|try|make|check|pay|put|move|use|track"
    r"|write|pick|choose|wait|think|look|build|cut|avoid|stop|aim|review|list|note|small|little|good|money|budget"
    r"|buffer|bill|bills|payday|habit|habits|month|week|day|costs?|regular|easier|easy|help|helps|many|people)\b", re.I)
_FINNISH_COMMON = re.compile(
    r"[äöÄÖ]|\b(?:ja|ei|että|kun|jos|tai|voit|voi|joka|jotka|mutta|sinun|kannattaa|rahaa|raha|kuin|myös|ennen|sitä"
    r"|siitä|tämä|tuo|niin|aina|kaikki|ovat|olla|on|se|ne|sen|sinä|sinulla|tee|pidä|aloita|siirrä|seuraa|katso"
    r"|valitse|odota|mieti|säästä|saasta|budjetti|puskuri|lasku|laskut|kuukausi|viikko|päivä|paiva|hyvä|hyva|pieni"
    r"|helpompi|helppo|moni|monet|usein|ensin|sitten|jo|vasta|vain|eri|oma|omat)\b", re.I)
_OTHER_LANGUAGE = re.compile(
    r"\b(?:och|att|är|för|inte|eller|också|månad\w*|pengar|utgifter|spara|ditt|dina|två|tre"
    r"|und|nicht|ist|das|ein|eine|oder|auch|monat\w*|geld|sparen|ausgaben|ihr\w*|dein\w*|zwei|drei"
    r"|los|las|que|meses|dinero|gastos|ahorr\w*|tus|una|por|pero|tres"
    r"|les|des|est|pas|mois|argent|dépenses|gardez|épargn\w*|vous|votre|une|pour|avec|deux|trois)\b", re.I)
_FINNISH_WORD = re.compile(r"[äöÄÖ]|\b(?:ja|ei|että|kun|jos|tai|voit|voi|joka|mutta|sinun|kannattaa|rahaa|kuin|myös"
                           r"|ennen|sitä|siitä|tämä|niin|aina|kaikki|ovat|olla)\b", re.I)
_ENGLISH_WORD = re.compile(r"\b(?:the|a|an|is|are|you|your|and|of|to|it|for|with|this|that|be|can|before|money)\b",
                           re.I)
# A Finnish word by its ending, for a Finnish sentence with no Finnish letter ("Budjetti on suunnitelma.")
_FINNISH_ENDING = re.compile(r"\b\w{3,}(?:tti|ssa|ssä|sta|stä|lla|llä|lta|ltä|ksi|nen|aan|ään|uu|yy)\b", re.I)
# On the Finnish side only (review of #618, pass 3): the clitics -kin / -kaan and the verb endings -aa / -ää / -vat
_FINNISH_ENDING_WIDE = re.compile(r"\b\w{3,}(?:kin|kaan|kään|aa|ää|vat|vät)\b", re.I)


def general_language_problems(text: str, language: str) -> list[str]:
    """A general answer in another language than the one asked, or in two (reviews of #618); [] when none."""
    name = "Finnish" if language == "fi" else "English"
    allowed = _LETTERS.get(language, _LETTERS["en"])
    problems = []
    foreign = sorted({ch for ch in TOKEN_TEXT.sub(" ", text).lower() if ch.isalpha() and ch not in allowed})
    if foreign:
        problems.append(f"'{''.join(foreign)[:10]}': a letter outside {name}; answer only in {name}")
    m = _OTHER_LANGUAGE.search(text)
    if m:
        problems.append(f"'{m.group(0)}': a word of another language; answer only in {name}")
    for sentence in (s for s in SENTENCE_BREAK.split(TOKEN_TEXT.sub(" ", text)) if s.strip()):
        english = len(_ENGLISH_WORD.findall(sentence))
        if language == "en":
            finnish = _FINNISH_WORD.search(sentence) or (_FINNISH_ENDING.search(sentence)
                                                         and not _ENGLISH_WORD.search(sentence))
            if finnish or not _ENGLISH_COMMON.search(sentence):
                problems.append(f"'{sentence.strip()[:40]}': not an English sentence; answer only in English")
                break
        else:
            if english >= 2 or not (_FINNISH_COMMON.search(sentence) or _FINNISH_ENDING.search(sentence)
                                    or _FINNISH_ENDING_WIDE.search(sentence)):
                problems.append(f"'{sentence.strip()[:40]}': not a Finnish sentence; answer only in Finnish")
                break
    return problems


TOKEN_TEXT = re.compile(r"\{\{n\d+\}\}")


def _general_copies(text: str) -> list[str]:
    """The text and the copies every general check also reads (closing review of #618): compatibility forms folded
    (fullwidth, mathematical letters), accents and format characters removed ("fïve"), hyphens, dots and apostrophes
    inside a word removed ("tw-enty", "f.i.v.e"), and runs of single letters joined ("T W E N T Y", "p e r c e n t")."""
    nfkc = unicodedata.normalize("NFKC", text)
    bare = "".join(ch for ch in unicodedata.normalize("NFKD", nfkc) if unicodedata.category(ch) not in ("Mn", "Me", "Cf"))
    inside = re.sub(r"(?<=\w)[-.'’·](?=\w)", "", bare)
    letters = re.sub(r"\b(?:\w[\s.\-]+){2,}\w\b", lambda m: re.sub(r"[\s.\-]+", "", m.group(0)), inside)
    return list(dict.fromkeys([text, nfkc, bare, inside, letters]))


def general_problems(text: str) -> list[str]:
    """What a general money answer (#572) must not contain, as retry reasons; [] when nothing. Every pattern reads the
    text and its folded copies (_general_copies); the digit check, the borrowing check and the other text rules run on
    it as on any model text."""
    problems = []
    copies = _general_copies(text)
    joined = re.sub(r"[\W_]+", "", copies[-1])   # all spaces and marks out, for the long number words only
    m = _JOINED_NUMBER.search(joined)
    if m and not any(_JOINED_NUMBER.search(c) for c in copies):
        problems.append(f"'{m.group(0)}': a number word split apart: a general answer states no number of any kind")
    for rx, why in ((_GENERAL_NUMBER_WORD, "a number word: a general answer states no number of any kind"),
                    (_NUMBER_PREFIX, "a number word: a general answer states no number of any kind"),
                    (_ROMAN_NUMERAL, "a Roman numeral: a general answer states no number of any kind"),
                    (_GENERAL_PRODUCT, "a product, bank or investment: a general answer names none"),
                    (_GENERAL_HEALTH, "health: a general answer gives no health advice"),
                    (_GENERAL_OTHERS, "other people's money: a general answer is about the user only"),
                    (_GENERAL_LINK, "a link, an address or a function name: a general answer names none"),
                    (GENERAL_BORROWING, "borrowing: a general answer never mentions a loan, credit or any "
                                        "borrowing"),
                    (_GENERAL_JUDGING, "judging or joking: a general answer never judges the user or jokes "
                                       "about spending"),
                    (_GENERAL_BORROWING_CLASS, "borrowing: a general answer never suggests paying later, in parts, "
                                               "in the red, with an advance or with someone else's money"),
                    (_GENERAL_PRODUCT_CLASS, "a financial product: a general answer recommends no account, card, "
                                             "insurance, app, interest or investment"),
                    (_GENERAL_BRAND, "a brand or a shop: a general answer names none"),
                    (_GENERAL_OWN_STATE, "the user's own money: a general answer reads no data, so it never says "
                                         "how the user is doing, what they can afford or what their money is")):
        m = next((found for found in (rx.search(c) for c in copies) if found), None)
        if m:
            problems.append(f"'{m.group(0)}': {why}")
    names = next((found for found in (_proper_nouns(c) for c in copies[:2]) if found), None)
    if names:
        # S-Pankki and S-mobiili pass this name check, but the product list above still rejects them in a general
        # answer (red-team row B, "Use the S-mobiili savings goal for it."), so the reason names Sentti only
        problems.append(f"'{names[0]}': a name: a general answer names no bank, brand, shop or product (Sentti is "
                        f"the only name it uses)")
    return problems


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


def length_problems(text: str, numbers: int, displays: Iterable[str] = (), kind: str = "ordinary") -> list[str]:
    """Why a text breaks the answer-length rule, or []. `numbers` is how many numbers it states; each
    display (or a {{nK}} token) counts as one word, and so does each date or period ("1 Apr – 30 Sep
    2026" names one thing, so it is one word, and its dots end no sentence). `kind` (answer_kind): "why" and
    "general" allow four sentences."""
    max_sentences = (MAX_SENTENCES_LONG if kind in LONG_KINDS else MAX_TEMPLATE_SENTENCES if kind == "template"
                     else MAX_SENTENCES)
    max_words = MAX_LONG_WORDS if kind in LONG_KINDS else MAX_TEMPLATE_WORDS if kind == "template" else MAX_SHORT_WORDS
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
    if sentences > max_sentences:
        problems.append(f"too long: {sentences} sentences, at most {max_sentences}")
    words = len(plain.split())
    if words > max_words:
        problems.append(f"too long: {words} words, at most {max_words}")
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


# ---- #417: an amount is never put into the bank's screen or product in one sentence ----------------------
# The screen behind the "monthly saving" button holds investment funds, so "put €360 a month into monthly
# saving" reads like personal investment advice. The rule fires on a DESTINATION or ACTION use only (decided
# in the review of #475): an amount in the same sentence as moving, putting, sending, setting, adding,
# starting, opening or investing into, to or in the bank's screen or product. A plain statement of a figure
# passes ("Your monthly saving is €184.61.", "In S-mobiili your balance is €5,864.86."). Shared by the
# pipeline's validator (token text, model drafts only) and the eval runner (rendered text, every answer).
# A bare "fund" is the bank's product only as a noun with a determiner or in the plural, so "enough to fund
# the trip" and "an emergency fund" pass.
_INVESTMENT_EN = r"(?:(?:investment|index|equity|stock|bond|mutual|money[- ]market)\s+funds?\b(?!-)|fund\s+units?\b)"
_FUND = (r"(?:(?:a|an|the|your|this|that)\s+(?:new\s+)?funds?\b(?!-)|funds\b(?!-)|" + _INVESTMENT_EN
         + r"|Bonus\s+to\s+fund\b)")
_PRODUCT_EN = r"(?:S-?mobiili\w*|monthly[\s-]+saving\b(?:\s+screen\b)?|" + _FUND + ")"
_BANK_DESTINATION_EN = re.compile(
    r"\b(?:into|to|in|towards?|for|with)\s+(?:the\s+|your\s+|an?\s+)?" + _PRODUCT_EN
    + r"|\binto\s+(?:your\s+)?monthly\s+savings\b|\bBonus\s+to\s+fund\b", re.I)
_BANK_OBJECT_EN = re.compile(
    r"\b(?:open|start|set\s+up|buy|bought)\w*\s+(?:a\s+|an\s+|the\s+|your\s+)?(?:new\s+)?" + _PRODUCT_EN, re.I)
# Destinations or product uses that need no verb (like the Finnish illative): a bare "into <product>"; "monthly
# saving of <amount>" together with the app ("Consider monthly saving of €360.00 in S-mobiili."); "a fund with
# <amount>"; an imperative "Fund your future ..."; and a named investment product (index fund, fund units), never
# a plain statement since Sentti has no fund data.
_BANK_ANY_EN = re.compile(
    r"\binto\s+(?:the\s+|your\s+|an?\s+)?" + _PRODUCT_EN
    + r"|\bmonthly[\s-]+saving\s+of\b(?=.*\bS-?mobiili)|\bS-?mobiili\w*\b(?=.*\bmonthly[\s-]+saving\s+of\b)"
    + r"|\b(?:a|an|the|your)\s+(?:new\s+)?funds?\s+with\b|^\W*fund\s+(?:your|the)\b|\b" + _INVESTMENT_EN
    # #499: "In monthly saving, €360.00 a month is enough."; "Monthly saving in S-mobiili: €360.00 a month would do."
    + r"|\bin\s+(?:your\s+)?monthly[\s-]+saving\b"
    + r"|\b(?:monthly[\s-]+saving|kuukausisäästämi\w*|kuukausisäästö\w*)(?:\s+(?:in\s+)?S-?mobiili\w*)?\s*:", re.I)
_ACTION_EN = re.compile(
    r"\b(?:mov(?:e|es|ed|ing)|put(?:s|ting)?|send(?:s|ing)?|sent|set(?:s|ting)?|add(?:s|ed|ing)?|start(?:s|ed|ing)?"
    r"|open(?:s|ed|ing)?|invest(?:s|ed|ing)?|transfer\w*|deposit\w*|sav(?:e|es|ed)|go(?:es)?|going|went"
    r"|turn(?:s|ed|ing)?|convert\w*|top(?:s|ped|ping)?\s+up|pa(?:y|ys|ying|id)|contribut\w*|allocat\w*"
    r"|direct(?:s|ed|ing)?(?!\s+debit)|keep(?:s|ing)?|kept|park(?:s|ed|ing)?|leav(?:e|es|ing)|left|stash\w*"
    r"|grow(?:s|ing|n)?|grew)\b", re.I)
# The bill's action ("Add €97.46 to your payments in S-mobiili") is not the saving product: with "payments" and
# no saving product named, the app alone is a place, not a destination.
_PAYMENTS = re.compile(r"\bpayments?\b|\bbills?\b|\bdue\s+date\b|\bmaksu(?:ihin|t|ja|si)?\b|\blasku\w*|\beräpäiv\w*",
                       re.I)
_SAVING_PRODUCT = re.compile(r"\bmonthly[\s-]+saving|" + _FUND + r"|kuukausisäästö|kuukausisäästämi|(?<!puskuri)(?<!hätä)rahasto",
                             re.I)
_PRODUCT_FI = re.compile(r"\bS-?mobiili\w*|kuukausisäästämi\w*|kuukausisäästö(?:ön|ihin|ssä|stä|llä)\b"
                         r"|(?<!puskuri)(?<!hätä)rahasto\w*", re.I)
# the illative ("into ...") is a destination by itself
_BANK_DESTINATION_FI = re.compile(
    r"\bS-?mobiiliin\b|kuukausisäästämiseen\b|kuukausisäästö(?:ön|ihin|ssä)\b|(?<!puskuri)(?<!hätä)rahasto(?:on|ihin)\b",
    re.I)
_ACTION_FI = re.compile(
    r"\b(?:laita|laitta|pane|pann|siirr|siirtä|lähetä|lähett|aseta|asett|lisää|lisät|aloita|aloitta|avaa|avat"
    r"|sijoit|säästä|talleta|tallett|pidä|pitä|käytä|käyttä|maksa)\w*", re.I)
# A sentence ends at . ! or ? followed by white space, or at a line break; "€1,080.42" and "360,00 €" stay
# whole, and a semicolon or a dash does not end a sentence.
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")
_EURO_AMOUNT = re.compile(r"€\s?[0-9]|[0-9]\s?€")


def bank_action(sentence: str) -> bool:
    """True when the sentence moves, puts, sends, sets, adds, starts, opens or invests into, to or in the bank's
    screen or product (English), or names one in the illative or with such a verb (Finnish)."""
    if _PAYMENTS.search(sentence) and not _SAVING_PRODUCT.search(sentence):
        return False
    if _BANK_OBJECT_EN.search(sentence) or _BANK_ANY_EN.search(sentence) or (
            _ACTION_EN.search(sentence) and _BANK_DESTINATION_EN.search(sentence)):
        return True
    return bool(_BANK_DESTINATION_FI.search(sentence)
                or (_ACTION_FI.search(sentence) and _PRODUCT_FI.search(sentence)))


def amount_beside_bank_product(text: str) -> str | None:
    """Rendered text: the first sentence that has a euro amount and puts something into the bank's screen or
    product, or None. "Your monthly saving is €184.61." and "an AI money coach inside S-mobiili" pass."""
    for sentence in SENTENCE_BREAK.split(text):
        if _EURO_AMOUNT.search(sentence) and bank_action(sentence):
            return sentence.strip()
    return None
