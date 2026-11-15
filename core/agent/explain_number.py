"""'What does this number mean?' after an answer (#821): the previous answer's main number explained.

`matches` is True only when the whole message asks what a number Sentti just gave means, where it comes from or how it
was calculated ("What does this number mean?", "Where did you get that?", "Mitäs tää numero tarkoittaa? Voitko selittää
mulle tarkasti", "Mistä tää luku tulee?", "Selitä tarkemmin"), or asks to have it said more simply ("Selitä
yksinkertaisemmin", "Can you put that more simply?"): a confident full match of every sentence, with a bare pointer
(this, that, it; tää, tämä, se) or a number word and nothing else that names a thing, a period or an amount.
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
# "more simply", "in simpler words": the plain explanation is the simpler way to say the answer's main number
_SIMPLER_EN = r"(more simply|simply|simpler|more clearly|in (simpler|plainer|plain|easier|simple) (terms|words|language|english)|" \
              r"like (im|i am) five)"
_MORE_EN = r"( to me)?( (in (more |full )?detail|more precisely|precisely|exactly|properly|further|more|again|a bit more|" \
           rf"a little more|{_SIMPLER_EN}))?"
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
    rf"((can|could|would|will) you )?(say|put|tell me|rephrase|word){_OBJ_EN} {_SIMPLER_EN}( please)?",
    r"(in (simpler|plainer|plain|easier) (terms|words|language|english)|simpler|more simply)",
]

_PTR_FI = r"(taa|tama|taman|tan|toi|tuo|tuon|ton|se|sen|nama|naa|noi|nuo)"
_NUM_FI = r"(luku|luvun|numero|numeron|summa|summan|lukema|lukeman|arvo|arvon|tulos|tuloksen)"
_OBJ_FI = rf"( {_PTR_FI}( {_NUM_FI})?| {_NUM_FI})"
_TO_ME_FI = r"( (mulle|minulle|meille))?"
_SIMPLER_FI = r"(yksinkertaisemmin|selkeammin|helpommin|simppelimmin|selkokielella|ymmarrettavammin|lyhyemmin|lyhyesti)"
_MORE_FI = rf"( (tarkemmin|tarkasti|tarkempaa|lisaa|enemman|uudestaan|vahan|viela|kunnolla|sanoin|{_SIMPLER_FI}))*"
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
    rf"(sano|kerro|sanoisitko|kertoisitko|(voitko|voisitko|voiksa|voitsa) (sanoa|kertoa)){_OBJ_FI}?{_TO_ME_FI}"
    rf"( (vahan|viela))* {_SIMPLER_FI}( sanoin)?",
    rf"{_SIMPLER_FI}( sanoin)?",
]

_LEAD = r"((ok|okay|okei|so|and|but|hmm|hm|um|hey|sorry|wait|no|ja|mut|mutta|hei|entas|anteeksi|siis|joo) )*"
_TAIL = r"( (please|pls|thanks|kiitos|pliis|sitten|siis|nyt))*"
_ASK = "|".join(_EN + _FI)
# a voice message may run two asks together with no punctuation ("mitäs tää numero tarkoittaa voitko selittää mulle")
_SENTENCE = re.compile(rf"{_LEAD}({_ASK})( (and |ja |or |vai )?({_ASK}))*{_TAIL}")
_FILLER_WORDS = frozenset({"ok", "okay", "okei", "so", "hmm", "hm", "um", "hey", "sorry", "wait", "hei", "joo",
                           "please", "pls", "thanks", "kiitos", "pliis", "anteeksi"})

LEAD = ("This is {label} for {period}.", "Tämä luku on {label}, {period}.")
LEAD_ONLY_LABEL = ("This is {label}.", "Tämä luku on {label}.")   # a period label the validator refuses ("the next 7 days")
# The number's own name in a sentence, where the method table's name reads oddly (local display strings only: no tool
# output and no model cache change). Safe to spend is "left to spend" / "käyttövara" on screen; the name carries its period.
NAMES = {
    "safe_to_spend.safe_to_spend_7d_eur@1": ("what's left to spend this week", "käyttövarasi tällä viikolla"),
}
COUNT = (("It rests on {count} transaction.", "It rests on {count} transactions."),
         ("Se perustuu {count} tapahtumaan.", "Se perustuu {count} tapahtumaan."))
WHICH = ("Which number would you like explained?", "Minkä luvun haluaisit selitettävän?")
_PEER = ("A figure of a group of similar customers, compared with your own monthly average; no one's own data is shown.",
         "Samankaltaisten asiakkaiden ryhmän tunnusluku verrattuna omaan kuukausikeskiarvoosi; kenenkään omia tietoja "
         "ei näytetä.")
# The evidence sheet's method summary (core/app/api/texts.py METHODS) with its digits ("the next 7 days", "x 7 /
# 30.4375", "at least 20") put in words: an answer text names no number that is not a Number (the validator).
SUMMARIES = {
    "safe_to_spend.safe_to_spend_7d_eur@1": (
        "The smaller of what your balance allows and what your monthly budget allows for the coming week, after your "
        "savings goal.",
        "Pienempi niistä summista, jotka saldosi ja kuukausibudjettisi sallivat tulevalle viikolle, kun säästötavoite on "
        "ensin laitettu sivuun."),
    "safe_to_spend.balance_limit_7d_eur@1": (
        "What is free until payday, spread evenly over the days to payday, for the coming week.",
        "Palkkapäivään asti vapaana oleva summa jaettuna tasan palkkapäivään jäljellä oleville päiville, tulevalle "
        "viikolle."),
    "safe_to_spend.budget_limit_7d_eur@1": (
        "What a typical month leaves free, minus your savings goal, scaled to a week.",
        "Tavallisesta kuukaudesta vapaaksi jäävä summa miinus säästötavoite, muunnettuna viikolle."),
    "safe_to_save.week_eur@1": ("What a typical month leaves, per week.", "Mitä tavallisesta kuukaudesta jää, viikkoa kohden."),
    "safe_to_save.day_eur@1": ("What a typical month leaves, per day.", "Mitä tavallisesta kuukaudesta jää, päivää kohden."),
    "safe_to_spend.usual_week_eur@1": (
        "Usual everyday spending in a typical month of the last six, per week.",
        "Tavallinen arkikulutus kuuden viime kuukauden tavallisessa kuukaudessa viikkoa kohden."),
    **{f"peer_benchmark.{m}@1": _PEER for m in ("peer_median_month_eur", "peer_p25_month_eur", "peer_p75_month_eur",
                                                 "percentile", "vs_median_pct", "peer_n")},
}
ACTION = ("Show the calculation", "Näytä laskelma")


def asks_simpler(message: str) -> bool:
    """An explain message that asks to have the last answer said more simply ("Selitä yksinkertaisemmin", "Explain it
    more simply"): after an answer in words it is talk mode's, not the number's (Codex run, test 11)."""
    return matches(message) and bool(re.search(rf"\b({_SIMPLER_EN}|{_SIMPLER_FI})\b", fold(message)))


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


def label_for(number, lang: str) -> tuple[str, bool]:
    """The number's label in the answer's language, and whether it was put into it (#833). After an answer in the other
    language the Number keeps that answer's label ("Safe to spend" before "Mitä tää numero tarkoittaa?"); when the label
    is its method's name in the other language, the method table gives it in this one. True: translated, so the period,
    still in the earlier answer's language, is left to the card."""
    from core.app.api import texts as api_texts   # the method table, as the evidence sheet names the number

    own = NAMES.get(number.method)
    if own is not None:
        return (own[1] if lang == "fi" else own[0]), True
    name = api_texts.method_info(number.method).name
    mine, other = (name[1], name[0]) if lang == "fi" else (name[0], name[1])
    if number.label == other and other != mine:
        return mine, True
    return number.label, False


def label_text(label: str) -> str:
    """The Number's label inside a sentence: lower case first letter unless it is an abbreviation ("S-Bonus")."""
    return label[:1].lower() + label[1:] if len(label) > 1 and label[1:2].islower() else label
