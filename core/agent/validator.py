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
    "reference_link": re.compile(r"\[[^\]\n]*\]\s?\[[^\]\n]*\]"),
    "link_definition": re.compile(r"(^|\n)[ \t]{0,3}\[[^\]\n]+\]:"),
    "url_scheme": re.compile(r"\b(java|vb)script\s*:|\b(data|file|mailto|tel|sms|ftp|blob|intent)\s*:(?=\S)|"
                             r"\b[a-z][a-z0-9+.\-]*://", re.I),
    "protocol_relative_link": re.compile(r"(^|[^\w:/])//[^\s/]"),
}

# Issue #123: numbers written as words (R1). A magnitude word states an amount anywhere; a cardinal
# word does when a unit of money or percent follows it. Other uses stay allowed: "one-off", "no one",
# "the next seven days", "yksin", "yhtä paljon". Any Unicode number character that is not a decimal
# digit (Roman numerals, fractions, superscripts; categories No and Nl) is rejected: NFKC does not
# turn them into digits, so the digit rule cannot see them.
_EN_CARDINAL = (r"(zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|"
                r"sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
                r"([- ](one|two|three|four|five|six|seven|eight|nine))?")
_FI_CARDINAL = (r"(nolla|yksi|yhden|kaksi|kahden|kahta|kolme|kolmen|kolmea|neljä|neljän|neljää|viisi|viiden|viittä|"
                r"kuusi|kuuden|kuutta|seitsemän|seitsemää|kahdeksan|kahdeksaa|yhdeksän|yhdeksää|kymmenen|"
                r"kymmentä|\w+toista|\w+kymmentä\w*)")
_UNIT_WORDS = (r"euros?|euroa|euron|euroon|euroilla|cents?|senttiä|dollars?|usd|pounds?|kruunu\w*|kronor|kroner|kronur|"
               r"krona|percent|per\s?cent|prosent\w*|promille\w*|per\s?mille|permille")
_UNIT = rf"(€|\$|£|‰|%|eur\b|(?:{_UNIT_WORDS})\b)"
# A unit word right after a token repeats the unit its display already carries ("{{n1}} euros").
UNIT_WORD_AFTER_TOKEN = re.compile(rf"\{{\{{n[0-9]+\}}\}}\s*(?:{_UNIT_WORDS})\b", re.I)
NUMBER_WORDS = re.compile(
    r"\b(hundreds?|thousands?|millions?|billions?|trillions?)\b|"
    r"\b\w*(sata|sataa|sadan|satoja|sadoin|tuhat|tuhatta|tuhannen|tuhansia|tuhansien)\b|"
    r"\bmiljoon\w*|\bmiljard\w*|"
    rf"\b({_EN_CARDINAL}|{_FI_CARDINAL})\s*{_UNIT}", re.I)


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
    for name, rx in MARKUP.items():
        if rx.search(text):
            errors.append(f"no {name.replace('_', ' ')} allowed")
    if UNIT_WORD_AFTER_TOKEN.search(text):
        errors.append("no unit word after a number token: the token's display carries its own")
    words = TOKEN.sub(" ", text)
    found = NUMBER_WORDS.search(words)
    if found:
        errors.append(f"a number written in words: '{found.group(0).strip()}'; cite every number as a {{{{id}}}} token")
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


def render(text: str, numbers: dict[str, Number]) -> str:
    """Replace every token with its Number's localised display (text_rendered)."""
    return TOKEN.sub(lambda m: numbers[m.group(1)].display, text)
