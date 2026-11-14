"""A question about a budget never gets a claim about one (#547). No database.

On the stand, "what was my budget last month" was planned by the model and answered "You did not set a budget for
August 2026, but your total spending was €4,175.17": no tool returned a budget. Sentti keeps no budget that the
customer sets. The rules now ask back for a budget of a past period, with what they can show; a budget for this week
stays the safe-to-spend question. The model-draft checks reject a draft that says the customer set or did not set a
budget, goal or limit when no label in the answer's data names one."""

from __future__ import annotations

import pytest

from core.agent.model import PlanInput
from core.agent.rules import BUDGET_BACK, BUDGET_OPTIONS, BUDGET_OPTIONS_THIS_MONTH, RuleModel, claim
from core.agent.toolset import KNOWN_TOOLS
from core.agent.validator import draft_problems, setting_claim

TOOLS = [{"name": t.function, "description": "", "parameters_json_schema": {}} for t in KNOWN_TOOLS]


def ask(question, language="en"):
    return claim(PlanInput(question=question, language=language, as_of="2026-09-30", tools=TOOLS))


PAST_BUDGET = [
    ("what was my budget last month", "en"), ("What was my budget last month?", "en"),
    ("did I stay within budget in August", "en"), ("Did I stay within my budget in August?", "en"),
    ("Did I go over my budget?", "en"), ("Did I go over my budget last month?", "en"),
    ("Am I over budget this month?", "en"), ("What was my spending limit last month?", "en"),
    ("Mikä oli budjettini viime kuussa?", "fi"), ("Pysyinkö budjetissa elokuussa?", "fi"),
    ("Ylitinkö budjettini?", "fi"), ("Ylitinkö budjettini viime kuussa?", "fi"),
]


@pytest.mark.parametrize("question,lang", PAST_BUDGET)
def test_a_budget_of_a_past_period_is_asked_back_with_what_sentti_can_show(question, lang):
    found = ask(question, lang)
    assert found.rule == "budget", (question, found)
    (call,) = found.calls
    i = 0 if lang == "en" else 1
    options = BUDGET_OPTIONS_THIS_MONTH if "this month" in question else BUDGET_OPTIONS   # the month asked about
    assert call.name == "ask_clarifying_question"
    assert call.args == {"question": BUDGET_BACK[i], "options": list(options[i])}


@pytest.mark.parametrize("question", ["How much did I spend vs my budget this week?",
                                      "Did I go over my budget this week?"])
def test_this_weeks_budget_keeps_its_question_back(question):
    """This week is the safe-to-spend question's week: the two rules still ask which one is meant, as on dev."""
    found = ask(question)
    assert (found.rule, found.reason) == (None, "competing"), (question, found)


@pytest.mark.parametrize("question,lang", PAST_BUDGET[:2] + PAST_BUDGET[8:9])
def test_the_question_back_is_a_recognised_answer_so_the_model_never_plans_it(question, lang):
    result = RuleModel().plan(PlanInput(question=question, language=lang, as_of="2026-09-30", tools=TOOLS))
    assert result.recognised and [c.name for c in result.calls] == ["ask_clarifying_question"], result


@pytest.mark.parametrize("text", BUDGET_BACK)
def test_the_question_back_makes_no_claim_about_a_budget(text):
    assert setting_claim(text) is None


@pytest.mark.parametrize("question,lang", [   # a budget for this week: the safe-to-spend question, as on dev
    ("What is my budget?", "en"), ("How much budget do I have left this week?", "en"),
    ("What's my budget for this week?", "en"), ("Do I have a budget?", "en"),
    ("mikä on budjettini", "fi"), ("Paljonko budjettia on jäljellä tällä viikolla?", "fi"),
    ("Onko minulla budjettia?", "fi"),
])
def test_a_budget_for_this_week_stays_the_safe_to_spend_question(question, lang):
    found = ask(question, lang)
    assert found.rule == "safe_to_spend", (question, found)


@pytest.mark.parametrize("question,lang", [("What is my monthly budget?", "en"), ("Mikä on kuukausibudjettini?", "fi")])
def test_a_monthly_budget_is_left_as_on_dev(question, lang):
    """The safe-to-spend card's own "Your monthly budget allows" is a figure Sentti derives, so the rules do not
    answer this one with "no budget"; the model plans it, and the draft checks keep it from a claim."""
    assert ask(question, lang).rule is None


STAND_DRAFT = "You did not set a budget for August 2026, but your total spending was {{n1}}."


@pytest.mark.parametrize("draft", [
    STAND_DRAFT,
    "You haven't set a savings goal yet, so here is what you spent: {{n1}}.",
    "You set a budget of {{n1}} for August.",
    "No budget was set for August; you spent {{n1}}.",
    "Your budget for August was {{n1}}.",
    "Et asettanut budjettia elokuulle, mutta kulutuksesi oli {{n1}}.",
    "Et ole asettanut säästötavoitetta.",
    "Sinulla ei ole kuukausibudjettia.",
])
def test_a_draft_that_says_a_budget_goal_or_limit_was_set_or_not_is_rejected(draft):
    problems = draft_problems(draft, {}, has_data=True, labels=["Spending", "Kulutus"])
    assert any("budget, goal or limit" in p for p in problems), problems


def test_a_draft_may_name_a_budget_figure_that_the_data_holds():
    """The safe-to-spend card's "Your monthly budget allows" is in the data: naming it is no claim of ours."""
    draft = "Your weekly safe to spend stays {{n1}}: your monthly budget limits it, not your balance."
    assert not draft_problems(draft, {}, has_data=True, labels=["Your monthly budget allows", "Safe to spend"])
    assert setting_claim(STAND_DRAFT, ["Your monthly budget allows"]) is None


@pytest.mark.parametrize("draft", [
    "In August 2026 you spent {{n1}} across {{n2}} transactions.",
    "You can safely spend {{n1}} this week.",
    "Elokuussa 2026 käytit {{n1}}.",
])
def test_a_plain_answer_passes(draft):
    assert setting_claim(draft) is None


# ---- #547, the added criterion: a count token keeps its noun ("across 16." on the dev environment) ----------

@pytest.mark.parametrize("draft", ["In August 2026 you spent {{n1}} across {{n2}}.",
                                   "In August 2026 you spent {{n1}} in {{n2}}.",
                                   "Elokuussa 2026 käytit {{n1}} yhteensä {{n2}}."])
def test_a_count_without_its_noun_is_rejected(draft):
    from test_agent_draft_checks import NUMBERS   # the count Number n2 and the total n1
    assert any("a count keeps its noun" in p for p in draft_problems(draft, NUMBERS, has_data=True)), draft


def test_a_count_with_its_noun_passes():
    from test_agent_draft_checks import NUMBERS
    draft = "In August 2026 you spent {{n1}} across {{n2}} transactions on groceries."
    assert not any("a count keeps its noun" in p for p in draft_problems(draft, NUMBERS, has_data=True))
