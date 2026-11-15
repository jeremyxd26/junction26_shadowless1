"""Bug fixes from the Codex conversation run (Renat's yes after the cutoff): confusion (test 3), "say it more simply"
refers to the last answer (test 11), light emotional lines (test 18), a greeting is never a person's name (test 22).
Rules and templates only. No database."""

from __future__ import annotations

import pytest
from agent_fakes import audit_records, run
from test_agent_glossary import glossary_registry

from core.agent import people, template
from core.agent.rules import RuleModel, meta_intent


def done_of(events):
    return dict(events)["done"]


def conversation(pipeline, messages, language="auto"):
    out, cid = [], None
    for message in messages:
        events = run(pipeline, message, language=language, conversation_id=cid)
        cid = cid or dict(events)["meta"]["conversation_id"]
        out.append(events)
    return out


@pytest.mark.parametrize("message", ["wait what", "what?", "huh", "täh", "häh", "mitä?", "anteeks mitä"])
def test_the_confusion_wordings(message):
    assert meta_intent(message) == "confused", message


def test_confusion_after_an_answer_offers_the_simpler_explanation(make_pipeline):
    pipeline = make_pipeline(RuleModel(), glossary_registry())
    _, en = conversation(pipeline, ["How much is safe to spend?", "wait what"], language="en")
    d = done_of(en)
    assert d["outcome"] == "answered" and d["text_rendered"] == template.CONFUSED[0]
    assert d["follow_ups"] == [template.CONFUSED_CHIP[0]] and not any(e == "card" for e, _ in en)
    _, fi = conversation(pipeline, ["Paljonko voin turvallisesti käyttää?", "täh"], language="fi")
    assert done_of(fi)["text_rendered"] == "Mikä jäi epäselväksi? Selitänkö edellisen vastauksen yksinkertaisemmin?"
    assert done_of(fi)["follow_ups"] == ["Selitä yksinkertaisemmin"]


def test_confusion_with_nothing_said_yet_is_a_greeting(make_pipeline):
    d = done_of(run(make_pipeline(RuleModel(), glossary_registry()), "huh", language="en"))
    assert d["outcome"] == "answered" and d["text_rendered"] != template.CONFUSED[0]


def test_simpler_after_an_answer_in_words_is_talk_mode_not_the_number(make_pipeline):
    pipeline = make_pipeline(RuleModel(), glossary_registry())
    kb, simpler = conversation(pipeline, ["How do I block my card?", "Explain it more simply"], language="en")
    assert done_of(kb)["outcome"] == "answered"
    turns = audit_records(pipeline)[-1]["planner_turns"]
    assert any(t.get("talk") == "understand" for t in turns), turns
    assert not any("explain_number" in t for t in turns)
    assert done_of(simpler)["outcome"] == "answered"


def test_simpler_after_a_number_answer_stays_the_number(make_pipeline):
    pipeline = make_pipeline(RuleModel(), glossary_registry())
    _, simpler = conversation(pipeline, ["Paljonko voin turvallisesti käyttää?", "Selitä yksinkertaisemmin"], language="fi")
    assert done_of(simpler)["text_rendered"].startswith("Tämä luku on käyttövarasi tällä viikolla.")


@pytest.mark.parametrize("message, lang", [("I'm tired", "en"), ("I'm stressed", "en"), ("bad day", "en"),
                                           ("väsyttää", "fi"), ("stressaa", "fi"), ("olen surullinen", "fi")])
def test_a_light_emotional_line_gets_a_kind_line_and_a_soft_offer(make_pipeline, message, lang):
    assert meta_intent(message) == "feelings"
    d = done_of(run(make_pipeline(RuleModel(), glossary_registry()), message, language=lang))
    assert d["outcome"] == "answered" and d["refusal"] is None
    assert d["text_rendered"] == template.pick(template.FEELINGS, lang)
    assert d["follow_ups"] == [template.pick(template.FEELINGS_CHIP, lang)]


@pytest.mark.parametrize("message", ["Moi, what's my spending?", "Hei, what's my spending?", "Okei, what's my spending?",
                                     "Hey, what's my spending?", "Terve, what's my spending?"])
def test_a_greeting_in_front_is_never_a_persons_name(make_pipeline, message):
    assert people.classify(message) is None
    d = done_of(run(make_pipeline(RuleModel(), glossary_registry()), message, language="en"))
    assert d["outcome"] != "refused", d


def test_another_persons_money_is_still_declined():
    assert people.classify("What's Anna's spending?") == people.DECLINE
    assert people.classify("Moi, what's Anna's salary?") == people.DECLINE
