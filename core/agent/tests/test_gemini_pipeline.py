"""The answer pipeline with the Gemini model when Gemini fails: the demo must still answer.

Every failure of the adapter (timeout, 429, 503 everywhere, an empty or cut response, invalid JSON
from the composer) must end in an answer from the rule planner and the template, never in an error
or an empty answer. Since #244 such an answer has the outcome "answered" and the warning
`llm_unavailable`. No network, no database: a fake transport and a
fake get_spending tool with fixed numbers.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import pytest

from core.agent.conversation import ConversationStore
from core.agent.gemini import GeminiModel, RulesFirstModel, not_recognised
from core.agent import gemini_client as gc
from core.agent.gemini_client import CallUsage, GeminiClient, Ledger
from core.agent.model import PlanInput
from core.agent.orchestrator import AskRequest, Pipeline
from core.agent.registry import Registry, ToolSpec
from core.agent.rules import RuleModel
from core.agent.tests.test_gemini_client import FakeTransport, api_error, call_response, text_response
from core.tools.models import Number, Period, ToolResult, Unit
from core.tools.spending import GetSpendingArgs

AUGUST = Period(start=date(2026, 8, 1), end=date(2026, 8, 31), label="August 2026")
QUESTION = "How much did I spend on groceries last month?"


def fake_spending(ctx, args):
    total = ctx.numbers.register(Number(value=1146.05, unit=Unit.EUR, period=AUGUST, method="spending.total@1",
                                        evidence_ref="ev_aaaaaaaaaaaa", label="Groceries", display="€1,146.05"))
    count = ctx.numbers.register(Number(value=16, unit=Unit.COUNT, period=AUGUST, method="spending.n_tx@1",
                                        evidence_ref="ev_bbbbbbbbbbbb", label="Transactions", display="16"))
    view = {"tool": "get_spending", "period": "August 2026", "direction": "out",
            "total": {"id": total.id, "value": 1146.05, "unit": "eur", "label": "Groceries"},
            "tx_count": {"id": count.id, "value": 16, "unit": "count", "label": "Transactions"},
            "comparison": None, "groups": [], "notes": []}
    return ToolResult(tool="get_spending", data={}, model_view=view)


class NoDatabase:
    @contextmanager
    def connection(self):
        yield None

    def customer_exists(self, customer_id):
        return True


class Audit:
    def __init__(self):
        self.records = []

    def write(self, record):
        self.records.append(record)


def pipeline(transport) -> tuple[Pipeline, Audit]:
    registry = Registry()
    registry.register(ToolSpec(name="get_spending", description="Spending for a period.", args_model=GetSpendingArgs,
                               fn=fake_spending, status_label=("Looking", "Katson")))
    client = GeminiClient("gemini-3.8-flash", transport, cache="off", fallback_model="gemini-3.1-pro-preview",
                          sleep=lambda s: None)
    audit = Audit()
    return Pipeline(registry, GeminiModel(client), NoDatabase(), as_of=date(2026, 9, 30),
                    store=ConversationStore(), audit=audit), audit


def ask(p: Pipeline, question: str = QUESTION, language: str = "en") -> dict:
    events = []
    p.run(AskRequest(customer_id="CUST00860", message=question, language=language), lambda e, d: events.append((e, d)))
    names = [e for e, _ in events]
    assert "error" not in names, events
    return dict(events)["done"]


class ByKind:
    """A transport that answers planner and composer requests differently."""

    def __init__(self, plan, compose):
        self.plan, self.compose = FakeTransport(plan), FakeTransport(compose)

    def __call__(self, model, contents, config, timeout_s):
        side = self.plan if "tools" in config else self.compose
        return side(model, contents, config, timeout_s)

    @property
    def requests(self):
        return self.plan.requests + self.compose.requests


PLAN_OK = call_response("get_spending", {"period": {"preset": "last_month"}, "filter": {"categories": ["Groceries"]}})
DRAFT_OK = '{"language": "en", "text": "In August 2026 you spent {{n1}} on groceries.", "cited": ["n1"], "lesson_key": null}'


def test_the_happy_path_answers_with_the_model():
    p, audit = pipeline(ByKind(PLAN_OK, text_response(DRAFT_OK)))
    done = ask(p)
    assert done["outcome"] == "answered"
    assert done["text_rendered"] == "In August 2026 you spent €1,146.05 on groceries."
    record = audit.records[-1]
    assert record["model"]["planner_prompt"].startswith("planner@")
    assert record["usage"]["prompt_tokens"] == 1500 and record["usage"]["cost_usd"] > 0


@pytest.mark.parametrize("failure", [
    pytest.param(TimeoutError(), id="timeout"),
    pytest.param(api_error(429), id="429"),
    pytest.param(api_error(503), id="503-everywhere"),
    pytest.param({"candidates": []}, id="empty"),
    pytest.param({"candidates": [{"finish_reason": "MAX_TOKENS", "content": {"parts": []}}]}, id="cut"),
])
def test_a_planner_failure_answers_from_the_rule_planner_and_the_template(failure):
    transport = FakeTransport(failure)
    p, audit = pipeline(transport)
    done = ask(p)
    assert done["outcome"] == "answered" and "llm_unavailable" in done["warnings"]
    assert "€1,146.05" in done["text_rendered"]       # the rule planner ran the tool; the template cites it
    record = audit.records[-1]
    assert any(t.get("source") == "fallback" for t in record["planner_turns"])
    assert len(transport.requests) <= 4                 # at most the 503 chain: 3 on flash + 1 on pro


def test_429_sends_one_request_and_no_retry():
    transport = FakeTransport(api_error(429))
    p, _ = pipeline(transport)
    assert ask(p)["outcome"] == "answered"
    assert ask(p)["outcome"] == "answered"             # the next question, still inside the pause
    assert len(transport.requests) == 1


@pytest.mark.parametrize("compose", [
    pytest.param(text_response("not json"), id="invalid-json"),
    pytest.param(text_response('{"language": "en", "text": "You spent 1146 euros.", "cited": [], "lesson_key": null}'),
                 id="stray-digits"),
    pytest.param(TimeoutError(), id="timeout"),
    pytest.param({"candidates": [{"finish_reason": "MAX_TOKENS", "content": {"parts": [{"text": "{"}]}}]}, id="cut"),
])
def test_a_composer_failure_answers_from_the_template(compose):
    transport = ByKind(PLAN_OK, compose)
    p, audit = pipeline(transport)
    done = ask(p)
    assert done["outcome"] == "answered" and "llm_unavailable" in done["warnings"]
    assert "€1,146.05" in done["text_rendered"] and "1146 euros" not in done["text_rendered"]
    assert len(audit.records[-1]["composer_attempts"]) == 3   # two model drafts, then the template


# ---- the daily budget and the off switch (the dev service is public) -------------------------------

def budget_pipeline(tmp_path, transport, budget: int):
    p, audit = pipeline(transport)
    p.model.client.ledger = Ledger(tmp_path / "requests.jsonl", budget, tmp_path / "model-off")
    return p, audit


def test_the_daily_budget_stops_requests_and_the_fallback_answers(tmp_path):
    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, _ = budget_pipeline(tmp_path, transport, budget=2)
    assert ask(p)["outcome"] == "answered"             # planner + composer: 2 requests
    done = ask(p)
    assert done["outcome"] == "answered" and "€1,146.05" in done["text_rendered"]
    assert len(transport.requests) == 2


def test_a_restart_keeps_the_days_count(tmp_path):
    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, _ = budget_pipeline(tmp_path, transport, budget=3)
    ask(p)
    restarted, _ = budget_pipeline(tmp_path, transport, budget=3)  # a new process, the same ledger file
    assert restarted.model.client.ledger.today() == 2
    assert ask(restarted)["outcome"] == "answered"     # one request left: the planner; the composer is refused
    assert len(transport.requests) == 3


def test_the_off_switch_stops_requests_without_a_restart(tmp_path):
    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, _ = budget_pipeline(tmp_path, transport, budget=100)
    (tmp_path / "model-off").touch()
    assert ask(p)["outcome"] == "answered"
    assert transport.requests == []
    (tmp_path / "model-off").unlink()
    assert ask(p)["outcome"] == "answered"


# ---- rules first ----------------------------------------------------------------------------------------

def rules_first(transport):
    p, audit = pipeline(transport)
    p.model = RulesFirstModel(RuleModel(), p.model)
    return p, audit


def test_a_recognised_question_is_planned_by_the_rules_and_costs_one_request():
    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, audit = rules_first(transport)
    done = ask(p)                                       # "How much did I spend on groceries last month?"
    assert done["outcome"] == "answered"
    assert transport.plan.requests == [] and len(transport.compose.requests) == 1
    assert audit.records[-1]["model"]["planner_prompt"].startswith("rules-first: planner@")


def test_a_rule_refusal_needs_no_request():
    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, _ = rules_first(transport)
    assert ask(p, "Should I put my savings into tech stocks?")["outcome"] == "refused"
    assert transport.requests == []


def test_an_unrecognised_question_goes_to_the_gemini_planner():
    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, _ = rules_first(transport)
    assert ask(p, "Tell me something useful about my groceries")["outcome"] == "answered"
    assert len(transport.plan.requests) == 1 and len(transport.compose.requests) == 1


def test_only_an_unmatched_question_is_not_recognised():
    unknown = RuleModel().plan(PlanInput(question="Tell me something", language="fi", as_of="2026-09-30",
                                         tools=[{"name": "get_spending"}]))
    assert not_recognised(unknown)
    spending = RuleModel().plan(PlanInput(question=QUESTION, language="en", as_of="2026-09-30",
                                          tools=[{"name": "get_spending"}]))
    assert not not_recognised(spending)
    refusal = RuleModel().plan(PlanInput(question="Will the bank approve my mortgage?", language="en",
                                         as_of="2026-09-30", tools=[{"name": "get_spending"}]))
    assert not not_recognised(refusal)


# ---- review fixes: requests per answer ---------------------------------------------------------------

def test_a_hanging_provider_costs_at_most_three_requests_then_pauses():
    transport = FakeTransport(TimeoutError())
    p, _ = pipeline(transport)
    p.model.client.fallback_model = None
    for _ in range(3):
        assert ask(p)["outcome"] == "answered"
    assert len(transport.requests) == 3                   # the failure streak pause stopped the rest


def test_a_503_storm_with_a_fallback_costs_two_requests_then_pauses():
    transport = FakeTransport(api_error(503))
    p, _ = pipeline(transport)
    assert ask(p)["outcome"] == "answered" and ask(p)["outcome"] == "answered"
    assert len(transport.requests) == 2                   # flash, then pro once; then the overload pause


def test_the_rules_first_model_starts_the_answer_for_the_composer_too():
    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, _ = rules_first(transport)
    for _ in range(gc.MAX_REQUESTS_PER_ANSWER + 2):       # many answers, one composer request each
        assert ask(p)["outcome"] == "answered"
    assert len(transport.compose.requests) == gc.MAX_REQUESTS_PER_ANSWER + 2


# ---- #244: the model may not be used; outcome and warning decided in one place -------------------------

def off_pipeline(tmp_path, transport, reason):
    """A rules-first pipeline whose model may not be used for `reason`."""
    p, audit = rules_first(transport)
    client = p.model.client
    client.ledger = Ledger(tmp_path / "requests.jsonl", 0 if reason == "budget0" else 2, tmp_path / "model-off")
    if reason == "off":
        (tmp_path / "model-off").touch()
    elif reason == "budget_used":
        for _ in range(2):                                # two requests already sent in the last 24 hours
            client.ledger.add("plan", "gemini-3.8-flash", "ok", 1, CallUsage())
    elif reason == "pause":
        client._pause(300, "rate_limited")
    return p, audit


@pytest.mark.parametrize("reason, code", [("off", "off"), ("budget0", "budget"), ("budget_used", "budget"),
                                          ("pause", "pause")])
def test_a_recognised_question_is_answered_by_the_template_when_the_model_may_not_be_used(tmp_path, reason, code):
    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, audit = off_pipeline(tmp_path, transport, reason)
    done = ask(p)                                         # "How much did I spend on groceries last month?"
    assert done["outcome"] == "answered" and "llm_unavailable" in done["warnings"]
    assert "€1,146.05" in done["text_rendered"]           # the template of the recognised question
    assert transport.requests == []                       # no model request at all
    assert audit.records[-1]["model_unavailable"] == code


def test_a_used_up_model_window_works_the_same_way():
    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, audit = rules_first(transport)
    events = []
    req = AskRequest(customer_id="CUST00860", message=QUESTION, language="en")
    req.model_allowed = False                             # the field #237 adds to AskRequest (#232)
    p.run(req, lambda e, d: events.append((e, d)))
    done = dict(events)["done"]
    assert done["outcome"] == "answered" and "llm_unavailable" in done["warnings"]
    assert transport.requests == [] and audit.records[-1]["model_unavailable"] == "model_window"


def test_the_template_answer_is_the_same_text_as_the_rule_models():
    off, _ = rules_first(ByKind(PLAN_OK, text_response(DRAFT_OK)))
    off.model.client._pause(300, "rate_limited")
    rules_only, _ = pipeline(FakeTransport(call_response()))
    rules_only.model = RuleModel()
    assert ask(off)["text"] == ask(rules_only)["text"]


def test_a_recognised_question_makes_no_planning_request_when_the_model_is_on():
    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, audit = rules_first(transport)
    done = ask(p)
    assert done["outcome"] == "answered" and "llm_unavailable" not in done["warnings"]
    assert transport.plan.requests == [] and len(transport.compose.requests) == 1
    assert audit.records[-1]["model_unavailable"] is None


def test_an_unrecognised_question_with_the_model_off_gets_the_general_clarifying_question(tmp_path):
    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, audit = off_pipeline(tmp_path, transport, "off")
    done = ask(p, "Tell me something useful about my groceries")
    assert done["outcome"] == "clarify" and done["clarify"] is not None
    assert "llm_unavailable" in done["warnings"] and transport.requests == []


def test_a_rules_refusal_needs_no_warning_when_the_model_is_off(tmp_path):
    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, _ = off_pipeline(tmp_path, transport, "off")
    done = ask(p, "Should I put my savings into tech stocks?")
    assert done["outcome"] == "refused" and "llm_unavailable" not in done["warnings"]


def test_a_failed_model_still_answers_with_the_warning_and_the_reason_error():
    transport = ByKind(PLAN_OK, TimeoutError())
    p, audit = rules_first(transport)
    done = ask(p)
    assert done["outcome"] == "answered" and "llm_unavailable" in done["warnings"]
    assert audit.records[-1]["model_unavailable"] == "error"
