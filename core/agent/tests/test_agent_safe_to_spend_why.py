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


# The review of #574: the why answer is decided where the safe-to-spend rule is, after every decline and guard.
# Kept on purpose: the safe-to-spend question with a why and a low word, and the bare whole message with no
# subject noun ("why so low?", "miksi niin vähän?").
KEEP = WHY + [("Why is my safe to spend lower than last week?", "en"), ("why is my safe to spend so low", "en"),
              ("Why is the amount I can safely spend this week so small?", "en"),
              ("why is my limit lower this week?", "en"), ("Why is my weekly budget so low?", "en"),
              ("why so low?", "en"), ("why is it lower?", "en"), ("miksi se on pieni?", "fi"),
              ("miksi voin käyttää niin vähän tällä viikolla?", "fi"),
              ("miksi turvallisesti käytettävä summa on alhainen?", "fi")]


@pytest.mark.parametrize("question,lang", KEEP)
def test_the_kept_why_questions_are_the_template_answer(question, lang):
    assert ask(question, lang).rule == "safe_to_spend_why" and plan(question, lang).template_answer


DECLINED = ("decline", "", ("decline",))
NOT_CLAIMED = (None, "", ())
BOTH = ("safe_to_spend+recurring_bills", "", ("get_safe_to_spend", "get_recurring_bills", "finish"))
# The rows the first version of #574 took from another rule: each has dev's outcome (rule, reason, calls).
AS_ON_DEV = [
    ("why pharmacy spending lower?", "en", DECLINED),
    ("miksi apteekkikulut ovat pienemmät?", "fi", DECLINED),
    ("why is my health spending so low?", "en", DECLINED),
    # the same decline, now by the health rule before the what-if rule (#571: a scenario about health declines whole)
    ("why is my budget so low, what if I cut doctor visits by 10%?", "en", DECLINED),
    ("miksi budjettini on pieni, mitä jos vähennän lääkärikäyntejä 10 %?", "fi", DECLINED),
    ("why is salary lower?", "en", ("recurring_bills", "", ("get_recurring_bills", "finish"))),
    ("why is income lower?", "en", ("recurring_bills", "", ("get_recurring_bills", "finish"))),
    ("miksi palkka on pieni?", "fi", ("recurring_bills", "", ("get_recurring_bills", "finish"))),
    ("why is balance low?", "en", NOT_CLAIMED),
    ("why is spending lower?", "en", (None, "period", ())),
    ("why is spending less?", "en", (None, "what_if_which", ())),
    ("miksi kulutus on pienempi?", "fi", (None, "period", ())),
    ("why so little interest?", "en", NOT_CLAIMED),
    ("why only 3 purchases?", "en", NOT_CLAIMED),
    ("Why is my overdraft limit so low?", "en", NOT_CLAIMED),
    ("why is my card limit lower?", "en", NOT_CLAIMED),
    ("Why is my credit card limit so low?", "en", NOT_CLAIMED),
    ("Why is my monthly budget lower than last month?", "en", ("spending", "", ("get_spending", "finish"))),
    ("why will my safe to spend be lower next week", "en", ("future", "", ("get_spending", "finish"))),
    ("why was my safe to spend lower in August?", "en", (None, "competing", ())),
    ("Why is my safe to spend lower, and what is my salary?", "en", BOTH),
    ("Why is my safe to spend lower? Also show my largest bills.", "en", BOTH),
    ("Why is my safe to spend lower? And what are my bills?", "en", BOTH),
    ("Why is my safe to spend lower and when is my next payday?", "en", BOTH),
    # a second question about what was spent, or about health, is never dropped for the why answer (follow-up of
    # the review of #574)
    ("Why is my safe to spend so low, and how much did I spend on the pharmacy?", "en", (None, "competing", ())),
    ("Why is my safe to spend so low and what did I spend on doctors?", "en", (None, "competing", ())),
    ("Why is my safe to spend so low, and how much did I spend?", "en", (None, "competing", ())),
    ("Why is my safe to spend so low, and how much did I spend this week?", "en", (None, "competing", ())),
    ("Why is my safe to spend so low when I spent less this week?", "en", (None, "competing", ())),
]


@pytest.mark.parametrize("question,lang,expected", AS_ON_DEV)
def test_declines_guards_other_rules_and_two_questions_keep_their_outcome(question, lang, expected):
    found = ask(question, lang)
    assert (found.rule, found.reason, tuple(c.name for c in found.calls)) == expected
    assert not plan(question, lang).template_answer


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


@pytest.mark.parametrize("v,lang,expected,ids", [   # the exact plain answer, English and Finnish (review of #574)
    (SANNA, "en", "To keep setting aside {{n10}}, about {{n6}} a week is safe to spend, below your usual {{n11}}.",
     ["n10", "n6", "n11"]),
    (SANNA, "fi", "Jotta voit laittaa sivuun {{n10}}, turvallisesti käytettävissä on noin {{n6}} viikossa, alle "
                  "tavallisen {{n11}}.", ["n10", "n6", "n11"]),
    (dict(SANNA, usual_week=None), "en", "You can spend about {{n6}} this week, after setting aside about {{n10}}.",
     ["n6", "n10"]),
    (dict(SANNA, usual_week=None), "fi", "Voit käyttää tällä viikolla noin {{n6}}, kun ensin laitat sivuun noin "
                                         "{{n10}}.", ["n6", "n10"]),
])
def test_the_plain_answer_text_in_both_languages(v, lang, expected, ids):
    assert template.goal_sentence(v, lang) == (expected, ids)
    assert safe_to_spend_problems(expected, [v]) == []
