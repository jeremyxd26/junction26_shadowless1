"""The answer speaks the question's language, thanks with a few words, "do you understand what we are talking
about?", and the käyttövara chip (Renat's Finnish session, 15.11 night). No database.

- A clear question's language wins over the app setting ("moi" with the UI in English gets Finnish); a short or
  unsure message keeps the previous turn's language, else the app's.
- "Kiitos, hyvä tietää", "kiitti, selvä", "thanks, good to know" are the thanks meta reply.
- "Ymmärrätkö sä, mistä me keskustelemme nyt?" names the previous answer's topic, with its question as the chip;
  with nothing talked about yet it is the greeting-style reply.
- The clarify chips say "What's left to spend this week?" / "Paljonko minulla on käyttövaraa tällä viikolla?",
  and the rules read käyttövara as safe to spend.
"""

from __future__ import annotations

import pytest
from agent_fakes import run

from core.agent import guard, template
from core.agent.model import FunctionCall, PlanInput, ScriptedModel
from core.agent.orchestrator import short_language
from core.agent.rules import claim, meta_intent
from core.agent.toolset import default_registry

SPEND = [FunctionCall("fake_spending", {"category": "Restaurants"}), FunctionCall("finish")]
GOOD = {"language": "en", "text": "In August 2026 you spent {{n1}} on restaurants, over {{n2}} visits.",
        "cited": ["n1", "n2"], "lesson_key": None}


def done_of(events) -> dict:
    return dict(events)["done"]


def test_moi_with_the_app_in_english_gets_finnish(make_pipeline):
    events = run(make_pipeline(ScriptedModel()), "moi", language="en")
    assert dict(events)["meta"]["language"] == "fi"
    assert done_of(events)["text"] == template.pick(template.INTRO, "fi")


@pytest.mark.parametrize("text, expected", [("moi", "fi"), ("Kiitti!", "fi"), ("ok", None), ("hi", None)])
def test_short_finnish_greetings_and_thanks_count_as_finnish(text, expected):
    assert short_language(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("Where did my money go?", "en"),
    ("Paljonko kulutin viime kuussa?", "fi"),
    ("Click to Pay?", None),             # a product name: the app's language decides
    ("Korttini on varastettu", None),    # one English-looking word next to Finnish ones: not clear enough
])
def test_only_a_clear_language_overrides_the_app_setting(text, expected):
    assert guard.confident_language(text) == expected


@pytest.mark.parametrize("text", ["Kiitos, hyvä tietää.", "kiitti, selvä", "thanks, good to know", "Thanks!"])
def test_thanks_with_a_few_words_is_the_thanks_reply(text):
    assert meta_intent(text) == "thanks"


def test_kiitos_hyva_tietaa_gets_the_finnish_thanks_after_an_answer(make_pipeline):
    pipe = make_pipeline(ScriptedModel(plans=[SPEND], drafts=[GOOD]))
    first = run(pipe, language="en")
    conv = dict(first)["meta"]["conversation_id"]
    done = done_of(run(pipe, "Kiitos, hyvä tietää.", language="en", conversation_id=conv))
    assert done["text"] == template.pick(template.THANKS, "fi")


def test_do_you_understand_names_the_previous_topic_with_its_question_as_the_chip(make_pipeline):
    pipe = make_pipeline(ScriptedModel(plans=[SPEND], drafts=[GOOD]))
    conv = dict(run(pipe, language="en"))["meta"]["conversation_id"]
    pipe.store.resolve(conv, "CUST00860")[0].turns[-1]["calls"] = [{"name": "get_savings_plan", "args": {}}]
    done = done_of(run(pipe, "Ymmärrätkö sä, mistä me keskustelemme nyt?", language="en", conversation_id=conv))
    assert done["text"] == "Kyllä — puhuimme säästämisestä. Haluatko, että selitän sen yksinkertaisemmin?"
    assert done["follow_ups"] == ["How much did I spend on restaurants in August 2026?"]
    assert meta_intent("do you understand what we're talking about?") == "context"


def test_do_you_understand_with_nothing_said_yet_is_a_greeting(make_pipeline):
    done = done_of(run(make_pipeline(ScriptedModel()), "Ymmärrätkö sä, mistä me keskustelemme nyt?", language="fi"))
    assert done["outcome"] == "answered" and "puhuimme" not in done["text"]


@pytest.mark.parametrize("question, language", [
    ("What's left to spend this week?", "en"),
    ("Paljonko minulla on käyttövaraa tällä viikolla?", "fi"),
    ("Mikä on käyttövarani tällä viikolla?", "fi"),
])
def test_the_left_to_spend_chips_are_claimed_as_safe_to_spend(question, language):
    found = claim(PlanInput(question=question, language=language, as_of="2026-09-30", tools=default_registry().schemas()))
    assert found.rule == "safe_to_spend"


def test_the_clarify_chips_say_left_to_spend():
    assert "What's left to spend this week?" in template.CLARIFY_GENERAL["options"][0]
    assert "Paljonko minulla on käyttövaraa tällä viikolla?" in template.CLARIFY_GENERAL["options"][1]
    assert not any("turvallisesti" in q for q in template.CLARIFY_GENERAL["options"][1])
