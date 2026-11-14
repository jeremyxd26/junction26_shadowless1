"""Pay yourself first in the rule answers (#552). No database.

"Why is my safe to spend lower / so low / so little", "miksi vähemmän / niin vähän" is a rule answer from the
safe-to-spend view, never the composer model's guess: the limit that binds by name, with the budget side the
savings goal set aside first, and the other side's figure. The plain safe-to-spend answer names the goal. Every
number is a Number of the tool."""

from __future__ import annotations

import pytest
from test_agent_safe_to_spend_checks import BALANCE_BINDS, NO_GOAL, SANNA, view

from core.agent import template
from core.agent.model import PlanInput
from core.agent.rules import RuleModel, claim
from core.agent.toolset import KNOWN_TOOLS
from core.agent.validator import safe_to_spend_problems

TOOLS = [{"name": t.function, "description": "", "parameters_json_schema": {}} for t in KNOWN_TOOLS]


def plan(question, language="en"):
    return RuleModel().plan(PlanInput(question=question, language=language, as_of="2026-09-30", tools=TOOLS))


def ask(question, language="en"):
    return claim(PlanInput(question=question, language=language, as_of="2026-09-30", tools=TOOLS))


WHY = [("why is my safe to spend lower than it was?", "en"), ("Miksi minulla on nyt vähemmän käytettävissä?", "fi"),
       ("Why is my safe to spend so low?", "en"), ("why so little?", "en"), ("miksi niin vähän?", "fi"),
       ("Miksi turvallisesti käytettävä summa on niin pieni?", "fi"), ("Why is safe to spend lower than last week?", "en"),
       ("Why can I only spend so little this week?", "en")]
PLAIN = [("What can I safely spend this week?", "en"), ("Paljonko voin turvallisesti käyttää tällä viikolla?", "fi"),
         ("how much can I spend this week?", "en"), ("is it ok if i spend a bit this week, what's my limit?", "en")]


@pytest.mark.parametrize("question,lang", WHY)
def test_why_lower_is_the_rules_template_answer_never_the_composers(question, lang):
    found = ask(question, lang)
    assert found.rule == "safe_to_spend_why" and [c.name for c in found.calls] == ["get_safe_to_spend", "finish"]
    assert plan(question, lang).template_answer


@pytest.mark.parametrize("question,lang", PLAIN)
def test_the_plain_question_stays_the_safe_to_spend_rule_and_the_composers(question, lang):
    found = ask(question, lang)
    assert found.rule == "safe_to_spend" and not plan(question, lang).template_answer


@pytest.mark.parametrize("question", ["Why did I spend less on groceries in August?", "Why is my rent so high?",
                                      "why did I save less last month?"])
def test_other_why_questions_are_not_the_safe_to_spend_answer(question):
    assert ask(question).rule != "safe_to_spend_why"


@pytest.mark.parametrize("v,lang,expected,cited", [
    (SANNA, "en", "This week {{n6}} is safe to spend because your monthly budget sets the limit, after setting aside "
                  "{{n10}} first. Your balance alone would allow {{n8}}.", ["n6", "n10", "n8"]),
    (SANNA, "fi", "Tällä viikolla turvallisesti käytettävissä on {{n6}}, koska kuukausibudjettisi asettaa rajan, kun "
                  "ensin laitat sivuun {{n10}}. Saldosi yksin sallisi {{n8}}.", ["n6", "n10", "n8"]),
    (NO_GOAL, "en", "This week {{n6}} is safe to spend because your monthly budget sets the limit. Your balance alone "
                    "would allow {{n8}}.", ["n6", "n8"]),
    (BALANCE_BINDS, "en", "This week {{n6}} is safe to spend because your balance sets the limit, after the bills and "
                          "reserves before payday. Your monthly budget would allow {{n9}}.", ["n6", "n9"]),
    (BALANCE_BINDS, "fi", "Tällä viikolla turvallisesti käytettävissä on {{n6}}, koska saldosi asettaa rajan, kun ennen "
                          "palkkapäivää erääntyvät laskut ja varaukset on otettu huomioon. Kuukausibudjettisi sallisi "
                          "{{n9}}.", ["n6", "n9"]),
])
def test_the_why_answer_names_the_binding_limit_and_the_goal(v, lang, expected, cited):
    text, ids = template.why_lower_sentence(v, lang)
    assert (text, ids) == (expected, cited)
    assert safe_to_spend_problems(text, [v]) == []          # the template passes the model-draft check


def test_equal_limits_say_both_set_the_same_limit():
    equal = view(binding="balance", goal=0.0, safe=100.0, balance_limit=100.0, budget_limit=100.0)
    text, ids = template.why_lower_sentence(equal, "en")
    assert ids == ["n6"] and "set the same limit" in text


@pytest.mark.parametrize("v", [SANNA, NO_GOAL, BALANCE_BINDS])
@pytest.mark.parametrize("question,lang", [WHY[0], WHY[1], PLAIN[0], PLAIN[1]])
def test_the_template_answer_passes_the_checks_and_never_says_a_zero_goal(v, question, lang):
    draft = template.template_draft([v], [], lang, None, question)
    assert safe_to_spend_problems(draft["text"], [v]) == [], draft["text"]
    if v is NO_GOAL:
        assert "{{n10}}" not in draft["text"]


def test_the_plain_answer_names_the_goal_even_without_the_usual_pace():
    v = dict(SANNA, usual_week=None)
    text, ids = template.goal_sentence(v, "en")
    assert ids == ["n6", "n10"] and "{{n10}}" in text
