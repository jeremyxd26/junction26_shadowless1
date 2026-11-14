"""#630: a Finnish "how are you" ("Miten sä voit") gets the short warm greeting with the offer, as the English one does,
alone or after hei / moi / terve, with or without ä and ö and the question mark. A greeting next to a real question
is that question; a sentence that merely contains the words keeps its outcome. No model, no database."""

from __future__ import annotations

import pytest
from agent_fakes import run

from core.agent import template
from core.agent.model import FunctionCall, PlanInput, ScriptedModel
from core.agent.rules import claim, meta_intent

FORMS = ["miten sä voit", "miten sinä voit", "miten voit", "kuinka sä voit", "kuinka sinä voit", "kuinka voit",
         "mitä sulle kuuluu", "mitä sinulle kuuluu", "mitä kuuluu", "miten menee", "kuinka menee"]
UNDOTTED = {"ä": "a", "ö": "o", "Ä": "A", "Ö": "O"}


def variants(form):
    for text in (form, form.translate(str.maketrans(UNDOTTED))):
        for lead in ("", "hei ", "Moi, ", "terve "):
            for end in ("", "?"):
                said = f"{lead}{text}{end}"
                yield said[:1].upper() + said[1:]


@pytest.mark.parametrize("message", [v for form in FORMS for v in variants(form)])
def test_every_finnish_how_are_you_is_the_greeting(message):
    assert meta_intent(message) == "greeting", message


@pytest.mark.parametrize("message", ["How are you?", "Hi, how are you doing?", "Miten sa voit", "Moi! Mitä kuuluu?"])
def test_the_greeting_answer_is_the_warm_one_with_the_offer_and_no_model_request(make_pipeline, message):
    model = ScriptedModel(plans=[[FunctionCall("fake_spending", {}), FunctionCall("finish")]])
    events = run(make_pipeline(model), message, language="auto")
    done = dict(events)["done"]
    lang = "en" if message.startswith(("How", "Hi")) else "fi"
    assert done["outcome"] == "answered" and done["refusal"] is None
    assert done["text"] in (template.pick(template.INTRO, lang), template.meta_text("greeting", lang, introduced=True))
    assert done["follow_ups"] == template.brief_questions(lang) and model.plan_inputs == []


TOOLS = [{"name": t, "description": "", "parameters_json_schema": {}} for t in
         ("get_spending", "get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "run_what_if")]


def decided(question, language):
    return claim(PlanInput(question=question, language=language, as_of="2026-09-30", tools=TOOLS))


@pytest.mark.parametrize("message, language", [
    ("Moi, miten menee? Paljonko voin käyttää tällä viikolla?", "fi"),
    ("Hi, how are you? What can I safely spend this week?", "en"),
])
def test_a_greeting_next_to_a_real_question_is_that_question(message, language):
    assert meta_intent(message) is None
    assert [c.name for c in decided(message, language).calls if c.name != "finish"] == ["get_safe_to_spend"]


@pytest.mark.parametrize("message", ["miten voit auttaa naapuriani", "Miten voit auttaa minua säästämään?",
                                     "Mitä kuuluu laskuihini?", "Miten menee kulutukseni tässä kuussa?"])
def test_a_sentence_that_merely_contains_the_words_is_no_greeting(message):
    assert meta_intent(message) is None, message


def test_the_neighbour_question_keeps_its_refusal():
    found = decided("miten voit auttaa naapuriani", "fi")
    assert found.calls and found.calls[0].name == "decline" and found.calls[0].args["kind"] == "other_person_data"


def test_the_finnish_generic_decline_reads_naturally():
    assert template.REFUSAL["out_of_scope"]["text"][1].startswith("Tämä ei kuulu osaamiseeni — olen rahavalmentajasi.")
