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

def test_a_hanging_provider_costs_one_request_an_answer_and_pauses_no_one():
    transport = FakeTransport(TimeoutError())
    p, _ = pipeline(transport)
    p.model.client.fallback_model = None
    for _ in range(3):
        assert ask(p)["outcome"] == "answered"
    # Per answer one planner request and no retry; after a planner failure the template writes, with no
    # composer request; and no pause for the next answer (#341).
    assert len(transport.requests) == 3 and p.model.client.unavailable_reason() is None


def test_a_composer_timeout_writes_the_template_with_one_composer_request():
    """#341: after a composer timeout the template writes at once; no second composer request waits for
    the rest of the answer's deadline."""
    transport = ByKind(PLAN_OK, TimeoutError())
    p, audit = pipeline(transport)
    done = ask(p)
    assert done["outcome"] == "answered" and "llm_unavailable" in done["warnings"]
    assert len(transport.compose.requests) == 1
    assert audit.records[-1]["model_unavailable"] == "error"


def test_a_503_storm_with_a_fallback_costs_two_requests_an_answer_and_pauses_no_one():
    transport = FakeTransport(api_error(503))
    p, _ = pipeline(transport)
    assert ask(p)["outcome"] == "answered" and ask(p)["outcome"] == "answered"
    # Per answer: the planner on flash, then pro, no retry; then the template writes; no pause (#341).
    assert len(transport.requests) == 4 and p.model.client.unavailable_reason() is None


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
    assert not done["clarify"]["question"].startswith("I could not")   # the model is off, not failed (#341)


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


def test_when_even_the_template_fails_the_outcome_is_fallback(tmp_path, monkeypatch):
    from core.agent import template as tmpl

    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, audit = off_pipeline(tmp_path, transport, "off")
    monkeypatch.setattr(tmpl, "template_draft", lambda *a, **k: {"language": "en", "text": "You spent 1146 euros.",
                                                                   "cited": [], "lesson_key": None})
    done = ask(p)
    assert done["outcome"] == "fallback" and "llm_unavailable" in done["warnings"]
    assert "1146" not in done["text_rendered"] and transport.requests == []


def test_without_a_key_the_rule_models_answer_carries_the_warning():
    p, audit = pipeline(FakeTransport(call_response()))
    p.model = RuleModel()                                 # the service without GEMINI_API_KEY
    done = ask(p)
    assert done["outcome"] == "answered" and "llm_unavailable" in done["warnings"]
    assert "€1,146.05" in done["text_rendered"] and audit.records[-1]["model_unavailable"] == "no_model"
    refusal = ask(p, "Should I put my savings into tech stocks?")
    assert refusal["outcome"] == "refused" and "llm_unavailable" not in refusal["warnings"]


# ---- #341: no answer without data to a data question; a plain note when the planner fails ------------------

FINISH_ONLY = call_response("finish", {})


def test_a_model_plan_with_no_data_call_is_planned_by_the_rules_instead():
    """The model's planner chose no data function: the composer could only introduce Sentti. The rules
    plan the question, so it is answered with its number."""
    transport = ByKind(FINISH_ONLY, text_response(DRAFT_OK))
    p, audit = pipeline(transport)
    done = ask(p)
    assert done["outcome"] == "answered" and "€1,146.05" in done["text_rendered"]
    turns = audit.records[-1]["planner_turns"]
    assert turns[0]["error"] == "no data call" and turns[1]["source"] == "rules"
    assert turns[0]["tokens"]["prompt_tokens"] > 0       # the replaced plan's usage stays in the audit
    assert "llm_unavailable" not in done["warnings"]


def test_a_question_the_rules_do_not_recognise_then_gets_their_general_clarifying_question():
    transport = ByKind(FINISH_ONLY, text_response(DRAFT_OK))
    p, _ = pipeline(transport)
    done = ask(p, "Tell me something useful about my groceries")
    assert done["outcome"] == "clarify" and transport.compose.requests == []
    assert done["clarify"]["question"].startswith("I could not work that out right now.")   # an empty plan


def test_after_a_planner_failure_the_clarifying_question_says_it_was_not_worked_out():
    transport = FakeTransport(TimeoutError())
    p, _ = pipeline(transport)
    p.model.client.fallback_model = None
    done = ask(p, "Tell me something useful about my groceries")
    assert done["outcome"] == "clarify" and "llm_unavailable" in done["warnings"]
    assert done["clarify"]["question"].startswith("I could not work that out right now. ")
    done = ask(p, "Kerro jotain hyödyllistä ruokaostoksistani", language="fi")
    assert done["clarify"]["question"].startswith("En pystynyt selvittämään tätä juuri nyt. ")


# ---- #304, #302: a model-written clarifying question ------------------------------------------------------

def clarify_response(question, options):
    return call_response("ask_clarifying_question", {"question": question, "options": options})


def test_clarify_options_the_rules_do_not_recognise_are_replaced_by_the_rules_question():
    """On dev the model asked back with fragments ("Where did money go"): tapped, they are not recognised,
    so with the model off the user got a second clarifying question (#304)."""
    transport = ByKind(clarify_response("What do you want to know?",
                                        ["Where did money go", "Safe to spend", "Recurring bills"]), text_response(DRAFT_OK))
    p, audit = pipeline(transport)
    done = ask(p, "money?")
    assert done["outcome"] == "clarify" and done["clarify"]["options"] != ["Where did money go", "Safe to spend",
                                                                           "Recurring bills"]
    rules = RuleModel()
    for option in done["clarify"]["options"]:
        plan = rules.plan(PlanInput(question=option, language="en", as_of="2026-09-30",
                                    tools=p.registry.schemas()))
        assert plan.recognised, option
    assert audit.records[-1]["planner_turns"][-1]["error"] == "clarify options not recognised"


def test_clarify_options_the_rules_recognise_are_kept_and_markdown_is_dropped():
    # Full questions: a bare "Last month" counts only after a spending question (#384), and "money?" is not one.
    options = ["How much did I spend last month?", "How much did I spend this month?"]
    transport = ByKind(clarify_response("**Which** of these do you mean?", options), text_response(DRAFT_OK))
    p, _ = pipeline(transport)
    done = ask(p, "money?")
    assert done["clarify"] == {"question": "Which of these do you mean?", "options": options}



def test_without_a_key_the_template_writes_with_no_model_draft_attempt():
    """Review of #401: with no key the rule model's own template is not run through the model-draft checks;
    composer_attempts holds only the template, and the text is the same."""
    from core.agent.rules import RuleModel

    p, audit = pipeline(FakeTransport(call_response()))
    p.model = RuleModel()
    done = ask(p)
    attempts = audit.records[-1]["composer_attempts"]
    assert [a["raw"] for a in attempts] == ["template"] and "llm_unavailable" in done["warnings"]
    assert done["outcome"] == "answered" and "€1,146.05" in done["text_rendered"]

def test_an_empty_plan_answered_by_the_rules_clarify_carries_the_warning_with_the_note():
    """#383 (from the review of #368): the note "I could not work that out" and llm_unavailable come together."""
    transport = ByKind(call_response("finish", {}), text_response(DRAFT_OK))
    p, _ = pipeline(transport)
    done = ask(p, "Tell me something useful about my groceries")
    assert done["outcome"] == "clarify" and done["clarify"]["question"].startswith("I could not")
    assert "llm_unavailable" in done["warnings"]



def test_a_rules_refusal_after_an_empty_plan_carries_no_warning():
    """Review of #422: the empty-plan warning is for the clarifying question only."""
    transport = ByKind(call_response("finish", {}), text_response(DRAFT_OK))
    p, _ = pipeline(transport)
    done = ask(p, "Should I put my savings into tech stocks?")
    assert done["outcome"] == "refused" and "llm_unavailable" not in done["warnings"]


def test_a_refused_planner_model_answers_on_its_fallback_without_a_warning():
    def transport(model, contents, config, timeout_s):
        if model == "gemini-3.8-flash" and "tools" in config:
            raise api_error(404)
        return PLAN_OK if "tools" in config else text_response(DRAFT_OK)

    p, audit = pipeline(transport)
    done = ask(p)
    assert done["outcome"] == "answered" and done["warnings"] == [] and "€1,146.05" in done["text_rendered"]


def test_a_composer_without_a_model_leaves_the_planner_asked():
    """Review of #446: all composer ids refused, the planner healthy: an unrecognised question is still planned
    by the model; the template writes, with the warning; the audit names the composer's reason."""
    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, audit = pipeline(transport)
    c = p.model.client
    c.compose_model, c.compose_fallback_model = "gemini-3.5-flash-lite", None
    c._refused["gemini-3.5-flash-lite"] = c.clock() + 600
    done = ask(p, "Tell me something useful about my groceries")
    assert len(transport.plan.requests) >= 1 and transport.compose.requests == []
    assert done["outcome"] == "answered" and "llm_unavailable" in done["warnings"]
    record = audit.records[-1]
    assert record["composer_unavailable"] == "model_refused" and record["planner_unavailable"] is None


def test_a_paused_planner_leaves_the_composer_writing_a_recognised_question():
    """Review of #446: the planner paused after its streak, the composer healthy: the rules plan a recognised
    question and the model writes it, with no warning and no note."""
    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, audit = pipeline(transport)
    p.model.client._role_paused_until["plan"] = p.model.client.clock() + 30
    done = ask(p)
    assert transport.plan.requests == [] and len(transport.compose.requests) == 1
    assert done["outcome"] == "answered" and done["warnings"] == [] and "€1,146.05" in done["text_rendered"]
    assert audit.records[-1]["planner_unavailable"] == "role_paused"


def test_both_roles_unavailable_is_as_before():
    transport = ByKind(PLAN_OK, text_response(DRAFT_OK))
    p, audit = pipeline(transport)
    p.model.client._pause(300, "rate_limited")
    done = ask(p, "Tell me something useful about my groceries")
    assert transport.requests == [] and "llm_unavailable" in done["warnings"]
    assert not done["clarify"]["question"].startswith("I could not")
