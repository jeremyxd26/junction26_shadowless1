"""The model comparison of #169 without a network, a database or a key: the NVIDIA transport's request
and its answer in the adapter's shape, its error codes, the planner questions and their grading, and the
composer summary."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from core.agent.gemini_client import _error_code, parse
from core.eval import model_compare, planner_compare

KEY = "test-key-not-real"
SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
CONFIG = {"system_instruction": "Write the answer.", "response_mime_type": "application/json",
          "response_json_schema": SCHEMA, "thinking_config": {"thinking_level": "minimal"}, "max_output_tokens": 900}
CONTENTS = [{"role": "user", "parts": [{"text": "the tool results"}]}]


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def sse(*chunks: dict) -> bytes:
    return b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks) + b"data: [DONE]\n\n"


def test_the_transport_sends_the_composer_request_with_reasoning_off_and_returns_the_adapters_shape():
    sent = {}

    def opener(request, timeout):
        sent["body"] = json.loads(request.data)
        sent["headers"] = dict(request.header_items())
        return FakeResponse(sse(
            {"choices": [{"delta": {"content": "```json\n{\"text\": "}}]},
            {"choices": [{"delta": {"content": "\"hello\"}\n```"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 9,
                                      "completion_tokens_details": {"reasoning_tokens": 0}}}))

    transport = model_compare.NvidiaTransport(KEY, opener=opener)
    raw = transport("nvidia/some-model", CONTENTS, CONFIG, 8.0)
    body = sent["body"]
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["messages"][0]["content"].startswith("/no_think\n") and body["messages"][1]["content"] == "the tool results"
    assert body["response_format"]["json_schema"]["schema"] == SCHEMA and body["max_tokens"] == 900
    assert body["stream"] is True
    reply = parse("nvidia/some-model", raw, latency_ms=10)
    assert json.loads(reply.text) == {"text": "hello"}                          # the fence is stripped
    assert (reply.usage.prompt_tokens, reply.usage.output_tokens, reply.finish_reason) == (120, 9, "STOP")
    assert transport.log[0]["ttft_ms"] is not None and transport.log[0]["finish"] == "stop"
    assert KEY not in json.dumps(raw) and KEY not in json.dumps(transport.log)   # the key only in the header
    assert sent["headers"]["Authorization"] == "Bearer " + KEY


def test_a_cut_answer_is_reported_as_max_tokens():
    transport = model_compare.NvidiaTransport(KEY, opener=lambda r, timeout: FakeResponse(sse(
        {"choices": [{"delta": {"content": "{\"text\": \"hel"}, "finish_reason": "length"}]})))
    assert transport("m", CONTENTS, CONFIG, 8.0)["candidates"][0]["finish_reason"] == "MAX_TOKENS"


@pytest.mark.parametrize("status, code", [(429, "rate_limited"), (401, "http_401"), (503, "server")])
def test_http_errors_carry_their_status_so_the_adapter_pauses(status, code):
    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, status, "error", {}, None)

    transport = model_compare.NvidiaTransport(KEY, opener=opener)
    with pytest.raises(model_compare.HttpStatusError) as exc:
        transport("m", CONTENTS, CONFIG, 8.0)
    assert _error_code(exc.value) == (code, status)


def test_the_planner_call_is_refused_without_a_request():
    transport = model_compare.NvidiaTransport(KEY, opener=lambda r, timeout: pytest.fail("no request"))
    with pytest.raises(model_compare.HttpStatusError):
        transport("m", CONTENTS, {"system_instruction": "plan", "tools": []}, 8.0)


def test_the_planner_questions_and_their_grading():
    items = planner_compare.questions()
    sets = {name: [i for i in items if i["set"] == name] for name in ("unrecognised", "red_team", "live")}
    assert len(sets["unrecognised"]) == 39 and len(sets["live"]) == 3 and len(sets["red_team"]) >= 18
    assert "Mihin kaytan eniten rahaa?" in [i["question"] for i in sets["unrecognised"]]   # typed without ä
    q4 = next(i for i in items if i["question"] == "how can I save money?")
    assert planner_compare.grade(q4, ["get_safe_to_save", "finish"], None) == "right"
    assert planner_compare.grade(q4, ["ask_clarifying_question"], None) == "clarify"
    assert planner_compare.grade(q4, ["run_what_if"], None) == "wrong tool"
    assert planner_compare.grade(q4, [], None) == "no call"
    red = sets["red_team"][0]
    assert planner_compare.grade(red, ["decline"], red["refusal_kinds"][0]) == "right"
    assert planner_compare.grade(red, ["get_spending"], None) == "wrong tool"


def test_the_composer_summary_counts_first_drafts_retries_and_templates():
    def row(lang, *validations, ms=800):
        return {"lang": lang, "composer_attempts": [{"validation": v} for v in validations],
                "calls": [{"kind": "compose", "ms": ms, "error": None, "prompt": 10, "thought": 0, "output": 2,
                           "network": True}]}

    summary = model_compare.summarise([
        row("en", "ok"), row("fi", ["unknown number ids: n10"], "ok", ms=1200),
        row("en", ["digits that are not a declared number or a returned date: '1'"], ["words must stand between"]),
    ])
    assert summary["outcomes"] == {"first draft": 1, "retry": 1, "template": 1}
    assert summary["first_draft_violations"] == {"unknown number id": 1, "digits not from a tool": 1}
    assert summary["compose_ms"]["median"] == 800 and summary["tokens"]["requests"] == 3
