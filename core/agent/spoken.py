"""The spoken script of an answer (#811 follow-up): what POST /api/tts reads aloud instead of the screen text.

The screen text is written to be read: exact figures with their unit marks ("63,17 € / kk eli 758,04 € /
v"), every number the answer declares, dates as digits, links. Read aloud, that is hard to follow. The
script is built from the answer's own audit record, deterministically, with no model call:

- Each `{{nK}}` token of `text` becomes a spoken form of its Number (value, unit, method): whole euros,
  "about" when rounded ("about 63 euros a month", "noin 63 euroa kuukaudessa"); never "/", "kk" or "€".
- At most MAX_SPOKEN different numbers are read, in the order they appear. A later number is left out with
  its clause (from the nearest , : or ; or the number read before it, up to the next punctuation); a
  sentence that would start with it, or be left with one word, is left out. The rest stays on the screen.
  The step plan (#822, three steps with one number each) keeps all three steps: the third is read without
  its number ("Third, check your small purchases.", #827).
- A leading period phrase ("During 1 Apr – 30 Sep 2026,", "Ajanjaksolla 1.4.–30.9.2026") is dropped, and
  one sentence at the end says where the numbers come from: "That's from your spending from April to
  September." / "Laskin tämän kulutuksestasi huhtikuusta syyskuuhun."
- Links and Markdown marks are not read; a Finnish date (15.10.2026) is read as "15. lokakuuta".

An answer without number tokens (a refusal, a knowledge-base answer, small talk) is read as its screen text
without links. Any record this cannot read falls back to `text_rendered`.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from core.tools.formatting import PER_MONTH_COUNT_METHODS, VS_MEDIAN_METHOD, ordinal_en
from core.tools.periods import MONTHS_EN, MONTHS_EN_SHORT

MAX_SPOKEN = 2

TOKEN = re.compile(r"\{\{(n\d+)\}\}")

FI_ELATIVE = ("tammikuusta", "helmikuusta", "maaliskuusta", "huhtikuusta", "toukokuusta", "kesäkuusta",
              "heinäkuusta", "elokuusta", "syyskuusta", "lokakuusta", "marraskuusta", "joulukuusta")
FI_ILLATIVE = ("tammikuuhun", "helmikuuhun", "maaliskuuhun", "huhtikuuhun", "toukokuuhun", "kesäkuuhun",
               "heinäkuuhun", "elokuuhun", "syyskuuhun", "lokakuuhun", "marraskuuhun", "joulukuuhun")
FI_GENITIVE = ("tammikuun", "helmikuun", "maaliskuun", "huhtikuun", "toukokuun", "kesäkuun", "heinäkuun",
               "elokuun", "syyskuun", "lokakuun", "marraskuun", "joulukuun")
FI_PARTITIVE = ("tammikuuta", "helmikuuta", "maaliskuuta", "huhtikuuta", "toukokuuta", "kesäkuuta",
                "heinäkuuta", "elokuuta", "syyskuuta", "lokakuuta", "marraskuuta", "joulukuuta")
FI_INESSIVE = ("tammikuussa", "helmikuussa", "maaliskuussa", "huhtikuussa", "toukokuussa", "kesäkuussa",
               "heinäkuussa", "elokuussa", "syyskuussa", "lokakuussa", "marraskuussa", "joulukuussa")
FI_NOMINATIVE = ("tammikuu", "helmikuu", "maaliskuu", "huhtikuu", "toukokuu", "kesäkuu", "heinäkuu", "elokuu",
                 "syyskuu", "lokakuu", "marraskuu", "joulukuu")

RATE = {
    "eur_per_day": (" a day", " päivässä"),
    "eur_per_week": (" a week", " viikossa"),
    "eur_per_month": (" a month", " kuukaudessa"),
    "eur_per_year": (" a year", " vuodessa"),
}
MONEY_UNITS = {"eur", *RATE}

_DASH = "[-‒–—−]"
_MON_SHORT = "|".join(MONTHS_EN_SHORT)
# "1 Apr – 30 Sep 2026", "1 Oct 2025 – 30 Sep 2026", "1–15 Jun 2026"
EN_RANGE = re.compile(rf"\b(\d{{1,2}})(?:\s+({_MON_SHORT})(?:\s+(\d{{4}}))?)?\s*{_DASH}\s*(\d{{1,2}})\s+({_MON_SHORT})\s+(\d{{4}})\b")
# "1.4.–30.9.2026", "1.10.2025–30.9.2026", "1.–15.6.2026"
FI_RANGE = re.compile(rf"\b(\d{{1,2}})\.(?:(\d{{1,2}})\.(\d{{4}})?)?\s*{_DASH}\s*(\d{{1,2}})\.(\d{{1,2}})\.(\d{{4}})")
FI_DATE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
EN_MONTH = re.compile(rf"\b({'|'.join(MONTHS_EN)})\s+(\d{{4}})\b")
FI_MONTH = re.compile(rf"\b({'|'.join(FI_INESSIVE + FI_NOMINATIVE)})\s+(\d{{4}})\b", re.IGNORECASE)
EN_LEAD = re.compile(rf"^(?:During|In|Between|Over|For)\s+{EN_RANGE.pattern},?\s+")
FI_LEAD = re.compile(rf"^(?:(?:Ajanjaksolla|Aikavälillä|Aikajaksolla|Jaksolla)\s+{FI_RANGE.pattern}|Jakson\s+{FI_RANGE.pattern}\s+aikana),?\s+")
URL = re.compile(r"\s*\(?https?://\S+\)?")

# Tools whose numbers look ahead (the balance, the bills, the coming days) rather than back at spending.
FORWARD_TOOLS = {"get_safe_to_spend", "get_safe_to_save", "get_balance_forecast", "get_recurring_bills"}


def _whole(value: Decimal, step: int = 1) -> int:
    return int((value / step).quantize(Decimal(1), rounding=ROUND_HALF_UP)) * step


def _decimal_text(value: Decimal, fi: bool) -> str:
    text = f"{value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}".removesuffix(".0")
    return text.replace(".", ",") if fi else text


def spoken_number(number: dict[str, Any], language: str) -> str | None:
    """One Number read aloud: "about 63 euros a month", "noin 63 euroa kuukaudessa"; None if unreadable."""
    try:
        value = Decimal(str(number["value"]))
    except Exception:  # noqa: BLE001 - a malformed number falls back to the screen text
        return None
    unit = number.get("unit")
    method = number.get("method")
    fi = language == "fi"
    minus = ("miinus " if fi else "minus ") if value < 0 else ""
    magnitude = abs(value)

    if unit in MONEY_UNITS:
        suffix = RATE.get(unit, ("", ""))[1 if fi else 0]
        if magnitude < 1 and magnitude > 0:
            cents = _whole(magnitude * 100)
            return f"{minus}{cents} {'senttiä' if fi else 'cents'}{suffix}"
        step = 1 if magnitude < 1000 else 10 if magnitude < 10000 else 100
        whole = _whole(magnitude, step)
        about = abs(magnitude - whole) >= Decimal("0.005")
        lead = ("noin " if fi else "about ") if about else ""
        if fi:
            return f"{minus}{lead}{whole} {'euro' if whole == 1 else 'euroa'}{suffix}"
        return f"{minus}{lead}{whole:,} {'euro' if whole == 1 else 'euros'}{suffix}"

    if unit == "percent":
        if method == VS_MEDIAN_METHOD:
            direction = "" if magnitude == 0 else (" vähemmän" if fi else " less") if value < 0 else (" enemmän" if fi else " more")
            return f"{_decimal_text(magnitude, fi)} {'prosenttia' if fi else 'percent'}{direction}"
        if magnitude >= 10:
            whole = _whole(magnitude)
            lead = ("noin " if fi else "about ") if abs(magnitude - whole) >= Decimal("0.05") else ""
            return f"{minus}{lead}{whole} {'prosenttia' if fi else 'percent'}"
        return f"{minus}{_decimal_text(magnitude, fi)} {'prosenttia' if fi else 'percent'}"

    if unit == "percentile":
        n = _whole(magnitude)
        return f"{n}. persentiili" if fi else f"{ordinal_en(n)} percentile"

    if unit == "count":
        text = str(_whole(magnitude)) if magnitude == magnitude.to_integral_value() else _decimal_text(magnitude, fi)
        if method in PER_MONTH_COUNT_METHODS:
            text += " kuukaudessa" if fi else " a month"
        return minus + text

    if unit in ("days", "months"):
        n = _whole(magnitude)
        if unit == "days":
            word = ("päivä" if n == 1 else "päivää") if fi else ("day" if n == 1 else "days")
        else:
            word = ("kuukausi" if n == 1 else "kuukautta") if fi else ("month" if n == 1 else "months")
        return f"{minus}{n} {word}"
    return None


def _sentences(text: str) -> list[str]:
    """Sentences, split after . ! ? followed by a space and a capital letter or a number token (a decimal
    never splits)."""
    return [part for part in re.split(r"(?<=[.!?])\s+(?=[A-ZÅÄÖ\"“]|\{\{)", text.strip()) if part]


RESTATED = re.compile(r"\{\{(n\d+)\}\}(,?\s*(?:that is|i\.e\.,?|or|eli|tai)\s+)\{\{(n\d+)\}\}")
# Words before a number that already say "about" (or "the"): the spoken form then drops its own "about".
ABOUT_BEFORE = re.compile(r"\b(?:about|around|roughly|approximately|the|noin|arviolta|suunnilleen)\s*$", re.IGNORECASE)
DOUBLED = re.compile(r"\b(more|less|enemmän|vähemmän) \1\b")


def _drop_restated(sentence: str, numbers: dict[str, Any]) -> str:
    """"€63.17 a month, that is €758.04 a year": the same money in another rate is said once, as the first."""
    def keep_first(match: re.Match[str]) -> str:
        first, second = numbers.get(match.group(1)) or {}, numbers.get(match.group(3)) or {}
        units = (first.get("unit"), second.get("unit"))
        if units[0] in MONEY_UNITS and units[1] in MONEY_UNITS and units[0] != units[1]:
            return "{{" + match.group(1) + "}}"
        return match.group(0)

    return RESTATED.sub(keep_first, sentence)


def _drop_extra(sentence: str, spoken: list[str]) -> str:
    """The sentence without the numbers beyond MAX_SPOKEN (each with its clause); `spoken` grows in place."""
    while True:
        extra = None
        kept_end = 0
        for match in TOKEN.finditer(sentence):
            key = match.group(1)
            if key in spoken:
                kept_end = match.end()
                continue
            if len(spoken) < MAX_SPOKEN:
                spoken.append(key)
                kept_end = match.end()
                continue
            extra = match
            break
        if extra is None:
            return sentence
        # The clause starts at the nearest , : or ; before the number ("Third, check your small purchases: they
        # add up to {{n3}}." keeps "Third, check your small purchases."), or right after the number read before it.
        boundary = max(sentence.rfind(mark, 0, extra.start()) for mark in ",:;")
        start = max(boundary, kept_end) if max(boundary, kept_end) > 0 else 0
        tail = re.search(r"[,.;:!?]", sentence[extra.end():])
        end = extra.end() + tail.start() if tail else len(sentence)
        if start == 0:
            return ""   # the sentence starts with a number left out: the whole sentence goes
        sentence = sentence[:start] + sentence[end:]
        if len(re.findall(r"\w+", TOKEN.sub("", sentence))) < 2:
            return ""   # never a sentence of one word ("Third.")


def _period(text: str, record: dict[str, Any], first_key: str | None) -> tuple[str, Any] | None:
    """Where the spoken numbers come from: ('range', (m1, y1, m2, y2)), ('month', (m, y)) or ('forward', None)."""
    def from_label(label: str) -> tuple[str, Any] | None:
        en = EN_RANGE.search(label)
        if en:
            d1, mon1, y1, d2, mon2, y2 = en.groups()
            m2 = MONTHS_EN_SHORT.index(mon2) + 1
            m1 = MONTHS_EN_SHORT.index(mon1) + 1 if mon1 else m2
            return "range", (m1, int(y1 or y2), m2, int(y2))
        fi = FI_RANGE.search(label)
        if fi:
            d1, mo1, y1, d2, mo2, y2 = fi.groups()
            return "range", (int(mo1 or mo2), int(y1 or y2), int(mo2), int(y2))
        month = EN_MONTH.search(label)
        if month:
            return "month", (MONTHS_EN.index(month.group(1)) + 1, int(month.group(2)))
        month = FI_MONTH.search(label)
        if month:
            word = month.group(1).lower()
            index = FI_INESSIVE.index(word) if word in FI_INESSIVE else FI_NOMINATIVE.index(word)
            return "month", (index + 1, int(month.group(2)))
        return None

    found = from_label(text)
    if found:
        if found[0] == "range" and found[1][0] == found[1][2] and found[1][1] == found[1][3]:
            return "month", (found[1][0], found[1][1])
        return found
    outputs = record.get("tool_outputs") or {}
    for output in outputs.values() if isinstance(outputs, dict) else []:
        if not isinstance(output, dict) or (first_key and f'"id": "{first_key}"' not in _flat(output)):
            continue
        if output.get("tool") in FORWARD_TOOLS:
            return "forward", None
        label = output.get("period")
        if isinstance(label, str) and (found := from_label(label)):
            return found
    return None


def _flat(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _source(period: tuple[str, Any] | None, language: str) -> str:
    fi = language == "fi"
    if period is None:
        return "Laskin tämän viime kuukausien kulutuksestasi." if fi else "That's from your spending in recent months."
    kind, data = period
    if kind == "forward":
        return ("Laskin tämän saldostasi, laskuistasi ja tavallisesta kulutuksestasi." if fi
                else "That's from your balance, your bills and your usual spending.")
    if kind == "month":
        m, _ = data
        return f"Laskin tämän {FI_GENITIVE[m - 1]} kulutuksestasi." if fi else f"That's from your spending in {MONTHS_EN[m - 1]}."
    m1, y1, m2, y2 = data
    if fi:
        if y1 != y2:
            return f"Laskin tämän kulutuksestasi {FI_ELATIVE[m1 - 1]} {y1} {FI_ILLATIVE[m2 - 1]} {y2}."
        return f"Laskin tämän kulutuksestasi {FI_ELATIVE[m1 - 1]} {FI_ILLATIVE[m2 - 1]}."
    if y1 != y2:
        return f"That's from your spending from {MONTHS_EN[m1 - 1]} {y1} to {MONTHS_EN[m2 - 1]} {y2}."
    return f"That's from your spending from {MONTHS_EN[m1 - 1]} to {MONTHS_EN[m2 - 1]}."


def _readable(text: str, language: str) -> str:
    """No links or Markdown marks; a Finnish date as words ("15. lokakuuta"); tidy spaces and punctuation."""
    text = URL.sub("", text).replace("**", "").replace("__", "").replace("`", "")
    if language == "fi":
        text = FI_RANGE.sub(lambda m: f"{FI_ELATIVE[int(m.group(2) or m.group(5)) - 1]} {FI_ILLATIVE[int(m.group(5)) - 1]}", text)
        text = FI_DATE.sub(lambda m: f"{int(m.group(1))}. {FI_PARTITIVE[int(m.group(2)) - 1]}" if 1 <= int(m.group(2)) <= 12 else m.group(0), text)
    text = re.sub(r":\s*$", ".", text.strip())
    text = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"\s{2,}", " ", text))
    return re.sub(r",\s*([.!?])", r"\1", text)


def spoken_script(record: dict[str, Any]) -> str:
    """What /api/tts reads aloud for this answer record (see the module docstring)."""
    rendered = record.get("text_rendered") or ""
    language = ((record.get("language") or {}).get("resolved")) or "en"
    language = language if language in ("en", "fi") else "en"
    text = record.get("text") or ""
    numbers = record.get("numbers") or {}
    try:
        if not TOKEN.search(text):
            return _readable(rendered, language) or rendered
        spoken: list[str] = []
        kept = [s for s in (_drop_extra(_drop_restated(sentence, numbers), spoken) for sentence in _sentences(text)) if s.strip()]
        if not kept:
            return _readable(rendered, language) or rendered
        forms = {key: spoken_number(numbers.get(key) or {}, language) for key in spoken}
        if any(form is None for form in forms.values()):
            return _readable(rendered, language) or rendered
        period = _period(text, record, spoken[0] if spoken else None)
        lead = FI_LEAD if language == "fi" else EN_LEAD
        if lead.match(kept[0]):
            rest = lead.sub("", kept[0], count=1)
            kept[0] = rest[:1].upper() + rest[1:]
        def fill(sentence: str) -> str:
            out, last = [], 0
            for match in TOKEN.finditer(sentence):
                before = sentence[last:match.start()]
                form = forms[match.group(1)]
                if ABOUT_BEFORE.search(sentence[:match.start()]):
                    form = form.removeprefix("about ").removeprefix("noin ")
                out += [before, form]
                last = match.end()
            return DOUBLED.sub(r"\1", "".join(out) + sentence[last:])

        body = " ".join(fill(s) for s in kept)
        script = _readable(body, language)
        if spoken:
            script = f"{script} {_source(period, language)}"
        return script
    except Exception:  # noqa: BLE001 - the screen text is always a safe fallback
        return rendered
