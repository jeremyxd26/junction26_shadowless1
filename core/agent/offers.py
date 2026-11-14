"""The answer's next step (#572, slice 2a): the first chip of every answered question is one listed follow-up offer.

The server picks at most one offer from OFFERS, by the answer's own tools and data (FOLLOWS, and the category rule
of "cut"), and puts its question first in `follow_ups`, the chips the app already shows: tapping it asks that
question, and the rule planner claims each of them with the tool and arguments listed here (tests). The answer's
text does not change, and nothing else of the contract does.

- The one preset of an offer, the what-if's cut, is the savings plan's own (config.SAVINGS_PLAN_FIRST): a chip's
  digit comes from config, never from the model.
- "cut" only for the categories a what-if may cut (the savings plan's levers), never Groceries or another regular
  essential, never Health, never with fewer purchases than config.TOO_FEW_TRANSACTIONS.
- No offer: health, an answer whose own card already offers the next step (the peer card's cut), an offer whose
  tool is the one just answered or whose question is the one just asked, and an answer with a pending review card
  (the review is the next step there). Only answered questions on the planned path get one: refusals, clarifying
  questions, missing-data answers, the introduction and the review-amount answer keep their own chips.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core.agent import template
from core.agent.guard import fold
from core.agent.rules import HEALTH
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
    text: str                    # the offer as a sentence (slice 2b appends it; unused here)
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


def choose(views: list[dict[str, Any]], language: str, question: str) -> Offer | None:
    """The one offer that fits the answer, or None."""
    data = [v for v in views or [] if isinstance(v, dict) and v.get("tool")]
    if not data or _health(data, question):
        return None
    first = data[0]
    if first.get("offers_cut"):
        return None                           # the peer card already offers its cut (#418)
    key = FOLLOWS.get(str(first.get("tool")))
    if key == "cut":
        found = _category(first, language)
        if found is None:
            return None
        offer = make("cut", language, key=found[0], label=found[1],
                     category=found[1].lower() if language == "en" else found[1])
    else:
        offer = make(key, language) if key else None
    if offer is None or any(v.get("tool") == offer.tool for v in data):
        return None                           # never the tool just answered
    if offer.chip.strip().lower() == question.strip().lower():
        return None                           # never the question just asked
    return offer


def _first(chip: str, follow_ups: list[str]) -> list[str]:
    """The chip first, duplicates removed, and no more chips than the answer had (at least one)."""
    rest = [f for f in follow_ups if f.strip().lower() != chip.strip().lower()]
    return ([chip] + rest)[:max(len(follow_ups), 1)]


def next_step(follow_ups: list[str], *, views: list[dict[str, Any]], language: str, question: str,
              outcome: str = "answered", review_pending: bool = False) -> list[str]:
    """The chips with the offer's question first, or unchanged when no offer fits, the answer is not an answered
    question, or a review card is pending."""
    if outcome != "answered" or review_pending:
        return follow_ups
    offer = choose(views, language, question)
    return follow_ups if offer is None else _first(offer.chip, follow_ups)


# A missing-data answer (#379): its next step is the breakdown of what there is, unless the answer is that breakdown
# (an unknown thing answered with the customer's own categories).
def missing_step(follow_ups: list[str], language: str, *, breakdown_answered: bool = False) -> list[str]:
    if breakdown_answered:
        return follow_ups
    return _first(_pick(template.BRIEF_QUESTIONS[0], language), follow_ups)


# Glossary terms without a Number of the customer's own (#568): their nearest data question first. Interest has no
# listed data question, so it keeps the generic chips (the QA run on dev 5455d87).
GLOSSARY_FOLLOWS = {"due_date": "bills", "reference_number": "bills", "e_invoice": "bills",
                    "direct_payment": "bills", "budget": "safe_to_spend"}


def glossary_step(term: str, follow_ups: list[str], language: str) -> list[str]:
    name = GLOSSARY_FOLLOWS.get(term)
    return follow_ups if name is None else _first(make(name, language).chip, follow_ups)
