"""Fixed texts and the deterministic template answer (agent-core.md sections 6.3, 7.4, 7.6 and 11).

- Refusal templates per kind, the no-data sentence, the default clarifying question, follow-up
  questions and the lesson catalogue, in English and Finnish. They are drafts for human review
  before the demo (agent-core.md section 7.7); none of them contains a digit.
- template_draft builds an AnswerDraft from the tools' model views only: it cites every number as a
  {{nK}} token and writes no digit itself, so it passes the validator. It is the composer of the
  rule model and the fallback after a failed composer (R12).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from core import answer_text

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
        "text": ("I can only help with questions about your own money, such as your spending, bills and savings.",
                 "Voin auttaa vain omiin raha-asioihisi liittyvissä kysymyksissä, kuten kulutuksessa, laskuissa ja säästämisessä."),
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
    ("What can I safely spend this week?", "Paljonko voin turvallisesti käyttää tällä viikolla?"),
    ("How could I save more?", "Miten voisin säästää enemmän?"),
)

NO_DATA = ("There are no transactions for that period in your data.",
           "Tältä jaksolta ei ole tapahtumia aineistossasi.")
TOOL_FAILED = ("Some of the data could not be computed right now.",
               "Osaa tiedoista ei voitu laskea juuri nyt.")
NOTHING = ("I could not find data for that question.", "En löytänyt tietoja tähän kysymykseen.")
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


def refusal(kind: str, language: str) -> tuple[str, dict[str, str]]:
    entry = REFUSAL[kind]
    return pick(entry["text"], language), {"kind": kind, "label": pick(entry["label"], language)}


def follow_ups(question: str, language: str, refused: bool = False) -> list[str]:
    """The partner's four questions minus the one just asked (agent-core.md section 7.6)."""
    asked = question.strip().lower()
    out = [pick(q, language) for q in BRIEF_QUESTIONS if pick(q, language).lower() != asked]
    return out[:2] if refused else out[:3]


def lesson(key: str | None, language: str) -> dict[str, str] | None:
    if key is None or key not in LESSONS:
        return None
    entry = LESSONS[key]
    return {"key": key, "title": pick(entry["title"], language), "text": pick(entry["text"], language)}


def _numbers_in(view: Any, label: str = "") -> list[tuple[str, str]]:
    """(label, id) of every number in a model view, in order. Groups use the group's label."""
    out: list[tuple[str, str]] = []
    if isinstance(view, dict):
        if {"id", "value", "unit"} <= view.keys() and isinstance(view.get("id"), str):
            return [(view.get("label") or label, view["id"])]
        group_label = view.get("label") if isinstance(view.get("label"), str) else label
        for key, value in view.items():
            if key in ("notes", "period", "tool"):
                continue
            out += _numbers_in(value, group_label)
    elif isinstance(view, list):
        for item in view:
            out += _numbers_in(item, label)
    return out


def template_draft(views: list[dict[str, Any]], errors: list[dict[str, Any]], language: str,
                   allowed: Any | None) -> dict[str, Any]:
    """An AnswerDraft built only from model views: '<period>. <label>: {{nK}}.' sentences.

    With `allowed` (validator.Allowed: the orchestrator knows the numbers' periods), any label or note
    whose digits are not returned dates is left out. Without it (a model sees only model views), the
    tools' period and number labels are kept and notes with digits are left out; the validator checks
    the result."""
    def ok(text: str, is_note: bool = False) -> bool:
        if allowed is None:
            return not (is_note and re.search(r"\d", text))
        return not answer_text.leftover_digits(text, dates=allowed.dates, periods=allowed.periods)

    sentences: list[str] = []
    cited: list[str] = []
    for view in views:
        period = view.get("period")
        if isinstance(period, str) and ok(period):
            sentences.append(f"{period}.")
        for label, number_id in _numbers_in(view):
            if number_id in cited or len(cited) >= MAX_TEMPLATE_NUMBERS:
                continue
            safe_label = label if label and ok(label) else ""
            sentences.append(f"{safe_label}: {{{{{number_id}}}}}." if safe_label else f"{{{{{number_id}}}}}.")
            cited.append(number_id)
        for note in view.get("notes") or []:
            if isinstance(note, str) and ok(note, is_note=True):
                sentences.append(note)
    if errors:
        if not views and all(e.get("error") == "period_out_of_range" for e in errors):
            sentences.append(pick(NO_DATA, language))
        else:
            sentences.append(pick(TOOL_FAILED, language))
    if not sentences:
        sentences.append(pick(NOTHING, language))
    return {"language": language, "text": " ".join(sentences), "cited": cited, "lesson_key": None}
