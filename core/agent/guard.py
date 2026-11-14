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
FI_WORDS = re.compile(
    r"\b(paljonko|kuinka|mitä|mikä|mitkä|mihin|missä|millainen|olen|voin|käytin|kuussa|minun|onko|"
    r"kannattaako|myöntääkö|ketä|pitäisi|viikolla|säästää|rahani|kulutus\w*|tällä|viime)\b", re.I)


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


def detect_language(text: str) -> str | None:
    """'fi', 'en', or None when unsure (too little text)."""
    if re.search(r"[äöå]", text, re.I) or FI_WORDS.search(text):
        return "fi"
    if len(re.findall(r"[A-Za-z]{2,}", text)) >= 2:
        return "en"
    return None
