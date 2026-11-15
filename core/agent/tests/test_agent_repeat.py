"""Renat: asked the same thing again, Sentti said it word for word, as if it tracked nothing. Now the repeat says
so ("Those are the same numbers as a moment ago — want some tips in words instead?"), keeps the answer's first sentence, sends no card again, and turns the chips to a
new angle (another period, more tips). No database."""

from __future__ import annotations

import pytest
from agent_fakes import run
from test_agent_glossary import glossary_registry

from core.agent import template
from core.agent.rules import RuleModel


def done_of(events):
    return dict(events)["done"]


def test_the_same_question_again_says_so_and_offers_a_new_angle(make_pipeline):
    pipeline = make_pipeline(RuleModel(), glossary_registry())
    first = run(pipeline, "How much is safe to spend?", language="en")
    cid = dict(first)["meta"]["conversation_id"]
    again = run(pipeline, "How much is safe to spend?", language="en", conversation_id=cid)
    d1, d2 = done_of(first), done_of(again)
    assert d2["outcome"] == "answered"
    assert d2["text_rendered"].startswith(template.REPEAT_LEAD[0] + " "), d2["text_rendered"]
    first_sentence = d1["text_rendered"].split(". ")[0]
    assert first_sentence in d2["text_rendered"]
    assert template.REPEAT_TIPS[0] in d2["follow_ups"] and d2["lesson"] is None
    assert not any(e == "card" for e, _ in again)


def test_the_same_data_in_finnish_is_a_repeat_too_and_a_first_question_never_is(make_pipeline):
    pipeline = make_pipeline(RuleModel(), glossary_registry())
    first = run(pipeline, "How much is safe to spend?", language="en")
    cid = dict(first)["meta"]["conversation_id"]
    other = done_of(run(pipeline, "Paljonko voin turvallisesti käyttää?", language="fi", conversation_id=cid))
    assert other["text_rendered"].startswith(template.REPEAT_LEAD[1] + " "), other["text_rendered"]
    fresh = done_of(run(make_pipeline(RuleModel(), glossary_registry()), "How much is safe to spend?", language="en"))
    assert not fresh["text_rendered"].startswith(template.REPEAT_LEAD[0])


def test_the_finnish_repeat_lead():
    assert template.REPEAT_LEAD[1] == "Luvut ovat samat kuin hetki sitten \u2014 haluatko vinkkejä sanoin?"
    assert template.repeat_follow_ups("Mihin rahani menivät?", "fi")[:2] == ["Anna vinkkejä säästämiseen",
                                                                            "Paljonko käytin viime kuussa?"]


@pytest.mark.parametrize("i, lang", [(0, "en"), (1, "fi")])
def test_the_tips_chip_is_talk_modes_tips(i, lang):
    from core.agent import talk_mode
    assert talk_mode.trigger(template.REPEAT_TIPS[i]) == "tips", template.REPEAT_TIPS[i]
