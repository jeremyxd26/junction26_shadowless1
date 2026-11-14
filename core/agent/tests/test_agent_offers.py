"""#572 slice 2a: every answered question gets its next step, the listed offer's question first among the chips
(core/agent/offers.py). The answer's text does not change. No model, no database: the rule planner, fake tools
and the scripted model. English and Finnish."""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from agent_fakes import AUG, FakeArgs, registry, run

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


# ---- every chip is a question the system answers with the stated tool and arguments ---------------------------

@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("name", ["save_more", "peer", "safe_to_spend", "forecast", "bills"])
def test_each_chip_is_claimed_with_its_tool_and_arguments(name, language):
    offer = offers.make(name, language)
    assert planned(offer.chip, language) == [(offer.tool, offer.args)], offer.chip
    assert not re.search(r"\d", offer.chip)


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("key", offers.CUT_CATEGORIES)
def test_the_cut_chip_is_claimed_for_each_lever_category_with_the_plans_preset(key, language):
    label = config.label(config.CATEGORY_LABELS[key], language)
    offer = offers.make("cut", language, key=key, label=label, category=label.lower() if language == "en" else label)
    assert planned(offer.chip, language) == [("run_what_if", {"selection": {"kind": "category", "value": key},
                                                              "cut_pct": offers.CUT_PCT})], offer.chip
    assert offers.CUT_PCT == config.SAVINGS_PLAN_FIRST[1] and str(offers.CUT_PCT) in offer.chip


# ---- which chip follows which answer --------------------------------------------------------------------------

def spending(label: str, count: int = 10, total: float = 147.64, labels: list[str] | None = None,
             groups: list | None = None) -> dict:
    labels = labels if labels is not None else [label]
    return {"tool": "get_spending", "period": "August 2026", "filter_parts": len(labels), "filter_labels": labels,
            "total": {"id": "n1", "value": total, "unit": "eur", "label": label},
            "tx_count": {"id": "n2", "value": count, "unit": "count", "label": "Transactions"}, "groups": groups or []}


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("key", offers.CUT_CATEGORIES)
def test_a_lever_category_spending_answer_gets_the_cut_chip(key, language):
    label = config.label(config.CATEGORY_LABELS[key], language)
    offer = offers.choose([spending(label)], language, "How much did I spend?")
    assert offer is not None and offer.key == "cut" and offer.args["selection"]["value"] == key


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("key, count, total, labels, groups", [
    ("Groceries", 10, 147.64, None, None), ("Housing", 10, 147.64, None, None),    # regular essentials: never cut
    ("Utilities", 10, 147.64, None, None), ("Health", 10, 147.64, None, None),     # health: never an offer
    ("Restaurants", config.TOO_FEW_TRANSACTIONS - 1, 147.64, None, None),           # too few purchases
    ("Restaurants", 10, 0, None, None),
    ("Restaurants", 10, 147.64, ["Restaurants", "Travel"], None),                   # two categories
    ("Restaurants", 10, 147.64, [], [{"key": "Restaurants", "label": "Restaurants"}]),   # a breakdown
], ids=["groceries", "housing", "utilities", "health", "too_few", "zero", "two_categories", "breakdown"])
def test_a_spending_answer_outside_the_levers_gets_no_cut_chip(language, key, count, total, labels, groups):
    label = config.label(config.CATEGORY_LABELS[key], language)
    view = spending(label, count=count, total=total, labels=labels, groups=groups)
    assert offers.choose([view], language, "How much did I spend?") is None


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("tool, name", [
    ("get_safe_to_spend", "save_more"), ("get_savings_plan", "peer"), ("get_basket_breakdown", "safe_to_spend"),
    ("get_recurring_bills", "forecast"), ("get_balance_forecast", "bills"), ("run_what_if", "save_more"),
    ("get_peer_benchmark", "save_more")])
def test_each_answer_kind_gets_its_listed_chip_and_tapping_it_asks_something_new(tool, name, language):
    offer = offers.choose([{"tool": tool}], language, "a question")
    assert offer is not None and offer.key == name
    assert offer.tool != tool                                  # never the tool just answered
    assert planned(offer.chip, language)[0][0] != tool         # tapping it does not ask the question just answered


def test_no_chip_when_the_card_already_offers_its_cut_or_the_chip_is_the_question_or_health():
    assert offers.choose([{"tool": "get_peer_benchmark", "offers_cut": True}], "en", "q") is None
    assert offers.choose([{"tool": "get_safe_to_spend"}], "en", "How could I save more?") is None
    assert offers.choose([{"tool": "get_safe_to_spend"}], "en", "how much did I spend at the pharmacy?") is None
    assert offers.choose([], "en", "q") is None


# ---- the chips ------------------------------------------------------------------------------------------------

CHIPS = ["Where did my money go?", "How could I save more?", "What kind of spender am I?"]


def test_the_chip_comes_first_duplicates_go_and_there_are_at_most_three():
    chips = offers.next_step(list(CHIPS), views=[{"tool": "get_safe_to_spend"}], language="en", question="q")
    assert chips == ["How could I save more?", "Where did my money go?", "What kind of spender am I?"]
    assert offers.next_step([], views=[{"tool": "get_safe_to_spend"}], language="en", question="q") == \
        ["How could I save more?"]


@pytest.mark.parametrize("over", [{"outcome": "refused"}, {"outcome": "clarify"}, {"outcome": "fallback"},
                                  {"review_pending": True}])
def test_nothing_changes_on_a_refusal_a_clarifying_question_a_fallback_or_a_pending_review(over):
    args = {"views": [{"tool": "get_safe_to_spend"}], "language": "en", "question": "q", **over}
    assert offers.next_step(list(CHIPS), **args) == CHIPS


# ---- end to end -------------------------------------------------------------------------------------------------

def fake_safe(ctx, args: FakeArgs) -> ToolResult:
    safe = ctx.numbers.register(Number(value=212.5, unit=Unit.EUR, period=AUG, method="safe_to_spend.safe_eur@1",
                                       evidence_ref="ev_aaaaaaaaaaa3", label="Safe to spend",
                                       display=display(Decimal("212.50"), Unit.EUR, ctx.language)))
    view = {"tool": "get_safe_to_spend", "period": AUG.label,
            "safe": {"id": safe.id, "value": safe.value, "unit": "eur", "label": safe.label}, "notes": []}
    return ToolResult(tool="get_safe_to_spend", data={}, card=None, evidence=[safe.evidence_ref], model_view=view)


SAFE = [FunctionCall("get_safe_to_spend", {}), FunctionCall("finish")]
GOOD = {"language": "en", "text": "You can safely spend {{n1}} this week.", "cited": ["n1"], "lesson_key": None}
GOOD_FI = {"language": "fi", "text": "Voit käyttää turvallisesti {{n1}} tällä viikolla.", "cited": ["n1"],
           "lesson_key": None}
BAD = {"language": "en", "text": "You can safely spend about 30 € more.", "cited": [], "lesson_key": None}


def pipe(make_pipeline, drafts):
    reg = registry(ToolSpec("get_safe_to_spend", "Safe to spend.", FakeArgs, fake_safe, ("Looking", "Katson")))
    return make_pipeline(ScriptedModel(plans=[SAFE], drafts=drafts), reg)


@pytest.mark.parametrize("message, language, draft, chip", [
    ("What can I safely spend this week?", "en", GOOD, "How could I save more?"),
    ("Paljonko voin käyttää turvallisesti tällä viikolla?", "fi", GOOD_FI, "Miten voisin säästää enemmän?"),
])
def test_an_answered_question_has_its_next_step_first_and_its_text_unchanged(make_pipeline, message, language,
                                                                             draft, chip):
    done = dict(run(pipe(make_pipeline, [draft]), message=message, language=language))["done"]
    assert done["text"] == draft["text"] and done["follow_ups"][0] == chip
    assert len(done["follow_ups"]) == len(set(done["follow_ups"])) <= 3


def test_a_template_answer_has_its_next_step_too(make_pipeline):
    done = dict(run(pipe(make_pipeline, [BAD, BAD]), message="What can I safely spend this week?",
                    language="en"))["done"]
    assert "llm_unavailable" in done["warnings"] and done["follow_ups"][0] == "How could I save more?"


def test_a_clarifying_question_keeps_its_own_options(make_pipeline):
    ask = [FunctionCall("ask_clarifying_question", {"question": "Which period do you mean?",
                                                    "options": ["This month", "Last month"]})]
    done = dict(run(make_pipeline(ScriptedModel(plans=[ask], drafts=[])), message="How much did I spend?",
                    language="en"))["done"]
    assert done["outcome"] == "clarify" and done["follow_ups"] == [] and done["clarify"]["options"]


# ---- answers outside the planned path: missing data, the glossary (QA's run on dev 5455d87) --------------------

@pytest.mark.parametrize("language, chips", [
    ("en", ["What if I cut restaurants?", "Where did my money go?"]),
    ("fi", ["Mitä arjen kulutukseeni kuuluu?"]),
])
def test_a_missing_data_answer_has_the_breakdown_question_first_and_no_more_chips(language, chips):
    first = offers.make("safe_to_spend", language)   # any listed offer: only to get the language's brief list
    breakdown = ("Where did my money go?", "Mihin rahani menivät?")[language == "fi"]
    out = offers.missing_step(list(chips), language)
    assert out[0] == breakdown and len(out) == len(chips) and len(set(out)) == len(out) and first.chip


def test_an_unknown_thing_answered_with_the_breakdown_keeps_its_own_chips():
    chips = ["What did I spend on restaurants?", "What did I spend on groceries?"]
    assert offers.missing_step(list(chips), "en", breakdown_answered=True) == chips


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("term, name", [("due_date", "bills"), ("reference_number", "bills"), ("e_invoice", "bills"),
                                        ("direct_payment", "bills"), ("budget", "safe_to_spend")])
def test_a_glossary_term_without_an_own_number_has_its_nearest_data_question_first(term, name, language):
    brief = [("Where did my money go?", "Mihin rahani menivät?")[language == "fi"], "b", "c", "d"]
    out = offers.glossary_step(term, list(brief), language)
    offer = offers.make(name, language)
    assert out[0] == offer.chip and len(out) == 4 and planned(offer.chip, language) == [(offer.tool, offer.args)]


def test_interest_has_no_listed_data_question_and_keeps_the_generic_chips():
    assert offers.glossary_step("interest", ["a", "b"], "en") == ["a", "b"]
