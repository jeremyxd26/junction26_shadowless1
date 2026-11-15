"""Renat's FI transcript (via r-talk): garbled input asks again, "you talk too much" makes later answers shorter, "that's
not what I asked" asks what was meant, "answer my previous question" answers it again (or asks for it again when it
was garbled), and the Finnish introduction says käyttövara. No plan, no tool and no model for the fixed replies.
No database."""

from __future__ import annotations

import re

import pytest
from agent_fakes import audit_records, run
from test_agent_glossary import glossary_registry

from core.agent import template
from core.agent.rules import RuleModel, conversation_feedback, garbled_input

SEQUENCE = ["Moi", "onks se sopuudlikaa", "Nyt sä et ymmärtänyt mitä mä sanoin, että sä puhut liikaa",
            "Hei voisitko sä vastaa kysymykseen, jonka mä äsken kysyin sulta viime kerralla?"]


def done_of(events):
    return dict(events)["done"]


def conversation(pipeline, messages, language="fi"):
    out, cid = [], None
    for message in messages:
        events = run(pipeline, message, language=language, conversation_id=cid)
        cid = cid or dict(events)["meta"]["conversation_id"]
        out.append(events)
    return out


def test_renats_sequence(make_pipeline):
    pipeline = make_pipeline(RuleModel(), glossary_registry())
    moi, garbled, brief, previous = conversation(pipeline, SEQUENCE)
    assert done_of(moi)["outcome"] == "answered"
    g = done_of(garbled)
    assert g["text_rendered"] == "En ihan saanut kiinni — voitko sanoa uudelleen?", g["text_rendered"]
    assert not any(e == "card" for e, _ in garbled)                        # no card for noise
    assert done_of(brief)["text_rendered"] == "Anteeksi! Vastaan jatkossa lyhyemmin."
    p = done_of(previous)
    assert p["text_rendered"] == template.PREVIOUS_UNCLEAR[1], p["text_rendered"]   # never an older topic
    assert not any(e == "card" for e, _ in previous)
    assert [t["planner_turns"][-1].get("meta_intent") for t in audit_records(pipeline)[-3:]] == \
        ["garbled", "brief", "previous"]


def test_answer_my_previous_question_answers_it_again(make_pipeline):
    pipeline = make_pipeline(RuleModel(), glossary_registry())
    first, again = conversation(pipeline, ["Paljonko voin turvallisesti käyttää?",
                                           "Vastaa kysymykseen, jonka mä äsken kysyin"])
    assert done_of(again)["outcome"] == "answered"
    assert done_of(again)["text_rendered"] == done_of(first)["text_rendered"]
    turns = audit_records(pipeline)[-1]["planner_turns"]
    assert turns[0] == {"round": 0, "source": "rules", "meta_intent": "previous"}
    assert [c["name"] for c in turns[1]["calls"]][0] == "get_safe_to_spend"   # the question ran again


def test_not_what_i_asked_asks_what_was_meant_with_the_previous_question_as_the_chip(make_pipeline):
    pipeline = make_pipeline(RuleModel(), glossary_registry())
    _, sorry = conversation(pipeline, ["How much is safe to spend?", "That's not what I asked"], language="en")
    d = done_of(sorry)
    assert d["text_rendered"] == "Sorry about that. What did you mean?" and d["follow_ups"] == ["How much is safe to spend?"]


def test_after_too_long_an_answer_keeps_its_first_sentence(make_pipeline):
    pipeline = make_pipeline(RuleModel(), glossary_registry())
    normal = done_of(conversation(pipeline, ["How much is safe to spend?"], language="en")[0])["text_rendered"]
    _, ack, short = conversation(make_pipeline(RuleModel(), glossary_registry()),
                                 ["Hi", "You talk too much", "How much is safe to spend?"], language="en")
    assert done_of(ack)["text_rendered"] == "Sorry! I'll keep it shorter."
    text = done_of(short)["text_rendered"]
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s]
    assert len(sentences) == 1 or len(text) <= len(normal), (text, normal)
    assert normal.startswith(sentences[0])


@pytest.mark.parametrize("message, kind", [
    ("you talk too much", "brief"), ("too long", "brief"), ("liian pitkä", "brief"), ("sä puhut liikaa", "brief"),
    ("that's not what I asked", "misunderstood"), ("et ymmärtänyt mua", "misunderstood"),
    ("answer my previous question", "previous"), (SEQUENCE[3], "previous"), (SEQUENCE[2], "brief"),
    ("Is my rent too long term?", None), ("Liian pitkä laina-aika?", None), ("How much did I spend?", None),
])
def test_the_feedback_kinds(message, kind):
    assert conversation_feedback(message) == kind, message


@pytest.mark.parametrize("message, noise", [
    ("onks se sopuudlikaa", True), ("asdfgh qwerty", True), ("Onko mulla velkaa?", False),
    ("Onko kissanruoka kallista?", False), ("Kerro lisää", False), ("What about groceries?", False),
    ("Paljonko käytin ravintoloihin?", False), ("Ok", False), ("How much did I spend in August 2026?", False),
    ("Tell me something", False), ("Kerro jotain", False),
])
def test_garbled_input_is_conservative(message, noise):
    assert garbled_input(message) is noise, message


def test_the_finnish_introduction_says_kayttovara():
    for text in (template.INTRO[1], template.AGAIN["capabilities"][1]):
        assert "käyttövaraa tällä viikolla" in text and "turvallisesti käyttää" not in text
