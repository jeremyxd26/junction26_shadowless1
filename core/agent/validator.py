"""The output validator (agent-core.md section 7.4). It runs on every composer output.

1. The JSON matches AnswerDraft; the text has at most 120 words.
2. Every {{nK}} token names a number produced in this answer, and `cited` equals the tokens used.
3. No stray digits (R1), by subtraction with the module the eval uses (core/answer_text.py): with
   the tokens removed, take out every whole date expression that equals a date or period returned in
   this answer (a number's period, a date field of a model view, or as_of); if any digit is left, the
   draft fails. Amounts, percentages and counts typed as digits fail in any locale format ("12.5%",
   "1 234,56 €", "−30"), and so do ids, IBANs and digits glued to letters. No sign or unit may be
   written next to a token (the token's display carries its own). The same check then runs on the
   rendered text, where only the cited displays may stand as whole tokens, so nothing glued to a
   token passes.
4. The draft's language is the resolved language (R14).
5. Deny lists: sensitive inferences (R9), investment instructions (R7), promises on estimates (R13).
6. No URLs, markdown links, HTML, headings or code; at most two **bold** spans of emphasis.
7. `lesson_key` is in the lesson catalogue or null.
"""

from __future__ import annotations

import json
import re
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
TOKEN_NEIGHBOUR = re.compile(rf"[{answer_text.DASH_CLASS}+€%$]\s?\{{\{{n[0-9]+\}}\}}|\{{\{{n[0-9]+\}}\}}\s?[€%$]")

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
}


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
    for name, rx in DENY.items():
        if rx.search(text):
            errors.append(f"not allowed: {name}")
    for name, rx in MARKUP.items():
        if rx.search(text):
            errors.append(f"no {name.replace('_', ' ')} allowed")
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
