"""Real Gemini exchanges, recorded once and replayed without network, key or database.

Each file in recordings/ holds one answer recorded by core/agent/gemini_eval.py (GEMINI_RECORD_DIR):
the question, every model response in order (candidates and token counts only), and what every data
tool returned (its model view and the Number objects it registered). The replay runs the real
pipeline and the real adapter: the transport hands back the recorded responses in order, and each
tool hands back its recorded result. The answer must come out exactly as recorded: the same outcome,
refusal, function calls and text, with every recorded response used.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

from core.agent import offers
from core.agent.conversation import ConversationStore
from core.agent.gemini import GeminiModel, RulesFirstModel
from core.agent.gemini_client import GeminiClient
from core.agent.orchestrator import AskRequest, Pipeline
from core.agent.registry import Registry, ToolSpec
from core.agent.rules import RuleModel
from core.agent.model import PlanInput
from core.agent.toolset import default_registry
from core.answer_text import length_problems
from core.tools.models import Number, ToolResult

RECORDINGS = sorted((Path(__file__).parent / "recordings").glob("*.json"))
RAW_ROW_MARKERS = ("merchant_id", "balance_after", "CUST0", "MRC", "transaction_id")


class Replay:
    """The recorded model responses, in order; fails on a request the recording does not have."""

    def __init__(self, exchanges: list[dict]) -> None:
        self.exchanges = list(exchanges)
        self.used = 0

    def __call__(self, model, contents, config, timeout_s):
        assert self.exchanges, "the pipeline made a model request the recording does not have"
        step = self.exchanges.pop(0)
        self.used += 1
        assert step["kind"] == ("plan" if "tools" in config else "compose")
        if "error" in step:
            raise TimeoutError(step["error"])
        return step["response"]


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


def recorded_registry(fixture: dict) -> Registry:
    """The service's tools with their real argument models, each returning its recorded result."""
    results = defaultdict(list)
    for entry in fixture["tools"]:
        results[entry["name"]].append(entry)
    registry = Registry()
    for name, spec in default_registry().tools.items():
        def fn(ctx, args, _name=name):
            assert results[_name], f"{_name} was not called in the recording"
            entry = results[_name].pop(0)
            for number in entry["numbers"]:
                registered = ctx.numbers.register(Number.model_validate({**number, "id": None}))
                assert registered.id == number["id"]
            return ToolResult(tool=_name, data={}, model_view=entry["model_view"])
        registry.register(ToolSpec(name, spec.description, spec.args_model, fn, spec.status_label,
                                   card_builder=lambda result: None))
    return registry


@pytest.mark.parametrize("path", RECORDINGS, ids=[p.stem for p in RECORDINGS])
def test_a_recorded_exchange_replays_without_network(path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    missing = {e["name"] for e in fixture["tools"]} - set(default_registry().tools)
    if missing:
        pytest.skip(f"tools not in this checkout: {sorted(missing)}")
    replay = Replay(fixture["exchanges"])
    gemini = GeminiModel(GeminiClient(fixture["model"], replay, cache="off", fallback_model=None,
                                      compose_model=fixture.get("compose_model"), sleep=lambda s: None))
    model = gemini if fixture["planner"] == "model" else RulesFirstModel(RuleModel(), gemini)
    audit = Audit()
    pipeline = Pipeline(recorded_registry(fixture), model, NoDatabase(), as_of=date.fromisoformat(fixture["as_of"]),
                        store=ConversationStore(), audit=audit)
    events = []
    pipeline.run(AskRequest(customer_id="CUST00860", message=fixture["question"], language=fixture["language"]),
                 lambda e, d: events.append((e, d)))
    done = dict(events).get("done")
    assert done is not None, events
    expect = fixture["expect"]
    assert done["outcome"] == expect["outcome"]
    assert (done.get("refusal") or {}).get("kind") == expect["refusal_kind"]
    calls = [c["name"] for t in audit.records[-1]["planner_turns"] for c in t.get("calls") or []]
    assert calls == expect["tool_calls"]
    # #572: the server may append one listed follow-up offer after the recorded model text
    text, offered = offers.strip_offer(done["text"])
    rendered, offered_rendered = offers.strip_offer(done["text_rendered"])
    assert text == expect["text"] and rendered == expect["text_rendered"] and offered == offered_rendered
    assert replay.exchanges == []                       # every recorded response was used
    for marker in RAW_ROW_MARKERS:                      # R3: no raw rows, ids or balances in the answer
        assert marker not in done["text_rendered"]
    for text in (done["text"], done["text_rendered"]):   # #302: plain text, even when the model wrote markdown
        assert not any(mark in text for mark in ("*", "`", "__", "](", "\n#"))
    if done["outcome"] == "answered":
        # #288: one takeaway and at most one more sentence, at most three numbers (Renat's rule)
        assert length_problems(done["text"], len(set(done["cited"]))) == []


def test_the_recordings_cover_the_required_exchanges():
    """Issue #66: a spending question, a basket question, a refusal (investment advice), a clarifying
    question, a Finnish question and an injection attempt."""
    fixtures = [json.loads(p.read_text(encoding="utf-8")) for p in RECORDINGS]
    if not fixtures:
        pytest.skip("no recordings yet")
    calls = [f["expect"]["tool_calls"] for f in fixtures]
    assert any("get_spending" in c for c in calls)
    assert any("get_basket_breakdown" in c for c in calls)
    assert any(f["expect"]["refusal_kind"] == "investment_advice" for f in fixtures)
    assert any(f["expect"]["outcome"] == "clarify" for f in fixtures)
    assert any(f["language"] == "fi" for f in fixtures)
    assert any("ignore" in f["question"].lower() for f in fixtures)
    assert any(f["planner"] == "model" for f in fixtures)   # the Gemini planner itself, not only the rules


def test_recordings_hold_no_key_and_no_http_headers():
    for path in RECORDINGS:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"A[I]za[0-9A-Za-z_-]{30,}", text)          # the shape of a Google API key
        assert "x-goog-api-key" not in text.lower() and "headers" not in text and "key=" not in text


def test_some_recorded_responses_hold_markdown_that_the_answer_drops():
    """#302: real composer responses with **bold** (recorded before the prompt asked for plain text); the
    replay above proves their answers come out without it."""
    drafts = [json.loads(json.loads(p.read_text(encoding="utf-8"))["exchanges"][-1]["response"]["candidates"][0]
                         ["content"]["parts"][-1]["text"])["text"]
              for p in RECORDINGS if json.loads(p.read_text(encoding="utf-8"))["exchanges"][-1]["kind"] == "compose"]
    assert any("**" in d for d in drafts)



# ---- #288: what the new prompts must show in real answers ------------------------------------------------

def load(name: str) -> dict:
    return json.loads((Path(__file__).parent / "recordings" / f"{name}.json").read_text(encoding="utf-8"))


def cited_methods(fixture: dict) -> list[str]:
    numbers = {n["id"]: n for t in fixture["tools"] for n in t["numbers"]}
    return [numbers[i]["method"] for i in re.findall(r"\{\{(n\d+)\}\}", fixture["expect"]["text"])]


def test_a_spending_question_without_a_period_is_asked_back_with_options_the_rules_recognise():
    """#304: "How much did I spend?" names no period: the planner asks back instead of picking August,
    and every option works as the next message when the model is off."""
    fixture = load("clarify-how-much-did-i-spend-en")
    assert fixture["expect"]["outcome"] == "clarify" and fixture["expect"]["tool_calls"] == ["ask_clarifying_question"]
    call = fixture["exchanges"][0]["response"]["candidates"][0]["content"]["parts"][0]["function_call"]
    rules = RuleModel()
    # As the pipeline checks them (Pipeline._options_work): a tapped option is the next message of this
    # conversation, so the question stands before it ("Last month" after "How much did I spend?", #384).
    after = [{"question": fixture["question"], "calls": [], "results": []}]
    for option in call["args"]["options"]:
        plan = rules.plan(PlanInput(question=option, language="en", as_of=fixture["as_of"],
                                    tools=default_registry().schemas(), history=after))
        assert plan.recognised and plan.calls[0].name != "ask_clarifying_question", option


def test_a_merchant_total_of_several_purchases_is_not_called_one_visit():
    """#301: Restaurant A's €24.88 adds up two purchases; the answer calls it a total, never a visit."""
    fixture = load("merchant-restaurants-total-en")
    groups = [g for t in fixture["tools"] for g in t["model_view"].get("groups") or []]
    several = {g["amount"]["id"] for g in groups if (g.get("transactions") or 0) > 1}
    text = fixture["expect"]["text"]
    assert several & set(re.findall(r"\{\{(n\d+)\}\}", text))          # the answer cites such a total
    assert not re.search(r"\b(?:visit|bill|purchase|receipt)\b", text, re.I)


def test_the_spender_type_answer_cites_the_comparison_with_similar_people():
    """The model comparison: both models left the peer numbers out of every spender-type answer."""
    assert any(m.startswith("peer_benchmark.") for m in cited_methods(load("spender-type-peers-en")))


def test_the_what_if_answer_states_its_baseline():
    """The model comparison: flash-lite left the dining baseline out three times in eight."""
    methods = cited_methods(load("what-if-restaurants-baseline-en"))
    assert "what_if.baseline_month_eur@1" in methods and "what_if.saving_month_eur@1" in methods


@pytest.mark.parametrize("path", RECORDINGS, ids=[p.stem for p in RECORDINGS])
def test_the_template_for_each_recorded_tool_result_repeats_no_period(path):
    """The repeated-period check runs on model drafts only at runtime (a template is never replaced for
    it), so the templates are checked here: the template text for every recorded tool result, in the
    recording's language, never says "a month a month" (#288, #390)."""
    from core.agent import template
    from core.agent.validator import allowed_from, repeated_period

    fixture = json.loads(path.read_text(encoding="utf-8"))
    if not fixture["tools"]:
        pytest.skip("no tool result in this recording")
    numbers = {n["id"]: Number.model_validate(n) for t in fixture["tools"] for n in t["numbers"]}
    views = [t["model_view"] for t in fixture["tools"]]
    allowed = allowed_from(numbers.values(), views, date.fromisoformat(fixture["as_of"]))
    text = template.template_draft(views, [], fixture["language"], allowed, fixture["question"])
    text = json.loads(text)["text"] if isinstance(text, str) and text.lstrip().startswith("{") else \
        (text["text"] if isinstance(text, dict) else text)
    assert repeated_period(text, numbers) is None, text



# ---- #398: the stand's composer rows in real answers (flash-lite) ----------------------------------------------

def test_a_named_feeling_is_acknowledged_first_and_sentti_does_not_introduce_itself():
    text = load("feeling-stressed-balance-en")["expect"]["text"]
    first = re.split(r"(?<=[.!?])\s", text)[0]
    assert re.search(r"stress|worr|understand|tough|hard", first, re.I) and "Sentti" not in text


def test_a_why_answer_names_a_cause_and_cites_each_number_once():
    fixture = load("why-safe-to-spend-low-en")
    used = re.findall(r"\{\{(n\d+)\}\}", fixture["expect"]["text"])
    assert len(used) == len(set(used)) >= 2                       # the result and at least one cause
    assert re.search(r"\bbecause\b|\bbills?\b|\bbalance\b|\breserve\b", fixture["expect"]["text"], re.I)


def test_a_count_keeps_its_noun_in_the_injection_answer():
    assert re.search(r"\{\{n\d+\}\} transactions", load("injection-groceries-print-transactions-en")["expect"]["text"])


def test_a_comparison_names_both_periods_without_joined_figures():
    text = load("comparison-restaurants-august-july-en")["expect"]["text"]
    assert "August 2026" in text and "July 2026" in text
    assert not re.search(r"\{\{n\d+\}\}\s+and\s+\{\{n\d+\}\}\s+compared", text)
    # Row 4 of #398: the direction in words after the change (re-recorded after the prompt example was fixed)
    assert re.search(r"\{\{n\d+\}\}\s+(?:more|less|higher|lower)\s+than\b", text), text


def test_upcoming_bills_take_no_past_window():
    text = load("regular-bills-upcoming-en")["expect"]["text"]
    assert not re.search(r"\b\d{1,2} [A-Z][a-z]{2} – \d{1,2} [A-Z][a-z]{2} \d{4}\b", text)   # e.g. "1 Apr – 30 Sep 2026"
    assert "before payday" in text or "15 October 2026" in text


@pytest.mark.parametrize("path", RECORDINGS, ids=[p.stem for p in RECORDINGS])
def test_no_recorded_answer_and_no_template_for_a_recorded_result_suggests_borrowing(path):
    """#419: the recorded answers, and the template text for every recorded tool result."""
    from core.agent import template
    from core.agent.validator import allowed_from
    from core.answer_text import borrowing_suggestion

    fixture = json.loads(path.read_text(encoding="utf-8"))
    assert borrowing_suggestion(fixture["expect"]["text"] or "") is None
    if not fixture["tools"]:
        return
    numbers = {n["id"]: Number.model_validate(n) for t in fixture["tools"] for n in t["numbers"]}
    views = [t["model_view"] for t in fixture["tools"]]
    allowed = allowed_from(numbers.values(), views, date.fromisoformat(fixture["as_of"]))
    draft = template.template_draft(views, [], fixture["language"], allowed, fixture["question"])
    text = draft["text"] if isinstance(draft, dict) else json.loads(draft)["text"]
    assert borrowing_suggestion(text) is None, text
