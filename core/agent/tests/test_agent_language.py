"""Language detection with and without the dots (issue #140, R14). No model, no database."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from agent_fakes import run

from core.agent.guard import detect_language
from core.agent.model import ScriptedModel

ROOT = Path(__file__).resolve().parents[3]

FINNISH_WITHOUT_DOTS = [
    "Haukku minut kulutukseni takia, ole tyly.",   # the six of issue #140
    "Kerro kulutukseni",
    "Saanko tilata pizzan tanaan?",
    "Mista voisin saastaa?",
    "Paljonko kulutin ruokaan viime kuussa?",
    "Mihin rahani menivat?",
    "Mita voin kayttaa talla viikolla?",          # the coordinator's words, typed on a phone
    "Missa rahani ovat?",
    "Kuinka paljon saastan kuukaudessa?",
    "Voinko ostaa uuden puhelimen?",
    "Millainen kuluttaja olen?",
]
ENGLISH = [
    "How much did I spend on restaurants last month?",   # "on" is English too
    "What can I safely spend this week?",
    "Where did my money go?",
    "Tell me something interesting.",
    "What if I cut dining out by 20%?",
    "And taxis in August?",
]


@pytest.mark.parametrize("text", FINNISH_WITHOUT_DOTS)
def test_language_finnish_typed_without_the_dots(text):
    assert detect_language(text) == "fi"
    assert detect_language(text.replace("a", "ä", 1)) == "fi"   # and with them


@pytest.mark.parametrize("text", ENGLISH)
def test_language_english_stays_english(text):
    assert detect_language(text) == "en"


def test_language_of_every_eval_question():
    cases = yaml.safe_load((ROOT / "core/eval/cases.yaml").read_text(encoding="utf-8"))["cases"]
    wrong = [(lang, q) for c in cases for lang, q in c["question"].items() if detect_language(q) != lang]
    assert wrong == []


def test_language_unsure_without_any_function_word():
    assert detect_language("Hello there") is None
    assert detect_language("42") is None


def test_language_the_request_field_wins_over_detection(make_pipeline):
    draft = {"language": "en", "text": "In August 2026 you spent {{n1}}.", "cited": ["n1"], "lesson_key": None}
    from agent_fakes import AS_OF  # noqa: F401 - the fixture's date
    from test_agent_pipeline import SPEND

    events = run(make_pipeline(ScriptedModel(plans=[SPEND], drafts=[draft])), "Paljonko kulutin viime kuussa?",
                 language="en")
    assert dict(events)["meta"]["language"] == "en"
    fi = run(make_pipeline(ScriptedModel(plans=[SPEND], drafts=[{**draft, "language": "fi",
                                                                 "text": "Elokuussa 2026 käytit {{n1}}."}])),
             "Paljonko kulutin viime kuussa?")
    assert dict(fi)["meta"]["language"] == "fi"
