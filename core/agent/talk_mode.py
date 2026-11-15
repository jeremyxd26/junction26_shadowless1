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
from pathlib import Path
from typing import Any

from core.agent import talk_checks
from core.agent.guard import fold
from core.agent.validator import TOKEN, render
from core.answer_text import SENTENCE_BREAK, length_problems, scan_numbers

MIN_TIP_EUR = 20.0
MIN_TIP_SHARE = 0.01
# While this file exists, talk mode writes only its templates, never the model (Renat's decision for #889). Read per
# answer, like var/model-off, so `touch` / `rm` on the stand needs no restart (docs/deploy.md).
MODEL_OFF_SWITCH = Path(__file__).resolve().parents[2] / "var" / "talk-model-off"


def model_switched_off() -> bool:
    """True while the talk-model switch file exists (read per answer)."""
    try:
        return MODEL_OFF_SWITCH.exists()
    except OSError:
        return True

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
    r"((and|so|ok|okay|but|hmm|well|right|ja|no|okei|joo|mut|mutta|entas|enta|eli) )*"
    r"(why|why not|why so|how|how so|how come|what else|anything else|and then|then what|what now|what next|go on"
    r"|tell me more|more|like what|such as|for example|for instance|really|meaning|and|in what way|what do you mean"
    r"|miksi|miksi niin|miten|miten niin|mita muuta|kerro lisaa|kerro viela|jatka|esimerkiksi|kuten|entas sitten"
    r"|ja sitten|mita sitten|siis|niin|mita tarkoitat|mita meinaat|onko muuta|muuta)"
    r"( (please|then|sitten|kiitos|again|more|viela))*")
_MAX_CHARS = 300
# Borrowing and affordability in a talk question (Renat's decision for #889): always the template, never the model,
# whatever the switch; hard declines still come first (orchestrator `_talk_stands_down`)
_TEMPLATE_ONLY = re.compile(
    r"\b(loans?|lainat?\w*|\w*laina\w*|credit\w*|luoto\w*|luotto\w*|\w*luotto\w*|borrow\w*|lend\w*|instal+ments?"
    r"|osamaks\w*|erissa|erittain maksu|financ\w*|rahoitu\w*|mortgage\w*|overdraft\w*|overdrawn|tilinylity\w*"
    r"|bnpl|buy now,? pay later|pay later|maksa myohemmin|klarna|pikavip\w*|vippi\w*|velka\w*|debt\w*"
    r"|afford\w*|voinko (ostaa|maksaa)|onko (minulla|mulla|mul) varaa|onks (mulla|mul) varaa|varaa (ostaa|tahan))\b")


def template_only(message: str) -> bool:
    """A talk question about borrowing or affordability: the template answers, never the model."""
    return bool(_TEMPLATE_ONLY.search(_words(fold(message or ""))))
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


# In a talk thread, "why should I save money?" asks for reasons, not numbers (in a fresh conversation it is the
# literacy route's)
_WHY_FOLLOW_UP = re.compile(r"((and|so|but|ok|ja|mutta|no) )*(why|miksi) (should|would|do|does|is|must|pitaisi|pitais"
                            r"|kannattaa|kannattaisi|kannattais|on|olisi)\b")


def why_follow_up(message: str) -> bool:
    """A "why should I…" question with no figure in it, which keeps talk mode after a talk answer."""
    if not isinstance(message, str) or len(message) > 120 or re.search(r"\d", message):
        return False
    flat = _words(fold(message))
    return bool(_WHY_FOLLOW_UP.match(flat)) and not _FIGURE.search(flat)


# Right after a tips answer, "why?", "how come?", "why does that help?", "miksi se auttaa?" ask why those tips help
# (#919). "Why should I save money?" stays a general why, and "what does this number mean?" stays #821's.
_WHY_TIPS = re.compile(
    r"((and|so|but|ok|okay|hmm|well|right|ja|no|okei|joo|mut|mutta|eli) )*"
    r"(why|why so|how come|how so|miksi|miks|miksi niin|miten niin|kuinka niin"
    r"|(why|how) (does|do|would|will|is|are|should|could) (it|that|this|these|those|they|them)"
    r"( (really|even|actually))? (help|helps|work|works)"
    r"|(miksi|miks|miten|kuinka) (se|tama|tuo|toi|taa|ne|nama|noi|nuo|naa)( (oikein|sitten))?"
    r" (auttaa|auttais|auttaisi|auttavat|toimii|toimis|toimisi|toimivat))"
    r"( (please|then|sitten|kiitos|again|exactly|really|oikein))*")


def asks_why_tips(message: str) -> bool:
    """A short "why?" of the explaining kind ("why?", "miksi?", "how come?", "why does that help?", "miksi se
    auttaa?"), which after a tips answer explains those tips (#919)."""
    if not isinstance(message, str) or len(message) > 80 or re.search(r"\d", message):
        return False
    parts = [_words(p) for p in re.split(r"[.?!;:\n]+", fold(message))]
    parts = [p for p in parts if p]
    return bool(parts) and all(_WHY_TIPS.fullmatch(p) for p in parts)


# ---- repetition guard -----------------------------------------------------------------------------------------------
_STOP = frozenset("""the and that this with from have will would could should your you they them their there then than
what when where which while about into over more most some such only also just very much many each every other these those
been being were was are is it its for not but can may might must our out off all any one ones like make makes made does
done doing more less same still even well here how why who whom whose ja on ei se että kun jos tai joka jotka mutta myös
niin kuin sitä siitä tämä tuo nyt jo vain sen ovat olla oli ole voi voit""".split())


def content_words(text: str) -> set[str]:
    """The answer's content words: lower case, four letters or more, without the small words and the number tokens."""
    words = re.findall(r"[^\W\d_]{4,}", TOKEN.sub(" ", (text or "").replace("[number]", " ")).lower())
    return {w for w in words if w not in _STOP}


def repeats(draft: str, previous: str | None, threshold: float = 0.6) -> bool:
    """More than `threshold` of the draft's content words were already in the previous answer (#889)."""
    mine = content_words(draft)
    if not previous or not mine:
        return False
    return len(mine & content_words(previous)) / len(mine) > threshold


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

# The fresh leak rows of #889's measurement (Renat's decision): borrowing by paraphrase and statements about the
# user's own money that #618's patterns let through, as classes of their own
_TALK_BORROWING = re.compile(
    r"\bspread\w*\s+(?:the\s+|a\s+)?(?:cost|costs|payment|payments|price|bill|purchase)\w*(?:\s+\w+){0,2}\s+over\b"
    r"|\b(?:go|goes|going|run|runs|dip|dips|slip)\w*\s+(?:into\s+(?:the\s+)?)?(?:negative|minus|below\s+zero)\b"
    r"|\bsettl\w*\s+(?:up\b|it\s+later|later|after\b|at\s+the\s+end\b)"
    r"|\b(?:wages?|salary|salaries|pay|paycheck|palk\w*)\s+(?:\w+\s+)?(?:ahead\s+of|early|before)\s+(?:payday|it\s+is\s+due)"
    r"|\brelease\w*\s+(?:\w+\s+)?(?:wages?|salary|pay)\b"
    r"|\bfront\w*\s+(?:you\s+|them\s+|the\s+|some\s+)?(?:money|cash|cost|sum)\b"
    r"|\b(?:paid|pay|paying|pays)\s+(?:it\s+|them\s+|the\s+\w+\s+)?back\b|\brepa(?:y|id|ying)\w*"
    r"|\bmaks\w*\s+(?:\w+\s+)?takaisin\b|\btakaisinmaks\w*|\bpyyta\w*\s+(?:\w+\s+){0,2}apua\b"
    r"|\b(?:running\s+)?tab\b|\bafter\s+it\s+arrives\b", re.I)
_TALK_OWN_STATE = re.compile(
    r"\b(?:shouldn['’]?t|should\s+not|won['’]?t|will\s+not|wouldn['’]?t|would\s+not)\s+(?:cause|be|make)\s+(?:any\s+|a\s+)?"
    r"(?:trouble|problem|issue|difference|dent)\w*"
    r"|\broom\s+in\s+the\s+budget\b|\bno\s+need\s+to\s+hold\s+back\b|\bthere['’]?s\s+(?:clearly\s+|plenty\s+of\s+)?room\b"
    r"|\b(?:money|cash)\s+(?:has\s+been\s+|is\s+|keeps\s+)?(?:leak\w*|tight|short|fine)\b|\bobviously\s+where\b"
    r"|\bfits?\s+(?:comfortably\s+|easily\s+|well\s+|nicely\s+)?(?:within|into|in)\b"
    r"|\b(?:is|are)\s+going\s+to\s+sting\b"
    r"|\b(?:costs?|spending|bills?|expenses|purchases)\s+(?:look|looks|seem|seems|are|is)\s+(?:perfectly\s+|quite\s+|very\s+"
    r"|rather\s+|pretty\s+)?(?:reasonable|fine|ok|okay|normal|high|low|healthy|modest)\b"
    r"|\bpuskuri\w*\s+riitt\w*|\briitt\w*\s+hyvin\b|\bkuluu\s+(?:\w+\s+)?(?:liikaa|liian|paljon)\b|\bselvasti\s+liikaa\b",
    re.I)


# "There are no further tips" (#907): talk mode always gives the next lever, practice or a closing instead
_NO_FURTHER = re.compile(
    r"\b(?:no|not\s+any|nothing)\s+(?:further|more|other|additional|new)\s+(?:\w+\s+){0,3}?"
    r"(?:tips?|suggestions?|advice|ideas?|recommendations?)\b"
    r"|\bthere\s+(?:are|is)\s+no\s+(?:further|more|other)\b"
    r"|\bei\s+(?:ole\s+)?(?:enaa\s+|muita\s+|lisaa\s+|uusia\s+)+(?:\w+\s+){0,2}?(?:vinkk\w*|neuvo\w*|ehdotu\w*)")


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
    copies = talk_checks._general_copies(clean) + [fold(clean)]
    for rx, why in ((_TALK_BORROWING, "borrowing: never suggest paying later, in parts, back, ahead of pay or in the red"),
                    (_TALK_OWN_STATE, "the user's own money: speak about the numbers, never say what the user's money "
                                      "is, fits or allows")):
        m = next((found for found in (rx.search(c) for c in copies) if found), None)
        if m:
            problems.append(f"'{m.group(0)}': {why}")
    problems += talk_checks.general_language_problems(clean, language)
    m = talk_checks.GENERAL_NON_ANSWER.search(clean)
    if m:
        problems.append(f"'{m.group(0)}': answer in words; do not say the question could not be worked out")
    m = _NO_FURTHER.search(fold(clean).lower())
    if m:
        problems.append(f"'{m.group(0)}': never say there are no more tips; give the practices in the data in words")
    return problems


# ---- the template ---------------------------------------------------------------------------------------------------

def lower(label: str) -> str:
    """A lever's label inside a sentence, lower case (the name check rejects a capital inside a sentence)."""
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
BORROWING = ("That decision belongs with the bank, so this answer stays with the numbers already shown. A steady habit "
             "in the biggest spending area does more over a month than many small cuts elsewhere.",
             "Se päätös kuuluu pankille, joten tämä vastaus pysyy jo näytetyissä luvuissa. Pysyvä tapa suurimmassa "
             "menoerässä vaikuttaa kuukaudessa enemmän kuin monet pienet leikkaukset muualla.")
# General saving practices beside the lever in a first tips answer (#889: three tips in one answer, the lever first);
# r-rag's literacy fragments supply this side once wired. In order; each answer takes the next two.
PRACTICES = (
    ("Move a set amount to savings right after payday, before the spending starts.",
     "Siirrä sovittu summa säästöön heti palkkapäivänä, ennen kuin kuluttaminen alkaa."),
    ("Make a shopping list before going to the shop, and stick to it.",
     "Tee kauppalista ennen kauppaan lähtöä ja pysy siinä."),
    ("Wait a day before any bigger purchase that was not planned.",
     "Odota päivä ennen isompaa ostosta, jota ei ollut suunniteltu."),
    ("Go through the regular payments now and then, and stop the ones nobody uses.",
     "Käy säännölliset maksut läpi silloin tällöin ja lopeta turhat."),
    ("Plan meals ahead, so fewer last-minute takeaways slip in.",
     "Suunnittele ateriat etukäteen, niin viime hetken noutoruoat vähenevät."),
    ("Keep a small buffer for surprises, so a broken item does not upset the month.",
     "Pidä pieni puskuri yllätyksiä varten, jotta rikkoutunut tavara ei sotke kuukautta."),
)
# Each practice's key and why (#919), in PRACTICES' order: "why?" right after a tips answer explains these
PRACTICE_KEYS = ("pay_yourself_first", "shopping_list", "wait_a_day", "regular_payments", "meal_plan", "buffer")
PRACTICE_WHY = (
    ("Moving money to savings on payday helps because what is set aside first is not spent by accident later.",
     "Säästöön siirtäminen palkkapäivänä auttaa, koska heti sivuun laitettu raha ei kulu vahingossa myöhemmin."),
    ("A shopping list helps because it keeps the visit to what was planned, so fewer extras end up in the basket.",
     "Kauppalista auttaa, koska ostokset pysyvät suunnitelmassa ja koriin päätyy vähemmän ylimääräistä."),
    ("Waiting a day helps because the urge to buy often fades, and only what still feels needed gets bought.",
     "Päivän odotus auttaa, koska ostohalu usein laantuu ja vain yhä tarpeelliselta tuntuva tulee ostettua."),
    ("Checking the regular payments helps because a forgotten one keeps going out every month unnoticed.",
     "Säännöllisten maksujen läpikäynti auttaa, koska unohtunut maksu lähtee joka kuukausi huomaamatta."),
    ("Planning meals helps because a plan at home makes a last-minute takeaway less tempting on a busy evening.",
     "Aterioiden suunnittelu auttaa, koska valmis suunnitelma tekee viime hetken noutoruoasta vähemmän houkuttelevan."),
    ("A small buffer helps because a surprise cost then comes from money set aside for it, not from the month's plan.",
     "Pieni puskuri auttaa, koska yllättävä kulu maksetaan silloin sitä varten säästetystä rahasta eikä kuukauden "
     "suunnitelmasta."),
)
# A lever's why (#919): by its key, else the first lever's (the most money behind it), else the default
LEVER_WHY = {
    "small_purchases": ("Small purchases matter because each one feels harmless, but together they add up over a month.",
                        "Pienet ostokset kannattaa huomata, koska yksittäin ne tuntuvat vähäisiltä mutta kertyvät "
                        "kuukaudessa."),
    "category:Restaurants": ("A change in {lever} helps because eating out repeats week after week, so even a small "
                             "steady change there adds up.",
                             "Muutos kohdassa {lever} auttaa, koska ulkona syöminen toistuu viikosta toiseen ja pienikin "
                             "pysyvä muutos kertyy."),
}
LEVER_WHY_FIRST = ("A change in {lever} comes first because the most money moves there, so a steady habit adds up faster "
                   "than small cuts elsewhere.",
                   "Muutos kohdassa {lever} on ensimmäisenä, koska siellä liikkuu eniten rahaa ja pysyvä tapa kertyy "
                   "nopeammin kuin pienet leikkaukset muualla.")
LEVER_WHY_DEFAULT = ("A change in {lever} helps because a steady habit there repeats every month, so it adds up more "
                     "than a one-off cut.",
                     "Muutos kohdassa {lever} auttaa, koska pysyvä tapa toistuu siellä joka kuukausi ja kertyy enemmän "
                     "kuin kertaluonteinen leikkaus.")
ONE_AT_A_TIME = ("Changing one habit at a time also makes it easier to keep.",
                 "Yhden tavan muuttaminen kerrallaan on myös helpompi pitää.")
TIP_FIRST = ("The change with the most money behind it is {lever}.", "Eniten rahaa liikkuu kohdassa {lever}.")
# "Any more tips?" once no further lever passes the bar (#907): the next practices, after this lead
MORE_FIRST = ("A few more everyday habits help as well.", "Myös muutama muu arkinen tapa auttaa.")
# When the levers and the practices are both used up (#907): a short warm closing, never "no further tips"; the
# answer's chip is the saving question (CHIP_SAVE). Two texts, so a second "any more tips?" never gets the same one.
CLOSING = (
    ("That is a good set of habits to work with. Picking one of them and keeping it going for a month is the best "
     "next step.",
     "Siinä on hyvä joukko tapoja, joista aloittaa. Paras seuraava askel on valita niistä yksi ja pitää siitä kiinni "
     "kuukauden ajan."),
    ("Small steady steps like these add up over time. Trying them one at a time makes each of them easier to keep.",
     "Tällaiset pienet pysyvät askeleet kertyvät ajan myötä. Kun niitä kokeilee yksi kerrallaan, kustakin on helpompi "
     "pitää kiinni."),
)


def practices(start: int, language: str, count: int = 2) -> list[str]:
    """The next `count` general practices from `start`, in the answer's language; [] when they are used up."""
    return [_pick(p, language) for p in PRACTICES[start:start + count]]


def three_tips(tip: dict[str, Any] | None, extra: list[str], language: str, more: bool = False) -> str:
    """The first tips answer without the model: the lever first, then the general practices (3 to 4 sentences).
    On "any more tips?" with no lever left (`more`), the practices follow MORE_FIRST instead (#907)."""
    if tip:
        lead = _pick(TIP_FIRST, language).format(lever=lower(tip["label"]))
    else:
        lead = _pick(MORE_FIRST if more else NO_TIP, language)
    return " ".join([lead, *extra])


def lever_why(lever: dict[str, Any], language: str) -> str:
    """Why one given lever helps (#919), without a number."""
    pair = LEVER_WHY.get(str(lever.get("key"))) or (LEVER_WHY_FIRST if lever.get("rank") == 1 else LEVER_WHY_DEFAULT)
    return _pick(pair, language).format(lever=lower(str(lever.get("label") or "")))


def tips_to_explain(gave: dict[str, Any], language: str) -> list[dict[str, str]]:
    """The tips the previous talk answer gave (its `gave` record: levers with key, label and rank; practice
    indices), each in words with its fixed why: the composer explains these and no other (#919)."""
    out = [{"tip": lower(str(lv.get("label") or "")), "why": lever_why(lv, language)}
           for lv in gave.get("levers") or [] if isinstance(lv, dict)]
    out += [{"tip": _pick(PRACTICES[i], language), "why": _pick(PRACTICE_WHY[i], language)}
            for i in gave.get("practices") or [] if isinstance(i, int) and 0 <= i < len(PRACTICES)]
    return out


def tip_keys(gave: dict[str, Any]) -> list[str]:
    """The keys of the tips a `gave` record holds: the levers' keys, then the practices' (#919)."""
    return ([str(lv.get("key")) for lv in gave.get("levers") or [] if isinstance(lv, dict)]
            + [PRACTICE_KEYS[i] for i in gave.get("practices") or [] if isinstance(i, int) and 0 <= i < len(PRACTICES)])


# Words a generic "why it matters" paragraph shares with the tips: they never count as naming a tip (#919)
_NAME_GENERIC = frozenset("""spending starts before after right going money month months small steady change habit
habits there elsewhere helps help every planned plan ennen alkaa kuluttaminen heti rahaa kuukausi pieni pienet pysyva
pysyvä tapa muutos auttaa""".split())


def _stems(text: str) -> set[str]:
    return {w[:max(5, len(w) - 3)] for w in content_words(text) if w not in _NAME_GENERIC}


def _names(text: str, tip: str) -> bool:
    words = content_words(text)
    return any(w.startswith(s) for w in words for s in _stems(tip))


def explain_problems(text: str, gave: dict[str, Any], language: str) -> list[str]:
    """Why a "why?"-after-tips draft does not explain the tips given (#919): it must name the lever when one was
    given, else at least one of the practices (by word stem, so Finnish inflection passes); [] when it does."""
    levers = [lower(str(lv.get("label") or "")) for lv in gave.get("levers") or [] if isinstance(lv, dict)]
    practices = [_pick(PRACTICES[i], language) for i in gave.get("practices") or []
                 if isinstance(i, int) and 0 <= i < len(PRACTICES)]
    if levers and not all(_names(text, lever) for lever in levers):
        return [f"explain the tips the previous answer gave: name {', '.join(levers)} and why each tip helps"]
    if not levers and practices and not any(_names(text, p) for p in practices):
        return ["explain the tips the previous answer gave: name each one and why it helps"]
    return []


def explain_tips(gave: dict[str, Any], language: str) -> str:
    """The template's "why?" after a tips answer (#919): each tip's fixed why, two to four sentences, no number."""
    sentences = [t["why"] for t in tips_to_explain(gave, language)][:4]
    if len(sentences) < 2:
        sentences.append(_pick(ONE_AT_A_TIME, language))
    return " ".join(sentences)


def closing(language: str, previous: str | None = None) -> str:
    """The warm closing once the levers and the practices are used up (#907), never the previous answer again."""
    texts = [_pick(pair, language) for pair in CLOSING]
    return next((t for t in texts if t != previous and not repeats(t, previous)), texts[0])


CHIP_MORE = ("Any more tips?", "Lisää vinkkejä?")
CHIP_SAVE = ("How could I save more?", "Miten voisin säästää enemmän?")


def _pick(pair: tuple[str, str], language: str) -> str:
    return pair[1] if language == "fi" else pair[0]


TIP_WHY = ("It matters because the most money moves in {lever}, so a steady habit there adds up faster than small cuts "
           "elsewhere. Changing one habit at a time also makes it easier to keep.",
           "Sillä on väliä, koska eniten rahaa liikkuu kohdassa {lever}, joten pysyvä tapa siellä kertyy nopeammin kuin "
           "pienet leikkaukset muualla. Yhden tavan muuttaminen kerrallaan on myös helpompi pitää.")


def template_text(kind: str, tip: dict[str, Any] | None, exhausted: bool, tools: list[str], language: str,
                  previous_tip: dict[str, Any] | None = None, previous: str | None = None) -> str:
    """The template answer, never the previous answer again (#889): when it would repeat it, another reasoned text."""
    text = _template_text(kind, tip, exhausted, tools, language, previous_tip)
    if previous is not None and (text == previous or repeats(text, previous)):
        for other in (NO_TIP, WHY_DEFAULT, NO_MORE):
            alternative = _pick(other, language)
            if alternative != previous and not repeats(alternative, previous):
                return alternative
    return text


def _template_text(kind: str, tip: dict[str, Any] | None, exhausted: bool, tools: list[str], language: str,
                   previous_tip: dict[str, Any] | None = None) -> str:
    """The answer in words without the model, and without a number: the next lever when tips were asked, why the last
    lever matters after a tip, else what the previous answer's tool means."""
    if tip is not None:
        return _pick(TIP, language).format(lever=lower(tip["label"]))
    if kind in ("tips", "no_numbers"):
        return _pick(NO_MORE if exhausted else NO_TIP, language)
    if previous_tip and previous_tip.get("lever"):
        return _pick(TIP_WHY, language).format(lever=lower(previous_tip["lever"]))
    for tool in tools:
        if tool in WHY:
            return _pick(WHY[tool], language)
    return _pick(WHY_DEFAULT, language)
