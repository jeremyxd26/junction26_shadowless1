"""Health spending in any language (#570; since #571 a plain health total is answered).

A plain health total is answered with get_spending and the Health filter (Renat, 14 Nov, #571): the rules plan it
themselves in English and Finnish. Anything beyond the total (a what-if, a comparison with people, advice, a guess
about the user's health) stays declined. A question in another language ("Was wäre, wenn ich 20 % weniger für
Medikamente ausgäbe?") is not the rules', so the rules-first model hands it to the model planner, whose prompt ends a
health what-if as the out_of_scope decline. Here the model planner is a scripted stand-in that declines as the prompt
says; the test shows the question reaches it, and that its decline ends the answer with no data call. A message in
Cyrillic with no Latin letter never reaches a planner: the pipeline answers it with "I answer in English or Finnish."
(#484). No database, no key.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_fakes import run

from core.agent.gemini import RulesFirstModel
from core.agent.model import FunctionCall, PlanInput, ScriptedModel
from core.agent.rules import RuleModel, claim

GERMAN_WHAT_IF = "Was wäre, wenn ich 20 % weniger für Medikamente ausgäbe?"
PLANNER = Path(__file__).resolve().parents[1] / "prompts" / "planner.md"
TOOLS = [{"name": t, "description": "", "parameters_json_schema": {}} for t in
         ("get_spending", "get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "run_what_if",
          "get_peer_benchmark")]


class _Client:
    def start_answer(self, request):
        pass


class ScriptedPlanner(ScriptedModel):
    """The model planner's stand-in: what a model following planner.md does with a health what-if."""

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


def test_a_health_what_if_in_another_language_reaches_the_planner_and_is_declined(make_pipeline):
    planner = ScriptedPlanner()
    done = dict(run(make_pipeline(RulesFirstModel(RuleModel(), planner)), GERMAN_WHAT_IF, language="en"))["done"]
    assert planner.questions == [GERMAN_WHAT_IF]               # the rules left it to the model planner
    assert done["outcome"] == "refused" and done["refusal"]["kind"] == "out_of_scope"
    assert done["cited"] == []


@pytest.mark.parametrize("question, language", [
    ("How much did I spend at the pharmacy last month?", "en"),
    ("How much did I spend on medicine in August?", "en"),
    ("Paljonko käytin lääkkeisiin viime kuussa?", "fi"),
    ("Paljonko käytin terveyteen viime kuussa?", "fi"),
])
def test_the_rules_answer_an_english_or_finnish_health_total_with_the_health_filter(question, language):
    found = claim(PlanInput(question=question, language=language, as_of="2026-09-30", tools=TOOLS))
    calls = [c for c in found.calls if c.name != "finish"]
    assert [c.name for c in calls] == ["get_spending"], (question, found)
    assert calls[0].args["filter"] == {"categories": ["Health"]}


def test_the_composer_states_a_health_amount_neutrally():
    composer = (PLANNER.parent / "composer.md").read_text(encoding="utf-8")
    assert "A health amount is stated neutrally: the total and the period, no comment, no tip, no follow-up offer, " \
           "no comparison." in composer
    assert "never names or states a Health amount" not in composer


def test_the_planner_prompt_answers_a_plain_health_total_and_declines_the_rest_in_any_language():
    out_of_scope = next(line for line in PLANNER.read_text(encoding="utf-8").splitlines()
                        if line.strip().startswith("- out_of_scope:"))
    assert "a plain health total is answered with get_spending and the Health filter" in out_of_scope
    assert "a health what-if, a health comparison with peers, health advice and guesses about the user's health " \
           "are declined, in any language or script" in out_of_scope
