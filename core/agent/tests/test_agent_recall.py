"""'What did I ask? Can you remind me?' (Renat, via r-coord): the previous question and the topic of its answer, then
"Want to continue?", from the conversation alone; with nothing asked yet, the question back. No plan, no tool, no
model and never the fallback text. No database."""

from __future__ import annotations

import pytest
from agent_fakes import audit_records, run
from test_agent_glossary import glossary_registry

from core.agent import template
from core.agent.rules import RuleModel, meta_intent

RENAT = "Okei, mitä se siis mitä mä kysyin? Voitko muistuttaa mulle?"


def done_of(events):
    return dict(events)["done"]


@pytest.mark.parametrize("question", [
    RENAT, "What did I ask?", "Remind me", "Can you remind me what I asked?", "What were we talking about?",
    "What was my last question?", "Mitä mä kysyin?", "Muistuta mua", "Mistä puhuttiin?",
    "Voitko muistuttaa minua mistä puhuttiin?",
])
def test_the_recall_phrasings(question):
    assert meta_intent(question) == "recall", question


@pytest.mark.parametrize("question", [
    "What did I spend on restaurants?", "Remind me to pay rent", "Mitä mä kysyin eilen ravintoloista",
    "Do you understand what we're talking about?",
])
def test_a_question_of_its_own_is_no_recall(question):
    assert meta_intent(question) != "recall", question


def test_renats_message_restates_the_previous_question_in_finnish(make_pipeline):
    pipeline = make_pipeline(RuleModel(), glossary_registry())
    first = run(pipeline, "Paljonko voin turvallisesti käyttää?", language="fi")
    assert done_of(first)["outcome"] == "answered"
    conversation_id = dict(first)["meta"]["conversation_id"]
    done = done_of(run(pipeline, RENAT, language="fi", conversation_id=conversation_id))
    assert done["outcome"] == "answered" and done["clarify"] is None and done["cited"] == []
    assert done["text_rendered"] == ("Kysyit: ”Paljonko voin turvallisesti käyttää?”. Puhuimme käyttövarastasi. "
                                     "Jatketaanko?"), done["text_rendered"]
    assert template.pick(template.NOT_WORKED_OUT, "fi") not in done["text_rendered"]
    assert done["follow_ups"] == ["Paljonko voin turvallisesti käyttää?"]
    assert audit_records(pipeline)[-1]["planner_turns"] == [{"round": 1, "source": "rules", "meta_intent": "recall"}]


def test_in_english_after_a_thanks_the_question_before_it(make_pipeline):
    pipeline = make_pipeline(RuleModel(), glossary_registry())
    first = run(pipeline, "How much is safe to spend?", language="en")
    conversation_id = dict(first)["meta"]["conversation_id"]
    run(pipeline, "Thanks", language="en", conversation_id=conversation_id)
    done = done_of(run(pipeline, "What did I ask?", language="en", conversation_id=conversation_id))
    assert done["text_rendered"] == ("You asked: “How much is safe to spend?”. We talked about what is left "
                                     "to spend this week. Want to continue?")


def test_with_nothing_asked_yet_it_asks_what_to_talk_about(make_pipeline):
    done = done_of(run(make_pipeline(RuleModel(), glossary_registry()), "What did I ask?", language="en"))
    assert done["outcome"] == "answered"
    assert done["text_rendered"] == "We haven't talked about anything yet. What would you like to know?"
    assert len(done["follow_ups"]) >= 1


def test_a_question_with_digits_is_named_by_its_topic_not_quoted():
    turns = [{"question": "How much did I spend in August 2026?", "calls": [{"name": "get_spending", "args": {}}],
              "views": [], "answer": "You spent [number] in August."}]
    text, chip = template.recall_text(turns, "en", lambda q: meta_intent(q) is not None)
    assert text == "You asked about your spending. Want to continue?" and chip == "How much did I spend in August 2026?"
    turns[0]["calls"] = []
    assert template.recall_text(turns, "fi", lambda q: False)[0] == "Kysyit raha-asioistasi. Jatketaanko?"


def test_an_answer_in_words_gets_its_first_sentence_as_the_gist():
    """Codex re-run, test 35: "What did I ask?" named the question but not what the answer said."""
    turns = [{"question": "Miksi mun pitäisi säästää?", "calls": [], "views": [], "words": True,
              "answer": "Säästäminen antaa puskurin yllätyksiin. Lisäksi se tuo rauhaa."}]
    text, chip = template.recall_text(turns, "en", lambda q: meta_intent(q) is not None)
    assert text == ("You asked: \u201cMiksi mun pitäisi säästää?\u201d. In short, I said: \u201cSäästäminen antaa "
                    "puskurin yllätyksiin.\u201d Want to continue?"), text
    assert chip == "Miksi mun pitäisi säästää?"
    turns[0]["answer"] = "You keep [number] for surprises."
    assert "In short" not in template.recall_text(turns, "en", lambda q: False)[0]   # hidden numbers: no gist
