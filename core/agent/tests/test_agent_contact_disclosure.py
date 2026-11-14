"""The way to a human and the AI disclosure in /api/ask (#420, contract 0.3.3). No database.

- Every refusal carries `actions` with the one `open_host_screen` action of target `contact_bank`; other
  answers carry an empty list.
- The first answer of a conversation carries `ai_disclosure` (the overview's text), unless that answer is
  the introduction, which says it itself. A later answer in the same conversation never repeats it; a new
  conversation discloses again.
"""

from __future__ import annotations

import pytest
from agent_fakes import run

from core.agent.model import FunctionCall, ScriptedModel
from core.agent.registry import DeclineKind
from core.app.api import texts as api_texts

SPEND = [FunctionCall("fake_spending", {"category": "Restaurants"}), FunctionCall("finish")]
GOOD = {"language": "en", "text": "In August 2026 you spent {{n1}} on restaurants, over {{n2}} visits.",
        "cited": ["n1", "n2"], "lesson_key": None}
CONTACT = {"en": {"type": "open_host_screen", "label": "Contact S-Pankki", "target": "contact_bank"},
           "fi": {"type": "open_host_screen", "label": "Ota yhteyttä S-Pankkiin", "target": "contact_bank"}}
DISCLOSURE = {"en": api_texts.AI_DISCLOSURE[0], "fi": api_texts.AI_DISCLOSURE[1]}
MESSAGE = {"en": "Tell me something", "fi": "Kerro jotain"}


def done_of(events) -> dict:
    return dict(events)["done"]


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("kind", [k.value for k in DeclineKind])
def test_every_refusal_carries_the_way_to_the_bank(make_pipeline, kind, language):
    pipe = make_pipeline(ScriptedModel(plans=[[FunctionCall("decline", {"kind": kind})]]))
    done = done_of(run(pipe, MESSAGE[language], language=language))
    assert done["outcome"] == "refused" and done["refusal"]["kind"] == kind
    assert done["actions"] == [CONTACT[language]]


def test_a_rule_refusal_carries_it_too(make_pipeline):
    """The rules decline before any model request ("should I buy bitcoin?"): the same action."""
    done = done_of(run(make_pipeline(ScriptedModel()), "Should I invest my savings in bitcoin?", language="en"))
    assert done["outcome"] == "refused" and done["actions"] == [CONTACT["en"]]


def test_a_data_answer_first_discloses_once(make_pipeline):
    pipe = make_pipeline(ScriptedModel(plans=[SPEND, SPEND, SPEND], drafts=[GOOD, GOOD, GOOD]))
    events = run(pipe)
    first = done_of(events)
    assert first["outcome"] == "answered" and first["actions"] == []
    assert first["ai_disclosure"] == DISCLOSURE["en"]
    second = done_of(run(pipe, conversation_id=dict(events)["meta"]["conversation_id"]))
    assert second["ai_disclosure"] is None                                  # never repeated
    other = done_of(run(pipe))                                               # a new conversation
    assert other["ai_disclosure"] == DISCLOSURE["en"]


def test_a_decline_first_discloses_and_the_next_answer_does_not(make_pipeline):
    pipe = make_pipeline(ScriptedModel(plans=[[FunctionCall("decline", {"kind": "out_of_scope"})], SPEND],
                                       drafts=[GOOD]))
    events = run(pipe, "Kerro vitsi", language="fi")
    first = done_of(events)
    assert first["ai_disclosure"] == DISCLOSURE["fi"] and first["actions"] == [CONTACT["fi"]]
    second = done_of(run(pipe, conversation_id=dict(events)["meta"]["conversation_id"]))
    assert second["outcome"] == "answered" and second["ai_disclosure"] is None and second["actions"] == []


def test_the_introduction_first_needs_no_disclosure(make_pipeline):
    pipe = make_pipeline(ScriptedModel(plans=[SPEND], drafts=[GOOD]))
    events = run(pipe, "Hi, who are you?", language="en")
    intro = done_of(events)
    assert intro["ai_disclosure"] is None and intro["actions"] == []        # the introduction says it
    after = done_of(run(pipe, conversation_id=dict(events)["meta"]["conversation_id"]))
    assert after["ai_disclosure"] is None


def test_a_thank_you_first_is_not_the_introduction(make_pipeline):
    done = done_of(run(make_pipeline(ScriptedModel()), "thanks", language="en"))
    assert done["ai_disclosure"] == DISCLOSURE["en"]
