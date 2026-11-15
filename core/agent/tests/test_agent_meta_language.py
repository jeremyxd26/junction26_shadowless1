"""Codex re-run: "wait what" and "I'm tired today." got Finnish replies with the Finnish UI. A meta message (confusion,
a feeling, thanks, feedback, "remind me") is answered in the language of its own words. No database."""

from __future__ import annotations

import pytest
from agent_fakes import run
from test_agent_glossary import glossary_registry

from core.agent import guard, template
from core.agent.rules import RuleModel


def done_of(events):
    return dict(events)["done"]


@pytest.mark.parametrize("message, lang", [
    ("wait what", "en"), ("I'm tired today.", "en"), ("thanks a lot", "en"), ("huh", "en"),
    ("täh", "fi"), ("väsyttää", "fi"), ("kiitos paljon", "fi"), ("No kiitos paljon neuvoista.", "fi"),
])
def test_the_meta_language_is_the_messages_own(message, lang):
    assert guard.meta_language(message) == lang, message


@pytest.mark.parametrize("message, expected", [
    ("I'm tired today.", template.FEELINGS[0]),
    ("thanks a lot", template.THANKS[0]),
    ("väsyttää", template.FEELINGS[1]),
    ("kiitos paljon", template.THANKS[1]),
])
def test_with_the_finnish_ui_an_english_meta_message_gets_english(make_pipeline, message, expected):
    done = done_of(run(make_pipeline(RuleModel(), glossary_registry()), message, language="fi"))
    assert done["text_rendered"] == expected, done["text_rendered"]


def test_wait_what_after_a_finnish_answer_is_answered_in_english(make_pipeline):
    pipeline = make_pipeline(RuleModel(), glossary_registry())
    first = run(pipeline, "Paljonko voin turvallisesti käyttää?", language="fi")
    cid = dict(first)["meta"]["conversation_id"]
    done = done_of(run(pipeline, "wait what", language="fi", conversation_id=cid))
    assert done["text_rendered"] == template.CONFUSED[0], done["text_rendered"]
