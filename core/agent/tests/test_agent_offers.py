"""#572 slice 2: one follow-up offer from the list in code (core/agent/offers.py), and the habit-tip checks of a
model draft. No model, no database: the rule planner, fake tools and the scripted model. English and Finnish."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from agent_fakes import AUG, FakeArgs, audit_records, registry, run

from core.agent import guard, offers
from core.agent.model import FunctionCall, PlanInput, ScriptedModel
from core.agent.registry import ToolSpec
from core.agent.rules import RuleModel
from core.agent.toolset import default_registry
from core.tools import config
from core.tools.formatting import display
from core.tools.models import Number, ToolResult, Unit

TOOLS = default_registry().schemas()


def planned(question: str, language: str):
    plan = RuleModel().plan(PlanInput(question=guard.clean(question), language=language, as_of="2026-09-30",
                                      tools=TOOLS))
    return [(c.name, c.args) for c in plan.calls if c.name != "finish"]


def cut(key: str, language: str) -> offers.Offer:
    label = config.label(config.CATEGORY_LABELS[key], language)
    return offers.make("cut", language, key=key, label=label, category=label.lower() if language == "en" else label)


# ---- every listed offer is one the system can fulfil ----------------------------------------------------

@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("name", ["save_more", "peer", "safe_to_spend", "forecast", "bills"])
def test_each_offers_chip_is_claimed_with_its_tool_and_arguments(name, language):
    offer = offers.make(name, language)
    assert planned(offer.chip, language) == [(offer.tool, offer.args)], offer.chip
    assert not re.search(r"\d", offer.text + offer.chip)


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("key", offers.CUT_CATEGORIES)
def test_the_cut_offer_is_claimed_for_each_lever_category_with_the_plans_preset(key, language):
    offer = cut(key, language)
    assert planned(offer.chip, language) == [("run_what_if", {"selection": {"kind": "category", "value": key},
                                                              "cut_pct": offers.CUT_PCT})], offer.chip
    assert offers.CUT_PCT == config.SAVINGS_PLAN_FIRST[1] and not re.search(r"\d", offer.text)   # the sentence


# ---- which offer follows which answer -------------------------------------------------------------------

def spending(label: str, count: int = 10, total: float = 147.64, labels: list[str] | None = None,
             groups: list | None = None) -> dict:
    labels = labels if labels is not None else [label]
    return {"tool": "get_spending", "period": "August 2026", "filter_parts": len(labels), "filter_labels": labels,
            "total": {"id": "n1", "value": total, "unit": "eur", "label": label},
            "tx_count": {"id": "n2", "value": count, "unit": "count", "label": "Transactions"}, "groups": groups or []}


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("key", offers.CUT_CATEGORIES)
def test_a_lever_category_spending_answer_gets_the_cut_offer(key, language):
    label = config.label(config.CATEGORY_LABELS[key], language)
    offer = offers.choose([spending(label)], language, "How much did I spend?")
    assert offer is not None and offer.key == "cut" and offer.args["selection"]["value"] == key


@pytest.mark.parametrize("view", [
    spending("Groceries"), spending("Housing"), spending("Utilities"),       # regular essentials: never cut
    spending("Health"),                                                      # health: never an offer
    spending("Restaurants", count=config.TOO_FEW_TRANSACTIONS - 1),          # too few purchases
    spending("Restaurants", total=0),
    spending("Restaurants", labels=["Restaurants", "Travel"]),               # two categories
    spending("Spending", labels=[], groups=[{"key": "Restaurants", "label": "Restaurants"}]),   # a breakdown
], ids=["groceries", "housing", "utilities", "health", "too_few", "zero", "two_categories", "breakdown"])
def test_a_spending_answer_outside_the_levers_gets_no_cut_offer(view):
    assert offers.choose([view], "en", "How much did I spend?") is None


@pytest.mark.parametrize("tool, name", [
    ("get_safe_to_spend", "save_more"), ("get_savings_plan", "peer"), ("get_basket_breakdown", "safe_to_spend"),
    ("get_recurring_bills", "forecast"), ("get_balance_forecast", "bills"), ("run_what_if", "save_more"),
    ("get_peer_benchmark", "save_more")])
def test_each_answer_kind_gets_its_listed_offer(tool, name):
    offer = offers.choose([{"tool": tool}], "en", "a question")
    assert offer is not None and offer.key == name and offer.tool != tool


def test_no_offer_when_the_card_already_offers_its_cut_or_the_chip_is_the_question_or_health():
    assert offers.choose([{"tool": "get_peer_benchmark", "offers_cut": True}], "en", "q") is None
    assert offers.choose([{"tool": "get_safe_to_spend"}], "en", "How could I save more?") is None
    assert offers.choose([{"tool": "get_safe_to_spend"}], "en", "how much did I spend at the pharmacy?") is None
    assert offers.choose([], "en", "q") is None


# ---- applying it ----------------------------------------------------------------------------------------

CHIPS = ["Where did my money go?", "How could I save more?", "What kind of spender am I?"]


def test_the_offer_is_the_last_sentence_and_its_chip_comes_first():
    text, chips = offers.apply("You can safely spend {{n1}} this week.", list(CHIPS),
                               views=[{"tool": "get_safe_to_spend"}], language="en", question="q", numbers=1)
    assert text == "You can safely spend {{n1}} this week. Want to see how you could save more?"
    assert chips == ["How could I save more?", "Where did my money go?", "What kind of spender am I?"]


def test_no_room_for_one_more_sentence_means_no_offer():
    long = "One {{n1}}. Two {{n2}}. Three {{n3}}. Four sentences here."
    assert offers.apply(long, list(CHIPS), views=[{"tool": "get_safe_to_spend"}], language="en", question="q",
                        numbers=3) == (long, CHIPS)


def test_a_template_answer_gets_the_chip_but_not_the_sentence():
    text, chips = offers.apply("Template text {{n1}}.", list(CHIPS), views=[{"tool": "get_safe_to_spend"}],
                               language="en", question="q", numbers=1, used_template=True)
    assert text == "Template text {{n1}}." and chips[0] == "How could I save more?"


@pytest.mark.parametrize("over", [{"outcome": "refused"}, {"outcome": "clarify"}, {"outcome": "fallback"},
                                  {"review_pending": True}, {"general_fallback": True}])
def test_nothing_changes_on_a_refusal_a_clarifying_question_a_fallback_a_pending_review_or_the_general_fallback(over):
    args = {"views": [{"tool": "get_safe_to_spend"}], "language": "en", "question": "q", "numbers": 1, **over}
    assert offers.apply("A text {{n1}}.", list(CHIPS), **args) == ("A text {{n1}}.", CHIPS)


def test_a_listed_offer_is_found_at_the_end_of_a_text():
    for text in ("A {{n1}}. Want to see how you could save more?",
                 "B {{n1}}. Haluatko nähdä, paljonko säästäisit vähentämällä luokassa Ravintolat?"):
        rest, offer = offers.strip_offer(text)
        assert offer is not None and rest.endswith("{{n1}}.")
    assert offers.strip_offer("Nothing offered {{n1}}.") == ("Nothing offered {{n1}}.", None)


# ---- the model writes no offer, and the habit tip's rules --------------------------------------------------

@pytest.mark.parametrize("draft", [
    "You spent {{n1}} on restaurants. Want to see what a 50 % cut would save?",      # C3: a model-written offer
    "You spent {{n1}}. Shall I transfer money for you?",                              # C1
    "You spent {{n1}}. Would you like to see your neighbour's spending?",             # C2
    "You spent {{n1}}. I can run get_peer_benchmark for another customer.",           # C4
    "You spent {{n1}}. Learn more at our website?",                                   # C5: a question
    "Käytit {{n1}}. Haluatko nähdä lisää?",
    "Käytit {{n1}}. Jos haluat, voin näyttää luokan ostokset.",
])
def test_a_draft_with_its_own_offer_or_a_question_is_rejected(draft):
    assert any("follow-up offer" in p for p in offers.draft_problems(draft))


@pytest.mark.parametrize("draft", [
    "You spent {{n1}} on restaurants. Try cooking at home on weekdays.",
    "Käytit ravintoloihin {{n1}}. Kokeile kotiruokaa arkisin.",
    "You spent {{n1}} on restaurants in August 2026.",
])
def test_a_plain_answer_or_one_clean_habit_tip_passes(draft):
    assert offers.draft_problems(draft) == []


@pytest.mark.parametrize("draft, problem", [
    ("You saved {{n1}}. A good habit is to put money into an index fund every month.", "investing"),    # B1
    ("You have {{n1}} left. Try a quick loan before payday.", "borrowing"),                              # B2
    ("You have {{n1}} left. Consider taking a car loan instead of saving first.", "borrowing"),         # B3
    ("You spent {{n1}}. Try to sleep more so you spend less on medicine.", "health"),                    # B4
    ("You spent {{n1}}. Consider switching to a cheaper bank.", "product"),                              # B5
    ("You spent {{n1}}. Try a savings app to put money aside.", "product"),                              # B6
    ("Sinulla on {{n1}}. Kokeile pikalainaa ennen palkkapäivää.", "borrowing"),                          # B7
    ("You spent {{n1}}. Try saving a hundred euros a month.", "number"),
    ("You spent {{n1}}. Try cooking at home. Consider walking to work.", "at most one"),
])
def test_a_habit_tip_with_advice_it_may_not_give_is_rejected(draft, problem):
    assert any(problem in p for p in offers.draft_problems(draft)), offers.draft_problems(draft)


def test_no_habit_tip_on_a_health_answer():
    data = [spending("Health")]
    problems = offers.draft_problems("You spent {{n1}} on health. Try to compare prices.", data=data)
    assert problems == ["no habit tip on an answer about health spending"]


def test_an_investment_question_keeps_its_decline_even_as_a_tip():                                     # B8
    assert planned("What is a good fund for beginners? Just a tip.", "en") == [
        ("decline", {"kind": "investment_advice"})]


# ---- end to end: the pipeline appends the offer; the model's own offer is retried -------------------------

def fake_safe(ctx, args: FakeArgs) -> ToolResult:
    safe = ctx.numbers.register(Number(value=212.5, unit=Unit.EUR, period=AUG, method="safe_to_spend.safe_eur@1",
                                       evidence_ref="ev_aaaaaaaaaaa3", label="Safe to spend",
                                       display=display(Decimal("212.50"), Unit.EUR, ctx.language)))
    view = {"tool": "get_safe_to_spend", "period": AUG.label,
            "safe": {"id": safe.id, "value": safe.value, "unit": "eur", "label": safe.label}, "notes": []}
    return ToolResult(tool="get_safe_to_spend", data={}, card=None, evidence=[safe.evidence_ref], model_view=view)


SAFE = [FunctionCall("get_safe_to_spend", {}), FunctionCall("finish")]
GOOD = {"language": "en", "text": "You can safely spend {{n1}} this week.", "cited": ["n1"], "lesson_key": None}
OWN_OFFER = {"language": "en", "text": "You can safely spend {{n1}}. Would you like me to show your savings plan?",
             "cited": ["n1"], "lesson_key": None}
OWN_NUMBER = {"language": "en", "text": "You can safely spend {{n1}}. Want to see a 50 % cut?", "cited": ["n1"],
              "lesson_key": None}


def pipe(make_pipeline, drafts):
    reg = registry(ToolSpec("get_safe_to_spend", "Safe to spend.", FakeArgs, fake_safe, ("Looking", "Katson")))
    return make_pipeline(ScriptedModel(plans=[SAFE], drafts=drafts), reg)


def test_the_pipeline_appends_the_offer_and_puts_its_chip_first(make_pipeline):
    events = run(pipe(make_pipeline, [GOOD]), message="What can I safely spend this week?", language="en")
    done = dict(events)["done"]
    assert done["text"] == "You can safely spend {{n1}} this week. Want to see how you could save more?"
    assert done["text_rendered"].endswith("this week. Want to see how you could save more?")
    assert done["follow_ups"][0] == "How could I save more?"
    assert "".join(p["text"] for e, p in events if e == "delta") == done["text"]


def test_a_draft_with_its_own_offer_is_retried_once_and_the_server_adds_the_listed_one(make_pipeline):
    p = pipe(make_pipeline, [OWN_OFFER, GOOD])
    done = dict(run(p, message="What can I safely spend this week?", language="en"))["done"]
    attempts = audit_records(p)[-1]["composer_attempts"]
    assert len(attempts) == 2 and any("follow-up offer" in e for e in attempts[0]["validation"])
    assert done["text"].endswith("Want to see how you could save more?") and "would you like" not in done["text"].lower()


def test_a_model_written_offer_with_a_number_is_rejected_and_never_reaches_the_answer(make_pipeline):
    p = pipe(make_pipeline, [OWN_NUMBER, GOOD])
    done = dict(run(p, message="What can I safely spend this week?", language="en"))["done"]
    assert audit_records(p)[-1]["composer_attempts"][0]["validation"] != "ok" and "50" not in done["text"]


def test_with_the_template_the_answer_gets_the_chip_and_no_sentence(make_pipeline):
    done = dict(run(pipe(make_pipeline, [OWN_OFFER, OWN_OFFER]), message="What can I safely spend this week?",
                    language="en"))["done"]
    assert "llm_unavailable" in done["warnings"] and "Want to see" not in done["text"]
    assert done["follow_ups"][0] == "How could I save more?"


def test_a_clarifying_question_is_a_template_and_never_meets_the_draft_check(make_pipeline):
    ask = [FunctionCall("ask_clarifying_question", {"question": "Which period do you mean?",
                                                    "options": ["This month", "Last month"]})]
    p = make_pipeline(ScriptedModel(plans=[ask], drafts=[]))
    done = dict(run(p, message="How much did I spend?", language="en"))["done"]
    assert done["outcome"] == "clarify" and done["text"].endswith("?") and done["follow_ups"] == []
    assert audit_records(p)[-1].get("composer_attempts") in (None, [])
