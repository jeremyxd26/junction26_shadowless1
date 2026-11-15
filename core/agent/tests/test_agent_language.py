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
    # The meta questions (#287: "Hi", "Kiitos!", Russian forms) are too short to detect by design; their
    # language comes from the request or the conversation, and a Russian message gets the English text.
    # A case tagged other_language asks in another language on purpose (a health question in Russian is the
    # planner's to decline); it is sent with the answer language of its key.
    wrong = [(lang, q) for c in cases if c["expect"] != "meta" and "other_language" not in (c.get("tags") or [])
             for lang, q in c["question"].items() if detect_language(q) != lang]
    assert wrong == []


def test_language_unsure_without_any_function_word():
    assert detect_language("Hello there") is None
    assert detect_language("42") is None


def test_language_the_question_wins_over_the_request_field(make_pipeline):
    # Renat (15.11 night): the answer speaks the question's language, not the app setting; the request's
    # language is only the fallback for a message the detector is unsure about.
    draft = {"language": "fi", "text": "Elokuussa 2026 käytit {{n1}}.", "cited": ["n1"], "lesson_key": None}
    from agent_fakes import AS_OF  # noqa: F401 - the fixture's date
    from test_agent_pipeline import SPEND

    events = run(make_pipeline(ScriptedModel(plans=[SPEND], drafts=[draft])), "Paljonko kulutin viime kuussa?",
                 language="en")
    assert dict(events)["meta"]["language"] == "fi"
    unsure = run(make_pipeline(ScriptedModel(plans=[SPEND], drafts=[{**draft, "language": "en",
                                                                     "text": "In August 2026 you spent {{n1}}."}])),
                 "42", language="en")
    assert dict(unsure)["meta"]["language"] == "en"
    fi = run(make_pipeline(ScriptedModel(plans=[SPEND], drafts=[{**draft, "language": "fi",
                                                                 "text": "Elokuussa 2026 käytit {{n1}}."}])),
             "Paljonko kulutin viime kuussa?")
    assert dict(fi)["meta"]["language"] == "fi"


@pytest.mark.parametrize("text", ["K-Ruoka spent?", "My Ravintola Savoy bill", "Spending on Lasku app",
                                  "How much at Käpylä store?"])
def test_language_a_finnish_name_inside_an_english_sentence_stays_english(text):
    # Review of PR #195: a capitalised word that does not start a sentence is a name, never Finnish.
    assert detect_language(text) == "en"


def test_language_swedish_with_a_ring_is_unsure_not_finnish():
    assert detect_language("Hur mycket spenderade jag på mat?") is None


def test_language_a_capitalised_word_that_starts_a_sentence_still_counts():
    assert detect_language("Kerro kulutukseni. Paljonko?") == "fi"
    assert detect_language("Paljonko kulutin K-Marketissa?") == "fi"


def test_language_known_limit_swedish_with_dots_reads_as_finnish():
    # Stated in guard.py: a lower-case word with ä or ö counts as Finnish. Pinned so a change is seen.
    assert detect_language("Hur mycket har jag använt på mat?") == "fi"


def test_language_a_finnish_comparison_question():
    assert detect_language("Prisma vai Lidl, kumpi on halvempi?") == "fi"
    assert detect_language("Kumpi on kalliimpi, Prisma vai Lidl?") == "fi"


def test_language_detection_is_linear_in_the_text():
    import time

    text = "How much did I spend on food last month? " * 25_000   # about a million characters
    started = time.perf_counter()
    assert detect_language(text) == "en"
    assert time.perf_counter() - started < 5.0      # was 28 s with the slicing before every word
