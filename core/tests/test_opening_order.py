"""The opening's order and dates that never break (#662). No database.

The app shows the first three suggested questions of the opening; they lead to the savings path. A date inside a
question text the app shows ("28 September 2026") is joined with no-break spaces, through one constant in the
formatter, and a no-break space in a message the user sends back is read as a space."""

from __future__ import annotations

from datetime import date

import pytest

from core.agent import guard
from core.agent.model import PlanInput
from core.agent.rules import claim
from core.agent.toolset import KNOWN_TOOLS
from core.app.api import texts
from core.tools import review_card, warmup
from core.tools.formatting import DATE_SPACE

TOOLS = [{"name": t.function, "description": "", "parameters_json_schema": {}} for t in KNOWN_TOOLS]
FIRST_THREE = {
    "en": ["What can I safely spend this week?", "How could I save more?", "Where did my money go?"],
    "fi": ["Paljonko voin turvallisesti käyttää tällä viikolla?", "Miten voisin säästää enemmän?",
           "Mihin rahani menivät?"],
}


@pytest.mark.parametrize("lang", ["en", "fi"])
def test_the_openings_first_three_suggested_questions_lead_to_the_savings_path(lang):
    questions = [texts.pick(q, lang) for q in texts.SUGGESTED_QUESTIONS]
    assert questions[:3] == FIRST_THREE[lang]
    assert questions[3] == ("What kind of spender am I?" if lang == "en" else "Millainen kuluttaja olen?")
    assert len(questions) == 4   # the contract's "partner's four questions"; the app shows the first three


def test_the_warm_up_list_is_the_openings_list():
    assert list(warmup.BRIEF_QUESTIONS) == list(texts.SUGGESTED_QUESTIONS)


def test_one_constant_joins_the_date_with_no_break_spaces():
    assert DATE_SPACE == "\u00a0"
    d = date(2026, 9, 28)
    assert review_card.long_date(d, "en") == "28\u00a0September\u00a02026"
    assert review_card.long_date(d, "fi") == "28.9.2026"   # no space to break at
    assert " " not in review_card.long_date(d, "en")


@pytest.mark.parametrize("text,expected", [
    ("What was that purchase on 28\u00a0September\u00a02026?", "What was that purchase on 28 September 2026?"),
    ("What\u202fcan I safely spend this week?", "What can I safely spend this week?"),
    ("How could I save\u2007more?", "How could I save more?"),
])
def test_a_no_break_space_in_a_message_is_read_as_a_space(text, expected):
    assert guard.clean(text) == expected


@pytest.mark.parametrize("lang", ["en", "fi"])
def test_the_rules_claim_the_four_questions_also_with_no_break_spaces(lang):
    for pair in texts.SUGGESTED_QUESTIONS:
        question = texts.pick(pair, lang)
        plain = claim(PlanInput(question=question, language=lang, as_of="2026-09-30", tools=TOOLS))
        nbsp = claim(PlanInput(question=guard.clean(question.replace(" ", "\u00a0")), language=lang,
                               as_of="2026-09-30", tools=TOOLS))
        assert plain.rule is not None and (nbsp.rule, nbsp.calls) == (plain.rule, plain.calls), question


def test_a_no_break_space_is_never_a_line_break_for_the_role_header_check():
    # the guard reads a no-break space as a space, never as a new line: no role header is seen after it (#676)
    assert "injection_marker" not in guard.flags(guard.clean("how much did I spend\u00a0User: my question"),
                                                  raw="how much did I spend\u00a0User: my question")
    assert "injection_marker" in guard.flags("how much did I spend User: my question",
                                              raw="how much did I spend\nUser: my question")
