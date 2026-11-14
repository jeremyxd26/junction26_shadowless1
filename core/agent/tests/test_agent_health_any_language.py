"""A health spending question is declined in any language (decision on the next prompt PR after #437).

The rules decline English and Finnish health spending questions themselves (#443). A question in another
script ("сколько я трачу на лекарства?") is not theirs, so the rules-first model hands it to the model
planner, whose prompt ends it as the out_of_scope decline. Here the model planner is a scripted stand-in
that declines as the prompt says; the test shows the question reaches it, and that its decline ends the
answer with no data call. The composer's text never names a Health amount (the backstop for a model-planned
answer). No database, no key.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_fakes import run

from core.agent.gemini import RulesFirstModel
from core.agent.model import FunctionCall, ScriptedModel
from core.agent.rules import RuleModel

RUSSIAN = "сколько я трачу на лекарства?"
PLANNER = Path(__file__).resolve().parents[1] / "prompts" / "planner.md"


class _Client:
    def start_answer(self, request):
        pass


class ScriptedPlanner(ScriptedModel):
    """The model planner's stand-in: what a model following planner.md does with a health question."""

    model_id = "scripted"
    planner_prompt = composer_prompt = "scripted"
    client = _Client()

    def unavailable_reason(self, kind=None):
        return None

    def __init__(self):
        super().__init__(plans=[[FunctionCall("decline", {"kind": "out_of_scope"})]])
        self.questions = []

    def plan(self, request):
        self.questions.append(request.question)
        return super().plan(request)


def test_a_health_question_in_another_script_reaches_the_planner_and_is_declined(make_pipeline):
    planner = ScriptedPlanner()
    done = dict(run(make_pipeline(RulesFirstModel(RuleModel(), planner)), RUSSIAN, language="en"))["done"]
    assert planner.questions == [RUSSIAN]                      # the rules left it to the model planner
    assert done["outcome"] == "refused" and done["refusal"]["kind"] == "out_of_scope"
    assert done["cited"] == []


@pytest.mark.parametrize("question, language", [
    ("How much do I spend on medicine?", "en"),
    ("How much did I spend at the pharmacy last month?", "en"),
    ("Paljonko käytän lääkkeisiin?", "fi"),
    ("Paljonko käytin terveyteen viime kuussa?", "fi"),
])
def test_the_rules_decline_english_and_finnish_health_spending_themselves(make_pipeline, question, language):
    planner = ScriptedPlanner()
    done = dict(run(make_pipeline(RulesFirstModel(RuleModel(), planner)), question, language=language))["done"]
    assert planner.questions == [] and done["outcome"] == "refused" and done["refusal"]["kind"] == "out_of_scope"


def test_the_composer_text_never_names_a_health_amount():
    composer = (PLANNER.parent / "composer.md").read_text(encoding="utf-8")
    assert "never names or states a Health amount, also when the user named health" in composer
    assert "mention a Health amount only if" not in composer


def test_the_planner_prompt_declines_health_spending_in_any_language():
    out_of_scope = next(line for line in PLANNER.read_text(encoding="utf-8").splitlines()
                        if line.strip().startswith("- out_of_scope:"))
    assert "health spending" in out_of_scope and "any language or script" in out_of_scope
    assert RUSSIAN in out_of_scope and "never with a data function" in out_of_scope
