"""Step 1a, the input guard, and language detection (agent-core.md sections 7.1 and 7.7).

Nothing is blocked on keywords alone: "How much did I invest?" is a valid question about the user's
own Invest Deposit history (R7). The flags are hints for the planner and go into the audit record.
"""

from __future__ import annotations

import re
import unicodedata

FLAGS = {
    "injection_marker": r"ignore (all |the )?(previous|prior|above) instructions|system (prompt|override)|"
                        r"admin mode|developer mode|you are now|act as",
    "investment_keyword": r"\b(stocks?|shares?|funds?|etfs?|crypto|bitcoin|osake\w*|rahasto\w*)\b",
    "other_person": r"\bCUST\d+|neighbou?r|naapuri|someone else|other customers?|muiden",
}
# Language detection (R14, issue #140) works on words with the dots taken off ("mitä" and "mita" are
# one word), because people often type Finnish on a phone without ä and ö.
# - FI_STRONG: words that are Finnish and never English, and any word with ä or ö; each counts 2.
# - FI_WEAK: short Finnish function words; each counts 1. "on" is left out: it is English too.
# - EN_WORDS: English function words; each counts 1.
# A capitalised word that does not start a sentence is a name ("K-Ruoka", "Ravintola Savoy", "Käpylä")
# and never counts as Finnish. "å" alone is no Finnish signal: Swedish has it too.
# Known limit: Swedish with ä or ö ("Hur mycket har jag använt på mat?") is detected as Finnish, because
# a lower-case word with ä or ö counts 2. The service has no Swedish, so a Finnish answer is accepted.
# The detector is linear in the text: the validator also runs it on model output, which has no bound.
# Finnish needs a score of at least 2 and more than the English score; English needs one English word.
# Anything else is unsure (None): the request's language, then the conversation's, then English.
FI_STRONG = re.compile(
    r"paljon(ko)?|kuinka|mita|mika|mitka|mihin|missa|mista|millainen|miten|milloin|miksi|onko|"
    r"olen(ko)?|olisi\w*|voin(ko)?|voisi\w*|saan(ko)?|kaytin|kaytan|kayta\w*|kulut\w*|kuussa|kuukau\w*|"
    r"viikko\w*|viikolla|minun|minulla|minulle|minut|kannattaako|myontaako|keta|pitaisi|saast\w*|"
    r"raha\w*|talla|tassa|viime|tanaan|huomenna|kerro\w*|haukku|takia|ole|tyly|enta|lasku\w*|"
    r"palkka\w*|ruoka\w*|ravintol\w*|turvallisesti|vahenta\w*|"
    r"kumpi\w*|kumpaa|\w+mpi|\w+mpaa|halvin\w*|kallein\w*")   # comparisons: "kumpi on halvempi?"
FI_WEAK = re.compile(r"ja|ei|en|se|etta|kun|jos|mutta|tai|nyt|vai|kanssa|siita|mina|sina")
EN_WORDS = re.compile(
    r"the|a|an|i|me|my|you|your|is|are|was|were|did|do|does|can|could|would|should|how|what|where|"
    r"when|which|why|much|many|and|or|of|to|in|on|at|for|with|this|that|last|month|week|spend|spent|spending|"
    r"money|save|cut|if|tell|show|give|it")


def clean(message: str) -> str:
    """Strip control characters (keep line breaks and tabs as spaces) and surrounding whitespace."""
    out = []
    for ch in message:
        if ch in "\n\t\r":
            out.append(" ")
        elif unicodedata.category(ch)[0] != "C":
            out.append(ch)
    return "".join(out).strip()


def flags(message: str) -> list[str]:
    return [name for name, rx in FLAGS.items() if re.search(rx, message, re.I)]


def _without_dots(text: str) -> str:
    """Lower case, with diacritics taken off: "Mistä säästää?" -> "mista saastaa?"."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _finnish_score(word: str) -> int:
    if re.search(r"[äö]", word, re.I):
        return 2
    plain = _without_dots(word)
    return 2 if FI_STRONG.fullmatch(plain) else 1 if FI_WEAK.fullmatch(plain) else 0


def detect_language(text: str) -> str | None:
    """'fi', 'en', or None when unsure. Typed with or without ä and ö (issue #140)."""
    fi = en = 0
    end = 0
    for m in re.finditer(r"[^\W\d_]+", text):
        word = m.group(0)
        # Only the gap since the previous word is looked at, so the whole run is linear in the text.
        starts_sentence = end == 0 or any(ch in ".!?" for ch in text[end:m.start()])
        end = m.end()
        if starts_sentence or not word[0].isupper():  # a capitalised word inside a sentence is a name
            fi += _finnish_score(word)
        en += 1 if EN_WORDS.fullmatch(_without_dots(word)) else 0
    if fi >= 2 and fi > en:
        return "fi"
    if en >= 1:
        return "en"
    return None


def fold(text: str) -> str:
    """A question as the rules read it: lower case, without diacritics ("Mitä?" -> "mita?"), so a Finnish
    question typed without ä and ö matches the same rules (issue #140, dev check of PR #195)."""
    return _without_dots(text)


def fold_pattern(pattern: str) -> str:
    """A rule pattern without diacritics, its case kept (regex escapes such as \\W stay as they are)."""
    decomposed = unicodedata.normalize("NFKD", pattern)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))
