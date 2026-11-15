"""Talk mode (#873): "why does it matter?", "explain", "I don't understand", "any tips?", "no numbers" get a short answer
in words, the `answer_in_words` route.

`trigger(message)` names the kind of a talk question, or None. It reads the folded message (guard.fold), never a
question that asks for a figure ("how much…", "paljonko…", any digit). A whole message that is only "explain" or
"selitä" stays the explain-number route (#821), which the pipeline asks first; here "explain" counts only beside
another talk sentence ("why does it matter? explain"). `follow_up(message)` is an open follow-up ("why?", "what
else?", "kerro lisää"), which keeps the mode after a talk answer, and after any data answer on the voice channel.

The answer (orchestrator `_answer_talk`) is the composer's, 2 to 4 plain sentences, with no card and one next-step
chip. It may cite at most one number, and only one already shown in this conversation (re-registered for the turn).
`draft_problems` is the whole output check; on failure, `template_text` reasons without numbers.

Tips are ranked here, in code, by the monthly euros each lever's tool computed (`rank_tips`), never by the model:
a savings plan lever's saving, a what-if's saving a month, the small purchases' monthly total. A lever under
MIN_TIP_EUR a month, or under MIN_TIP_SHARE of the monthly spending when that is known, is never given.
"""

from __future__ import annotations

import re
from typing import Any

from core.agent import talk_checks
from core.agent.guard import fold
from core.agent.validator import TOKEN, render
from core.answer_text import SENTENCE_BREAK, length_problems, scan_numbers

MIN_TIP_EUR = 20.0
MIN_TIP_SHARE = 0.01

# ---- triggers -------------------------------------------------------------------------------------------------------

_WHY = [
    r"\bwhy (does|do|would|should|is|did|will) (it|this|that|any of (this|that|it)|these|those|this stuff|that stuff)"
    r"( (really|even|actually))? (matter|matters|important|count)\b",
    r"\bwhy (it|this|that) (matters|is important)\b",
    r"\bhow (does|do|would|will|is) (it|this|that)( (really|even|actually))? (matter|help|important)\b",
    r"\bwhy should i care\b",
    r"\bwhat difference does (it|this|that) make\b",
    r"\bmiksi (silla|talla|tolla|sil|se|tama|tuo|toi|taa)? ?(on|olis|olisi|ois|oisi) (valia|merkitysta|tarkeaa)\b",
    r"\bmita valia (silla|talla|tolla) (on|olis|olisi)\b",
    r"\bmiten (se|tama|tuo|toi|taa) (auttaa|vaikuttaa)\b",
]
_UNDERSTAND = [
    r"\bi (do not|dont|didnt|did not) (really )?(understand|get it|get that|get this|follow)\b",
    r"\bi (am|m) (confused|lost)\b",
    r"\ben (oikein |ihan )?(tajua|tajunnut|ymmarra|ymmartanyt|kasita)\b",
]
_TIPS = [
    r"\b(tips?|advice|suggestions?|recommendations?|pointers)\b",
    r"\bwhat (should|could|can|shall) i do\b",
    r"\bwhat (do|would) you (suggest|recommend|advise)\b",
    r"\b(vinkk\w*|vinki\w*|neuvo|neuvoa|neuvoja|neuvot|ehdotu\w*|ehdota|ehdottaisit)\b",
    r"\bmita (mun|minun|ma|mina) (pitais|pitaisi|kannattais|kannattaisi|kannattaa|vois|voisin|voin)\w* tehda\b",
    r"\bmita (teen|tekisin|kannattaa tehda)\b",
]
_NO_NUMBERS = [
    r"\b(no|without|not|dont need|don t need|do not need|dont want|do not want|skip the|less|fewer|stop with the"
    r"|no more|not more) (more )?(the |any )?(numbers|figures|stats|statistics)\b",
    r"\bjust (talk|chat|in words|words)\b",
    r"\bin (plain )?words\b",
    r"\b(ei|ilman|en tarvi\w*|en tarvitse|en halua|ei enaa) (enaa |mitaan |yhtaan )?(numeroita|numerot|lukuja|luvut)\b",
]
# "explain" counts as a sentence of its own beside another talk sentence ("why does it matter? explain"); alone, the
# whole message is the explain-number route's (#821), which runs first
_EXPLAIN_SENTENCE = re.compile(
    r"((can|could|would|will) you )?(explain|selita|selittaisitko|(voitko|voisitko|voiksa) selittaa)"
    r"( (it|that|this|why|more|please|to me|again|better|se|sita|tama|tata|toi|mulle|minulle|lisaa|tarkemmin|viela"
    r"|paremmin|kiitos))*")
KINDS = (("why", _WHY), ("understand", _UNDERSTAND), ("tips", _TIPS), ("no_numbers", _NO_NUMBERS))
_KIND_RX = [(kind, re.compile("|".join(parts))) for kind, parts in KINDS]
# A question for a figure keeps its own route ("how much should I save, any tips?")
_FIGURE = re.compile(r"\bhow (much|many)\b|\bwhat (is|s|was|are|were) my\b|\bpaljonko\b|\bkuinka (paljon|monta)\b"
                     r"|\bmontako\b|\bpaljon (mina|ma) \w+|\bwhat if\b|\bjos (mina|ma|vahentaisin)\b|\bwhat does (this|that|it)"
                     r" (number|figure)\b|\bmita (tama|taa|toi|tuo) (numero|luku)\b")
_OPEN = re.compile(
    r"((and|so|ok|okay|but|hmm|well|right|ja|no|okei|joo|mut|mutta|entas|eli) )*"
    r"(why|why not|why so|how|how so|how come|what else|anything else|and then|then what|what now|what next|go on"
    r"|tell me more|more|like what|such as|for example|for instance|really|meaning|and|in what way|what do you mean"
    r"|miksi|miksi niin|miten|miten niin|mita muuta|kerro lisaa|kerro viela|jatka|esimerkiksi|kuten|entas sitten"
    r"|ja sitten|mita sitten|siis|niin|mita tarkoitat|mita meinaat|onko muuta|muuta)"
    r"( (please|then|sitten|kiitos|again|more|viela))*")
_MAX_CHARS = 300
# The question side of the stand-down (orchestrator `_talk_stands_down`): a talk question about a bank, a product, an
# investment, gambling, someone else's money or health keeps the normal path, where the rules decline or ask back as
# they do today. Broad on purpose: a miss here would only send the question to dev's route.
TOPIC_STANDS_DOWN = re.compile(
    r"\b(banks?|banking|pankki\w*|pankin|accounts?|tili\w*|cards?|kortti\w*|kortin|funds?|rahasto\w*|stocks?|shares?"
    r"|osake\w*|osakkeiden|invest\w*|sijoit\w*|crypto\w*|krypto\w*|bitcoin\w*|ethereum|insurance|vakuut\w*|apps?"
    r"|sovellu\w*|broker\w*|nordea\w*|nordnet\w*|op|danske\w*|s-pankki\w*|s-mobiili\w*|tesla\w*|etf|gold|kulta\w*|gambl\w*|casino\w*"
    r"|kasino\w*|betting|bets?|vedonly\w*|uhkapel\w*|veikkau\w*|lotter\w*|lotto\w*|tax|taxes|taxation|verot|verotus"
    r"|veroja|partner\w*|wife|husband|spouse|puoliso\w*|vaimo\w*|miehe\w*|ystava\w*|friend\w*)\b")


def _words(part: str) -> str:
    return " ".join(re.sub(r"[^\w\s']", " ", part).replace("'", "").split())


def trigger(message: str) -> str | None:
    """The talk kind of the message ("why", "understand", "tips", "no_numbers", "explain"), or None."""
    if not isinstance(message, str) or len(message) > _MAX_CHARS or re.search(r"\d", message):
        return None
    folded = fold(message)
    flat = _words(folded)
    if not flat or _FIGURE.search(flat):
        return None
    for kind, rx in _KIND_RX:
        if rx.search(flat):
            return kind
    return None


def explain_beside(message: str) -> bool:
    """A sentence that is only "explain" / "selitä" (with a pointer), in a message of more than one sentence."""
    parts = [_words(p) for p in re.split(r"[.?!;:\n]+", fold(message or ""))]
    parts = [p for p in parts if p]
    return len(parts) > 1 and any(_EXPLAIN_SENTENCE.fullmatch(p) for p in parts)


def follow_up(message: str) -> bool:
    """An open follow-up with nothing else in it ("why?", "what else?", "kerro lisää", "and then?")."""
    if not isinstance(message, str) or len(message) > 80 or re.search(r"\d", message):
        return False
    parts = [_words(p) for p in re.split(r"[.?!;:\n]+", fold(message))]
    parts = [p for p in parts if p]
    return bool(parts) and all(_OPEN.fullmatch(p) for p in parts)


def wants_more_tips(message: str) -> bool:
    """"Any more tips?", "anything else?", "lisää vinkkejä": the next lever of the ranking, not the first one."""
    flat = _words(fold(message or ""))
    return bool(re.search(r"\b(more|other|another|else|next|lisaa|muita|muuta|toinen|seuraava|viela)\b", flat))


# ---- tips ranked by money impact ------------------------------------------------------------------------------------

_SMALL = ("small purchases", "pienet ostokset")


def _value(number: Any) -> float | None:
    if isinstance(number, dict) and isinstance(number.get("value"), (int, float)):
        return float(number["value"])
    return None


def monthly_spending(views: list[dict[str, Any]]) -> float | None:
    """The monthly everyday spending the tools computed, for the 1 % floor: the small purchases' monthly total
    divided by their share of everyday spending. None when no tool of the conversation gave it."""
    for view in views:
        if isinstance(view, dict) and view.get("tool") == "get_small_purchases":
            per_month, share = _value(view.get("per_month")), _value(view.get("share_of_everyday"))
            if per_month and share and share > 0:
                return per_month / (share / 100.0)
    return None


def rank_tips(views: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    """The levers the conversation's tools computed, largest monthly euro impact first, without the immaterial ones
    (under MIN_TIP_EUR a month, or under MIN_TIP_SHARE of the monthly spending when known). Each: key, label,
    monthly_eur, source. The euros stay in code: the composer gets the order and the labels only."""
    found: dict[str, dict[str, Any]] = {}

    def add(key: str, label: str, eur: float | None, source: str) -> None:
        if not label or eur is None:
            return
        if key not in found or eur > found[key]["monthly_eur"]:
            found[key] = {"key": key, "label": label, "monthly_eur": round(eur, 2), "source": source}

    for view in views:
        if not isinstance(view, dict):
            continue
        tool = view.get("tool")
        if tool == "get_savings_plan":
            for lever in view.get("levers") or []:
                add(f"category:{lever.get('key')}", str(lever.get("category") or ""), _value(lever.get("saving")),
                    tool)
        elif tool == "run_what_if":
            sel = view.get("selection") or {}
            if sel.get("kind") == "category":
                add(f"category:{sel.get('value')}", str(sel.get("value") or ""), _value(view.get("saving_per_month")),
                    tool)
        elif tool == "get_small_purchases":
            add("small_purchases", _SMALL[1] if language == "fi" else _SMALL[0], _value(view.get("per_month")), tool)
    spend = monthly_spending(views)
    floor = max(MIN_TIP_EUR, MIN_TIP_SHARE * spend) if spend else MIN_TIP_EUR
    ranked = [t for t in found.values() if t["monthly_eur"] >= floor]
    return sorted(ranked, key=lambda t: (-t["monthly_eur"], t["label"]))


# ---- the output check -----------------------------------------------------------------------------------------------

def _sentences(text: str) -> int:
    return len([s for s in SENTENCE_BREAK.split(text.strip()) if s.strip()])


def draft_problems(text: str, numbers: dict[str, Any], shown: set[str], language: str) -> list[str]:
    """Every reason a talk-mode draft is rejected; [] when it passes. `numbers` is the turn's registry (the shown
    numbers re-registered), `shown` their ids."""
    problems: list[str] = []
    used = set(TOKEN.findall(text))
    if len(used) > 1:
        problems.append("at most one number: cite one number already shown in this conversation, or none")
    for token in sorted(used):
        if token not in shown:
            problems.append(f"'{token}': only a number already shown in this conversation may be cited")
    stripped = TOKEN.sub(" ", text)
    if re.search(r"\d", stripped):
        problems.append("a number that was not shown in this conversation: write no number except one cited token")
    # The new check (#873): every number the user reads equals a number already shown in this conversation
    if not problems:
        values = [float(numbers[t].value) for t in used if t in numbers]
        for value, _unit in scan_numbers(render(text, numbers), language):
            if not any(abs(value - v) < 0.006 or abs(abs(value) - abs(v)) < 0.006 for v in values):
                problems.append(f"'{value}': a number that is not one already shown in this conversation")
                break
    count = _sentences(stripped)
    if count < 2:
        problems.append("too short: write two to four plain sentences")
    problems += length_problems(text, len(used), kind="general")
    clean = re.sub(r"\s+", " ", stripped).strip()
    problems += talk_checks.general_problems(clean)
    problems += talk_checks.general_language_problems(clean, language)
    m = talk_checks.GENERAL_NON_ANSWER.search(clean)
    if m:
        problems.append(f"'{m.group(0)}': answer in words; do not say the question could not be worked out")
    return problems


# ---- the template ---------------------------------------------------------------------------------------------------

def _lower(label: str) -> str:
    return label[:1].lower() + label[1:] if len(label) > 1 and label[1:2].islower() else label.lower()


TIP = ("The change with the most money behind it is {lever}. A steady habit there moves more over a month than many "
       "small cuts elsewhere, so it is the best next thing to try.",
       "Eniten rahaa liikkuu kohdassa {lever}. Pysyvä tapa siellä vaikuttaa kuukaudessa enemmän kuin monet pienet "
       "leikkaukset muualla, joten se kannattaa kokeilla seuraavaksi.")
NO_TIP = ("No single change stands out in the numbers so far. Small, steady habits help most, such as a plan before "
          "shopping and a pause before bigger purchases.",
          "Mikään yksittäinen muutos ei erotu tähänastisista luvuista. Pienet pysyvät tavat auttavat eniten, kuten "
          "suunnitelma ennen kauppaa ja tauko ennen isompia ostoksia.")
NO_MORE = ("Those were the changes with the most money behind them. The rest are small, so keeping the habits above "
           "matters more than adding new ones.",
           "Nuo olivat muutokset, joissa liikkuu eniten rahaa. Loput ovat pieniä, joten edellisten tapojen pitäminen "
           "on tärkeämpää kuin uusien lisääminen.")
WHY = {
    "get_safe_to_spend": (
        "That figure is what can go out this week without touching the savings goal or the bills ahead. Keeping "
        "inside it means the month ends as planned, with no surprise before payday.",
        "Tuo luku kertoo, mitä tällä viikolla voi käyttää ilman, että säästötavoite tai tulevat laskut kärsivät. Kun "
        "sen sisällä pysyy, kuukausi päättyy suunnitellusti eikä ennen palkkapäivää tule yllätyksiä."),
    "get_savings_plan": (
        "The plan shows where a small, steady cut would add up the most. Changing a habit in the biggest areas "
        "matters more than trimming many little things.",
        "Suunnitelma näyttää, missä pieni pysyvä leikkaus kertyy eniten. Tavan muuttaminen suurimmissa kohdissa on "
        "tärkeämpää kuin monen pienen asian karsiminen."),
    "run_what_if": (
        "The what-if shows how a steady cut adds up over time. It matters because a habit repeated every month adds "
        "up to more than it seems at first.",
        "Laskelma näyttää, miten pysyvä leikkaus kertyy ajan myötä. Sillä on väliä, koska joka kuukausi toistuva tapa "
        "kasvaa suuremmaksi kuin aluksi näyttää."),
    "get_peer_benchmark": (
        "The comparison shows how similar customers spend, as a reference point and not a target. What matters most "
        "is whether the spending fits the plans and the savings goal.",
        "Vertailu näyttää, miten samankaltaiset asiakkaat kuluttavat, ja se on vertailukohta eikä tavoite. "
        "Tärkeintä on, sopiiko kulutus omiin suunnitelmiin ja säästötavoitteeseen."),
}
WHY_DEFAULT = (
    "The numbers above show where the money goes, and the biggest areas are where a change matters most. A small, "
    "steady change there adds up over the months, more than cutting many little things.",
    "Yllä olevat luvut näyttävät, mihin raha menee, ja suurimmissa kohdissa muutoksella on eniten väliä. Pieni "
    "pysyvä muutos siellä kertyy kuukausien mittaan enemmän kuin monen pienen asian karsiminen.")
CHIP_MORE = ("Any more tips?", "Lisää vinkkejä?")
CHIP_SAVE = ("How could I save more?", "Miten voisin säästää enemmän?")


def _pick(pair: tuple[str, str], language: str) -> str:
    return pair[1] if language == "fi" else pair[0]


TIP_WHY = ("It matters because the most money moves in {lever}, so a steady habit there adds up faster than small cuts "
           "elsewhere. Changing one habit at a time also makes it easier to keep.",
           "Sillä on väliä, koska eniten rahaa liikkuu kohdassa {lever}, joten pysyvä tapa siellä kertyy nopeammin kuin "
           "pienet leikkaukset muualla. Yhden tavan muuttaminen kerrallaan on myös helpompi pitää.")


def template_text(kind: str, tip: dict[str, Any] | None, exhausted: bool, tools: list[str], language: str,
                  previous_tip: dict[str, Any] | None = None) -> str:
    """The answer in words without the model, and without a number: the next lever when tips were asked, why the last
    lever matters after a tip, else what the previous answer's tool means."""
    if tip is not None:
        return _pick(TIP, language).format(lever=_lower(tip["label"]))
    if kind in ("tips", "no_numbers"):
        return _pick(NO_MORE if exhausted else NO_TIP, language)
    if previous_tip and previous_tip.get("lever"):
        return _pick(TIP_WHY, language).format(lever=_lower(previous_tip["lever"]))
    for tool in tools:
        if tool in WHY:
            return _pick(WHY[tool], language)
    return _pick(WHY_DEFAULT, language)
