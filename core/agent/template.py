"""Fixed texts and the deterministic template answer (agent-core.md sections 6.3, 7.4, 7.6 and 11).

- Refusal templates per kind, the no-data sentence, the default clarifying question, follow-up
  questions and the lesson catalogue, in English and Finnish. They are drafts for human review
  before the demo (agent-core.md section 7.7); none of them contains a digit.
- template_draft builds an AnswerDraft from the tools' model views only: it cites every number as a
  {{nK}} token and writes no digit itself, so it passes the validator. It is the composer of the
  rule model and the fallback after a failed composer (R12).
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from decimal import Decimal
from typing import Any

from core import answer_text
from core.tools import config as tools_config
from core.agent import answer_sentences
from core.agent.guard import fold, fold_pattern

REFUSAL: dict[str, dict[str, Any]] = {
    "investment_advice": {
        "label": ("Investment advice is outside what I can help with", "Sijoitusneuvonta ei kuulu siihen, missä voin auttaa"),
        "text": ("I can't give investment advice, such as which shares or funds to buy. I can show how much you could "
                 "set aside each month, so you know what you have to work with. For investing, an S-Pankki adviser can help.",
                 "En voi antaa sijoitusneuvontaa, esimerkiksi siitä, mitä osakkeita tai rahastoja kannattaa ostaa. Voin "
                 "näyttää, paljonko voisit säästää kuukaudessa. Sijoittamisessa auttaa S-Pankin neuvoja."),
    },
    "credit_decision": {
        "label": ("Loan decisions are made by the bank's loan process", "Lainapäätökset tehdään pankin lainaprosessissa"),
        "text": ("I can't predict whether a loan or mortgage would be approved, and I don't rate creditworthiness. "
                 "The bank's loan process gives that answer. I can show what you could save each month.",
                 "En voi ennustaa, myönnetäänkö laina tai asuntolaina, enkä arvioi luottokelpoisuutta. Vastauksen antaa "
                 "pankin lainaprosessi. Voin näyttää, paljonko voisit säästää kuukaudessa."),
    },
    "other_person_data": {
        "label": ("I can only look at your own money", "Voin katsoa vain omia raha-asioitasi"),
        "text": ("I can only look at your own transactions, never anyone else's. Ask me about your own spending instead.",
                 "Voin katsoa vain omia tapahtumiasi, en koskaan muiden. Kysy minulta omasta kulutuksestasi."),
    },
    "out_of_scope": {
        "label": ("This is outside what I can help with", "Tämä ei kuulu siihen, missä voin auttaa"),
        # The warmer generic decline (#287, the product owner's first sentence). It reads complete without the
        # four brief questions that follow as chips (#352): a full stop and two examples in words.
        "text": ("That's outside my lane — I'm your money coach. I can help with things like your spending or your bills.",
                 "Tämä menee ohi osaamiseni — olen rahavalmentajasi. Voin auttaa esimerkiksi kulutuksessasi tai "
                 "laskuissasi."),
    },
    "unsafe": {
        "label": ("I can't help with that request", "En voi auttaa tässä pyynnössä"),
        "text": ("I can't help with that. I only read and explain your own spending, and I never move money or show raw records.",
                 "En voi auttaa siinä. Luen ja selitän vain omaa kulutustasi, enkä koskaan siirrä rahaa tai näytä raakatietoja."),
    },
}

BRIEF_QUESTIONS = (
    ("Where did my money go?", "Mihin rahani menivät?"),
    ("What kind of spender am I?", "Millainen kuluttaja olen?"),
    ("What can I safely spend this week?", "Paljonko minulla on turvallisesti käytettävissä tällä viikolla?"),
    ("How could I save more?", "Miten voisin säästää enemmän?"),
)

MONTHLY_AVERAGE = ("monthly average", "kuukausikeskiarvo")
# "How could I save more?" without a category or a cut: the answer shows the basket shares and the bills
# due, and ends by offering a what-if on the largest everyday category. The offer names no amount: the
# coach never suggests a cut (issue #142, R1); the user says by how much.
SAVE_MORE = (r"save more(?! time)|saving more(?! time)|help me save|help me to save|säästää enemmän|"
             r"säästäisin enemmän|säästämään enemmän|säästöä enemmän|säästän enemmän|"
             # the everyday ways of asking it (#340); the rules read the same words (rules.plan_what_if)
             r"\bhow (can|could|do|should|would) i save\b(?! time)|\bsave money\b|"
             r"\b(help me|tips to|ways to|how (can|could|do) i) (spend less|cut back)\b|"
             r"\bways to save\b|\bsaving tips\b|\btips to save\b|\bwhere (can|could|should) i (save|cut)\b|"
             r"\bput (more |some )?(money )?aside\b|"
             r"\bmiten (voisin|voin|saisin) säästä\w*|\bmissä (voisin|voin) säästä\w*|\bsäästöön\b")
# One sentence each, so the save-more answer stays within two sentences (#342, Renat's length rule).
WHAT_IF_OFFER = ("Tell me how much you would cut {category} by, and I'll show what you'd save.",
                 "Kerro, kuinka paljon vähentäisit luokassa {category}, niin näytän säästön.")
WHAT_IF_OFFER_ANY = ("Name a category and how much you would cut it by, and I'll show what you'd save.",
                     "Kerro luokka ja kuinka paljon vähentäisit, niin näytän säästön.")
# The peer benchmark's reasons for showing nothing (#216): the reason only, never a number.
PEER_REASON = {
    "group_too_small": ("There are too few people like you in the data to compare with.",
                        "Aineistossa on liian vähän kaltaisiasi vertailuun."),
    "not_comparable": ("Your spending cannot be compared with people like you for this period.",
                       "Kulutustasi ei voi verrata kaltaisiisi tällä jaksolla."),
}
NO_DATA = ("There are no transactions for that period in your data.",
           "Tältä jaksolta ei ole tapahtumia aineistossasi.")
TOOL_FAILED = ("Some of the data could not be computed right now.",
               "Osaa tiedoista ei voitu laskea juuri nyt.")
NOTHING = ("I could not find data for that question.", "En löytänyt tietoja tähän kysymykseen.")
# Missing data (#379): what is missing, then what Sentti can answer instead, as chips the rules recognise.
# The future names the last day of the data (a returned date); the past names no date, the chip does.
MISSING = {
    "period_in_future": ("My data ends on {end}, so I can't see future months. I can show what you typically have "
                         "left each month, or whether your money lasts until payday.",
                         "Tietoni ulottuvat {end} asti, joten en näe tulevia kuukausia. Voin näyttää, paljonko "
                         "sinulle tavallisesti jää kuukaudessa tai riittävätkö rahasi palkkapäivään."),
    "period_before_data": ("My data does not reach back that far, so I can't see that period. I can show any month "
                           "since my data starts, or the past year.",
                           "Tietoni eivät ulotu niin kauas taaksepäin, joten en näe sitä jaksoa. Voin näyttää minkä "
                           "tahansa kuukauden aineiston alusta lähtien tai viimeisen vuoden."),
}
MISSING_CHIPS = {
    "period_in_future": (("How could I save more?", "Will my money last until payday?"),
                         ("Miten voisin säästää enemmän?", "Riittävätkö rahani palkkapäivään?")),
    "period_before_data": (("How much did I spend in {month_en}?", "How much did I spend over the past year?"),
                           ("Paljonko käytin {month_fi}?", "Paljonko käytin viimeisen vuoden aikana?")),
}
# A category never used, an object no category maps, too few purchases (#379, part B). Chips name the
# customer's own largest categories the rules can answer, Health never among them unless asked (R9).
ABSENT = ("I can't find any spending on {what} in your data. Your largest categories are {categories}.",
          "Tiedoistasi ei löydy kulutusta luokassa {what}. Suurimmat luokkasi ovat {categories}.")
ABSENT_PLAIN = ("I can't find any spending on {what} in your data.", "Tiedoistasi ei löydy kulutusta luokassa {what}.")
UNKNOWN_PLAIN = ("I can't see \u201c{word}\u201d on its own in your transactions: they are grouped into categories.",
                 "En löydä tapahtumistasi erikseen sanaa \u201d{word}\u201d: kulutus on ryhmitelty luokkiin.")
UNKNOWN = ("I can't see \u201c{word}\u201d on its own in your transactions: they are grouped into categories, and your "
           "largest are {categories}.",
           "En löydä tapahtumistasi erikseen sanaa \u201d{word}\u201d: kulutus on ryhmitelty luokkiin, ja suurimmat ovat "
           "{categories}.")
TOO_FEW = {"none": tools_config.WHAT_IF_TEXT["too_few_none"], "one": tools_config.WHAT_IF_TEXT["too_few_one"],
           "few": tools_config.WHAT_IF_TEXT["too_few_few"]}
CATEGORY_CHIP = ("How much did I spend on {category} last month?", "Paljonko käytin luokkaan {category} viime kuussa?")
# The categories the rules map from words (rules.CATEGORY_WORDS): a chip must be a question they answer.
CHIP_CATEGORIES = ("Groceries", "Restaurants", "Entertainment", "Housing", "Utilities", "Travel", "Lifestyle",
                   "Home & Tech")
# "Kodin laskut" would read as the bills question in Finnish: no chip for it.
FI_NO_CHIP = frozenset({"Utilities"})
FI_MONTH_STEMS = ("tammi", "helmi", "maalis", "huhti", "touko", "kesä", "heinä", "elo", "syys", "loka", "marras",
                  "joulu")
CLARIFY_GENERAL = {
    "question": ("What would you like to know about your money?", "Mitä haluaisit tietää raha-asioistasi?"),
    "options": (("Where did my money go?", "What can I safely spend this week?", "How could I save more?"),
                ("Mihin rahani menivät?", "Paljonko minulla on turvallisesti käytettävissä tällä viikolla?",
                 "Miten voisin säästää enemmän?")),
}
# "What was that €1,080?" (#341): the pending review's purchase, from the review card's data. {why} is
# the card's own "why" text; {amount} is the card amount's token.
REVIEW_PURCHASE = (   # "what was that €1,080?": two sentences (the answer-length rule)
    "That was your {category} purchase on {date}: {amount}. It is the large purchase I asked you about: "
    "was it needed, or your choice?",
    "Se oli ostoksesi {date} luokassa {category}: {amount}. Tästä isosta ostoksesta kysyin sinulta: oliko se "
    "välttämätön hankinta vai oma valinta?",
)
REVIEW_WHY = (   # "why are you asking me about 1080 euros?": the answer opens with the why (#398)
    "I asked because {amount} on {category} on {date} stands out from your usual purchases in that category: "
    "was it needed, or your choice? Your answer only changes how your own spending is grouped.",
    "Kysyin, koska {amount} luokassa {category} {date} erottuu tavallisista ostoksistasi tässä luokassa: oliko "
    "se välttämätön hankinta vai oma valinta? Vastauksesi muuttaa vain sitä, miten omat menosi ryhmitellään.",
)
# Before the rules' clarifying question when the model could not plan the question (#341).
NOT_WORKED_OUT = ("I could not work that out right now.", "En pystynyt selvittämään tätä juuri nyt.")
CLARIFY = {
    "question": ("Which period do you mean?", "Mitä ajanjaksoa tarkoitat?"),
    "options": (("This month", "Last month", "The last three months"),
                ("Tämä kuukausi", "Viime kuukausi", "Viimeiset kolme kuukautta")),
}
STATUS_UNDERSTANDING = ("Reading your question", "Luen kysymystäsi")
STATUS_WRITING = ("Writing the answer", "Kirjoitan vastausta")

# Lessons: short, reviewed texts the composer may pick by key; the model never writes them.
LESSONS: dict[str, dict[str, tuple[str, str]]] = {
    "one_off_vs_habit": {"title": ("One-offs and habits", "Kertaostokset ja tavat"),
                         "text": ("A one-off cost shows up once. A habit repeats every month, so a small change there adds up over a year.",
                                  "Kertaostos näkyy kerran. Tapa toistuu joka kuukausi, joten pieni muutos siinä kertyy vuodessa.")},
    "fixed_vs_flexible": {"title": ("Fixed and flexible costs", "Kiinteät ja joustavat menot"),
                          "text": ("Fixed costs like rent change slowly. Flexible costs like eating out are where quick changes are possible.",
                                   "Kiinteät menot, kuten vuokra, muuttuvat hitaasti. Joustavissa menoissa, kuten ulkona syömisessä, muutos on nopeampi.")},
    "safety_buffer": {"title": ("A safety buffer", "Puskuri"),
                      "text": ("Keeping a small amount untouched on the account protects you from surprises before payday.",
                               "Pieni koskematon summa tilillä suojaa yllätyksiltä ennen palkkapäivää.")},
    "small_amounts_add_up": {"title": ("Small amounts add up", "Pienet summat kertyvät"),
                             "text": ("Small, frequent purchases are easy to miss, but together they can be a large part of a month.",
                                      "Pienet, toistuvat ostokset jäävät helposti huomaamatta, mutta yhdessä ne voivat olla iso osa kuukautta.")},
    "price_level": {"title": ("Price levels", "Hintataso"),
                    "text": ("The same basket can cost a different amount in different stores.",
                             "Sama ostoskori voi maksaa eri kaupoissa eri verran.")},
    "estimate_not_promise": {"title": ("An estimate, not a promise", "Arvio, ei lupaus"),
                             "text": ("This is based on your past months; the coming months can differ.",
                                      "Tämä perustuu menneisiin kuukausiisi; tulevat kuukaudet voivat poiketa."),},
    "peer_context": {"title": ("Compared with others", "Vertailu muihin"),
                     "text": ("A comparison with people like you is context, not a target.",
                              "Vertailu kaltaisiisi ihmisiin on taustatietoa, ei tavoite.")},
}

MAX_TEMPLATE_NUMBERS = 8


def pick(pair: tuple[str, str], language: str) -> str:
    return pair[1] if language == "fi" else pair[0]


# A request to make up or forecast a number about the user's own money (#352, decision 3) is no off-topic
# question: it keeps the kind `out_of_scope` (no new refusal kind) but gets its own text, and the chips offer
# the typical income instead.
MADE_UP = fold_pattern(r"just (estimate|guess)|any number|make up (a |an |some )?(number|amount|figure)|"
                       r"guess (a |an |some )?(number|amount|figure)|"
                       r"invent (a |an )?(number|amount)|keksi (jokin |joku )?(luku|summa)|"
                       r"arvaa (jokin |joku )?(luku|summa)|mika tahansa (luku|summa)")
MADE_UP_REFUSAL = {
    "label": ("I only use numbers from your transactions", "Käytän vain tilitapahtumiesi lukuja"),
    "text": ("I only use numbers from your own transactions, so I can't make up or forecast an amount. I can show "
             "your typical monthly income instead.",
             "Käytän vain omien tilitapahtumiesi lukuja, joten en voi keksiä tai ennustaa summaa. Voin näyttää "
             "tavallisen kuukausitulosi."),
}
MADE_UP_CHIP = ("How much income did I get last month?", "Paljonko tuloja sain viime kuussa?")


def made_up_request(question: str) -> bool:
    return bool(re.search(MADE_UP, fold(question)))


def refusal(kind: str, language: str, question: str = "") -> tuple[str, dict[str, str]]:
    entry = MADE_UP_REFUSAL if kind == "out_of_scope" and made_up_request(question) else REFUSAL[kind]
    return pick(entry["text"], language), {"kind": kind, "label": pick(entry["label"], language)}


# Sentti introduces itself (#287): greeting, identity, capabilities and help get the introduction, thanks
# gets one short sentence; both are followed by the four brief questions as chips (done.follow_ups).
# The product owner's texts, word for word; no digits and no number words.
INTRO = ("Hi, I'm Sentti — an AI money coach inside S-mobiili. I look at your own transactions and explain where "
         "your money goes, what's safe to spend this week and how you could save more. Every number comes from your "
         "transactions — tap it to see them. Sometimes I'll ask you a question too.",
         "Hei, olen Sentti — tekoälyvalmentaja S-mobiilissa. Katson omia tilitapahtumiasi ja kerron, mihin rahasi "
         "menevät, paljonko voit turvallisesti käyttää tällä viikolla ja miten voisit säästää enemmän. Jokainen luku "
         "tulee tilitapahtumistasi — napauta sitä, niin näet ne. Kysyn myös joskus sinulta jotain.")
THANKS = ("You're welcome — ask me anything about your money.", "Ole hyvä — kysy minulta mitä tahansa raha-asioistasi.")
# #352: the full introduction once per conversation; a later greeting, identity, capabilities or help
# message gets one short sentence (no "Hi") and the chips.
AGAIN = {
    "greeting": ("Hello again — what would you like to know about your money?",
                 "Hei taas — mitä haluaisit tietää raha-asioistasi?"),
    "identity": ("I'm Sentti, an AI money coach that works with your own transactions.",
                 "Olen Sentti, tekoälyvalmentaja, joka käyttää omia tilitapahtumiasi."),
    "capabilities": ("I can show where your money goes, what's safe to spend this week and how you could save more.",
                     "Voin näyttää, mihin rahasi menevät, paljonko voit turvallisesti käyttää tällä viikolla ja miten "
                     "voisit säästää enemmän."),
    "help": ("Here are some things you can ask me.", "Tässä muutama asia, jota voit kysyä minulta."),
}
# "Is my data safe with you?" (#352): a fixed answer, DRAFT for the product owner (the review of #484). It says
# only what the code does: what the model gets (core/agent/gemini.py, the tools' model views; #487 keeps the
# peer group and the bill id out) and that the demo server keeps a record. Exempt from the two-sentence rule.
PRIVACY = ("Your own numbers are calculated from your transactions; comparisons with others and the S-Bonus use group "
           "figures and fixed rules. When an AI model writes an answer, it gets your question as you typed it, the "
           "earlier turns of this chat, and the amounts, dates and categories I calculated, never your customer number, "
           "an account number or shop names from your transactions. This demo runs on synthetic data, and its server "
           "keeps a record of questions and answers.",
           "Omat lukusi lasketaan tilitapahtumistasi; vertailut muihin ja S-Bonus perustuvat ryhmän lukuihin ja "
           "kiinteisiin sääntöihin. Kun tekoälymalli kirjoittaa vastauksen, se saa kysymyksesi sellaisena kuin kirjoitit "
           "sen, tämän keskustelun aiemmat viestit sekä laskemani summat, päivämäärät ja luokat, ei koskaan "
           "asiakasnumeroasi, tilinumeroa eikä tilitapahtumiesi kauppojen nimiä. Tämä demo käyttää keksittyä dataa, "
           "ja sen palvelin tallentaa kysymykset ja vastaukset.")
# A message in a language Sentti does not speak (#352): one line, in English.
LANGUAGE = ("I answer in English or Finnish.", "Vastaan englanniksi tai suomeksi.")


def meta_text(intent: str, language: str, introduced: bool = False) -> str:
    """The text of a meta answer; `introduced`: the full introduction was given earlier in the conversation."""
    if intent == "thanks":
        return pick(THANKS, language)
    if intent == "privacy":
        return pick(PRIVACY, language)
    if intent == "language":
        return pick(LANGUAGE, language)
    return pick(AGAIN[intent] if introduced and intent in AGAIN else INTRO, language)


def brief_questions(language: str) -> list[str]:
    """All four brief questions, the chips of an introduction and of the generic decline (#287)."""
    return [pick(q, language) for q in BRIEF_QUESTIONS]


def follow_ups(question: str, language: str, refused: bool = False, views: list | None = None) -> list[str]:
    """The partner's four questions minus the one just asked (agent-core.md section 7.6). A tool may offer one
    question of its own in its view (`follow_up`, no digits), which comes first: the savings plan offers the
    S-Bonus question, so the S-Bonus is answered on its own and never next to the plan's total (#411)."""
    asked = question.strip().lower()
    offered = [v["follow_up"] for v in views or [] if isinstance(v, dict) and isinstance(v.get("follow_up"), str)
               and v["follow_up"] and not re.search(r"\d", v["follow_up"])]
    out = [q for q in dict.fromkeys(offered + [pick(q, language) for q in BRIEF_QUESTIONS]) if q.lower() != asked]
    return out[:2] if refused else out[:3]


def _listed(labels: list[str], language: str) -> str:
    joiner = " ja " if language == "fi" else " and "
    return labels[0] if len(labels) == 1 else ", ".join(labels[:-1]) + joiner + labels[-1]


def _chip_categories(categories: list[dict[str, Any]], language: str) -> list[str]:
    """The labels of up to three of the customer's categories, largest first, that a chip can ask about."""
    keys = CHIP_CATEGORIES if language == "en" else tuple(k for k in CHIP_CATEGORIES if k not in FI_NO_CHIP)
    return [c["label"].lower() if language == "en" else c["label"] for c in categories
            if c.get("key") in keys and isinstance(c.get("label"), str)
            and not re.search(r"\d", c["label"])][:3]


def _category_chips(labels: list[str], language: str) -> list[str]:
    return [pick(CATEGORY_CHIP, language).format(category=label) for label in labels] or list(brief_questions(language)[:2])


def _iso_day(raw: Any) -> date | None:
    try:
        return date.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def _quotable(word: str) -> bool:
    """A thing the user named, safe to quote back: up to four words of letters ("Café Müller", "gym")."""
    return len(word) <= 40 and bool(re.fullmatch(r"[^\W\d_][\w'-]*(?: [^\W\d_][\w'-]*){0,3}", word)) and len(word) > 1


UNKNOWN_NO_WORD = ("I can't see that on its own in your transactions: they are grouped into categories.",
                   "En löydä sitä tapahtumistasi erikseen: kulutus on ryhmitelty luokkiin.")


def unknown_lead(word: str, language: str) -> str:
    """#598: the sentence for a thing no category maps, before the answer to the other question; the user's word is
    quoted when it is safe to quote, and never with a digit (the answer's text has no digits of its own)."""
    quote = bool(word) and _quotable(word) and not re.search(r"\d", word)
    return pick(UNKNOWN_PLAIN, language).format(word=word) if quote else pick(UNKNOWN_NO_WORD, language)


def _first_month(details: dict[str, Any]) -> date:
    """The customer's own first day of data from the tool's error (#379), else the dataset's first day."""
    first = _iso_day(details.get("first"))
    return max(first, tools_config.DATA_START) if first else tools_config.DATA_START


def missing_data_answer(views: list[dict[str, Any]], errors: list[dict[str, Any]], language: str,
                        as_of: date, unknown: str | None = None,
                        unfiltered_spending: bool = False) -> tuple[str, list[str]] | None:
    """The answer and its chips when the tools found nothing but a missing-data reason (#379): no view, and
    every error carries a reason this module writes; or an object no category maps, answered with the
    breakdown of the customer's categories only. None for anything else (the composer writes)."""
    if unknown and views and not errors and all(v.get("tool") == "get_basket_breakdown" for v in views):
        found = sorted((c for v in views for b in v.get("baskets") or [] for c in b.get("categories") or []
                        if c.get("key") != "Health"),
                       key=lambda c: -float(((c.get("amount") or {}).get("value")) or 0))
        labels = _chip_categories(found, language)
        word = unknown if _quotable(unknown) else None
        if labels and word:
            return pick(UNKNOWN, language).format(word=word, categories=_listed(labels, language)), \
                _category_chips(labels, language)
        return None
    if unknown and views and not errors and unfiltered_spending and \
            _quotable(unknown):
        # the model planned the unfiltered total for it: the thing is named, the total is not given
        return pick(UNKNOWN_PLAIN, language).format(word=unknown), list(brief_questions(language)[:2])
    if views or not errors or not all(e.get("reason") in (*MISSING, "category_absent", "too_few_transactions")
                                      for e in errors):
        return None
    by_reason = {e["reason"]: e.get("details") or {} for e in errors}
    if "too_few_transactions" in by_reason:
        d = by_reason["too_few_transactions"]
        kind = {0: "none", 1: "one"}.get(d.get("n"), "few")   # none: nothing in the window to cut (#498)
        what = str(d.get("what") or "")
        if re.search(r"\d", what + str(d.get("period") or "x")) and not d.get("period"):
            return None
        span = d.get("span") or (("Jaksolla " if language == "fi" else "In ") + str(d.get("period")))
        text = pick(TOO_FEW[kind], language).format(span=span, what=what,
                                                   total="{{" + str(d.get("total")) + "}}",
                                                   count="{{" + str(d.get("count")) + "}}")
        return text, list(brief_questions(language)[:2])
    if "category_absent" in by_reason:
        d = by_reason["category_absent"]
        what = str(d.get("what") or "")
        if re.search(r"\d", what):
            return None
        labels = _chip_categories(d.get("top") or [], language)
        what = what.lower() if language == "en" else what
        if labels:
            return pick(ABSENT, language).format(what=what, categories=_listed(labels, language)), \
                _category_chips(labels, language)
        return pick(ABSENT_PLAIN, language).format(what=what), list(brief_questions(language)[:2])
    reasons = set(by_reason)
    reason = "period_in_future" if "period_in_future" in reasons else "period_before_data"
    last = min(_iso_day((by_reason.get("period_in_future") or {}).get("last")) or as_of, as_of)   # the tool's last day
    end = f"{last.day}.{last.month}.{last.year}" if language == "fi" else \
        f"{last.day} {calendar.month_name[last.month]} {last.year}"
    first = _first_month(by_reason.get("period_before_data") or {})
    chips = [c.format(month_en=f"{calendar.month_name[first.month]} {first.year}",
                      month_fi=f"{FI_MONTH_STEMS[first.month - 1]}kuussa {first.year}")
             for c in pick(MISSING_CHIPS[reason], language)]
    return pick(MISSING[reason], language).format(end=end), chips


def lesson(key: str | None, language: str) -> dict[str, str] | None:
    if key is None or key not in LESSONS:
        return None
    entry = LESSONS[key]
    return {"key": key, "title": pick(entry["title"], language), "text": pick(entry["text"], language)}


def _numbers_in(view: Any, label: str = "") -> list[tuple[str, str]]:
    """(label, id) of every number in a model view, the shallow ones first (a total and each group's
    amount before nested details such as a basket's categories), in view order within a depth.
    Groups use the group's label."""
    found: list[tuple[int, int, str, str]] = []

    def walk(node: Any, depth: int, current: str) -> None:
        if isinstance(node, dict):
            if {"id", "value", "unit"} <= node.keys() and isinstance(node.get("id"), str):
                found.append((depth, len(found), node.get("label") or current, node["id"]))
                return
            group_label = node.get("label") if isinstance(node.get("label"), str) else current
            for key, value in node.items():
                if key not in ("notes", "period", "tool"):
                    walk(value, depth + 1, group_label)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1, current)

    walk(view, 0, label)
    return [(lab, number_id) for _, _, lab, number_id in sorted(found)]


TAKEAWAY_SIZE = 4  # the main number and at most three supporting ones (issue #112); the rest stay in the cards
NEXT_PAYDAY = ("Next payday", "Seuraava palkkapäivä")
BILL_TYPICAL = r"regular|monthly|usual|every month|säännölli|kuukausi|tavallis"
# A bills question is a bills question even when it names payday ("Which bills are due before payday?",
# "Mitä laskuja on tulossa ennen palkkapäivää?"); only a question without bills is about income.
BILL_WORDS = r"\bbills?\b|lasku\w*"   # also inside a compound: "kuukausilaskuni"
# Income and payday words: the rule that sends the question to the bills tool (rules.py) and the
# takeaway below read them from here, so a question routed for its income gets the income (#216).
INCOME_WORDS = (r"\b(pay ?day|salary|income|take-? ?home pay|net pay|earn(s|ed|ings)?|palkka\w*|tulo|tulot|tuloni|"
                r"tuloja|tienaa?\w*|ansaitse\w*)\b")

# Matched against the folded question (no diacritics), so folded here too.
SAVE_MORE, BILL_TYPICAL, BILL_WORDS, INCOME_WORDS = (fold_pattern(rx) for rx in (SAVE_MORE, BILL_TYPICAL, BILL_WORDS, INCOME_WORDS))


def asks_income(q: str) -> bool:
    """A folded question about income or payday and not about the bills ("Which bills are due before
    payday?" is a bills question)."""
    return bool(re.search(INCOME_WORDS, q)) and not re.search(BILL_WORDS, q)


def _num(node: Any, label: str | None = None) -> tuple[str, str] | None:
    if isinstance(node, dict) and {"id", "value", "unit"} <= node.keys() and isinstance(node.get("id"), str):
        return (label or node.get("label") or "", node["id"])
    return None


def takeaway(view: dict[str, Any], question: str = "", language: str = "en") -> tuple[list[tuple[str, str]], list[str]]:
    """The numbers one tool's answer cites, main number first, at most TAKEAWAY_SIZE, in the order of
    agent-core.md section 6.2; and extra sentences without numbers (a date). A tool not listed here
    gets its shallowest numbers."""
    tool = view.get("tool")
    q = fold(question)
    picks: list[tuple[str, str] | None] = []
    extra: list[str] = []
    if tool == "get_spending":
        comparison = view.get("comparison") or {}
        picks.append(_num(view.get("total")))
        if comparison:
            picks += [_num(comparison.get("baseline")), _num(comparison.get("change")), _num(comparison.get("change_pct"))]
        else:
            picks.append(_num(view.get("tx_count")))
            picks += [_num(g.get("amount"), g.get("label")) for g in view.get("groups") or []]
    elif tool == "get_basket_breakdown":
        if not re.search(SAVE_MORE, q):  # "save more": the three shares, the rest stays in the card
            picks.append(_num(view.get("total")))
        picks += [_num(b.get("share"), b.get("label")) for b in view.get("baskets") or []]
    elif tool == "get_safe_to_save":
        # The monthly figure is the main number (#216); "save more" cites it alone next to the basket
        # shares. When it is 0, the tool's reason says why (a text without digits), never a negative.
        picks.append(_num(view.get("monthly")))
        if not re.search(SAVE_MORE, q):
            picks.append(_num(view.get("stock")))
        reason = view.get("reason") or {}
        if (view.get("monthly") or {}).get("value") == 0 and isinstance(reason.get("text"), str):
            extra.append(reason["text"])
    elif tool == "get_bonus_estimate":
        # The estimate and its assumptions sentence; the user's share stays out of the text (#216).
        if view.get("status") == "not_offered":
            if isinstance(view.get("reason"), str):
                extra.append(view["reason"])
        else:
            # The share is cited too: the user's own number when they gave one ("Share at S-Group
            # stores"), else the assumed default ("Assumed share ..."), so a "half" answer never reads
            # like one for all groceries (review of #246).
            picks += [_num(view.get(k)) for k in ("total_month", "share", "total_year", "grocery_month")]
            assumptions = [a for a in view.get("assumptions") or [] if isinstance(a, str)]
            if assumptions:
                extra.append(assumptions[-1])  # "...a what-if, not a fact about where you shop."
    elif tool == "get_peer_benchmark":
        # The position, the difference from the median with the tool's own display (it carries its
        # direction word), the median and the group size; nothing but the reason when not shown (#216).
        if view.get("shown") is False:
            if view.get("reason") in PEER_REASON:
                extra.append(pick(PEER_REASON[view["reason"]], language))
        else:
            picks += [_num(view.get("percentile")), _num(view.get("vs_median")), _num(view.get("peer_median")),
                      _num((view.get("peer_group") or {}).get("size"))]
    elif tool == "get_safe_to_spend":
        picks += [_num(view.get(k)) for k in ("safe_to_spend", "balance_limit", "budget_limit")]
    elif tool == "run_what_if":
        # The cut is the user's own number and stays out of the text.
        picks += [_num(view.get(k)) for k in ("saving_per_month", "baseline_per_month", "saving_per_year")]
    elif tool == "get_recurring_bills":
        if re.search(SAVE_MORE, q):  # "save more": the bills due before payday, one number
            picks.append(_num(view.get("upcoming_total")))
        elif asks_income(q):
            picks += [_num(i.get("typical_month"), i.get("label")) for i in view.get("income") or []]
            if isinstance(view.get("next_payday"), str):
                extra.append(f"{pick(NEXT_PAYDAY, language)}: {_date(view['next_payday'], language)}.")
        elif re.search(BILL_TYPICAL, q):
            picks += [_num(b.get("typical_month"), b.get("label")) for b in view.get("bills") or []]
        else:
            picks.append(_num(view.get("upcoming_total")))
            picks += [_num(b.get("due_until_payday"), b.get("label")) for b in view.get("bills") or []]
    else:
        picks = list(_numbers_in(view))
    out = [p for p in picks if p is not None][:TAKEAWAY_SIZE]
    return out, extra


# Safe to spend as one takeaway sentence with its reason (coordinator, after #246): the amount, and which
# limit binds. The three numbers are the ones the takeaway always cited.
SAFE_SENTENCE = {
    "budget": ("Safe to spend in the coming week: {safe}, because your monthly budget is the limit ({budget}); "
               "your balance would allow more ({balance}).",
               "Turvallisesti käytettävissä tulevalla viikolla: {safe}, koska kuukausibudjettisi on raja ({budget}); "
               "saldosi sallisi enemmän ({balance})."),
    "balance": ("Safe to spend in the coming week: {safe}, because your balance is the limit ({balance}); "
                "your monthly budget would allow more ({budget}).",
                "Turvallisesti käytettävissä tulevalla viikolla: {safe}, koska saldosi on raja ({balance}); "
                "kuukausibudjettisi sallisi enemmän ({budget})."),
    "equal": ("Safe to spend in the coming week: {safe}; your balance and your monthly budget set the same limit "
              "({balance}).",
              "Turvallisesti käytettävissä tulevalla viikolla: {safe}; saldosi ja kuukausibudjettisi asettavat saman "
              "rajan ({balance})."),
}


def _id(node: Any) -> str | None:
    return node["id"] if isinstance(node, dict) and isinstance(node.get("id"), str) else None


def _value(node: Any) -> float:
    return node.get("value") if isinstance(node, dict) and isinstance(node.get("value"), (int, float)) else 0


def goal_sentence(view: dict[str, Any], language: str) -> tuple[str, list[str]] | None:
    """Pay yourself first (#391): the weekly figure with the savings goal quoted next to it, so the two add
    up. Safe to spend: "You can spend about X this week, after setting aside about Y a month", or, when
    the weekly figure is more than USUAL_PACE_MARGIN_EUR under the usual pace, "To keep setting aside Y,
    about X a week is safe to spend, below your usual Z". Safe to save: the goal next to safe to spend, or
    the goal against what the usual pace leaves. None without a goal (the sentences stay as before)."""
    tool = view.get("tool")
    goal = view.get("savings_goal")
    if tool not in ("get_safe_to_spend", "get_safe_to_save") or _value(goal) <= 0 or not _id(goal):
        return None
    def tok(node: Any) -> str:
        return f"{{{{{node['id']}}}}}"
    if tool == "get_safe_to_spend":
        safe, usual = view.get("safe_to_spend"), view.get("usual_week")
        if view.get("binding_limit") != "budget" or not _id(safe):
            return None
        # without the usual pace the goal is still said (#552): the plain goal sentence
        if _id(usual) and _value(safe) < _value(usual) - float(tools_config.USUAL_PACE_MARGIN_EUR):
            text = tools_config.label(tools_config.SAFE_TO_SPEND_TEXT["below_usual_with_goal"], language)
            return text.format(goal=tok(goal), safe=tok(safe), usual=tok(usual)), [goal["id"], safe["id"], usual["id"]]
        text = tools_config.label(tools_config.SAFE_TO_SPEND_TEXT["with_goal"], language)
        return text.format(safe=tok(safe), goal=tok(goal)), [safe["id"], goal["id"]]
    monthly, weekly = view.get("monthly"), view.get("safe_to_spend_week")
    if not (_id(monthly) and _id(weekly)):
        return None
    if _value(monthly) >= _value(goal):
        text = tools_config.label(tools_config.SAFE_TO_SAVE_TEXT["subtitle_with_goal"], language)
        return text.format(goal=tok(goal), weekly=tok(weekly)), [goal["id"], weekly["id"]]
    text = tools_config.label(tools_config.SAFE_TO_SAVE_TEXT["subtitle_below_goal"], language)
    return text.format(goal=tok(goal), monthly=tok(monthly)), [goal["id"], monthly["id"]]


# "Why is my safe to spend lower / so low / so little", "miksi vähemmän / niin vähän" (#552): a rule answer from the
# safe-to-spend view (why_lower_sentence), never a model guess. Matched on the folded question; the rule planner
# also wants the safe-to-spend words, or a short bare question, and no category.
WHY_LOWER = (r"\b(why|how come)\b.*\b(lower|low|so little|less|smaller|so small|only)\b"
             r"|\bmiksi\b.*\b(vahemman|vahan|pieni\w*|pienempi|pienemp\w*|alhai\w*|matala\w*)\b")


def why_lower(q: str) -> bool:
    return bool(re.search(WHY_LOWER, q))


def why_lower_sentence(view: dict[str, Any], language: str) -> tuple[str, list[str]] | None:
    """The answer to "why is my safe to spend lower?" (#552): the limit that binds by name (the view's
    binding_limit), with the budget side the savings goal set aside first, and the other side's figure. None when
    a number is missing."""
    if view.get("tool") != "get_safe_to_spend":
        return None
    safe, goal, balance, budget = (view.get(k) for k in ("safe_to_spend", "savings_goal", "balance_limit",
                                                         "budget_limit"))
    if not (_id(safe) and _id(balance) and _id(budget)):
        return None
    if _value(balance) == _value(budget):
        key, cited = "why_equal", [safe]
    elif view.get("binding_limit") == "budget":
        key, cited = ("why_budget_goal", [safe, goal, balance]) if _value(goal) > 0 and _id(goal) else \
            ("why_budget", [safe, balance])
    else:
        key, cited = "why_balance", [safe, budget]
    tokens = {name: f"{{{{{node['id']}}}}}" for name, node in
              (("safe", safe), ("goal", goal), ("balance", balance), ("budget", budget)) if _id(node)}
    text = tools_config.label(tools_config.SAFE_TO_SPEND_TEXT[key], language)
    text = text.format(**{**{"goal": ""}, **tokens})
    # #575: a pending or "Needed" review's purchase (core.agent.why_review) takes the place of the other side's
    # figure: the first sentence stays, the review sentence follows, still at most three numbers.
    review = view.get("review_effect") or {}
    amount_id = (review.get("amount") or {}).get("id")
    review_key = {("pending", True): "why_review_pending_lowers", ("pending", False): "why_review_pending_same",
                  ("needed", True): "why_review_needed_moved", ("needed", False): "why_review_needed_same"}.get(
        (review.get("state"), bool(review.get("moved"))))
    if amount_id and review_key:
        first = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
        kept = cited[:2] if key == "why_budget_goal" else cited[:1]
        sentence = tools_config.label(tools_config.SAFE_TO_SPEND_TEXT[review_key], language).format(
            amount="{{" + amount_id + "}}")
        return first + " " + sentence, [node["id"] for node in kept] + [amount_id]
    return text, [node["id"] for node in cited]


def safe_to_spend_sentence(view: dict[str, Any], language: str) -> tuple[str, list[str]] | None:
    """The safe-to-spend takeaway as one sentence, and the ids it cites; None when a number is missing.
    With a savings goal it is the goal sentence (#391)."""
    with_goal = goal_sentence(view, language)
    if with_goal is not None:
        return with_goal
    if view.get("tool") != "get_safe_to_spend":
        return None
    nums = {k: view.get(k) for k in ("safe_to_spend", "balance_limit", "budget_limit")}
    if not all(isinstance(n, dict) and isinstance(n.get("id"), str) for n in nums.values()):
        return None
    if nums["balance_limit"].get("value") == nums["budget_limit"].get("value"):
        kind, ids = "equal", [nums["safe_to_spend"]["id"], nums["balance_limit"]["id"]]
    else:
        kind = "balance" if view.get("binding_limit") == "balance" else "budget"
        ids = [nums[k]["id"] for k in ("safe_to_spend", "balance_limit", "budget_limit")]
    tokens = {k.split("_")[0] if k != "safe_to_spend" else "safe": f"{{{{{n['id']}}}}}" for k, n in nums.items()}
    return pick(SAFE_SENTENCE[kind], language).format(**tokens), ids


# Small purchases as one takeaway sentence (#256), in the voice of the brief and within the length rule (review
# of #390): the takeaway number first, at most three numbers (the total, the count, the monthly average), the
# period in words. The limit stays on the card. Words always stand between a count and a date, so a count
# never reads as a day of a month. No advice, no judgement.
SMALL_SENTENCE = {
    "summary": ("You spent {total} on {count} small purchases{limit} {period}{month}, {where_part}.",
                "Käytit {total} pieniin ostoksiin {period}: {count} ostosta{limit}{month}, {where_part}."),
    "few": ("Only {count} {noun}{limit} {period}, {total} in all: not much to see here.",
            "Vain {count} {noun} {period}{limit}, yhteensä {total}: tässä ei ole paljon nähtävää."),
    "none": ("No small purchases{limit} {period}.", "Ei yhtään pientä ostosta {period}{limit}."),
    # the monthly Number's display already says "a month" / "/ kk" (eur_per_month)
    "month": (", about {month}", ", noin {month}"),
    # a limit other than the default (#465): its Number, in the place of the monthly average. Finnish says
    # "enintään" ("at most"); "rajalla" read as "right at the limit" (review of #476)
    "limit": (" of {limit} or less", ", enintään {limit}"),
    # SMALL_PURCHASE_WHERE carries each category's preposition ("at restaurants and cafés", "on entertainment")
    "most": ("most of them {where}", "suurin osa {where}"),
    "largest": ("the largest part {where}", "eniten {where}"),
    "noun_one": ("small purchase", "pieni ostos"),
    "noun_many": ("small purchases", "pientä ostosta"),
    "label": ("in {label}", "jaksolla {label}"),
}
# A preset period in words, without digits (review of #390: the period named in words). The validator accepts a
# month only when it equals a returned period exactly, so "from July to September 2026" would not pass; these do.
PRESET_WORDS = {
    "last_3_months": ("in the last three months", "viimeisen kolmen kuukauden aikana"),
    "last_6_months": ("in the last six months", "viimeisen kuuden kuukauden aikana"),
    "last_12_months": ("in the last twelve months", "viimeisen kahdentoista kuukauden aikana"),
    "last_month": ("last month", "viime kuussa"),
    "this_month": ("this month", "tässä kuussa"),
    "this_week": ("this week", "tällä viikolla"),
    "last_week": ("last week", "viime viikolla"),
    "year_to_date": ("this year", "tänä vuonna"),
}


def period_words(view: dict[str, Any], language: str) -> str | None:
    """The period of a small-purchases view: a preset in words ("in the last three months", "viime kuussa"),
    another period by its label ("in 3–24 Aug 2026"); None when there is neither."""
    preset = view.get("period_preset")
    if preset in PRESET_WORDS:
        return pick(PRESET_WORDS[preset], language)
    label = view.get("period")
    return pick(SMALL_SENTENCE["label"], language).format(label=label) if isinstance(label, str) else None


def small_purchases_sentence(view: dict[str, Any], language: str) -> tuple[str, list[str]] | None:
    """The small-purchases takeaway as one sentence, and the ids it cites (at most three); None when a number
    or the period is missing."""
    if view.get("tool") != "get_small_purchases":
        return None
    nums = {k: view.get(k) for k in ("count", "total", "per_month", "max_amount")}

    def has(key: str) -> bool:
        return isinstance(nums[key], dict) and isinstance(nums[key].get("id"), str)

    when = period_words(view, language)
    if not (has("count") and has("total") and when):
        return None
    token = {k: f"{{{{{nums[k]['id']}}}}}" for k in nums if has(k)}
    kind = (view.get("takeaway") or {}).get("kind")
    s = lambda key: pick(SMALL_SENTENCE[key], language)  # noqa: E731
    # The limit is named only when it is not the default (#465); then it takes the monthly average's place.
    other_limit = has("max_amount") and \
        Decimal(str(nums["max_amount"].get("value"))) != Decimal(tools_config.SMALL_PURCHASE_MAX_EUR)
    limit = s("limit").format(limit=token["max_amount"]) if other_limit else ""
    limit_ids = [nums["max_amount"]["id"]] if other_limit else []
    if kind == "none":
        text, ids = s("none").format(period=when, limit=limit), limit_ids
    elif kind == "few":
        noun = s("noun_one") if nums["count"].get("value") == 1 else s("noun_many")
        text = s("few").format(count=token["count"], noun=noun, period=when, total=token["total"], limit=limit)
        ids = [nums["count"]["id"]] + limit_ids + [nums["total"]["id"]]
    else:
        categories = view.get("categories") or []
        largest = categories[0] if categories else {}
        key, label = largest.get("key"), largest.get("label") or ""
        where = (pick(tools_config.SMALL_PURCHASE_WHERE[key], language) if key in tools_config.SMALL_PURCHASE_WHERE
                 else pick(tools_config.SMALL_PURCHASE_WHERE_OTHER, language).format(
                     label=label.lower() if language == "en" else label))
        share = (largest.get("share") or {}).get("value")
        if not label and key not in tools_config.SMALL_PURCHASE_WHERE or re.search(r"\d", where):
            return None
        where_part = s("most" if isinstance(share, (int, float)) and share > 50 else "largest").format(where=where)
        month = s("month").format(month=token["per_month"]) if has("per_month") and not other_limit else ""
        text = s("summary").format(total=token["total"], count=token["count"], period=when, month=month,
                                   where_part=where_part, limit=limit)
        ids = ([nums[k]["id"] for k in ("total", "count")] + limit_ids
               + ([nums["per_month"]["id"]] if month else []))
    return text[:1].upper() + text[1:], ids


# The savings plan (#369) in at most two sentences and three numbers, the plan's total a month first
# (coordinator, #411): the total and the total a year with the cuts, then the savings goal set aside first, the
# same Number the safe-to-spend answer cites (#468; never added in, left out at 0). A cut share is said in words
# when the setting has them (the view's `cut_words`), else cited as its Number; a cited cut share takes the
# place of the year, then of the goal, so the answer never cites more than three
# numbers; two equal shares are said once ("each a fifth less"), so a share is cited once. The levers' own
# amounts stay on the card; the S-Bonus is never here, it is the answer's first follow-up. Nothing quotes safe
# to spend (coordinator). The monthly and yearly displays already carry "a month" / "a year"; the sentences do not.
PLAN_SENTENCE = {
    "plan": ("These changes could add about {total}, about {year}: {cuts}.",
             "Nämä muutokset voisivat lisätä noin {total}, noin {year}: {cuts}."),
    "plan_no_year": ("These changes could add about {total}: {cuts}.",
                     "Nämä muutokset voisivat lisätä noin {total}: {cuts}."),
    "goal": ("That is on top of the about {goal} you set aside first.",
             "Tämä on sen lisäksi, että laitat ensin sivuun noin {goal}."),
    "first": ("eating out {cut} less", "ulkona syöminen {cut} vähemmän"),
    "other": ("spending {cut} less on {other}", "luokassa {other} {cut} vähemmän"),
    "each": ("eating out and spending on {other}, each {cut} less",
             "ulkona syöminen ja luokka {other}, kumpikin {cut} vähemmän"),
    "and": (" and ", " ja "),
    "none": ("None of the usual cuts would add much here.", "Tavalliset vähennykset eivät lisäisi tässä paljon."),
    "none_goal": ("None of the usual cuts would add much here; you already set aside about {goal} first.",
                  "Tavalliset vähennykset eivät lisäisi tässä paljon; laitat jo ensin sivuun noin {goal}."),
    # What already goes to savings (#560), before the plan; it takes the goal's place in the text (the goal stays in
    # the tool result and on the safe-to-spend card), so the answer never names two amounts "set aside". The
    # amount's display carries "a month". The neutral line has no digit and no amount (the bank-screen rule) and ends
    # at "yet": with the plan sentence it would pass the length rule's 35 words, and the card's own action speaks.
    "already": ("A regular transfer of about {amount} already goes to savings ({share} of your income).",
                "Säästöihin menee jo säännöllisesti noin {amount}, mikä on {share} tuloistasi."),
    "already_no_share": ("A regular transfer of about {amount} already goes to savings.",
                         "Säästöihin menee jo säännöllisesti noin {amount}."),
    "no_transfer": ("In this account I don't see a regular transfer to savings yet.",
                    "Tällä tilillä en vielä näe säännöllistä siirtoa säästöön."),
}
PLAN_MAX_NUMBERS = 3


def savings_plan_sentence(view: dict[str, Any], language: str) -> tuple[str, list[str]] | None:
    """The savings-plan takeaway (at most two sentences, three numbers) and the ids it cites; None when it
    cannot be built."""
    if view.get("tool") != "get_savings_plan":
        return None

    def num(node: Any) -> dict[str, Any] | None:
        return node if isinstance(node, dict) and isinstance(node.get("id"), str) else None

    goal = num(view.get("savings_goal"))
    goal = goal if goal and isinstance(goal.get("value"), (int, float)) and goal["value"] > 0 else None
    s = lambda key: pick(PLAN_SENTENCE[key], language)  # noqa: E731
    tok = lambda n: f"{{{{{n['id']}}}}}"  # noqa: E731
    # What already goes to savings (#560): a lead sentence with its amount and share, or the neutral line when the
    # tool saw no regular transfer; either takes the goal's place in the text. None when it could not be read.
    saving, share = num(view.get("already_saving")), num(view.get("already_share"))
    lead: tuple[str, list[str]] | None = None
    if view.get("saving_seen") is True and saving:
        lead = ((s("already").format(amount=tok(saving), share=tok(share)), [saving["id"], share["id"]]) if share
                else (s("already_no_share").format(amount=tok(saving)), [saving["id"]]))
    elif view.get("saving_seen") is False:
        lead = (s("no_transfer"), [])
    if view.get("kind") != "plan":
        if lead:
            return s("none") + " " + lead[0], lead[1]
        return (s("none_goal").format(goal=tok(goal)), [goal["id"]]) if goal else (s("none"), [])
    total, year = num(view.get("total_month")), num(view.get("total_year"))
    levers = view.get("levers") or []
    if not (total and year and levers):
        return None
    first_key = tools_config.SAVINGS_PLAN_FIRST[0]
    shares, cut_ids = {}, []                 # lever key -> its share in words or as a token
    for lever in levers:
        words, cut = lever.get("cut_words"), num(lever.get("cut"))
        if isinstance(words, str) and words and not re.search(r"\d", words):
            shares[lever.get("key")] = words
        elif cut is not None:
            shares[lever.get("key")] = tok(cut)   # "15.0%": a cut share without words is cited, never typed
            if cut["id"] not in cut_ids:           # two equal shares are one Number: said and counted once
                cut_ids.append(cut["id"])
        else:
            return None
    first = next((lv for lv in levers if lv.get("key") == first_key), None)
    other_lever = next((lv for lv in levers if lv.get("key") != first_key), None)
    other = ""
    if other_lever is not None:
        other = other_lever.get("category") or ""
        if not other or re.search(r"\d", other):
            return None
        other = other.lower() if language == "en" else other   # "luokassa Ostokset ja vapaa-aika"
    if first and other_lever and shares[first["key"]] == shares[other_lever["key"]]:
        cuts = [s("each").format(cut=shares[first["key"]], other=other)]
    else:
        cuts = ([s("first").format(cut=shares[first["key"]])] if first else []) + \
               ([s("other").format(cut=shares[other_lever["key"]], other=other)] if other_lever else [])
    if len(cut_ids) + 1 > PLAN_MAX_NUMBERS:
        return None
    cuts_text = s("and").join(cuts)
    if lead and lead[1]:
        # The transfer first, then the plan's total (no year, no goal), within three numbers: the share leaves first,
        # then the whole lead.
        if len(lead[1]) + 1 + len(cut_ids) > PLAN_MAX_NUMBERS and len(lead[1]) > 1:
            lead = (s("already_no_share").format(amount=tok(saving)), [saving["id"]])
        if len(lead[1]) + 1 + len(cut_ids) <= PLAN_MAX_NUMBERS:
            text = lead[0] + " " + s("plan_no_year").format(total=tok(total), cuts=cuts_text)
            return text, lead[1] + [total["id"]] + cut_ids
        lead = None
    if lead:   # the neutral line takes the goal's place; the plan sentence is as it is without the goal
        goal = None
    # The total and any cited cut share first, then the goal, then the year, within three numbers.
    with_goal = bool(goal) and len(cut_ids) + 2 <= PLAN_MAX_NUMBERS
    with_year = len(cut_ids) + 2 + with_goal <= PLAN_MAX_NUMBERS
    if with_year:
        sentences = [s("plan").format(total=tok(total), year=tok(year), cuts=cuts_text)]
    else:
        sentences = [s("plan_no_year").format(total=tok(total), cuts=cuts_text)]
    if with_goal:
        sentences.append(s("goal").format(goal=tok(goal)))
    if lead:
        sentences.append(lead[0])
    ids = [total["id"]] + ([year["id"]] if with_year else []) + cut_ids + ([goal["id"]] if with_goal else [])
    return " ".join(sentences), ids


def lead_sentences(view: dict[str, Any], language: str) -> list[str]:
    """Text that comes before a tool's numbers. None today: the spender profile names its type in its own
    sentence (answer_sentences.profile, #342), so the answer stays within two sentences."""
    return []


def save_more_plan(views: list[dict[str, Any]], question: str) -> bool:
    """The save-more plan ran: the baskets answered "How could I save more?", and no what-if did."""
    tools = {v.get("tool") for v in views}
    return bool(re.search(SAVE_MORE, fold(question))) and "get_basket_breakdown" in tools and "run_what_if" not in tools


def what_if_offer(views: list[dict[str, Any]], language: str) -> str:
    """The offered next question: a cut of the largest everyday category, with no amount (R1)."""
    largest = None
    for view in views:
        for basket in view.get("baskets") or [] if view.get("tool") == "get_basket_breakdown" else []:
            if basket.get("key") != "everyday_spending":
                continue
            for c in basket.get("categories") or []:
                if c.get("key") not in tools_config.WHAT_IF_CATEGORIES:  # only a cut the rules can plan
                    continue
                amount = (c.get("amount") or {}).get("value")
                if isinstance(amount, (int, float)) and c.get("label") and (largest is None or amount > largest[0]):
                    largest = (amount, c["label"])
    if largest is None or re.search(r"\d", largest[1]):
        return pick(WHAT_IF_OFFER_ANY, language)
    category = largest[1].lower() if language == "en" else largest[1]
    return pick(WHAT_IF_OFFER, language).format(category=category)


def _date(iso: str, language: str) -> str:
    y, m, d = iso.split("-")
    return iso if language == "en" else f"{int(d)}.{int(m)}.{y}"


def template_draft(views: list[dict[str, Any]], errors: list[dict[str, Any]], language: str,
                   allowed: Any | None, question: str = "") -> dict[str, Any]:
    """An AnswerDraft built only from model views: '<period>. <label>: {{nK}}.' sentences.

    With `allowed` (validator.Allowed: the orchestrator knows the numbers' periods), any label or note
    whose digits are not returned dates is left out. Without it (a model sees only model views), the
    tools' period and number labels are kept and notes with digits are left out; the validator checks
    the result."""
    def ok(text: str, is_note: bool = False) -> bool:
        if allowed is None:
            # Without the answer's dates: a note with digits is left out; a label is kept only if all its
            # digits are inside date expressions ("August 2026" yes, "Next 7 days" no). The validator
            # then checks that those dates were returned.
            if is_note:
                return not re.search(r"\d", text)
            return not re.search(r"\d", answer_text.find_dates(text, blank_all=True)[1])
        return not answer_text.leftover_digits(text, dates=allowed.dates, periods=allowed.periods)

    sentences: list[str] = []
    cited: list[str] = []
    q = fold(question)
    # #342: human sentences for the tools answer_sentences writes; the others (profile, peer, S-Bonus,
    # safe to spend, an unknown tool) keep their own form below.
    owns = [answer_sentences.for_view(view, language, ok, save_more=bool(re.search(SAVE_MORE, q)),
                                      asks_income=asks_income(q), bill_typical=bool(re.search(BILL_TYPICAL, q)))
            for view in views]
    generic = views   # the views that get the sentence-per-tool form below
    if views and all(own is not None for own in owns):
        offer = what_if_offer(views, language) if save_more_plan(views, question) else None
        sentences, generic = own_answer([own[0] for own in owns], bool(errors), offer), []
    for view, own in zip(generic, owns):
        # One sentence per tool: "<period>: <label>: {{n1}}; <label>: {{n2}}." Items are joined with
        # semicolons, so a number is never followed by ". " and a label (a count then "10. heinäkuu 2026"
        # would read as a date). Signed values keep their sign in the token's display.
        items = []
        period = view.get("period")
        has_head = isinstance(period, str) and ok(period)
        chosen, extra = takeaway(view, question, language)
        sentences += [s for s in lead_sentences(view, language) if ok(s, is_note=True)]
        custom = ((why_lower_sentence(view, language) if why_lower(q) else None)
                  or safe_to_spend_sentence(view, language)
                  or small_purchases_sentence(view, language)
                  or savings_plan_sentence(view, language))
        if custom and not set(custom[1]) & set(cited) and len(cited) + len(custom[1]) <= MAX_TEMPLATE_NUMBERS:
            sentences.append(custom[0])
            cited += custom[1]
            chosen = []  # the sentence above cites them
        if own and not set(own[1]) & set(cited) and len(cited) + len(own[1]) <= MAX_TEMPLATE_NUMBERS:
            sentences += own[0]   # the tool's notes stay on its card (Renat's length rule)
            cited += own[1]
            continue
        for label, number_id in chosen:
            if number_id in cited or len(cited) >= MAX_TEMPLATE_NUMBERS:
                continue
            safe_label = label if label and ok(label) else ""
            if not safe_label and (items or not has_head):
                continue  # a bare token after another token would read as one number with it
            items.append(f"{safe_label}: {{{{{number_id}}}}}" if safe_label else f"{{{{{number_id}}}}}")
            cited.append(number_id)
        head = f"{period}: " if has_head and items else ""
        if head and view.get("monthly_average"):  # say that the amounts are averages, not one month
            head = f"{period}, {pick(MONTHLY_AVERAGE, language)}: "
        if items:
            # Each sentence starts with a capital: "…: 10. syyskuu 2026: …" would read as a date in the
            # rendered text, "…: 10. Syyskuu 2026: …" does not (a day takes a lower-case month).
            sentence = head + "; ".join(items) + "."
            sentences.append(sentence[:1].upper() + sentence[1:])
        sentences += extra  # built from the view's own ISO dates (next payday): returned dates
        for note in view.get("notes") or []:
            if isinstance(note, str) and ok(note, is_note=True):
                sentences.append(note)
    if generic and sentences and save_more_plan(views, question):
        sentences.append(what_if_offer(views, language))
    if errors:
        if not views and all(e.get("error") == "period_out_of_range" for e in errors):
            sentences.append(pick(NO_DATA, language))
        else:
            sentences.append(pick(TOOL_FAILED, language))
    if not sentences:
        sentences.append(pick(NOTHING, language))
    text = " ".join(sentences)
    if not generic:   # own_answer may leave a view out: cite exactly the tokens the text says, in order
        cited = list(dict.fromkeys(TOKEN.findall(text)))
    return {"language": language, "text": text, "cited": cited, "lesson_key": None}


TOKEN = re.compile(r"\{\{(n\d+)\}\}")
ANSWER_SENTENCES = 2   # Renat's length rule on #342: the whole answer
ANSWER_NUMBERS = 3


def own_answer(views: list[list[str]], errors: bool, offer: str | None) -> list[str]:
    """The answer when answer_sentences writes every view (#342, review of #365): the first view that says
    something is the takeaway and is always said whole; a later view is said only while the answer stays
    within two sentences and three numbers, otherwise it is left out whole and its card shows it. The
    save-more offer and the error sentence count as sentences."""
    room = ANSWER_SENTENCES - (1 if errors else 0)
    sentences: list[str] = []
    tokens: set[str] = set()
    for texts in views:
        more = tokens | set(TOKEN.findall(" ".join(texts)))
        if not sentences or (len(sentences) + len(texts) <= room and len(more) <= ANSWER_NUMBERS):
            sentences += texts
            tokens = more
    if offer and sentences and len(sentences) < room:
        sentences.append(offer)
    return sentences
