"""Plain-language definitions of 15 money terms (#568): "What is X?" in English or Finnish.

A definition is ours, fixed here in both languages; the model never writes one. The answer is the definition
and, when an existing Number means exactly what its sentence says, the customer's own Number from an existing
tool, with that tool's method id and evidence (the pipeline runs the tool as for any answer). No new method
id, no tool declaration, no prompt.

`match` claims only a whole message that asks what exactly one term means ("What is a buffer?", "Mitä
tarkoittaa eräpäivä?"). A message about the customer's own figure ("What is my safe to spend?"), a second
question, an instruction or any other clause is not a match, and the message goes the usual way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core.tools import config

# The two bill terms the bill explanation already defines keep that one text (config.BILL_GLOSSARY).
_BILL = {key: config.BILL_GLOSSARY[key][1] for key in ("due_date", "reference_number")}


@dataclass(frozen=True)
class Term:
    key: str
    en: str                     # the names that match, as a regex on the folded, lower-case message
    fi: str
    text: tuple[str, str]       # the definition, (English, Finnish): one sentence, no digit


# The definitions follow the product's own texts (config.SAFE_TO_SPEND_TEXT, SAFE_TO_SAVE_TEXT, BASKET_LABELS)
# so a term never means two things. "Interest" is neutral: what it is, never a suggestion to borrow or invest.
TERMS: tuple[Term, ...] = (
    Term("safe_to_spend", r"safe[ -]to[ -]spend(?: amount)?",
         r"turvallisesti kaytettavissa(?: oleva(?: summa| raha)?)?",
         ("Safe to spend is what you can use before your next payday after your bills, your usual essentials and a "
          "small cushion are set aside.",
          "Turvallisesti käytettävissä on se, mitä voit käyttää ennen seuraavaa palkkapäivää, kun laskut, tavalliset "
          "välttämättömät menot ja pieni puskuri on pantu sivuun.")),
    Term("safe_to_save", r"safe[ -]to[ -]save(?: amount)?",
         r"turvallisesti saastettavissa(?: oleva(?: summa| raha)?)?",
         ("Safe to save is what a typical month leaves after your income has covered bills, your usual essentials, a "
          "reserve for surprises and your everyday spending.",
          "Turvallisesti säästettävissä on se, mitä tavallisesta kuukaudesta jää, kun tuloilla on katettu laskut, "
          "tavalliset välttämättömät menot, varaus yllätyksiin ja arkikulutus.")),
    Term("regular_essentials", r"regular essentials?", r"saannolli(?:set|nen) valttamatto(?:mat|n)(?: menot| meno)?",
         ("Regular essentials are the costs you cannot skip and that come back every month, such as rent, "
          "electricity and insurance.",
          "Säännölliset välttämättömät ovat menoja, joita et voi jättää väliin ja jotka toistuvat joka kuukausi, "
          "kuten vuokra, sähkö ja vakuutukset.")),
    Term("unexpected_necessities", r"unexpected necessit(?:y|ies)",
         r"odottamatto(?:mat|n) valttamatto(?:mat|n)(?: menot| meno)?",
         ("Unexpected necessities are costs you did not plan but could not avoid, such as a car repair or a "
          "broken phone.",
          "Odottamattomat välttämättömät ovat menoja, joita et suunnitellut mutta joita et voinut välttää, kuten "
          "auton korjaus tai rikkoutunut puhelin.")),
    Term("everyday_spending", r"everyday spending", r"arjen kulutus|arkikulutus",
         ("Everyday spending is the money you choose to spend day to day, such as eating out, hobbies and shopping.",
          "Arjen kulutus on rahaa, jonka käytät omien valintojesi mukaan päivästä toiseen, kuten ulkona syömiseen, "
          "harrastuksiin ja ostoksiin.")),
    Term("regular_bill", r"(?:regular|recurring) bills?", r"saannolli(?:nen|set) lasku(?:t)?|toistuva(?:t)? lasku(?:t)?",
         ("A regular bill is a payment that comes back at about the same time and size, such as rent or a phone "
          "plan.",
          "Säännöllinen lasku on maksu, joka toistuu suunnilleen samaan aikaan ja samansuuruisena, kuten vuokra tai "
          "puhelinliittymä.")),
    Term("buffer", r"(?:safety )?buffer|cushion", r"puskuri",
         ("The buffer is a small fixed amount Sentti keeps back until payday, so a surprise does not empty your "
          "account.",
          "Puskuri on pieni kiinteä summa, jonka Sentti pitää sivussa palkkapäivään asti, jotta yllätys ei tyhjennä "
          "tiliäsi.")),
    Term("pay_yourself_first", r"pay(?:ing)? yourself first",
         r"maksa (?:ensin itsellesi|itsellesi ensin)|maksa ensin itselle",
         ("Pay yourself first means setting your savings aside as soon as money comes in, before you spend on "
          "anything else.",
          "Maksa ensin itsellesi tarkoittaa, että siirrät säästösi sivuun heti rahan tultua, ennen kuin käytät "
          "rahaa mihinkään muuhun.")),
    Term("due_date", r"due date", r"erapaiva", _BILL["due_date"]),
    Term("reference_number", r"reference number", r"viitenumero", _BILL["reference_number"]),
    Term("e_invoice", r"e-?invoice|e invoice|electronic invoice", r"e-?lasku|verkkolasku",
         ("An e-invoice is a bill that arrives straight in your online bank, ready to be checked and paid.",
          "E-lasku on lasku, joka tulee suoraan verkkopankkiisi valmiina tarkistettavaksi ja maksettavaksi.")),
    Term("direct_payment", r"direct payment", r"suoramaksu",
         ("A direct payment is a bill the bank pays from your account on the due date, after letting you know "
          "beforehand.",
          "Suoramaksu on lasku, jonka pankki maksaa tililtäsi eräpäivänä ilmoitettuaan siitä sinulle etukäteen.")),
    Term("interest", r"interest(?: rate)?", r"korko",
         ("Interest is the price of money over time: a borrower pays it on a loan, and a bank may pay it on savings.",
          "Korko on rahan hinta ajan kuluessa: lainaaja maksaa sitä lainasta, ja pankki voi maksaa sitä säästöille.")),
    Term("budget", r"budget", r"budjetti",
         ("A budget is a plan for how much you will spend on different things in a month.",
          "Budjetti on suunnitelma siitä, paljonko käytät rahaa eri asioihin kuukaudessa.")),
    Term("peer_median", r"peer median", r"vertais(?:ryhman )?mediaani|vertaisryhman mediaani",
         ("The peer median is the middle amount in a group of people like you: half of them spend less, half "
          "spend more.",
          "Vertaisryhmän mediaani on keskimmäinen summa sinun kaltaistesi ihmisten ryhmässä: puolet käyttää "
          "vähemmän, puolet enemmän.")),
)
BY_KEY = {t.key: t for t in TERMS}

# The question frames, on the folded message without its end punctuation. Only these, whole.
_ARTICLE = r"(?:a |an |the )?"
_FRAMES_EN = (r"what is {a}{t}", r"what'?s {a}{t}", r"what does {a}{t} mean", r"what is meant by {a}{t}",
              r"explain {a}{t}", r"define {a}{t}", r"what are {t}", r"what do {t} mean")
_FRAMES_FI = (r"mita on {t}", r"mika on {t}", r"mita tarkoittaa {t}", r"mita {t} tarkoittaa", r"selita {t}",
              r"mita ovat {t}", r"mitka ovat {t}", r"mita {t} ovat")
_FOLD = str.maketrans({"ä": "a", "ö": "o", "å": "a", "’": "'"})


def _fold(message: str) -> str:
    text = message.lower().translate(_FOLD)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s*[?!.]+$", "", text)


def _patterns() -> list[tuple[re.Pattern, str]]:
    out = []
    for term in TERMS:
        for names, frames in ((term.en, _FRAMES_EN), (term.fi, _FRAMES_FI)):
            for frame in frames:
                out.append((re.compile(frame.format(a=_ARTICLE, t=f"(?:{names})")), term.key))
    return out


_COMPILED = _patterns()


def match(message: str) -> Term | None:
    """The one term a whole message asks about, or None: any other word, a second question or an instruction
    leaves the message to the usual path."""
    text = _fold(message)
    if not text or "?" in text or "\n" in message.strip():
        return None   # an inner question mark: a second question ("What is a budget? And my balance?")
    found = {key for rx, key in _COMPILED if rx.fullmatch(text)}
    return BY_KEY[found.pop()] if len(found) == 1 else None


# ---- the customer's own Number ----

@dataclass(frozen=True)
class Own:
    tool: str
    args: dict[str, Any]
    sentence: tuple[str, str]   # with {n}: the token of the Number, whose display carries its unit and period


def _component(view: dict, key: str) -> Any:
    return next((c.get("amount") for c in view.get("components") or [] if c.get("key") == key), None)


def _basket(view: dict, key: str) -> Any:
    return next((b.get("amount") for b in view.get("baskets") or [] if b.get("key") == key), None)


# term -> (how to get it, which Number of the view). Only a Number that means exactly what its sentence says.
OWN: dict[str, Own] = {
    "safe_to_spend": Own("get_safe_to_spend", {}, ("Yours right now is {n}.", "Sinulla se on nyt {n}.")),
    "safe_to_save": Own("get_safe_to_save", {}, ("Yours is {n}.", "Sinulla se on {n}.")),
    "buffer": Own("get_safe_to_spend", {}, ("Yours is {n}.", "Sinulla se on {n}.")),
    "pay_yourself_first": Own("get_safe_to_spend", {}, ("Your savings goal is {n}.", "Säästötavoitteesi on {n}.")),
    "regular_bill": Own("get_safe_to_spend", {}, ("Your regular bills due before your next payday: {n}.",
                                                  "Säännölliset laskusi ennen seuraavaa palkkapäivää: {n}.")),
    "regular_essentials": Own("get_basket_breakdown", {"period": {"preset": "last_month"}},
                              ("Over the last full month yours averaged {n}.", "Viimeisenä täytenä kuukautena sinulla keskimäärin {n}.")),
    "unexpected_necessities": Own("get_basket_breakdown", {"period": {"preset": "last_month"}},
                                  ("Over the last full month yours averaged {n}.", "Viimeisenä täytenä kuukautena sinulla keskimäärin {n}.")),
    "everyday_spending": Own("get_basket_breakdown", {"period": {"preset": "last_month"}},
                             ("Over the last full month yours averaged {n}.", "Viimeisenä täytenä kuukautena sinulla keskimäärin {n}.")),
    "peer_median": Own("get_peer_benchmark", {"metric": "spend_total"},
                       ("For total spending in your peer group it is {n}.",
                        "Vertaisryhmäsi kokonaiskulutuksessa se on {n}.")),
}

_PICK = {
    "safe_to_spend": lambda v: v.get("safe_to_spend"),
    "safe_to_save": lambda v: v.get("monthly"),
    "buffer": lambda v: _component(v, "cushion"),
    "pay_yourself_first": lambda v: v.get("savings_goal"),   # dev since #391 / #426; absent before
    "regular_bill": lambda v: _component(v, "bills_due"),
    "regular_essentials": lambda v: _basket(v, "regular_essentials"),
    "unexpected_necessities": lambda v: _basket(v, "unexpected_necessities"),
    "everyday_spending": lambda v: _basket(v, "everyday_spending"),
    "peer_median": lambda v: v.get("peer_median") if v.get("shown") else None,
}


def own_number_id(key: str, view: dict) -> str | None:
    """The id of the view's Number for this term, or None: absent, not shown or zero gives the definition alone."""
    number = _PICK[key](view) if key in _PICK else None
    if not isinstance(number, dict) or not number.get("id"):
        return None
    try:
        if float(number.get("value")) == 0:
            return None
    except (TypeError, ValueError):
        return None
    return number["id"]


def answer_text(key: str, language: str, number_id: str | None) -> str:
    """The definition, then the own-Number sentence when there is a Number."""
    i = 0 if language == "en" else 1
    text = BY_KEY[key].text[i]
    if number_id is not None and key in OWN:
        text += " " + OWN[key].sentence[i].format(n="{{" + number_id + "}}")
    return text
