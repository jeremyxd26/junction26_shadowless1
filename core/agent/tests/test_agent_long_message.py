"""A long message, or several questions in one, is never claimed by the spending rule (#399). No database.

A 429-character question that mentioned rent, eating out and a laptop, and asked where most of the money goes
and what one change would help most, was answered with the sum of Housing and Restaurants. The spending rule now
never claims a message longer than LONG_MESSAGE_CHARS or with more than one question mark: the other rules, or
the model, take it."""

from __future__ import annotations

import pytest

from core.agent.model import PlanInput
from core.agent.rules import LONG_MESSAGE_CHARS, claim, long_message
from core.agent.toolset import KNOWN_TOOLS

TOOLS = [{"name": t.function, "description": "", "parameters_json_schema": {}} for t in KNOWN_TOOLS]
LONG = ("Hi, so I pay rent every month, which is a lot, and I often go out to eat with colleagues after work. In "
        "September I also bought a new laptop for my studies. I would like to understand where most of my money "
        "goes in September and what one change would help me save the most, because I want to put more aside "
        "for a trip next summer.")
LONG_FI = ("Hei, maksan vuokraa joka kuukausi ja syön usein ulkona työkavereiden kanssa töiden jälkeen. Syyskuussa "
           "ostin myös uuden kannettavan opintoja varten. Haluaisin ymmärtää, mihin suurin osa rahoistani menee "
           "syyskuussa ja mikä yksi muutos auttaisi minua säästämään eniten, koska haluan laittaa sivuun matkaa varten.")


def ask(question, language="en"):
    return claim(PlanInput(question=question, language=language, as_of="2026-09-30", tools=TOOLS))


@pytest.mark.parametrize("question,lang", [(LONG, "en"), (LONG_FI, "fi")])
def test_a_long_message_is_never_answered_with_a_sum_of_its_categories(question, lang):
    assert len(question) > LONG_MESSAGE_CHARS and long_message(question)
    found = ask(question, lang)
    assert "spending" not in (found.rule or "").split("+"), found
    assert not [c for c in found.calls if c.name == "get_spending"], found


def test_several_question_marks_keep_the_spending_rule_out():
    found = ask("Where does my money go? And how much did I spend on restaurants in September?")
    assert not [c for c in found.calls if c.name == "get_spending"], found
    assert long_message("How much did I spend? Why?") and not long_message("How much did I spend in September?")


@pytest.mark.parametrize("question,lang,categories", [
    ("How much did I spend on housing and restaurants in September?", "en", ["Restaurants", "Housing"]),
    ("Paljonko käytin asumiseen ja ravintoloihin syyskuussa?", "fi", ["Restaurants", "Housing"]),
])
def test_a_short_question_about_two_categories_is_still_the_spending_question(question, lang, categories):
    found = ask(question, lang)
    assert found.rule == "spending" and sorted(found.calls[0].args["filter"]["categories"]) == sorted(categories)


def test_the_brief_questions_stay_claimed():
    assert ask("Where did my money go?").rule == "where_money_went"
    assert ask("How much did I spend on restaurants last month?").rule == "spending"
