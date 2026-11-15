"""'What does this number mean?' after an answer (#821): the previous answer's main number explained.

`matches` is True only when the whole message asks what a number Sentti just gave means, where it comes from or how it
was calculated ("What does this number mean?", "Where did you get that?", "Mitäs tää numero tarkoittaa? Voitko selittää
mulle tarkasti", "Mistä tää luku tulee?", "Selitä tarkemmin"): a confident full match of every sentence, with a bare
pointer (this, that, it; tää, tämä, se) or a number word and nothing else that names a thing, a period or an amount.
A question about the user's own money ("What does my spending on restaurants look like?", "Mitä mun ruokamenot on?")
never matches: it keeps its own route.

The answer (orchestrator `_answer_explain_number`) is a template: the number's label and period, the method's summary
as the evidence sheet shows it, and the transactions it rests on, with a card whose action opens the evidence. With no
previous answer that cited a number, the question back asks which number. No plan, no model request.
"""

from __future__ import annotations

import re

from core.agent.guard import fold

_PTR_EN = r"(this|that|it|these|those|the)"
_THIS_EN = r"(this|that|these|those)"   # "what is the total?" is a question of its own
_NUM_EN = r"(numbers?|figures?|amounts?|sums?|totals?|values?|results?)"
_OBJ_EN = rf"( {_PTR_EN}( {_NUM_EN})?| {_NUM_EN})"
_MORE_EN = r"( to me)?( (in (more |full )?detail|more precisely|precisely|exactly|properly|further|more|again|a bit more|" \
           r"a little more))?"
_EN = [
    rf"what (does|do|did) {_PTR_EN}( {_NUM_EN})? (mean|stand for|show|tell me)",
    rf"what (is|s|are) {_THIS_EN} {_NUM_EN}( based on)?",
    rf"what (is|s|are) {_PTR_EN}( {_NUM_EN})? based on",
    rf"where (did|do) you get{_OBJ_EN}( from)?",
    rf"where (does|did|do) {_PTR_EN}( {_NUM_EN})? come from",
    rf"where (is|s|are) {_PTR_EN}( {_NUM_EN})? from",
    rf"how (did|do) you (calculate|compute|count|get|work out|figure out|come up with|arrive at|reach){_OBJ_EN}",
    rf"how (is|was|s|were|are) {_PTR_EN}( {_NUM_EN})? (calculated|computed|counted|worked out|made up)",
    rf"((can|could|would|will) you )?explain{_OBJ_EN}?{_MORE_EN}",
    rf"((can|could|would|will) you )?(break down|walk me through){_OBJ_EN}{_MORE_EN}",
]

_PTR_FI = r"(taa|tama|taman|tan|toi|tuo|tuon|ton|se|sen|nama|naa|noi|nuo)"
_NUM_FI = r"(luku|luvun|numero|numeron|summa|summan|lukema|lukeman|arvo|arvon|tulos|tuloksen)"
_OBJ_FI = rf"( {_PTR_FI}( {_NUM_FI})?| {_NUM_FI})"
_TO_ME_FI = r"( (mulle|minulle|meille))?"
_MORE_FI = r"( (tarkemmin|tarkasti|tarkempaa|lisaa|enemman|uudestaan|vahan|viela|kunnolla))*"
_FI = [
    rf"mita(s|ha|hn)?( {_PTR_FI})?( {_NUM_FI})? (tarkoittaa|tarkottaa|merkitsee|kertoo)",
    rf"mita(s|ha)? (talla|tolla|silla)( (luvulla|numerolla|summalla))? tarkoitetaan",
    rf"mista{_OBJ_FI} (tulee|on peraisin|tuli)",
    rf"mista (sait|saat|olet saanut|otit|otat){_OBJ_FI}",
    rf"(miten|kuinka) (laskit|lasket|olet laskenut|sait|saat|paadyit){_OBJ_FI}",
    rf"(miten|kuinka){_OBJ_FI} (on )?(laskettu|lasketaan|saatu|muodostuu|syntyy)",
    rf"selita{_TO_ME_FI}{_OBJ_FI}?{_TO_ME_FI}{_MORE_FI}",
    rf"(voitko|voisitko|voiksa|voitsa|voisiksa|voiks|voisitsa|osaatko) selittaa{_TO_ME_FI}{_OBJ_FI}?{_TO_ME_FI}"
    rf"{_MORE_FI}",
    rf"selittaisitko{_TO_ME_FI}{_OBJ_FI}?{_TO_ME_FI}{_MORE_FI}",
]

_LEAD = r"((ok|okay|okei|so|and|but|hmm|hm|um|hey|sorry|wait|no|ja|mut|mutta|hei|entas|anteeksi|siis|joo) )*"
_TAIL = r"( (please|pls|thanks|kiitos|pliis|sitten|siis|nyt))*"
_ASK = "|".join(_EN + _FI)
# a voice message may run two asks together with no punctuation ("mitäs tää numero tarkoittaa voitko selittää mulle")
_SENTENCE = re.compile(rf"{_LEAD}({_ASK})( (and |ja |or |vai )?({_ASK}))*{_TAIL}")
_FILLER_WORDS = frozenset({"ok", "okay", "okei", "so", "hmm", "hm", "um", "hey", "sorry", "wait", "hei", "joo",
                           "please", "pls", "thanks", "kiitos", "pliis", "anteeksi"})

LEAD = ("That's {label} for {period}.", "Luku on {label}, {period}.")
LEAD_ONLY_LABEL = ("That's {label}.", "Luku on {label}.")   # a period label the validator refuses ("the next 7 days")
COUNT = (("It rests on {count} transaction.", "It rests on {count} transactions."),
         ("Se perustuu {count} tapahtumaan.", "Se perustuu {count} tapahtumaan."))
WHICH = ("Which number would you like explained?", "Minkä luvun haluaisit selitettävän?")
ACTION = ("Show the calculation", "Näytä laskelma")


def matches(message: str) -> bool:
    """The whole message asks what a number just given means, or how it was calculated (see the module text)."""
    if not isinstance(message, str) or re.search(r"\d", message) or len(message) > 200:
        return False
    found = False
    for part in re.split(r"[.?!;:\n]+", fold(message)):
        words = " ".join(re.sub(r"[^\w\s']", " ", part).replace("'", "").split())
        if not words:
            continue
        if _SENTENCE.fullmatch(words):
            found = True
        elif not all(w in _FILLER_WORDS for w in words.split()):
            return False
    return found


def label_text(label: str) -> str:
    """The Number's label inside a sentence: lower case first letter unless it is an abbreviation ("S-Bonus")."""
    return label[:1].lower() + label[1:] if len(label) > 1 and label[1:2].islower() else label
