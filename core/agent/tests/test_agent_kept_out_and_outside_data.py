"""A limit the user states is kept through the questions back (#804), and a list of transactions for a period
outside the data is one missing-data answer (#805). No database.

On the stand, "If I cannot reduce rent, what is one realistic way to save more without cutting essentials?" was
asked back "By how much would you like to cut it?" (rent was read as the what-if's selection), and the reply "20%"
went to the model, which cut all everyday spending. "Show my transactions in 2021" was planned by the model, which
said there was no data and added unrelated 2026 totals."""

from __future__ import annotations

import pytest
from agent_fakes import AS_OF, audit_records, registry, run

from core.agent import template
from core.agent.model import PlanInput
from core.agent.registry import ClarifyArgs, ToolSpec
from core.agent.rules import (KEEP_OUT_OPTIONS, KEEP_OUT_WHICH, WHAT_IF_AMOUNT, RuleModel, claim, plan_what_if)
from core.agent.toolset import KNOWN_TOOLS
from core.agent.validator import Allowed, check_text
from core.tools.models import Args
from core.tools.periods import PeriodOutOfRange

TOOLS = [{"name": t.function, "description": "", "parameters_json_schema": {}} for t in KNOWN_TOOLS]
RENT_EN = "If I cannot reduce rent, what is one realistic way to save more without cutting essentials?"
RENT_FI = "Jos en voi vähentää vuokraa, miten voisin säästää enemmän ilman että leikkaan välttämättömistä?"


def chain(messages: list[str], language: str = "en"):
    """The rules' claim of the last message, after each earlier one was answered as the rules planned it: a
    question back is a turn with no calls, as the pipeline stores it."""
    history: list[dict] = []
    for message in messages[:-1]:
        found = claim(PlanInput(question=message, language=language, as_of=AS_OF.isoformat(), tools=TOOLS,
                                history=list(history)))
        calls = [c for c in found.calls if c.name not in ("finish", "ask_clarifying_question")]
        history.append({"question": message, "calls": [{"name": c.name, "args": c.args} for c in calls],
                        "results": []})
    return claim(PlanInput(question=messages[-1], language=language, as_of=AS_OF.isoformat(), tools=TOOLS,
                           history=history))


def only(found, name):
    calls = [c for c in found.calls if c.name != "finish"]
    assert len(calls) == 1 and calls[0].name == name, found
    return calls[0].args


def is_kept_out_question(found, language="en"):
    args = only(found, "ask_clarifying_question")
    assert args == {"question": template.pick(KEEP_OUT_WHICH, language),
                    "options": list(template.pick(KEEP_OUT_OPTIONS, language))}


@pytest.mark.parametrize("question,language", [
    (RENT_EN, "en"), (RENT_FI, "fi"),
    ("How could I save more without cutting rent?", "en"),
    ("If I can't cut groceries, how could I save more?", "en"),
    ("Miten voisin säästää enemmän, paitsi vuokrasta?", "fi"),
])
def test_a_save_more_question_with_a_limit_asks_which_flexible_spending_and_never_cuts_what_was_ruled_out(
        question, language):
    kind, what_if = plan_what_if(question)
    assert kind == "kept_out" and ({"Housing", "Groceries"} & set(what_if["ruled_out"]))
    found = claim(PlanInput(question=question, language=language, as_of=AS_OF.isoformat(), tools=TOOLS))
    assert found.rule == "what_if"
    is_kept_out_question(found, language)


@pytest.mark.parametrize("question,language,left", [
    ("Where can I cut back besides restaurants?", "en", ["Entertainment", "Not sure — show ideas"]),
    ("Miten voisin säästää enemmän ilman että leikkaan ravintoloista?", "fi", ["Viihde", "En tiedä — näytä ideoita"]),
])
def test_a_flexible_category_the_user_ruled_out_is_never_an_option(question, language, left):
    found = claim(PlanInput(question=question, language=language, as_of=AS_OF.isoformat(), tools=TOOLS))
    assert only(found, "ask_clarifying_question")["options"] == left
    # and tapping it anyway asks again, never a cut of it
    again = chain([question, "Restaurants 20%" if language == "en" else "Ravintolat 20 %"], language)
    assert only(again, "ask_clarifying_question")["options"] == left


@pytest.mark.parametrize("language", ["en", "fi"])
def test_the_question_back_fits_the_clarify_schema_and_the_clarify_text_rules(language):
    question, options = template.pick(KEEP_OUT_WHICH, language), list(template.pick(KEEP_OUT_OPTIONS, language))
    ClarifyArgs(question=question, options=options)
    for text in [question, *options]:
        assert check_text(text, Allowed(frozenset({AS_OF}), frozenset())) == [], text


@pytest.mark.parametrize("messages,language", [
    ([RENT_EN, "20%"], "en"), ([RENT_FI, "20 %"], "fi"),
    ([RENT_EN, "Rent 20%"], "en"), ([RENT_EN, "groceries 10%"], "en"), ([RENT_EN, "fuel by half"], "en"),
    ([RENT_FI, "vuokra 20 %"], "fi"),
])
def test_a_cut_with_no_flexible_selection_or_of_what_was_ruled_out_asks_again(messages, language):
    found = chain(messages, language)
    assert found.rule == "what_if"          # the rules answer: never the model's guess at a selection
    is_kept_out_question(found, language)


@pytest.mark.parametrize("messages,language", [
    ([RENT_EN, "20%", "Restaurants"], "en"), ([RENT_EN, "Restaurants", "20%"], "en"),
    ([RENT_FI, "Ravintolat", "20 %"], "fi"), ([RENT_FI, "20 %", "Ravintolat"], "fi"),
    ([RENT_EN, "restaurants 20%"], "en"),
])
def test_a_flexible_selection_and_a_cut_over_the_replies_run_that_what_if(messages, language):
    found = chain(messages, language)
    assert found.rule == "what_if"
    assert only(found, "run_what_if") == {"selection": {"kind": "category", "value": "Restaurants"}, "cut_pct": 20}


@pytest.mark.parametrize("messages,language", [([RENT_EN, "Entertainment"], "en"), ([RENT_FI, "Viihde"], "fi")])
def test_a_flexible_selection_with_no_cut_asks_how_much(messages, language):
    found = chain(messages, language)
    assert found.rule == "what_if"
    assert only(found, "ask_clarifying_question")["question"] == template.pick(WHAT_IF_AMOUNT, language)


@pytest.mark.parametrize("messages,language", [
    ([RENT_EN, "Not sure — show ideas"], "en"), ([RENT_FI, "En tiedä — näytä ideoita"], "fi"),
])
def test_not_sure_is_the_savings_plan_which_cuts_only_flexible_categories(messages, language):
    found = chain(messages, language)
    assert found.rule == "save_more"
    assert only(found, "get_savings_plan") == {}


def test_a_question_of_its_own_after_the_question_back_is_read_as_before():
    found = chain([RENT_EN, "How much did I spend last month?"])
    assert only(found, "get_spending") == {"period": {"preset": "last_month"}}
    assert only(chain([RENT_EN, "Restaurants last month"]), "get_spending") == {
        "filter": {"categories": ["Restaurants"]}, "period": {"preset": "last_month"}}
    for reply in ["How much did I spend?", "How much on restaurants?", "Paljonko käytin?"]:
        found = chain([RENT_EN, reply])
        assert found.rule is None or found.rule != "what_if", (reply, found)


@pytest.mark.parametrize("messages", [
    ["What if I cut rent by 10%?"], ["How could I save more?"], ["How could I save more without a budget?"],
    ["How much did I spend on groceries?", "Restaurants"], ["What if I cut restaurants?", "20%"],
])
def test_without_a_stated_limit_nothing_changes(messages):
    found = chain(messages)
    if messages == ["What if I cut rent by 10%?"]:
        assert only(found, "run_what_if") == {"selection": {"kind": "category", "value": "Housing"}, "cut_pct": 10}
    elif messages == ["How could I save more?"]:
        assert only(found, "get_savings_plan") == {}
    else:
        assert found.rule is None   # as on dev: the next planner, or the general question back


@pytest.mark.parametrize("language,question,reply", [("en", RENT_EN, "20%"), ("fi", RENT_FI, "20 %")])
def test_the_pipeline_sends_the_question_back_verbatim_and_keeps_the_limit_after_the_reply(make_pipeline, language,
                                                                                           question, reply):
    pipe = make_pipeline(RuleModel())
    events = run(pipe, question, language=language)
    done = dict(events)["done"]
    expected = {"question": template.pick(KEEP_OUT_WHICH, language),
                "options": list(template.pick(KEEP_OUT_OPTIONS, language))}
    assert done["outcome"] == "clarify" and done["clarify"] == expected
    again = dict(run(pipe, reply, language=language, conversation_id=dict(events)["meta"]["conversation_id"]))["done"]
    assert again["outcome"] == "clarify" and again["clarify"] == expected
    assert "card" not in [e for e, _ in events]


@pytest.mark.parametrize("question,language", [
    ("Show my transactions in 2021", "en"), ("show me my transactions in 2023", "en"),
    ("Näytä tapahtumani vuonna 2021", "fi"), ("Show my transactions in 2027", "en"),
])
def test_a_list_of_transactions_outside_the_data_is_one_spending_call_for_that_period(question, language):
    found = claim(PlanInput(question=question, language=language, as_of=AS_OF.isoformat(), tools=TOOLS))
    assert found.rule == "spending"
    period = only(found, "get_spending")["period"]
    assert period["preset"] == "custom" and period["start"][:4] == period["end"][:4] == question[-4:]


@pytest.mark.parametrize("question", ["Show my transactions last month", "Show my transactions in August 2026",
                                      "Näytä tapahtumani viime kuussa"])
def test_a_list_of_transactions_inside_the_data_is_read_as_before(question):
    assert claim(PlanInput(question=question, language="en", as_of=AS_OF.isoformat(), tools=TOOLS)).rule is None


@pytest.mark.parametrize("language,first,last", [("en", "October 2024", "September 2026"),
                                                 ("fi", "lokakuusta 2024", "syyskuuhun 2026")])
def test_the_before_data_answer_names_the_data_range_from_the_tools_error(language, first, last):
    errors = [{"tool": "get_spending", "error": "period_out_of_range", "reason": "period_before_data",
               "details": {"first": "2024-10-01", "last": "2026-09-30"}}]
    text, chips = template.missing_data_answer([], errors, language, AS_OF)
    assert first in text and last in text
    assert chips   # periods inside the data, questions the rules answer


class _SpendArgs(Args):
    period: dict | None = None
    filter: dict | None = None


def _before_data(ctx, args: _SpendArgs):
    raise PeriodOutOfRange("no data", reason="period_before_data", first="2024-10-01", last="2026-09-30")


@pytest.mark.parametrize("language,question,first,last", [
    ("en", "Show my transactions in 2021", "October 2024", "September 2026"),
    ("fi", "Näytä tapahtumani vuonna 2021", "lokakuusta 2024", "syyskuuhun 2026"),
])
def test_the_pipeline_answers_transactions_in_2021_once_with_the_range_and_no_other_total(make_pipeline, language,
                                                                                         question, first, last):
    spec = ToolSpec("get_spending", "Spending.", _SpendArgs, _before_data, ("Looking", "Katson"))
    pipe = make_pipeline(RuleModel(), registry(spec))
    events = run(pipe, question, language=language)
    done = dict(events)["done"]
    assert done["outcome"] == "answered" and done["cited"] == [] and done["refusal"] is None
    assert first in done["text"] and last in done["text"]
    assert done["follow_ups"]
    assert "card" not in [e for e, _ in events]      # no totals of another period
    calls = [c for t in audit_records(pipe)[-1]["planner_turns"] for c in t.get("calls") or [] if c["name"] != "finish"]
    assert [c["name"] for c in calls] == ["get_spending"]   # one call, nothing else planned
    assert calls[0]["args"]["period"] == {"preset": "custom", "start": "2021-01-01", "end": "2021-12-31"}
