"""A short thanks in other words gets the thanks reply (r-talk: "No kiitos paljon neuvoista." got the fallback); a
thanks with a question in it stays a question. No database."""

from __future__ import annotations

import pytest
from agent_fakes import run
from test_agent_glossary import glossary_registry

from core.agent import template
from core.agent.rules import RuleModel, meta_intent


@pytest.mark.parametrize("message", [
    "No kiitos paljon neuvoista.", "Okei kiitti avusta", "Hyvä, kiitoksia", "Kiitos!", "great, thanks for the advice",
    "thank you so much for the help", "ok thanks", "appreciate it",
])
def test_a_short_thanks_is_the_thanks_intent(message):
    assert meta_intent(message) == "thanks", message


@pytest.mark.parametrize("message", [
    "kiitos, mutta paljonko mulla on rahaa?", "kiitos mutta paljonko mulla on rahaa", "Thanks, how much did I spend?",
    "kiitos, kerro lisää säästämisestä", "Thanks for nothing, show my balance",
])
def test_a_thanks_with_a_question_stays_a_question(message):
    assert meta_intent(message) is None, message


def test_renats_sentence_gets_the_thanks_reply(make_pipeline):
    done = dict(run(make_pipeline(RuleModel(), glossary_registry()), "No kiitos paljon neuvoista.", language="fi"))["done"]
    assert done["outcome"] == "answered" and done["text_rendered"] == "Ole hyvä! Kerro, jos haluat jatkaa."
    assert template.THANKS == ("You're welcome! Tell me if you want to continue.", "Ole hyvä! Kerro, jos haluat jatkaa.")


def test_the_question_after_a_thanks_is_answered_as_a_question(make_pipeline):
    done = dict(run(make_pipeline(RuleModel(), glossary_registry()), "kiitos, mutta paljonko mulla on rahaa?",
                    language="fi"))["done"]
    assert done["text_rendered"] != template.THANKS[1]
