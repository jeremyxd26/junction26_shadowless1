"""Missing data (#379, part A): a period outside the data is answered by the template, whoever planned.

The tool reports why it has nothing (period_before_data, period_in_future); an answer that is only that
reason takes a fixed route: outcome "answered", the template's text, chips the rules answer, no compose
request, the same with the model on or off (the coordinator's decision A). No model, no database.
"""

from __future__ import annotations

import re
from datetime import date

import pytest
from agent_fakes import AS_OF, FakeArgs, fake_spending, registry, run

from core.agent import template
from core.agent.model import FunctionCall, PlanInput, ScriptedModel
from core.agent.registry import ToolSpec
from core.agent.rules import RuleModel
from core.agent.validator import Allowed, check_text
from core.tools import config
from core.tools.periods import PeriodOutOfRange, clamp

ALL = ["get_spending", "get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "get_safe_to_save",
       "run_what_if", "get_spender_profile", "get_peer_benchmark", "get_bonus_estimate", "get_balance_forecast"]


@pytest.mark.parametrize("start,end,reason", [
    (date(2023, 1, 1), date(2023, 12, 31), "period_before_data"),
    (date(2024, 9, 1), date(2024, 9, 30), "period_before_data"),
    (date(2026, 10, 1), date(2026, 10, 31), "period_in_future"),
    (date(2027, 3, 1), date(2027, 3, 31), "period_in_future"),
])
def test_a_period_outside_the_data_says_which_side(start, end, reason):
    with pytest.raises(PeriodOutOfRange) as exc:
        clamp(start, end, AS_OF)
    assert exc.value.reason == reason


@pytest.mark.parametrize("reason,lang", [(r, lang) for r in template.MISSING for lang in ("en", "fi")])
def test_each_reason_text_is_short_has_no_number_and_its_chips_are_questions_the_rules_answer(reason, lang):
    text, chips = template.missing_data_answer([], [{"tool": "get_spending", "error": "period_out_of_range",
                                                     "reason": reason}], lang, AS_OF)
    assert text == template.pick(template.MISSING[reason], lang).format(
        end="30.9.2026" if lang == "fi" else "30 September 2026")
    sentences = [x for x in re.split(r"[.?](?=\s+[A-ZÄÖÅ]|\s*$)", text) if x.strip()]
    assert len(text.split()) <= 35 and len(sentences) <= 2
    # The only date in the text is the last day of the data (a returned date); no other digit.
    assert check_text(text, Allowed(frozenset({AS_OF}), frozenset())) == []
    tools = [{"name": t, "description": "", "parameters_json_schema": {}} for t in ALL]
    for chip in chips:
        assert RuleModel().plan(PlanInput(question=chip, language=lang, as_of=AS_OF.isoformat(), tools=tools)).recognised, chip


def test_the_chips_name_the_first_month_of_the_data():
    _, chips = template.missing_data_answer([], [{"reason": "period_before_data"}], "en", AS_OF)
    assert chips[0] == f"How much did I spend in October {config.DATA_START.year}?"
    _, chips = template.missing_data_answer([], [{"reason": "period_before_data"}], "fi", AS_OF)
    assert chips[0] == f"Paljonko käytin lokakuussa {config.DATA_START.year}?"


def test_a_view_with_data_or_an_error_without_a_reason_is_not_a_missing_data_answer():
    assert template.missing_data_answer([{"tool": "x"}], [{"reason": "period_in_future"}], "en", AS_OF) is None
    assert template.missing_data_answer([], [{"error": "tool_failed"}], "en", AS_OF) is None
    assert template.missing_data_answer([], [], "en", AS_OF) is None


def outside(reason: str):
    def tool(ctx, args: FakeArgs):
        raise PeriodOutOfRange("no data", reason=reason)
    return ToolSpec("fake_outside", "A period outside the data.", FakeArgs, tool, ("Looking", "Katson"))


@pytest.mark.parametrize("reason", ["period_in_future", "period_before_data"])
def test_the_pipeline_answers_a_period_outside_the_data_with_the_template_and_no_compose_request(make_pipeline, reason):
    model = ScriptedModel(plans=[[FunctionCall("fake_outside", {}), FunctionCall("finish")]])
    events = run(make_pipeline(model, registry(outside(reason))), "How much did I spend then?", language="en")
    done = dict(events)["done"]
    assert done["outcome"] == "answered" and done["cited"] == [] and done["refusal"] is None
    assert done["text"] == template.missing_data_answer([], [{"reason": reason}], "en", AS_OF)[0]
    assert done["follow_ups"] and model.compose_inputs == []          # the model wrote nothing
    assert "card" not in [e for e, _ in events]                        # nothing to show


def test_a_period_outside_the_data_next_to_real_data_is_written_by_the_composer(make_pipeline):
    draft = {"language": "en", "text": "In August 2026 you spent {{n1}}.", "cited": ["n1"], "lesson_key": None}
    model = ScriptedModel(plans=[[FunctionCall("fake_spending", {}), FunctionCall("fake_outside", {}),
                                  FunctionCall("finish")]], drafts=[draft])
    reg = registry(outside("period_in_future"))
    events = run(make_pipeline(model, reg), "How much did I spend in August and next month?", language="en")
    assert len(model.compose_inputs) == 1
    assert model.compose_inputs[0].errors[0]["reason"] == "period_in_future"   # the composer sees the reason
    assert dict(events)["done"]["outcome"] == "answered"
    assert fake_spending  # the registry's own data tool ran beside it
    # on the rule path the same message is claimed by no rule: the model plans both calls (review of #443)
    tools = [{"name": n, "description": "", "parameters_json_schema": {}} for n in ALL]
    assert not RuleModel().plan(PlanInput(question="How much did I spend in August and next month?", language="en",
                                          as_of=AS_OF.isoformat(), tools=tools)).recognised
