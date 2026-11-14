"""Step 1a, the input guard, and language detection (agent-core.md sections 7.1 and 7.7).

Nothing is blocked on keywords alone: "How much did I invest?" is a valid question about the user's
own Invest Deposit history (R7). The flags are hints for the planner and go into the audit record.
"""

from __future__ import annotations

import re
import unicodedata

# #526: an attempt to set the rules aside, or to speak as the system, is refused before any data tool is planned
# (core/agent/rules.py DECLINE_RULES, "unsafe") and flagged here. English and Finnish (the service languages),
# Swedish and Russian ignore-forms as well. Only the rules themselves or the system's own text: "ignore the rent",
# "the rules of thumb", "show me the S-Bonus rules" and "which system do you use" are ordinary questions.
# Known limits, not reached by a pattern: base64 or other encodings, leetspeak, homoglyphs (a Cyrillic "o" in
# "ignore"), and instructions spread over several turns or phrased as a persona ("from now on ..."). The answer
# pipeline still holds there: no model output can name a customer, call a write tool or state a number.
SET_ASIDE = (
    r"\b(ignore|forget|disregard|bypass|override)\s+(all\s+|any\s+)?(of\s+)?(your|the|these|those|previous|prior|"
    r"above|earlier)\s+((previous|prior|above|earlier)\s+)?(instructions|rules|guidelines|system prompt|prompt|"
    r"restrictions)\b(?!\s+of\s+thumb)|"
    r"\b(pretend|imagine|suppose)\b[^.?!]{0,40}\b(no|without)\s+(rules|limits|restrictions|instructions|guidelines)\b|"
    r"\b(reveal|print|show|repeat|recite|tell me)\s+(me\s+)?(your|the)\s+(system prompt|hidden (instructions|rules|"
    r"prompt))\b|\b(reveal|print|repeat|recite)\s+(me\s+)?your\s+(instructions|rules|prompt)\b|"
    r"\brepeat the (text|words|message) above\b|\bhidden (instructions|rules|prompt)\b|"
    r"\b(unohda|ohita|sivuuta)\b[^.?!]{0,40}\b(ohje\w*|säännö\w*|sääntö\w*|rajoitu\w*)|"
    r"\bälä välitä\b[^.?!]{0,40}\b(ohje\w*|säännö\w*|sääntö\w*)|"
    r"\b(kerro|näytä|toista|paljasta)\b[^.?!]{0,30}\b(ohjeesi|sääntösi)\b|\bjärjestelmäkehot\w*|"
    r"\bignorera\s+(alla\s+|tidigare\s+|dina\s+)*(instruktioner|regler)\b|"
    r"\u0438\u0433\u043d\u043e\u0440\u0438\u0440\u0443[\u0438\u0439][^.?!]{0,40}\u0438\u043d\u0441\u0442\u0440\u0443\u043a\u0446\u0438")
# Role text in the user's message: "[system: ...]", "<system>", "[INST]", "</user_message>", "system:" at the start.
ROLE_TEXT = (r"\[\s*/?\s*(system|developer|assistant|admin|inst)\b[^\]]{0,200}\]|"
             r"<\s*/?\s*(system|developer|assistant|user_message|admin)\s*>|<\|\s*(system|im_start|im_end)|"
             r"^\W*(system|developer)\s*:")
# Softer headers that only flag (the planner sees the flag): a refusal would catch ordinary questions too often.
SOFT_HEADERS = r"#{2,}\s*new instructions|\bnote for the assistant\b|\btool result\s*:"

FLAGS = {
    # "you are now" and "act as" only with a persona after them (#526): "You are now over budget" and "my savings
    # act as a buffer" are ordinary questions.
    "injection_marker": r"ignore (all |the )?(previous|prior|above) instructions|system (prompt|override)|"
                        r"admin mode|developer mode|"
                        r"\byou are now (in |an? )?(admin|developer|dan|free\w*|unrestricted|uncensored|jailbroken|my|"
                        r"a different|another)\b|"
                        r"\bact as (if you|though you|an? (different|new|unrestricted|uncensored|evil)\b|my (grandmother|"
                        r"admin|developer)\b|dan\b)|" + SET_ASIDE + "|" + ROLE_TEXT + "|" + SOFT_HEADERS,
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
    r"kumpi\w*|kumpaa|\w+mpi|\w+mpaa|halvin\w*|kallein\w*|"   # comparisons: "kumpi on halvempi?"
    r"kuka|olet|oletko|osaat|kiitos|kiitti|apua|hei|moi|moikka|terve|huomenta")   # questions to Sentti (#287)
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
    """The guard's hints for one message, read as written and folded ("ala valita ohjeistasi" as "älä välitä
    ohjeistasi"), as the rules read it (#526)."""
    folded = fold(message)
    return [name for name, rx in FLAGS.items()
            if re.search(rx, message, re.I) or re.search(fold_pattern(rx), folded, re.I)]


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
