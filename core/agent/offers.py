"""One follow-up offer, and the habit-tip checks of a model draft (#572, slice 2).

The offer
- The server picks at most one offer from OFFERS, by the answer's own tools and data (FOLLOWS, and the
  category rule of "cut"), and appends its sentence as the answer's last sentence when the answer stays within
  the length rule. The same offer's question goes first in `follow_ups`, the chips the app already shows: tapping
  it asks that question, and the rule planner claims each of them with the tool and arguments listed here
  (tests). No contract change: `done.actions` stays as it is.
- The offer sentence has no number. The one preset of an offer, the what-if's cut, is the savings plan's own
  (config.SAVINGS_PLAN_FIRST) and appears in the chip only.
- No offer: health, declines, clarifying questions, glossary answers, missing-data answers, the introduction,
  the review-amount answer, an answer with a pending review card, an answer whose own card already offers the
  next step (the peer card's cut), the general route's fixed fallback (it carries its own offer), and any
  answer that would break the length rule with one more sentence. A template answer (the model unavailable)
  gets the chip but not the sentence, so no template text changes.

The model writes no offer and asks the user nothing: a draft that does is rejected and retried once
(draft_problems, model drafts only; a clarifying question is a template and never passes through it).

The habit tip: at most one suggesting sentence in a model draft, with no digit or number word, no product, no
bank screen or bank product (answer_text.bank_action, #417), no borrowing (answer_text.borrowing_suggestion,
#419), no investing (the guard's investment words) and no health (the rules' health words); no tip at all on a
health answer. The validator's own number scan already covers the whole draft.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Any, Iterable

from core import answer_text
from core.agent import template
from core.agent.guard import FLAGS, fold
from core.agent.rules import HEALTH
from core.agent.validator import NUMBER_WORDS
from core.tools import config

# The what-if offer's preset: the savings plan's own cut of eating out (config), checked once at import.
CUT_PCT = config.SAVINGS_PLAN_FIRST[1]
assert isinstance(CUT_PCT, int) and 0 < CUT_PCT < 100 and CUT_PCT in (
    config.SAVINGS_PLAN_FIRST[1], config.SAVINGS_PLAN_OTHER_CUT_PCT), "the offer's cut must be a plan preset"
# The categories a what-if may cut: the savings plan's levers. Never Groceries, Housing, Utilities or Health.
CUT_CATEGORIES = (config.SAVINGS_PLAN_FIRST[0], *config.SAVINGS_PLAN_OTHER_CATEGORIES)
assert not set(CUT_CATEGORIES) & {"Groceries", "Housing", "Utilities", "Health"}


@dataclass(frozen=True)
class Offer:
    key: str
    text: str                    # the answer's last sentence
    chip: str                    # the question asked when tapped: first in follow_ups
    tool: str
    args: dict[str, Any]


# key -> ((English sentence, English chip), (Finnish sentence, Finnish chip)), tool, args. The chips are
# questions the rule planner claims with exactly this tool and these arguments (test_agent_offers.py).
OFFERS: dict[str, tuple[tuple[tuple[str, str], tuple[str, str]], str, dict[str, Any]]] = {
    "cut": ((("Want to see what a cut on {category} would save?", "What if I spend {pct}% less on {category}?"),
             ("Haluatko nähdä, paljonko säästäisit vähentämällä luokassa {label}?",
              "Entä jos vähentäisin luokassa {label} {pct} %?")),
            "run_what_if", {"selection": {"kind": "category", "value": "{key}"}, "cut_pct": CUT_PCT}),
    "save_more": ((("Want to see how you could save more?", template.BRIEF_QUESTIONS[3][0]),
                   ("Haluatko nähdä, miten voisit säästää enemmän?", template.BRIEF_QUESTIONS[3][1])),
                  "get_savings_plan", {}),
    "peer": ((("Want to see how your spending compares with people like you?",
               "How does my spending compare with people like me?"),
              ("Haluatko nähdä, miten kulutuksesi vertautuu kaltaisiisi?", "Miten kulutukseni vertautuu kaltaisiini?")),
             "get_peer_benchmark", {"metric": "spend_total"}),
    "safe_to_spend": ((("Want to see what you can safely spend this week?", template.BRIEF_QUESTIONS[2][0]),
                       ("Haluatko nähdä, paljonko voit käyttää turvallisesti tällä viikolla?",
                        template.BRIEF_QUESTIONS[2][1])),
                      "get_safe_to_spend", {}),
    "forecast": ((("Want to see whether your money lasts until payday?", "Will my money last until payday?"),
                  ("Haluatko nähdä, riittävätkö rahasi palkkapäivään asti?", "Riittävätkö rahani palkkapäivään asti?")),
                 "get_balance_forecast", {}),
    "bills": ((("Want to see which bills are due before payday?", "Which bills are due before payday?"),
               ("Haluatko nähdä, mitkä laskut erääntyvät ennen palkkapäivää?",
                "Mitkä laskut erääntyvät ennen palkkapäivää?")),
              "get_recurring_bills", {}),
}
# The answer's own (first) data tool -> the offer that follows it. get_spending: "cut" only for one lever category.
FOLLOWS = {"get_spending": "cut", "get_safe_to_spend": "save_more", "get_savings_plan": "peer",
           "get_basket_breakdown": "safe_to_spend", "get_recurring_bills": "forecast",
           "get_balance_forecast": "bills", "run_what_if": "save_more", "get_peer_benchmark": "save_more"}
# The general answer's topic (slice 1's template.general_topic) -> the offer that follows it.
GENERAL_FOLLOWS = {"budget": "safe_to_spend", "saving": "save_more", "bills": "bills", "spending": "safe_to_spend"}


def _pick(pair: tuple[str, str], language: str) -> str:
    return pair[1] if language == "fi" else pair[0]


def _category(view: dict[str, Any], language: str) -> tuple[str, str] | None:
    """(key, label) of a spending answer filtered to exactly one lever category with enough purchases."""
    labels = view.get("filter_labels") or []
    if view.get("filter_parts") != 1 or len(labels) != 1 or view.get("groups"):
        return None
    key = next((k for k in CUT_CATEGORIES if config.label(config.CATEGORY_LABELS[k], language) == labels[0]), None)
    count = (view.get("tx_count") or {}).get("value")
    if key is None or not isinstance(count, (int, float)) or count < config.TOO_FEW_TRANSACTIONS:
        return None
    if not float(((view.get("total") or {}).get("value")) or 0) > 0:
        return None
    return key, labels[0]


def _health(views: list[dict[str, Any]], question: str) -> bool:
    text = " ".join(str(v.get("filter_labels") or "") + " " + str((v.get("total") or {}).get("label") or "")
                    for v in views if isinstance(v, dict))
    return any(re.search(HEALTH, s, re.I) or re.search(HEALTH, fold(s), re.I) for s in (question, text))


def make(name: str, language: str, **values: str) -> Offer:
    (en, fi), tool, args = OFFERS[name]
    text, chip = _pick((en, fi), language)
    fill = {"pct": str(CUT_PCT), **values}
    args = {k: ({**v, "value": values.get("key", "")} if isinstance(v, dict) else v) for k, v in args.items()}
    return Offer(name, text.format(**fill), chip.format(**fill), tool, args)


def listed(spec: str | dict[str, str], language: str) -> Offer:
    """An offer named by an eval case: "save_more", or {"name": "cut", "category": "Restaurants"}."""
    if isinstance(spec, str):
        return make(spec, language)
    label = config.label(config.CATEGORY_LABELS[spec["category"]], language)
    return make(spec["name"], language, key=spec["category"], label=label,
                category=label.lower() if language == "en" else label)


def choose(views: list[dict[str, Any]], language: str, question: str, *, kind: str = "ordinary",
           general: bool = False) -> Offer | None:
    """The one offer that fits the answer, or None."""
    data = [v for v in views or [] if isinstance(v, dict) and v.get("tool")]
    if _health(data, question):
        return None
    if general:
        topic = getattr(template, "general_topic", None)
        key = GENERAL_FOLLOWS.get(topic(question)) if topic else None
        offer = make(key, language) if key else None
    else:
        if not data:
            return None
        first = data[0]
        tool = str(first.get("tool"))
        if first.get("offers_cut"):
            return None                       # the peer card already offers its cut (#418)
        key = FOLLOWS.get(tool)
        if key == "cut":
            found = _category(first, language)
            if found is None:
                return None
            label = found[1]
            offer = make("cut", language, key=found[0], label=label,
                         category=label.lower() if language == "en" else label)
        else:
            offer = make(key, language) if key else None
        if offer is not None and any(v.get("tool") == offer.tool for v in data):
            return None                       # never the tool just answered
    if offer is None or offer.chip.strip().lower() == question.strip().lower():
        return None
    return offer


def strip_offer(text: str) -> tuple[str, str | None]:
    """The text without a listed offer sentence at its end, and that sentence (None when there is none)."""
    for (en, fi), _, _ in OFFERS.values():
        for sentence, _chip in (en, fi):
            rx = re.escape(sentence)
            for slot in ("{category}", "{label}"):
                rx = rx.replace(re.escape(slot), r"[^.?!]+")
            m = re.search(r"\s+(" + rx + r")$", text)
            if m:
                return text[:m.start()], m.group(1)
    return text, None


def _fits(text: str, numbers: int, displays: Iterable[str], kind: str) -> bool:
    """The text within the length rule of its kind (slice 1's kind-aware rule when it is there)."""
    params = inspect.signature(answer_text.length_problems).parameters
    extra = {"kind": kind} if "kind" in params else {}
    return not answer_text.length_problems(text, numbers, displays, **extra)


def apply(text: str, follow_ups: list[str], *, views: list[dict[str, Any]], language: str, question: str,
          kind: str = "ordinary", numbers: int = 0, displays: Iterable[str] = (), outcome: str = "answered",
          used_template: bool = False, review_pending: bool = False, general: bool = False,
          general_fallback: bool = False) -> tuple[str, list[str]]:
    """The answer's text with the offer as its last sentence (when it fits) and the chips with the offer's question
    first. Anything that is not an ordinary answered question is returned unchanged."""
    if outcome != "answered" or review_pending or general_fallback:
        return text, follow_ups
    offer = choose(views, language, question, kind=kind, general=general)
    if offer is None:
        return text, follow_ups
    chips = [offer.chip] + [f for f in follow_ups if f.strip().lower() != offer.chip.strip().lower()]
    if used_template:
        return text, chips[:3]                # a template text stays exactly as tests pin it
    offered = text.rstrip() + " " + offer.text
    if not _fits(offered, numbers, displays, kind):
        return text, follow_ups               # no room for one more sentence: no offer at all
    return offered, chips[:3]


# ---- checks of a model draft ----------------------------------------------------------------------------------

# The model writes no offer and asks the user nothing (the server adds the one listed offer).
OFFER_WORDS = re.compile(
    r"\b(?:want\s+to\s+see|would\s+you\s+like|do\s+you\s+want|shall\s+i|should\s+i\s+(?:show|check|run)|"
    r"let\s+me\s+know\s+if|i\s+can\s+(?:also\s+)?(?:show|check|run|look)|i\s+could\s+(?:show|check|run|look)|"
    r"tap\s+(?:the|a|here)|haluatko|haluaisitko|voinko\s+(?:näyttää|katsoa|laskea)|näytänkö|kerronko|"
    r"jos\s+haluat,?\s+(?:voin|näytän|katson))\b", re.I)
# A habit tip: a suggestion in words, without a number token ("Try cooking at home on weekdays.").
TIP_WORDS = re.compile(
    r"\b(?:try|consider|a\s+good\s+habit|one\s+habit|a\s+simple\s+habit|tip|it\s+helps\s+to|could\s+help|"
    r"you\s+might|set\s+aside|make\s+it\s+a\s+habit|kokeile|kokeilla|harkitse|kannattaa|vinkki|hyvä\s+tapa|"
    r"tapa\s+on|voisit|auttaa\s+usein)\b", re.I)
INVESTING = re.compile(FLAGS["investment_keyword"] + r"|\binvest\w*|\bsijoit\w*|\bindex\b|\bindeksi\w*", re.I)
# A tip is a suggestion by definition, so any borrowing word in it is a borrowing suggestion (beside the shared
# borrowing check, which tells a statement from a suggestion), and the rules' health words gain a few of a tip.
BORROWING = re.compile(r"\b(?:loans?|credit|overdraft\w*|instal+ments?|borrow\w*|buy\s+now,?\s+pay\s+later|"
                       r"\w*laina\w*|luot\w*|osamaks\w*|limiit\w*)\b", re.I)
TIP_HEALTH = re.compile(HEALTH + r"|\bmedicin\w*|\bmedica\w*|\bsleep\w*|\bdiet\w*|\bexercis\w*|\bvitamin\w*|"
                        r"\bunta\b|\bnukk\w*|\bruokavalio\w*|\bliikun\w*", re.I)
PRODUCT_TIP = re.compile(
    r"\b(?:switch\w*|open\w*|get|getting|download\w*|sign\w*\s+up|choos\w*|use|using|appl\w*|mov\w*|try|trying|"
    r"consider\w*)\b[^.!?]{0,40}?\b(?:apps?|application|"
    r"(?:savings?\s+)?accounts?|cards?|banks?|funds?|insurance|loans?|services?)\b|"
    r"\b(?:vaihda|avaa|hanki|lataa|valitse|käytä|siirry)\b[^.!?]{0,40}?\b(?:sovellu\w*|tili\w*|kortti\w*|korti\w*|"
    r"pankki\w*|panki\w*|rahasto\w*|vakuutu\w*|laina\w*|palvelu\w*)", re.I)
_TOKEN = re.compile(r"\{\{n\d+\}\}")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in answer_text.SENTENCE_BREAK.split(text or "") if s.strip()]


def tip_sentences(text: str) -> list[str]:
    return [s for s in _sentences(text) if TIP_WORDS.search(s) and not _TOKEN.search(s)]


def draft_problems(text: str, numbers: Any = None, *, kind: str = "ordinary", has_data: bool = True,
                   data: list[dict[str, Any]] | None = None, question: str = "") -> list[str]:
    """What a model draft gets wrong of slice 2's rules, as retry reasons; [] when nothing."""
    problems: list[str] = []
    if "?" in text or OFFER_WORDS.search(text) or OFFER_WORDS.search(fold(text)):
        problems.append("do not ask the user anything and write no follow-up offer: the server adds the one offer")
    tips = tip_sentences(text)
    if tips and data is not None and _health([v for v in data if isinstance(v, dict)], question):
        problems.append("no habit tip on an answer about health spending")
        return problems
    if len(tips) > 1:
        problems.append("at most one habit tip")
    for tip in tips:
        folded = fold(tip)
        if re.search(r"\d", tip) or NUMBER_WORDS.search(tip) or NUMBER_WORDS.search(folded):
            problems.append(f"'{tip}': a habit tip has no number")
        if answer_text.bank_action(tip) or PRODUCT_TIP.search(tip) or PRODUCT_TIP.search(folded):
            problems.append(f"'{tip}': a habit tip names no product, bank or bank screen")
        if answer_text.borrowing_suggestion(tip) or BORROWING.search(tip) or BORROWING.search(folded):
            problems.append(f"'{tip}': a habit tip never suggests borrowing")
        if INVESTING.search(tip) or INVESTING.search(folded):
            problems.append(f"'{tip}': a habit tip never suggests investing")
        if TIP_HEALTH.search(tip) or TIP_HEALTH.search(folded):
            problems.append(f"'{tip}': a habit tip gives no health advice")
    return problems
