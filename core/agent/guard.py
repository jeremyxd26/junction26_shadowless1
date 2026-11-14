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
# - FI_STRONG: words that are Finnish and never English; each counts 2.
# - FI_WEAK: short Finnish function words; each counts 1. "on" is left out: it is English too.
# - EN_WORDS: English function words; each counts 1.
# Finnish needs a score of at least 2 and more than the English score; English needs one English word.
# Anything else is unsure (None): the request's language, then the conversation's, then English.
FI_STRONG = re.compile(
    r"paljon(ko)?|kuinka|mita|mika|mitka|mihin|missa|mista|millainen|miten|milloin|miksi|onko|"
    r"olen(ko)?|olisi\w*|voin(ko)?|voisi\w*|saan(ko)?|kaytin|kaytan|kayta\w*|kulut\w*|kuussa|kuukau\w*|"
    r"viikko\w*|viikolla|minun|minulla|minulle|minut|kannattaako|myontaako|keta|pitaisi|saast\w*|"
    r"raha\w*|talla|tassa|viime|tanaan|huomenna|kerro\w*|haukku|takia|ole|tyly|enta|lasku\w*|"
    r"palkka\w*|ruoka\w*|ravintol\w*|turvallisesti|vahenta\w*")
FI_WEAK = re.compile(r"ja|ei|en|se|etta|kun|jos|mutta|tai|nyt|vai|kanssa|siita|mina|sina")
EN_WORDS = re.compile(
    r"the|a|an|i|me|my|you|your|is|are|was|were|did|do|does|can|could|would|should|how|what|where|"
    r"when|which|why|much|many|and|or|of|to|in|on|at|for|with|this|that|last|month|week|spend|spent|"
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


def detect_language(text: str) -> str | None:
    """'fi', 'en', or None when unsure. Typed with or without ä and ö (issue #140)."""
    if re.search(r"[äöå]", text, re.I):
        return "fi"
    words = re.findall(r"[a-z]+", _without_dots(text))
    fi = sum(2 for w in words if FI_STRONG.fullmatch(w)) + sum(1 for w in words if FI_WEAK.fullmatch(w))
    en = sum(1 for w in words if EN_WORDS.fullmatch(w))
    if fi >= 2 and fi > en:
        return "fi"
    if en >= 1:
        return "en"
    return None
