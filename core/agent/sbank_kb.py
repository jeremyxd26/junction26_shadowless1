"""S-Bank knowledge base (#791): a question about S-Bank or S-mobiili answered from S-Bank's public help pages.

The answers are ours, fixed in core/knowledge/sbank_faq.yaml in English and Finnish, each with its source page;
the model never writes one. No number, no price, no advice, never the bank's voice.

The one lookup is `find_bank_entry(question, lang)`: the route and the template answer call only it, so a
retriever can replace it later and the answer stays a template built from the entry. Its first implementation
is a keyword matcher: the entry whose phrases (in the request's language) cover the most of the message.

`answer_for` decides the route's text: the matching entry and its source line, or, for a message clearly about
S-Bank that matches no entry, the "I don't know that one" line. A message about the customer's own figures
("How much did I spend at S-market?", "my S-mobiili balance") or one asking for a recommendation is never
claimed here; the orchestrator also leaves a message to the usual path when a rule declines it or a data rule
claims it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from core.agent.guard import fold

log = logging.getLogger(__name__)

KB_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "sbank_faq.yaml"


@dataclass(frozen=True)
class Entry:
    id: str
    topic: str
    questions_en: tuple[str, ...]
    questions_fi: tuple[str, ...]
    answer_en: str
    answer_fi: str
    source_url: str
    retrieved_at: str
    keywords_en: tuple[str, ...] = ()
    keywords_fi: tuple[str, ...] = ()

    def answer(self, lang: str) -> str:
        return self.answer_fi if lang == "fi" else self.answer_en


def _load(path: Path = KB_PATH) -> tuple[Entry, ...]:
    """The entries of the file; none when the file is missing or unreadable (the route then never answers)."""
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        log.error("S-Bank knowledge base not loaded (%s)", type(exc).__name__)
        return ()
    out = []
    for raw in doc.get("entries") or []:
        keywords = raw.get("keywords") or {}
        out.append(Entry(id=str(raw["id"]), topic=str(raw["topic"]),
                         questions_en=tuple(raw.get("questions_en") or ()),
                         questions_fi=tuple(raw.get("questions_fi") or ()),
                         answer_en=str(raw["answer_en"]).strip(), answer_fi=str(raw["answer_fi"]).strip(),
                         source_url=str(raw["source_url"]), retrieved_at=str(raw["retrieved_at"]),
                         keywords_en=tuple(keywords.get("en") or ()), keywords_fi=tuple(keywords.get("fi") or ())))
    return tuple(out)


ENTRIES: tuple[Entry, ...] = _load()
BY_ID = {e.id: e for e in ENTRIES}

SOURCE_LINE = ("From S-Bank's public help pages: {url}", "S-Pankin julkisilta ohjesivuilta: {url}")
UNKNOWN = ("I don't know that one; the bank can tell you.", "En tiedä sitä; pankki osaa kertoa.")

# The message names S-Bank, S-mobiili or an S-Bank card (folded: lower case, no diacritics).
ABOUT_SBANK = r"\bs[- ]?(?:bank|pankk|pankin|mobiil|etukort)\w*"
# The customer's own figures: a data question, never a knowledge-base answer.
OWN_FIGURES = (r"\d|€|\beur(?:o|os)?\b|\bhow (?:much|many)\b|\bbalance\b|\b(?:did|have|had) (?:i|we) "
               r"(?:spend|spent|pay|paid|buy|bought|earn|earned|get|got|receive|received|save|saved)\b|"
               r"\bi (?:spent|paid|bought|earned|saved)\b|\bmy (?:spending|money|income|salary|budget|savings|"
               r"expenses|bills|purchases|transactions)\b|"
               r"\bpaljonko\b|\bkuinka (?:paljon|monta)\b|\bmontako\b|\bsaldo\w*|\bkaytin\b|\bkulutin\b|"
               r"\bmaksoin\b|\bostin\b|\bsaastin\b|\bkulutukse\w*|\btuloni\b|\bmenoni\b|\bostokseni\b|"
               r"\btapahtumani\b|\brahani (?:menivat|meni|riittavat|riittaa)\b")
# A recommendation or a comparison: out of scope (the mentor rule), never a knowledge-base answer.
ADVICE = (r"\bshould i\b|\bwhich (?:\w+ )?(?:is|would be) (?:better|best)\b|\bbest\b|\bbetter\b|\brecommend\w*|"
          r"\bworth it\b|\bcompare\w*|\bkannattaako\b|\bkannattaa\b|\bparas\w*|\bparempi\w*|\bsuosittel\w*|"
          r"\bvertaa\w*")


def _norm(text: str) -> str:
    text = fold(text).replace("’", "'")
    return " ".join(re.sub(r"[^\w\s'/-]", " ", text).split())


def _compile(phrases: tuple[str, ...]) -> tuple[tuple[re.Pattern, int], ...]:
    return tuple((re.compile(r"(?<![\w-])" + re.escape(_norm(p))), len(_norm(p))) for p in phrases if _norm(p))


_KEYWORDS = {e.id: {"en": _compile(e.keywords_en + e.questions_en), "fi": _compile(e.keywords_fi + e.questions_fi)}
             for e in ENTRIES}


def about_sbank(question: str) -> bool:
    return bool(re.search(ABOUT_SBANK, _norm(question)))


def own_figures(question: str) -> bool:
    return bool(re.search(OWN_FIGURES, _norm(question)))


def asks_advice(question: str) -> bool:
    return bool(re.search(ADVICE, _norm(question)))


def find_bank_entry(question: str, lang: str) -> Entry | None:
    """The knowledge-base entry that answers the question in this language, or None. The keyword matcher:
    the entry whose phrases (keywords and question variants) cover the most characters of the message; a tie
    goes to the earlier entry in the file."""
    text = _norm(question)
    lang = "fi" if lang == "fi" else "en"
    best, best_score = None, 0
    for entry in ENTRIES:
        score = sum(size for rx, size in _KEYWORDS[entry.id][lang] if rx.search(text))
        if score > best_score:
            best, best_score = entry, score
    return best


@dataclass(frozen=True)
class KbAnswer:
    entry_id: str | None   # None: the "I don't know that one" line
    text: str


def answer_for(question: str, lang: str) -> KbAnswer | None:
    """The route's answer, or None (the usual path): the entry's text and its source line; for a message
    clearly about S-Bank with no entry, the "I don't know that one" line. Never for the customer's own figures,
    a recommendation, or a message with more than one line."""
    if not question.strip() or "\n" in question.strip() or own_figures(question) or asks_advice(question):
        return None
    i = 1 if lang == "fi" else 0
    entry = find_bank_entry(question, lang)
    if entry is not None:
        return KbAnswer(entry.id, f"{entry.answer(lang)} {SOURCE_LINE[i].format(url=entry.source_url)}")
    if about_sbank(question):
        return KbAnswer(None, UNKNOWN[i])
    return None
