"""The orchestrator with the scripted model and fake tools: steps 1 to 7, the rules it enforces
(R1, R3, R4, R6, R12, R15) and the failure modes of agent-core.md section 11. No database."""

from __future__ import annotations

import json

from agent_fakes import CANARY, FakeArgs, FakeData, audit_records, db_down_tool, failing_tool, registry, run

from core.agent.model import FunctionCall, ModelError, ScriptedModel
from core.agent.registry import ToolSpec

SPEND = [FunctionCall("fake_spending", {"category": "Restaurants"}), FunctionCall("finish")]
GOOD = {"language": "en", "text": "In August 2026 you spent {{n1}} on restaurants, over {{n2}} visits.",
        "cited": ["n1", "n2"], "lesson_key": None}


def names(events):
    return [e for e, _ in events]


def test_spending_question_end_to_end(make_pipeline):
    pipe = make_pipeline(ScriptedModel(plans=[SPEND], drafts=[GOOD]))
    events = run(pipe)
    assert names(events) == ["meta", "status", "status", "card", "numbers", "delta", "done"]
    done = dict(events)["done"]
    assert done["outcome"] == "answered" and done["cited"] == ["n1", "n2"]
    assert done["text_rendered"] == "In August 2026 you spent €147.64 on restaurants, over 10 visits."
    numbers = dict(events)["numbers"]["numbers"]
    assert set(numbers) == {"n1", "n2"} and numbers["n1"]["display"] == "€147.64"
    assert numbers["n1"]["evidence_ref"] == "ev_aaaaaaaaaaa1"
    deltas = "".join(p["text"] for e, p in events if e == "delta")
    assert deltas == done["text"]


def test_numbers_event_comes_before_the_first_sentence_that_cites_it(make_pipeline):
    draft = {"language": "en", "text": "Here is August 2026. It cost {{n1}}. There were {{n2}} visits.",
             "cited": ["n1", "n2"], "lesson_key": None}
    events = run(make_pipeline(ScriptedModel(plans=[SPEND], drafts=[draft])))
    stream = [(e, p) for e, p in events if e in ("numbers", "delta")]
    assert [e for e, _ in stream] == ["delta", "numbers", "delta", "numbers", "delta"]
    assert list(stream[1][1]["numbers"]) == ["n1"] and list(stream[3][1]["numbers"]) == ["n2"]


def test_invented_number_is_rejected_retried_then_template(make_pipeline):
    bad = {"language": "en", "text": "You spent {{n1}}, about 30 € more than usual.", "cited": ["n1"], "lesson_key": None}
    model = ScriptedModel(plans=[SPEND], drafts=[bad, bad])
    pipe = make_pipeline(model)
    events = run(pipe)
    done = dict(events)["done"]
    assert done["outcome"] == "fallback" and "llm_unavailable" in done["warnings"]
    assert "30" not in done["text"]                       # the template cites tokens only
    assert len(model.compose_inputs) == 2 and model.compose_inputs[1].validation_errors  # retried with errors
    record = audit_records(pipe)[-1]
    assert [a["validation"] != "ok" for a in record["composer_attempts"][:2]] == [True, True]


def test_retry_succeeds_on_the_second_draft(make_pipeline):
    bad = {"language": "en", "text": "You spent 147.64.", "cited": [], "lesson_key": None}
    done = dict(run(make_pipeline(ScriptedModel(plans=[SPEND], drafts=[bad, GOOD]))))["done"]
    assert done["outcome"] == "answered" and done["cited"] == ["n1", "n2"]


def test_model_cannot_choose_the_customer(make_pipeline):
    calls = [FunctionCall("fake_spending", {"category": "Restaurants", "customer_id": "CUST00002"}),
             FunctionCall("fake_spending", {"filter": {"customer": "CUST00002"}})]
    model = ScriptedModel(plans=[calls, [FunctionCall("finish")]], drafts=[])
    pipe = make_pipeline(model, data=FakeData())
    events = run(pipe)
    assert "card" not in names(events)                     # no data was read
    responses = model.plan_inputs[1].responses
    assert [r.response for r in responses] == [{"error": "customer_argument_not_allowed"}] * 2
    statuses = [c["status"] for t in audit_records(pipe)[-1]["planner_turns"] for c in t["calls"]]
    assert statuses.count("rejected: customer_argument_not_allowed") == 2
    for p in model.plan_inputs:                            # the model never saw the customer id (R4)
        assert "CUST00860" not in json.dumps(p.__dict__, default=str)


def test_unknown_function_goes_back_to_the_model(make_pipeline):
    model = ScriptedModel(plans=[[FunctionCall("transfer_money", {"amount": 500})], SPEND], drafts=[GOOD])
    done = dict(run(make_pipeline(model)))["done"]
    assert model.plan_inputs[1].responses[0].response == {"error": "unknown_function"}
    assert done["outcome"] == "answered"


def test_declined_question_makes_no_data_tool_call(make_pipeline):
    data = FakeData()
    model = ScriptedModel(plans=[[FunctionCall("decline", {"kind": "investment_advice"}),
                                  FunctionCall("fake_spending", {})]])
    pipe = make_pipeline(model, data=data)
    events = run(pipe, "Should I buy tech stocks?")
    done = dict(events)["done"]
    assert done["outcome"] == "refused" and done["refusal"]["kind"] == "investment_advice"
    assert data.connections == 0 and "card" not in names(events)
    assert not any(ch.isdigit() for ch in done["text"])
    calls = audit_records(pipe)[-1]["planner_turns"][0]["calls"]
    assert {c["name"]: c["status"] for c in calls} == {"decline": "ok", "fake_spending": "not_run"}


def test_decline_in_round_two_ends_the_turn(make_pipeline):
    model = ScriptedModel(plans=[[FunctionCall("fake_spending", {})], [FunctionCall("decline", {"kind": "unsafe"})]])
    events = run(make_pipeline(model))
    assert dict(events)["done"]["outcome"] == "refused" and names(events).count("card") == 1


def test_clarifying_question_ends_the_turn(make_pipeline):
    ask = FunctionCall("ask_clarifying_question", {"question": "Which period do you mean?",
                                                   "options": ["This month", "Last month"]})
    events = run(make_pipeline(ScriptedModel(plans=[[ask]])), "How much did I spend?")
    done = dict(events)["done"]
    assert done["outcome"] == "clarify"
    assert done["clarify"] == {"question": "Which period do you mean?", "options": ["This month", "Last month"]}


def test_clarifying_question_with_a_number_is_replaced(make_pipeline):
    ask = FunctionCall("ask_clarifying_question", {"question": "Did you spend 300 euros?", "options": []})
    done = dict(run(make_pipeline(ScriptedModel(plans=[[ask]]))))["done"]
    assert done["clarify"]["question"] == "Which period do you mean?"


def test_tool_error_is_a_normal_answer_with_a_warning(make_pipeline):
    reg = registry(ToolSpec("broken_tool", "Fails.", FakeArgs, failing_tool, ("x", "x")))
    model = ScriptedModel(plans=[[FunctionCall("broken_tool", {}), FunctionCall("fake_spending", {}), FunctionCall("finish")]],
                          drafts=[GOOD])
    pipe = make_pipeline(model, reg=reg)
    events = run(pipe)
    done = dict(events)["done"]
    assert done["outcome"] == "answered" and "tool_failed" in done["warnings"]
    record = json.dumps(audit_records(pipe)[-1])
    assert "secret" not in record and "boom" not in record       # exception text never leaves the process


def test_database_down_is_an_error_event(make_pipeline):
    reg = registry(ToolSpec("db_tool", "Needs the database.", FakeArgs, db_down_tool, ("x", "x")))
    pipe = make_pipeline(ScriptedModel(plans=[[FunctionCall("db_tool", {})]]), reg=reg)
    events = run(pipe)
    assert names(events)[-1] == "error" and "done" not in names(events)
    assert dict(events)["error"]["error"]["code"] == "data_unavailable"
    assert audit_records(pipe)[-1]["outcome"] == "error"


def test_planner_failure_falls_back_to_the_keyword_planner(make_pipeline):
    model = ScriptedModel(plans=[ModelError("quota"), ModelError("quota")])
    events = run(make_pipeline(model), "Should I put my savings into tech stocks?")
    done = dict(events)["done"]
    assert done["outcome"] == "refused" and done["refusal"]["kind"] == "investment_advice"


def test_model_sees_model_views_only_and_the_audit_holds_no_rows(make_pipeline):
    model = ScriptedModel(plans=[[FunctionCall("fake_spending", {})], [FunctionCall("finish")]], drafts=[GOOD])
    pipe = make_pipeline(model)
    run(pipe)
    seen = json.dumps([p.__dict__ for p in model.plan_inputs] + [c.__dict__ for c in model.compose_inputs], default=str)
    assert CANARY not in seen and "ev_aaaaaaaaaaa1" not in seen        # R3: no ids, no evidence refs
    record = json.dumps(audit_records(pipe)[-1])
    assert CANARY not in record and "rows" not in record
    rec = audit_records(pipe)[-1]
    assert rec["text"] and rec["numbers"]["n1"]["evidence_ref"] == "ev_aaaaaaaaaaa1"
    assert set(rec["usage"]) == {"prompt_tokens", "thought_tokens", "output_tokens", "cost_usd"}


def test_conversation_is_bound_to_one_customer(make_pipeline):
    model = ScriptedModel(plans=[SPEND, SPEND], drafts=[GOOD, GOOD])
    pipe = make_pipeline(model)
    first = dict(run(pipe))["meta"]["conversation_id"]
    events = run(pipe, customer_id="CUST00493", conversation_id=first)
    assert dict(events)["meta"]["conversation_id"] != first
    assert "conversation_reset" in dict(events)["done"]["warnings"]
    assert model.plan_inputs[1].history == []                         # earlier results are never reused


def test_at_most_six_data_calls(make_pipeline):
    many = [FunctionCall("fake_spending", {}) for _ in range(5)]
    model = ScriptedModel(plans=[many, many], drafts=[GOOD])
    pipe = make_pipeline(model)
    run(pipe)
    statuses = [c["status"] for t in audit_records(pipe)[-1]["planner_turns"] for c in t["calls"]]
    assert statuses.count("ok") == 6 and statuses.count("not_run: call limit") == 4


def test_finnish_answer_with_finnish_formatting(make_pipeline):
    draft = {"language": "fi", "text": "Elokuussa 2026 ravintoloihin meni {{n1}}.", "cited": ["n1"], "lesson_key": None}
    events = run(make_pipeline(ScriptedModel(plans=[SPEND], drafts=[draft])),
                 "Paljonko käytin ravintoloihin elokuussa 2026?")
    done = dict(events)["done"]
    assert dict(events)["meta"]["language"] == "fi"
    assert done["outcome"] == "answered" and done["text_rendered"] == "Elokuussa 2026 ravintoloihin meni 147,64 €."


def test_independent_calls_of_one_turn_run_in_parallel(make_pipeline):
    import threading

    from agent_fakes import fake_spending

    barrier = threading.Barrier(2, timeout=5)

    def together(ctx, args):
        barrier.wait()  # passes only if the other call runs at the same time
        return fake_spending(ctx, args)

    reg = registry(ToolSpec("other_spending", "Same data, another tool.", FakeArgs, together, ("x", "x")))
    reg.tools["fake_spending"] = ToolSpec("fake_spending", "t", FakeArgs, together, ("x", "x"))
    model = ScriptedModel(plans=[[FunctionCall("fake_spending", {}), FunctionCall("other_spending", {}),
                                  FunctionCall("finish")]], drafts=[GOOD])
    data = FakeData()
    pipe = make_pipeline(model, reg=reg, data=data)
    events = run(pipe)
    assert names(events).count("card") == 2 and data.connections == 2
    calls = audit_records(pipe)[-1]["planner_turns"][0]["calls"]
    assert [c["name"] for c in calls] == ["fake_spending", "other_spending", "finish"]
    assert [c["status"] for c in calls] == ["ok", "ok", "ok"]
    ids = [p["card"]["primary"]["id"] for e, p in events if e == "card"]
    assert ids == ["n1", "n1"]  # one shared registry: the same evidence ref gets the same id in both calls
    assert dict(events)["done"]["outcome"] == "answered"
