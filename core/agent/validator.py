"""The output validator (agent-core.md section 7.4). It runs on every composer output.

1. The JSON matches AnswerDraft; the text has at most 120 words.
2. Every {{nK}} token names a number produced in this answer, and `cited` equals the tokens used.
3. No stray digits (R1), by subtraction with the module the eval uses (core/answer_text.py): with
   the tokens removed, take out every whole date expression that equals a date or period returned in
   this answer (a number's period, a date field of a model view, or as_of); if any digit is left, the
   draft fails. Amounts, percentages and counts typed as digits fail in any locale format ("12.5%",
   "1 234,56 €", "−30"), and so do ids, IBANs and digits glued to letters. No sign or unit may be
   written next to a token (the token's display carries its own), and two tokens need a word between
   them ("{{n2}} {{n4}}" renders as one number). The same check then runs on the
   rendered text, where only the cited displays may stand as whole tokens, so nothing glued to a
   token passes. No number written in words either (issue #123): a magnitude word anywhere, a
   cardinal next to a unit of money or percent, or a Unicode number character other than a digit.
4. The draft's language is the resolved language (R14).
5. Deny lists: sensitive inferences (R9), investment instructions (R7), promises on estimates (R13).
6. No URLs (any scheme, or "//host"), markdown links or images (inline or reference style, or a link
   definition), HTML, headings or code; at most two **bold** spans of emphasis.
7. `lesson_key` is in the lesson catalogue or null.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core import answer_text
from core.tools.models import Number

MAX_WORDS = 120
MAX_BOLD_SPANS = 2
LESSON_KEYS = ("one_off_vs_habit", "fixed_vs_flexible", "safety_buffer", "small_amounts_add_up",
               "price_level", "estimate_not_promise", "peer_context")

TOKEN = re.compile(r"\{\{(n[0-9]+)\}\}")
ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
# A sign, unit or mark next to a token: a dash, currency, percent, per mille, "×", "#", "+", or a
# standalone "x" ("x{{n1}}", "{{n1}} x").
_MARK = re.escape(answer_text.MARKS)
TOKEN_NEIGHBOUR = re.compile(rf"(?:[{answer_text.DASH_CLASS}{_MARK}]|(?<![^\W\d_])[xX])\s?\{{\{{n[0-9]+\}}\}}|"
                             rf"\{{\{{n[0-9]+\}}\}}\s?(?:[{_MARK}]|[xX](?![^\W\d_]))")
LETTER = re.compile(r"[^\W\d_]")


def tokens_without_words(text: str) -> list[str]:
    """Two number tokens with no letter between them: "{{n2}} {{n4}}" reads as one number ("10 500"),
    "{{n2}}/{{n2}}" as a date, "{{n1}}, {{n2}}" as a decimal. A list separator needs a word after it."""
    found = list(TOKEN.finditer(text))
    return [text[a.start():b.end()] for a, b in zip(found, found[1:]) if not LETTER.search(text[a.end():b.start()])]

DENY = {
    "sensitive_inference": re.compile(
        r"\b(you (may|might|could) be (ill|sick|pregnant)|you are (ill|sick|pregnant)|pregnan\w*|religio\w*|"
        r"political views?|diagnos\w*|illness\w*|disease\w*|olet sairas|raskaana|uskonto\w*)\b", re.I),
    "investment_instruction": re.compile(
        r"\b(you should (buy|sell|invest)|(buy|sell) (some |more )?(stocks?|shares?|funds?|etfs?|bonds?|crypto\w*)|"
        r"osta \w*(osake|rahasto)\w*)\b", re.I),
    # "not a guarantee" and "isn't guaranteed" are fine; "this saving is guaranteed" is not.
    "promise": re.compile(r"(?<!not )(?<!not a )(?<!no )(?<!n't )\bguarantee[ds]?\b|\b(will definitely|takuulla|taatusti)\b",
                          re.I),
}
MARKUP = {
    "url": re.compile(r"https?://|\bwww\.", re.I),
    "markdown_link": re.compile(r"\[[^\]]*\]\([^)]*\)"),
    "html": re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>"),
    "heading": re.compile(r"(^|\n)\s*#"),
    "code": re.compile(r"`"),
    # Issue #105: reference-style links and images ("[here][j]", "![chart][c]", "[x][]"), link
    # definitions ("[c]: target"), URL schemes with or without "//", and protocol-relative "//host".
    "reference_link": re.compile(r"\[[^\]\n]*\]\[[^\]\n]*\]"),
    "link_definition": re.compile(r"(^|\n)[ \t]{0,3}\[[^\]\n]+\]:"),
    "url_scheme": re.compile(r"\b(java|vb)script\s*:|\b(data|file|mailto|tel|sms|ftp|blob|intent)\s*:(?=\S)|"
                             r"\b[a-z][a-z0-9+.\-]*://", re.I),
    "protocol_relative_link": re.compile(r"(^|[^\w:/])//[^\s/]"),
}

# Issue #123: numbers written as words (R1). A magnitude word states an amount anywhere; a cardinal
# word does when a unit of money or percent stands next to it. Other uses stay allowed: "one-off",
# "no one", "the next seven days", "yksin", "yhtä paljon", "osata", "tasata", "sataa" (it rains).
# Any Unicode number character that is not a decimal digit (Roman numerals, fractions, superscripts;
# categories No and Nl) is rejected: NFKC does not turn them into digits, so the digit rule cannot see
# them.
_EN_UNITS = (r"zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
             r"sixteen|seventeen|eighteen|nineteen")
_EN_TENS = r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
_EN_CARDINAL = rf"(?:(?:{_EN_TENS})(?:[- ]?(?:one|two|three|four|five|six|seven|eight|nine))?|{_EN_UNITS})"
def _fi_cases(stem_strong: str, stem_weak: str, partitive: str, illative: str, essive: str,
              nominative: str, genitive: str | None = None) -> list[str]:
    """The singular case forms of a Finnish numeral: nominative, genitive, partitive, the six local
    cases, translative and essive ("kaksi": kahden, kahta, kahdessa, kahdesta, kahteen, kahdella,
    kahdelta, kahdelle, kahdeksi, kahtena). Vowel harmony follows the stem: a stem without a, o or u
    takes front endings ("viisi": viidessä, viidellä; "neljä": neljässä)."""
    weak = stem_weak
    front = not any(v in weak for v in "aou")
    ssa, sta, lla, lta = ("ssä", "stä", "llä", "ltä") if front else ("ssa", "sta", "lla", "lta")
    return [nominative, genitive or weak + "n", partitive, weak + ssa, weak + sta, illative,
            weak + lla, weak + lta, weak + "lle", weak + "ksi", essive]


_FI_NUMERALS = (
    _fi_cases("yhte", "yhde", "yhtä", "yhteen", "yhtenä", "yksi")
    + _fi_cases("kahte", "kahde", "kahta", "kahteen", "kahtena", "kaksi")
    + _fi_cases("kolme", "kolme", "kolmea", "kolmeen", "kolmena", "kolme")
    + _fi_cases("neljä", "neljä", "neljää", "neljään", "neljänä", "neljä")
    + _fi_cases("viite", "viide", "viittä", "viiteen", "viitenä", "viisi")
    + _fi_cases("kuute", "kuude", "kuutta", "kuuteen", "kuutena", "kuusi")
    + _fi_cases("seitsemä", "seitsemä", "seitsemää", "seitsemään", "seitsemänä", "seitsemän", "seitsemän")
    + _fi_cases("kahdeksa", "kahdeksa", "kahdeksaa", "kahdeksaan", "kahdeksana", "kahdeksan", "kahdeksan")
    + _fi_cases("yhdeksä", "yhdeksä", "yhdeksää", "yhdeksään", "yhdeksänä", "yhdeksän", "yhdeksän")
    + _fi_cases("nolla", "nolla", "nollaa", "nollaan", "nollana", "nolla")
)
# Every case form of the digit words, "kymmenen" and its forms, and any word built on "kymmen" (tens:
# kahdellakymmenellä, kahdenkymmenen) or ending in "toista" (teens: kahdeksallatoista).
_FI_DIGIT_WORDS = "|".join(sorted(set(_FI_NUMERALS), key=len, reverse=True))
_FI_CARDINAL = rf"(?:{_FI_DIGIT_WORDS}|\w*kymmen\w*|\w+toista)"
_CARDINAL = rf"(?:{_EN_CARDINAL}|{_FI_CARDINAL})"
# Case forms of "sata" (100) and "tuhat" (1000) as whole words. "sataa" alone is the verb "it rains":
# it counts only inside a compound ("kaksisataa").
_SATA = (r"sata|sadan|sadassa|sadasta|sataan|sadalla|sadalta|sadalle|sadaksi|sadat|satojen|satoja|sadoissa|"
         r"sadoista|satoihin|sadoilla|sadoilta|sadoille|sadoiksi|sadoin")
_TUHAT = (r"tuhat|tuhannen|tuhatta|tuhannessa|tuhannesta|tuhanteen|tuhannella|tuhannelta|tuhannelle|tuhanneksi|"
          r"tuhannet|tuhansien|tuhansia|tuhansissa|tuhansista|tuhansiin|tuhansilla|tuhansilta|tuhansille|"
          r"tuhansiksi|tuhansin")
# The Finnish currency and percent words in every case: euro (euroa, euron, eurolla, euroksi, eurosta,
# euroissa, …), sentti, prosentti, promille.
_FI_EURO = r"euro(?:a|n|on|lla|lta|lle|ksi|ssa|sta|na|t|jen|ja|issa|ista|ihin|illa|ilta|ille|iksi|in)?"
_UNIT_WORDS = (rf"euros?|{_FI_EURO}|cents?|sent(?:ti|in|tiä|tiin|illä|iltä|ille|iksi|issä|istä|tinä)|dollars?|bucks?|"
               r"quid|usd|pounds?|kruunu\w*|kronor|kroner|kronur|krona|percent|per\s?cent|pct|prosent\w*|promille\w*|"
               r"per\s?mille|permille")
_UNIT = rf"(?:€|\$|£|‰|%|eur\b|(?:{_UNIT_WORDS})\b)"
# A unit word right after a token repeats the unit its display already carries ("{{n1}} euros").
UNIT_WORD_AFTER_TOKEN = re.compile(rf"\{{\{{n[0-9]+\}}\}}\s*(?:{_UNIT_WORDS})\b", re.I)
NUMBER_WORDS = re.compile(
    r"\b(?:hundreds?|thousands?|millions?|billions?|trillions?|dozens?)\b|\btusin\w*|"
    rf"\b(?:{_SATA}|{_TUHAT})\b|"
    rf"\b(?:{_FI_DIGIT_WORDS})(?:sat|sad|tuhat|tuhan|tuhans)\w*|"     # compounds: kaksisataa, kolmentuhannen
    r"\bmiljoon\w*|\bmiljard\w*|"
    r"\btonn(?:i|in|ia|issa|ista|iin|illa|ilta|ille|iksi|ina|it|ien|eja|eissa|eista|eihin|eilla|eilta|eille)\b|"
    r"\bsatas\w*|\bsatanen\b|\bkymp\w*|\bvitonen\b|\bvitosen\b|"  # slang ("tonnikala" passes)
    r"\ba\s+grand\b(?!\s+(?:total|scheme|plan|tour|idea|day|time|opening|view))|"
    rf"\b{_CARDINAL}\s+grand\b|\b{_CARDINAL}\s*k\b(?!-)|"         # "five k", not "Seven K-Market"
    rf"\b{_CARDINAL}\s*{_UNIT}|"                                      # fifty euros, twenty percent
    rf"(?:€|\$|£|\beur\b|\beuros?\b|\busd\b)\s*{_CARDINAL}\b",         # €twenty, EUR twenty
    re.I)

# Roman numerals next to a currency ("MM euros", "€XL"), matched case-sensitively with two or more letters so
# that words such as "did" or "mix" never count (#447).
ROMAN_MONEY = re.compile(
    rf"\b[MDCLXVI]{{2,}}\b\.?\s*(?i:€|\$|£|eur\b|(?:{_UNIT_WORDS})\b)"
    r"|(?i:€|\$|£|\beur\b|\beuros?\b|\busd\b)\s*[MDCLXVI]{2,}\b")
# A number word spelled with its letters apart ("o n e  m i l l i o n", #447): the letters are joined and
# searched for a number word without word edges.
_SPACED_RUN = re.compile(r"(?<!\S)(?:[^\W\d_]\s+){2,}[^\W\d_](?!\S)")
_NUMBER_ROOT = re.compile(r"hundred|thousand|million|billion|trillion|dozen|miljoon|miljard|tuhat|tuhan|sata|sadan"
                          r"|tusin", re.I)


def spaced_number_word(text: str) -> str | None:
    """Letters spaced apart that spell a number word, or None."""
    for m in _SPACED_RUN.finditer(text):
        joined = re.sub(r"\s+", "", m.group(0))
        if _NUMBER_ROOT.search(joined) or re.fullmatch(_CARDINAL, joined, re.I):
            return m.group(0)
    return None


# Obfuscation (review of #129): model text may hold no Unicode format character (category Cf: zero-
# width space, soft hyphen, word joiner, BOM, bidi marks) and no combining mark left after NFC (our
# Finnish letters are precomposed). The word and link rules also run on a folded copy: NFKC (fullwidth
# letters become ASCII) with a hyphen between two letters removed ("hun-dred"). A word that mixes Latin
# with Cyrillic or Greek letters (a homoglyph, as a Cyrillic "о" in "thousand") is rejected.
_HYPHEN_IN_WORD = re.compile(r"(?<=[^\W\d_])[-‐‑‒–—](?=[^\W\d_])")
_WORD = re.compile(r"[^\W\d_]+")


def fold(text: str) -> str:
    """The copy the word and link rules also run on: NFKC, format characters and combining marks
    removed, and hyphens inside a word removed."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) not in ("Cf", "Mn", "Me"))
    return _HYPHEN_IN_WORD.sub("", text)


def strip_marks(text: str) -> str:
    """A second folded copy with every accent removed (NFKD): a combining mark typed after a letter
    composes into a new letter ("n" + acute = "ń") and would hide "hundred" from the folded copy. The
    word rules also run on this copy; it is never shown or stored."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) not in ("Cf", "Mn", "Me"))
    return _HYPHEN_IN_WORD.sub("", text)


def hidden_characters(text: str) -> list[str]:
    """Format characters and combining marks that remain after NFC."""
    return [ch for ch in unicodedata.normalize("NFC", text) if unicodedata.category(ch) in ("Cf", "Mn", "Me")]


def _script(ch: str) -> str:
    name = unicodedata.name(ch, "")
    return name.split(" ", 1)[0] if name else ""


def mixed_script_words(text: str) -> list[str]:
    """Words that mix Latin letters with Cyrillic or Greek ones."""
    out = []
    for word in _WORD.findall(unicodedata.normalize("NFC", text)):
        scripts = {_script(ch) for ch in word}
        if "LATIN" in scripts and scripts & {"CYRILLIC", "GREEK"}:
            out.append(word)
    return out


def number_characters(text: str) -> list[str]:
    """Unicode number characters other than decimal digits (categories No and Nl), such as "Ⅿ" or "½"."""
    return [ch for ch in text if unicodedata.category(ch) in ("No", "Nl")]


class AnswerDraft(BaseModel):
    """The composer's JSON (agent-core.md section 7.2)."""

    model_config = ConfigDict(extra="forbid")

    language: Literal["en", "fi"]
    text: str = Field(min_length=1)
    cited: list[str]
    lesson_key: Literal[LESSON_KEYS] | None  # type: ignore[valid-type]


@dataclass(frozen=True)
class Allowed:
    """The dates and periods a text may name: those returned in this answer (rule 3)."""

    dates: frozenset[date]
    periods: frozenset[tuple[date, date]]


def allowed_from(numbers: Iterable[Number], model_views: Iterable[dict[str, Any]], as_of: date) -> Allowed:
    """The periods of this answer's numbers, ISO date fields in the tools' model views (a bill's
    next_expected, a payday) and as_of."""
    dates = {as_of}
    periods = {(n.period.start, n.period.end) for n in numbers}

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
        elif isinstance(obj, str):
            m = ISO_DATE.match(obj)
            if m:
                dates.add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))

    for view in model_views:
        walk(view)
    return Allowed(frozenset(dates), frozenset(periods))


# Markdown a model may write although its prompt asks for plain text (#302). The contract defines no
# emphasis: if the answer ever needs it, it will be a structured field the app draws, never markdown.
_MD_LINK_DEFINITION = re.compile(r"(?m)^[ \t]*\[[^\]\n]+\]:[ \t]*\S+[^\n]*\n?")
_MD_IMAGE = re.compile(r"!\[([^\]\n]*)\]\([^)\n]*\)")
_MD_LINK = re.compile(r"\[([^\]\n]+)\]\([^)\n]*\)")
_MD_REFERENCE_LINK = re.compile(r"\[([^\]\n]+)\][ \t]?\[[^\]\n]*\]")
_MD_HEADING = re.compile(r"(?m)^[ \t]*#{1,6}[ \t]+")
_MD_BULLET = re.compile(r"(?m)^[ \t]*[-*+\u2022][ \t]+")
# A numbered list marker, but not a date that starts a line ("15. lokakuuta 2026 on palkkapäiväsi"): it is
# stripped only when two or more lines carry one and the line does not go on with a month name.
_MD_NUMBERED = re.compile(r"(?m)^[ \t]*\d{1,2}[.)][ \t]+(?!(?:tammi|helmi|maalis|huhti|touko|kesä|heinä|elo|syys"
                          r"|loka|marras|joulu)kuu|(?:january|february|march|april|may|june|july|august|september"
                          r"|october|november|december)\b)", re.I)
_MD_EMPHASIS = re.compile(r"\*+|__+|`+")


def plain_text(text: str) -> str:
    """The text without markdown (#302): bold and italic asterisks, double underscores, backticks,
    heading marks and list bullets at a line start, and links or images (their text stays, the target
    goes; a link definition line goes entirely). Words and number tokens are left as they are."""
    text = _MD_LINK_DEFINITION.sub("", text)
    text = _MD_IMAGE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_REFERENCE_LINK.sub(r"\1", text)
    text = _MD_HEADING.sub("", text)
    text = _MD_BULLET.sub("", text)
    if len(_MD_NUMBERED.findall(text)) >= 2:
        text = _MD_NUMBERED.sub("", text)
    else:
        text = re.sub(r"(?m)^[ \t]*\d{1,2}[.)][ \t]+(?=\{\{n\d+\}\})", "", text)   # "1. {{n7}} is safe to spend." 
    return _MD_EMPHASIS.sub("", text).strip()


# "I do not have a calculated safe-to-spend limit available" next to an overview showing it (#316): when
# no calculation failed, a draft that says a figure is unavailable describes the plan, not the data, and is
# rejected. With a failed calculation, saying so is right (the composer prompt asks for it).
UNAVAILABLE_CLAIM = re.compile(
    r"\b(?:not|n't)\b[^.!?,;]{0,50}\bavailable\b|\bno\s+(?:data|figure|number|calculation)s?\s+(?:is\s+|are\s+)?available\b"
    r"|\bunavailable\b|\b(?:could\s*not|couldn't|cannot|can't|can\s+not)\s+(?:be\s+)?(?:calculat|comput|work)\w*"
    r"|\bcannot\s+be\s+shown\b|\bei\s+ole\s+(?:saatavilla|saatavissa|laskettu\w*)\b|\bei\s+(?:voitu|voida)\s+laskea\b"
    r"|\bunable\s+to\s+(?:calculat|comput|work\s+out|show)\w*|\b(?:calculation|it)\s+is\s+not\s+possible\b"
    r"|\bnot\s+possible\s+to\s+(?:calculat|comput)\w*"
    r"|\b(?:don't|do\s+not|doesn't|does\s+not)\s+have\s+(?:that|this|the|a|any)\s+(?:\w+\s+)?(?:figure|number|data|amount|limit)\b",
    re.I)


# "€185.30 on health, which includes your gym visits" (#395): no tool says what a category contains, so a
# draft that says so states something no data supports.
CONTENTS_CLAIM = re.compile(
    r"\b(?:which|that)\s+(?:includes?|included|covers?|contains?)\b|\bincluding\s+(?:your|the)\b"
    r"|\b(?:includes|covers|contains)\s+your\b|\bsisältä(?:ä|vät|en)\b|\bpitää\s+sisällään\b", re.I)


def _category_labels() -> list[str]:
    from core.tools import config

    labels = set()
    for table in (config.CATEGORY_LABELS, config.BASKET_LABELS, config.MCC_GROUP_LABELS):
        for en, fi in table.values():
            labels.update({en.lower(), fi.lower()})
    labels.update(key.lower() for key in config.CATEGORY_LABELS)
    return sorted(labels, key=len, reverse=True)


def contents_claim(text: str) -> str | None:
    """The words in which a draft says what a CATEGORY contains, or None: the verb ("which includes",
    "sisältää") must follow a category label closely, and what it introduces is neither a number token nor
    another category label ("including the {{n7}} for housing" and "your balance, which covers the next
    week" are fine; "on health, which includes your gym visits" is not)."""
    labels = _category_labels()
    for m in CONTENTS_CLAIM.finditer(text):
        verb = m.group(0).lower()
        raw_after = text[m.end():m.end() + 60].lower().lstrip()
        if raw_after.startswith(("all ", "kaikki ")):
            continue                 # "the total contains all your purchases" is the total's definition
        after = re.sub(r"^\s*(?:your|the|sinun)?\s*", "", raw_after)
        if after.startswith("{{") or any(after.startswith(label) for label in labels):
            continue
        if re.match(r"(?:[^\s{}]+\s+){1,3}\{\{n\d+\}\}", after):
            continue                 # each item carries its number: "sisältävät vuokran {{n2}}" is data (#437)
        if "cover" in verb:
            # "covers" is about coverage ("still covers your bills until payday") unless a category label
            # stands right before it ("Restaurants, which covers your lunches").
            before = text[max(0, m.start() - 40):m.start()].lower()
            if not any(re.search(r"\b" + re.escape(label), before) for label in labels):
                continue
        return m.group(0)
    return None


def unavailable_claim(text: str) -> str | None:
    """The words in which a draft says a figure is not available or cannot be calculated, or None."""
    m = UNAVAILABLE_CLAIM.search(text)
    return m.group(0) if m else None


def check_text(text: str, allowed: Allowed) -> list[str]:
    """Rules 3, 5 and 6 on any text the model wrote (answer text, clarify question or options)."""
    errors = answer_text.leftover_digits(TOKEN.sub(" ", text), dates=allowed.dates, periods=allowed.periods)
    if TOKEN_NEIGHBOUR.search(text):
        errors.append("no sign or unit next to a number token: the token's display carries its own")
    for pair in tokens_without_words(text):
        errors.append(f"words must stand between two number tokens: '{pair}' reads as one number")
    for name, rx in DENY.items():
        if rx.search(text):
            errors.append(f"not allowed: {name}")
    folded = fold(text)
    for name, rx in MARKUP.items():
        if rx.search(text) or rx.search(folded):
            errors.append(f"no {name.replace('_', ' ')} allowed")
    if hidden_characters(text):
        errors.append("no invisible characters or combining marks")
    if mixed_script_words(text):
        errors.append("a word mixes Latin with Cyrillic or Greek letters")
    if UNIT_WORD_AFTER_TOKEN.search(text) or UNIT_WORD_AFTER_TOKEN.search(folded):
        errors.append("no unit word after a number token: the token's display carries its own")
    words = TOKEN.sub(" ", text)
    found = (NUMBER_WORDS.search(words) or NUMBER_WORDS.search(TOKEN.sub(" ", folded))
             or NUMBER_WORDS.search(TOKEN.sub(" ", strip_marks(text))) or ROMAN_MONEY.search(words))
    spelled = found.group(0).strip() if found else spaced_number_word(words)
    if spelled:
        errors.append(f"a number written in words: '{spelled}'; cite every number as a {{{{id}}}} token")
    if number_characters(words):
        errors.append("a number character that is not a digit; cite every number as a {{id}} token")
    bold = text.count("**")
    if bold % 2 or bold // 2 > MAX_BOLD_SPANS or "*" in text.replace("**", ""):
        errors.append(f"at most {MAX_BOLD_SPANS} **bold** spans and no other emphasis")
    return errors


def validate(raw: str | dict, *, language: str, numbers: dict[str, Number],
             allowed: Allowed) -> tuple[AnswerDraft | None, list[str]]:
    """(draft, []) when the composer output passes every rule, else (None or draft, errors)."""
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None, ["the output is not valid JSON"]
    try:
        draft = AnswerDraft.model_validate(payload)
    except ValidationError as exc:
        return None, [f"schema: {'.'.join(str(p) for p in e['loc']) or 'draft'}: {e['type']}" for e in exc.errors()]
    # The service returns plain text (#302): markdown is removed before the checks, so it never reaches
    # the app and a draft is never rejected only for markup that is dropped anyway.
    draft = draft.model_copy(update={"text": plain_text(draft.text)})

    errors = []
    words = len(draft.text.split())
    if words > MAX_WORDS:
        errors.append(f"too long: {words} words, at most {MAX_WORDS}")
    used = TOKEN.findall(draft.text)
    unknown = sorted({t for t in used if t not in numbers})
    if unknown:
        errors.append(f"unknown number ids: {', '.join(unknown)}")
    stripped = TOKEN.sub(" ", draft.text)
    if "{{" in stripped or "}}" in stripped:
        errors.append("malformed number token")
    if set(draft.cited) != set(used):
        errors.append("cited must list exactly the ids used in text")
    if draft.language != language:
        errors.append(f"language must be {language}")
    else:
        # The text itself, not only the field (R14). Conservative: English text that reads as Finnish,
        # or a Finnish text with no Finnish letter and several English words.
        from core.agent.guard import detect_language  # local import: guard has no validator dependency

        detected = detect_language(stripped)
        if language == "en" and detected == "fi":
            errors.append("the text must be in English")
        english_words = re.findall(r"\b(the|you|your|and|of|was|were|spent|is|are|this|that)\b", stripped, re.I)
        if language == "fi" and not re.search(r"[äöå]", stripped, re.I) and len(english_words) >= 3:
            errors.append("the text must be in Finnish")
    errors += check_text(draft.text, allowed)
    if not unknown:
        # Rule 3 again on the text the user reads: each token replaced by its display. A token glued to
        # another token, a digit, a unit word or a month ("{{n2}}{{n2}}", "{{n2}}.{{n2}}", "{{n2}} euros",
        # "On {{n2}} August 2026") leaves digits there that the token-stripped check cannot see.
        rendered = answer_text.leftover_digits(render(draft.text, numbers),
                                               displays=[numbers[i].display for i in set(used)],
                                               dates=allowed.dates, periods=allowed.periods)
        errors += [f"rendered text: {p}" for p in rendered if p not in errors]
    return draft, errors


# A token whose display carries its period ("€229.56 a month", "229,56 € / kk") followed by a period word
# again renders as "€3,010.59 a month a month" (live, #288; also seen in a template, #390).
_PERIOD_UNITS = {"eur_per_day", "eur_per_week", "eur_per_month", "eur_per_year"}
_PERIOD_WORDS = re.compile(
    r"[ \t]*(?:(?:a|per|each|every)\s+(?:day|week|month|year)\b|daily\b|weekly\b|monthly\b|yearly\b|annually\b"
    r"|/\s*(?:pv|vk|kk|v)\b|päivässä\b|viikossa\b|kuukaudessa\b|kuussa\b|vuodessa\b|vuosittain\b"
    r"|kuukausittain\b|viikoittain\b)", re.I)
_REPEATED_RENDERED = re.compile(
    r"\b((?:a|per) (?:day|week|month|year))[ \t]+\1\b|(/ ?(?:pv|vk|kk|v))[ \t]*\2\b"
    r"|\b(päivässä|viikossa|kuukaudessa|kuussa|vuodessa)[ \t]+\3\b", re.I)


def repeated_period(text: str, numbers: dict[str, Number]) -> str | None:
    """The period phrase written again after a number whose display already carries it, or None."""
    for m in TOKEN.finditer(text):
        number = numbers.get(m.group(0)[2:-2])
        if number is not None and number.unit.value in _PERIOD_UNITS:
            after = _PERIOD_WORDS.match(text, m.end())
            if after:
                return (number.display + after.group(0)).strip()
    found = _REPEATED_RENDERED.search(render(text, numbers))
    return found.group(0) if found else None


def render(text: str, numbers: dict[str, Number]) -> str:
    """Replace every token with its Number's localised display (text_rendered)."""
    return TOKEN.sub(lambda m: numbers[m.group(1)].display, text)


# ---- model-draft checks for the composer defects seen on the stand (#398) ------------------------------------
# They run on model drafts only (orchestrator._compose): a rejected draft is retried with the reason, then the
# template writes. A template is never rejected by them.

SELF_INTRO = re.compile(r"^\W*(?:(?:hi|hello|hei|moi)\W+)?(?:i am|i'm|olen)\s+sentti\b", re.I)
# A number explained as a sum or a combination of others (row 1): "{{n1}} combined with your bills", "together
# they make {{n1}}". "Your income, combined with lower bills, leaves {{n1}}" and "the sum of money safe to
# spend" are plain sentences, not sums (review of #437).
COMPOSITE_CLAIM = re.compile(
    r"\{\{n\d+\}\}\s*,?\s*(?:combined|together)\s+with\b|\bcombined\s+with\s+(?:your\s+|the\s+)?\{\{n\d+\}\}"
    r"|\badds?\s+up\s+to\b|\bthe\s+sum\s+of\s+(?!money\b)"
    r"|\btogether\s+(?:they\s+|these\s+|those\s+|both\s+|the\s+two\s+|this\s+)?"
    r"(?:make|makes|come\s+to|comes\s+to|total|totals|add\s+up\s+to|amount\s+to)\b"
    r"|\b(?:make|makes|come\s+to|comes\s+to|total|totals|amount\s+to)\s+\{\{n\d+\}\}\s+together\b"
    r"|\byhteenlaskettuna\b|\byhdessä\s+(?:ne\s+)?(?:muodostavat|tekevät|ovat)\b", re.I)
JOINED_COMPARISON = re.compile(r"\{\{n\d+\}\}\s+(?:and|ja)\s+\{\{n\d+\}\}\s+(?:compared|verrattuna)", re.I)
# A suggestion to cut a regular essential (row 9). Only a suggesting form counts ("could / try / consider /
# want to see ... cut housing", an imperative "Cut your rent"), with the essential as the cut's object in the
# same clause; a negation in that clause ("not cut", "nothing to cut", "can't cut", "ei voi vähentää") is a
# statement, not a suggestion. "Lower" is left out: "lower than usual" is a comparison (review of #437).
_FIXED_EN = r"(?:housing|rent|utilities|utility\s+bills?|insurance|loans?|mortgage)"
_FIXED_FI = r"(?:asumi\w*|vuokra\w*|vakuutu\w*|laina\w*|asunto\w*|sähkö\w*)"
_CUT_EN = r"(?:cut|cuts|cutting|reduce|reducing|trim|trimming|bring\s+down|bringing\s+down)"
_CUT_FI = r"(?:vähen\w*|leikka\w*|leikat\w*|karsi\w*|pienen\w*|tinki\w*)"
# Up to two words may stand between the cut and the essential ("cut your monthly rent"), never a conjunction:
# "cut restaurants and rent stays" cuts restaurants (review of #437).
_FREE = r"(?:\s+(?!(?:and|or|but|while|so|ja|tai|mutta|kun|joten)\b)\w+)"
_OBJECT_EN = rf"(?:\s+(?:back|down))?(?:\s+on)?(?:\s+(?:your|the|some|of|a))*{_FREE}{{0,2}}?\s+{_FIXED_EN}\b"
_SUGGEST_EN = (r"\b(?:why\s+not|could|can|try|trying|consider|considering|want\s+to\s+see|would\s+you\s+like\s+to|how\s+about"
               r"|what\s+if\s+you|should|might|may\s+want\s+to|recommend|suggest|maybe|perhaps)\b")
_SUGGEST_FI = (r"\b(?:voisit|voit|voisitte|kokeile|kokeilla|kokeilisit|harkitse|harkita|harkitsisit|kannattaa"
               r"|kannattaisi|haluatko\s+nähdä|mitä\s+jos|entä\s+jos|suosittelen|ehdotan)\b")
FIXED_CUT = re.compile(
    rf"{_SUGGEST_EN}[^.!?;:,]{{0,30}}?\b{_CUT_EN}{_OBJECT_EN}"
    rf"|{_SUGGEST_EN}[^.!?;:,]{{0,30}}?\b{_FIXED_EN}\s+cuts?\b"
    rf"|(?:^|[.!?]\s+)(?:cut|reduce|trim){_OBJECT_EN}"
    rf"|{_SUGGEST_FI}[^.!?;:,]{{0,30}}?\b{_CUT_FI}{_FREE}{{0,2}}?\s+{_FIXED_FI}"
    rf"|{_SUGGEST_FI}[^.!?;:,]{{0,30}}?\b{_FIXED_FI}{_FREE}{{0,2}}?\s+{_CUT_FI}"
    rf"|(?:^|[.!?]\s+)(?:vähennä|leikkaa|karsi|pienennä){_FREE}{{0,2}}?\s+{_FIXED_FI}"
    # "by cutting your rent you would save", "tinkimällä vuokrasta säästäisit": the means of a saving
    rf"|\bby\s+(?:cutting|reducing|trimming|bringing\s+down){_OBJECT_EN}"
    rf"|\b(?:vähentämällä|leikkaamalla|karsimalla|pienentämällä|tinkimällä){_FREE}{{0,2}}?\s+{_FIXED_FI}", re.I)
# Words the composer got wrong on the stand, in the tester's exact forms: "Salgosi" for "Saldosi" (row 5) and
# "luokittelemattomat" for the app's own label (row 8). "luokittelematon" and "luokittelematta" are real words.
KNOWN_WRONG = re.compile(r"\bsalgo\w*|\bluokittelemattomat\b", re.I)
# The stand's count without its noun (row 2): "cost {{n1}} across {{n2}}." The count follows across / over / in
# / yhteensä and no noun follows it. A count whose noun comes first ("the number of transactions was {{n2}}",
# "tapahtumien määrä oli {{n2}}") is fine (review of #437).
_COUNT_BEFORE = re.compile(r"\b(?:across|over|in|yhteensä)\s+$", re.I)
_COUNT_END = re.compile(r"\s*(?:[.,;:!?)]|$|(?:and|but|ja|mutta)\b)", re.I)
_COUNT_NOUN_BEFORE = re.compile(
    r"\b(?:number\s+of|count\s+of|transactions?|purchases?|payments?|visits?|times|määrä\w*|lukumäärä\w*|oli"
    r"|tapahtum\w*|osto\w*|maksu\w*|käyn\w*|kertaa)\b", re.I)
# Ranking and judgement words in a comparison with similar people (#418): "near the top", "better than most
# people", "you beat most people", "parempi kuin useimmat", "olet kärjessä". "The top category is restaurants"
# names a category, not a rank.
RANKING = re.compile(
    r"\b(?:near|at|in|among|to)\s+the\s+(?:very\s+)?(?:top|bottom)\b(?!\s+(?:categor\w*|rows?|lines?|items?))"
    r"|\b(?:top|bottom)\s+(?:\{\{n\d+\}\}|\d|percent|tier|spenders?|savers?|half|third|quarter|group|of\s+the)\b"
    r"|\b(?:better\s+than|worse\s+than|beat|beats|beating|outperform\w*|outrank\w*|outspend\w*|outsave\w*"
    r"|ahead\s+of|rank\w*)\b"
    # "best" / "worst" rank only the user ("you're the best saver", "among the best"), not "the best way to see".
    r"|\b(?:you(?:['’]re|\s+are)|you['’]ve\s+been)\s+(?:the\s+|one\s+of\s+the\s+)?(?:very\s+)?(?:best|worst)\b"
    r"|\b(?:among|one\s+of)\s+the\s+(?:best|worst)\b|\b(?:best|worst)\s+(?:spenders?|savers?|in\s+(?:your|the)\s+group)\b"
    r"|\b(?:paras(?!\s+(?:tapa|keino|vaihtoehto))|parhai(?!llaan|mmillaan|ten\s+(?:näet|näkee))\w*|huonoin\w*|huonoim(?!millaan)\w*|paremp\w*|huonomp\w*|kärj\w*|kärki\w*"
    r"|häntäpää\w*"
    r"|sijoitu\w*|sijalla|voitat|peittoat)\b", re.I)


def fixed_cut(text: str) -> str | None:
    """The words in which a draft suggests cutting a regular essential, or None (review of #437)."""
    for m in FIXED_CUT.finditer(text):
        start = max((text.rfind(c, 0, m.start() + 1) for c in ".!?;:,"), default=-1) + 1
        if not answer_text.negated(text[start:m.end()]):
            return m.group(0).strip(" .!?")
    return None


def count_without_noun(text: str, numbers: dict[str, Number]) -> str | None:
    """The token of a count that stands alone the way the stand's row 2 did, or None."""
    for token in TOKEN.finditer(text):
        number = numbers.get(token.group(1))
        if number is None or number.unit.value != "count":
            continue
        before = text[:token.start()]
        if not _COUNT_BEFORE.search(before) or not _COUNT_END.match(text, token.end()):
            continue
        clause = re.split(r"[.!?;:]", before)[-1]
        if _COUNT_NOUN_BEFORE.search(clause):
            continue
        return token.group(1)
    return None


def draft_problems(text: str, numbers: dict[str, Number], *, has_data: bool,
                   labels: Iterable[str] = ()) -> list[str]:
    """What a model draft gets wrong of the stand's defects (#398), as retry reasons; [] when nothing.
    `labels` are the labels in the answer's data, which a draft may always name (#419)."""
    problems = []
    cited_methods = [numbers[i].method for i in TOKEN.findall(text) if i in numbers]
    if any(m.startswith("peer_benchmark.") for m in cited_methods):
        ranked = RANKING.search(text)
        if ranked:
            problems.append(f"'{ranked.group(0)}': no ranking words in a comparison with similar people")
    borrowing = answer_text.borrowing_suggestion(text, labels)
    if borrowing:
        problems.append(f"'{borrowing}': never suggest borrowing (a loan, credit, a credit card, instalments, an "
                        "overdraft); say what is safe to spend, or offer saving towards a date from <data>")
    if has_data and SELF_INTRO.search(text):
        problems.append("do not introduce yourself in an answer about the user's money; start with the answer")
    m = COMPOSITE_CLAIM.search(text)
    if m:
        problems.append(f"'{m.group(0)}': never explain a number as a sum or combination of other numbers")
    if JOINED_COMPARISON.search(text):
        problems.append("write a comparison with its direction in words, not two figures joined by 'and'")
    cut = fixed_cut(text)
    if cut:
        problems.append(f"'{cut}': never suggest cutting housing, utilities, insurance or loans")
    m = KNOWN_WRONG.search(text)
    if m:
        problems.append(f"'{m.group(0)}': a wrong word; use correct Finnish and the labels in <data>")
    alone = count_without_noun(text, numbers)
    if alone:
        problems.append(f"a count keeps its noun: write '{{{{{alone}}}}} transactions', not the number alone")
    used = TOKEN.findall(text)
    if len(used) != len(set(used)):
        problems.append("cite each number once; a result is not its own reason")
    return problems
