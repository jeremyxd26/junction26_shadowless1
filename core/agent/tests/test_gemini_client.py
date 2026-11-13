"""The Gemini client (core/agent/gemini_client.py) with fake transports: no network, no key."""

from __future__ import annotations

import json
from typing import Any

import pytest
from google.genai import errors

from core.agent import gemini_client as gc
from core.agent.gemini_client import GeminiClient, GeminiError, Ledger, SdkTransport

FLASH, PRO = "gemini-3.8-flash", "gemini-3.1-pro-preview"


def api_error(code: int) -> errors.APIError:
    return errors.APIError(code, {"error": {"code": code, "message": "fake", "status": "FAKE"}})


def call_response(name: str = "get_spending", args: dict | None = None, signature: str | None = "c2ln") -> dict:
    part: dict[str, Any] = {"function_call": {"name": name, "args": args or {}, "id": "call_1"}}
    if signature:
        part["thought_signature"] = signature
    return {"candidates": [{"content": {"role": "model", "parts": [part, {"function_call": {"name": "finish", "args": {}}}]},
                            "finish_reason": "STOP"}],
            "usage_metadata": {"prompt_token_count": 1000, "thoughts_token_count": 20, "candidates_token_count": 30},
            "sdk_http_response": {"headers": {"server": "fake", "date": "today"}}}


def text_response(text: str, finish: str = "STOP") -> dict:
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finish_reason": finish}],
            "usage_metadata": {"prompt_token_count": 500, "candidates_token_count": 40}}


class FakeTransport:
    """Returns or raises the scripted steps in order; records every request."""

    def __init__(self, *steps: Any) -> None:
        self.steps = list(steps)
        self.requests: list[tuple[str, float]] = []

    def __call__(self, model, contents, config, timeout_s):
        self.requests.append((model, timeout_s))
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, BaseException):
            raise step
        return step


def client(transport, tmp_path=None, **kw) -> GeminiClient:
    kw.setdefault("cache", "off" if tmp_path is None else "on")
    if tmp_path is not None:
        kw.setdefault("cache_dir", tmp_path / "cache")
    return GeminiClient(FLASH, transport, sleep=lambda s: None, **kw)


PLAN_ARGS = ("planner prompt", [{"role": "user", "parts": [{"text": "q"}]}],
             [{"name": "get_spending", "description": "d", "parameters_json_schema": {"type": "object"}}])


# ---- parsing --------------------------------------------------------------------------------------

def test_plan_parses_calls_usage_and_cost():
    c = client(FakeTransport(call_response()))
    reply = c.plan(*PLAN_ARGS)
    assert [x["name"] for x in reply.calls] == ["get_spending", "finish"]
    assert reply.calls[0]["id"] == "call_1"
    assert reply.content["parts"][0]["thought_signature"] == "c2ln"  # kept for the replay of round 2
    assert (reply.usage.prompt_tokens, reply.usage.thought_tokens, reply.usage.output_tokens) == (1000, 20, 30)
    # flash: $0.75 per 1M input, $3.75 per 1M output including thoughts
    assert reply.usage.cost_usd == pytest.approx((1000 * 0.75 + 50 * 3.75) / 1e6)
    assert c.calls[-1].network and not c.calls[-1].cached


@pytest.mark.parametrize("raw, code", [
    ({"candidates": []}, "empty"),
    (text_response("   "), "empty"),
    (text_response('{"language": "en", "te', finish="MAX_TOKENS"), "truncated"),
    ({"candidates": [{"finish_reason": "MALFORMED_FUNCTION_CALL", "content": {"parts": []}}]}, "malformed_function_call"),
])
def test_unusable_responses_raise_a_short_code(raw, code):
    with pytest.raises(GeminiError) as exc:
        client(FakeTransport(raw)).compose("s", "u", {"type": "object"})
    assert exc.value.code == code


def test_a_safety_block_is_reported_not_raised():
    reply = client(FakeTransport({"prompt_feedback": {"block_reason": "SAFETY"}})).plan(*PLAN_ARGS)
    assert reply.blocked and not reply.calls


def test_compose_returns_invalid_json_unchanged_for_the_validator():
    reply = client(FakeTransport(text_response("not json"))).compose("s", "u", {"type": "object"})
    assert reply.text == "not json"


# ---- cache ----------------------------------------------------------------------------------------

def test_the_same_request_is_served_from_the_cache_without_headers(tmp_path):
    transport = FakeTransport(call_response())
    c = client(transport, tmp_path)
    first = c.plan(*PLAN_ARGS)
    second = c.plan(*PLAN_ARGS)
    assert len(transport.requests) == 1
    assert second.cached and second.calls == first.calls and second.latency_ms == first.latency_ms
    stored = json.loads(next((tmp_path / "cache").glob("*.json")).read_text(encoding="utf-8"))
    assert set(stored["response"]) <= set(gc.STORED_FIELDS)
    assert "sdk_http_response" not in json.dumps(stored)


def test_a_changed_prompt_misses_the_cache(tmp_path):
    transport = FakeTransport(call_response())
    c = client(transport, tmp_path)
    c.plan(*PLAN_ARGS)
    c.plan("another prompt", *PLAN_ARGS[1:])
    assert len(transport.requests) == 2


def test_unusable_responses_are_not_cached(tmp_path):
    transport = FakeTransport({"candidates": []}, call_response())
    c = client(transport, tmp_path)
    with pytest.raises(GeminiError):
        c.plan(*PLAN_ARGS)
    assert c.plan(*PLAN_ARGS).calls  # the retry goes to the network, not to a cached empty answer
    assert len(transport.requests) == 2


def test_replay_mode_never_reaches_the_network(tmp_path):
    c = GeminiClient(FLASH, None, cache="replay", cache_dir=tmp_path)
    with pytest.raises(GeminiError) as exc:
        c.plan(*PLAN_ARGS)
    assert exc.value.code == "cache_miss"


# ---- errors, retries and the fallback model ----------------------------------------------------

def test_503_is_retried_twice_with_a_pause_then_succeeds():
    pauses: list[float] = []
    transport = FakeTransport(api_error(503), api_error(503), call_response())
    c = GeminiClient(FLASH, transport, cache="off", sleep=pauses.append)
    assert c.plan(*PLAN_ARGS).calls
    assert len(transport.requests) == 3 and pauses == list(gc.SERVER_RETRY_BACKOFF_S)


def test_an_overwhelmed_model_falls_back_to_the_other_model_once():
    transport = FakeTransport(api_error(503), api_error(503), api_error(503), call_response())
    c = client(transport, fallback_model=PRO)
    reply = c.plan(*PLAN_ARGS)
    assert [m for m, _ in transport.requests] == [FLASH, FLASH, FLASH, PRO]
    assert reply.model == PRO
    assert reply.usage.cost_usd == pytest.approx((1000 * 2.00 + 50 * 12.00) / 1e6)  # priced as pro


def test_an_outage_everywhere_raises_and_pauses_further_requests():
    transport = FakeTransport(api_error(503))
    c = client(transport, fallback_model=PRO)
    with pytest.raises(GeminiError) as exc:
        c.plan(*PLAN_ARGS)
    assert exc.value.code == "server" and len(transport.requests) == 4
    with pytest.raises(GeminiError):
        c.compose("s", "u", {"type": "object"})  # paused: the pipeline's retry adds no request
    assert len(transport.requests) == 4


def test_429_is_not_retried_and_pauses_every_later_call():
    now = [1000.0]
    transport = FakeTransport(api_error(429), call_response())
    c = GeminiClient(FLASH, transport, cache="off", fallback_model=PRO, sleep=lambda s: None, clock=lambda: now[0])
    with pytest.raises(GeminiError) as exc:
        c.plan(*PLAN_ARGS)
    assert exc.value.code == "rate_limited" and len(transport.requests) == 1
    with pytest.raises(GeminiError):
        c.plan(*PLAN_ARGS)
    assert len(transport.requests) == 1  # no second request inside the pause
    now[0] += gc.RATE_LIMIT_COOLDOWN_S + 1
    assert c.plan(*PLAN_ARGS).calls
    assert len(transport.requests) == 2


@pytest.mark.parametrize("code", [401, 403, 404])
def test_a_refused_key_or_model_pauses_every_later_call(code):
    transport = FakeTransport(api_error(code), call_response())
    c = client(transport, fallback_model=PRO)
    for _ in range(3):                                  # the pipeline's retry and the next questions
        with pytest.raises(GeminiError) as exc:
            c.plan(*PLAN_ARGS)
        assert exc.value.code == f"http_{code}"
    assert len(transport.requests) == 1


def test_a_timeout_is_not_retried_here():
    transport = FakeTransport(TimeoutError(), call_response())
    with pytest.raises(GeminiError) as exc:
        client(transport, fallback_model=PRO).plan(*PLAN_ARGS)
    assert exc.value.code == "timeout" and len(transport.requests) == 1


def test_a_client_error_is_not_retried():
    transport = FakeTransport(api_error(400), call_response())
    with pytest.raises(GeminiError) as exc:
        client(transport, fallback_model=PRO).plan(*PLAN_ARGS)
    assert exc.value.code == "http_400" and len(transport.requests) == 1


def test_error_codes_carry_no_response_text():
    transport = FakeTransport(errors.APIError(500, {"error": {"message": "secret-looking detail"}}))
    with pytest.raises(GeminiError) as exc:
        client(transport).plan(*PLAN_ARGS)
    assert "detail" not in str(exc.value)


# ---- request budget ------------------------------------------------------------------------------

def test_the_ledger_counts_requests_and_stops_at_the_daily_cap(tmp_path):
    ledger = Ledger(tmp_path / "requests.jsonl", daily_cap=2)
    transport = FakeTransport(call_response())
    c = client(transport, ledger=ledger)
    c.plan(*PLAN_ARGS)
    c.plan(*PLAN_ARGS)
    with pytest.raises(GeminiError) as exc:
        c.plan(*PLAN_ARGS)
    assert exc.value.code == "budget" and len(transport.requests) == 2 and ledger.today() == 2
    text = (tmp_path / "requests.jsonl").read_text(encoding="utf-8")
    assert "planner prompt" not in text and '"q"' not in text  # no prompt text in the ledger


def test_cache_hits_do_not_count_against_the_budget(tmp_path):
    ledger = Ledger(tmp_path / "requests.jsonl", daily_cap=1)
    c = client(FakeTransport(call_response()), tmp_path, ledger=ledger)
    c.plan(*PLAN_ARGS)
    assert c.plan(*PLAN_ARGS).cached
    assert ledger.today() == 1


# ---- the SDK transport ---------------------------------------------------------------------------

def test_sdk_transport_keeps_the_server_deadline_at_its_minimum(monkeypatch):
    transport = SdkTransport("test-key-not-real")
    seen = {}

    def fake_generate_content(model, contents, config):
        seen["timeout"] = config.http_options.timeout
        seen["headers"] = config.http_options.headers
        seen["mode"] = config.tool_config.function_calling_config.mode
        seen["level"] = config.thinking_config.thinking_level
        from google.genai import types
        return types.GenerateContentResponse.model_validate(call_response())

    monkeypatch.setattr(transport._client.models, "generate_content", fake_generate_content)
    c = GeminiClient(FLASH, transport, cache="off", plan_timeout_s=8.0)
    reply = c.plan(*PLAN_ARGS)
    assert reply.calls[0]["name"] == "get_spending"
    assert seen["timeout"] <= 8000                      # the client gives up after our deadline
    assert int(seen["headers"]["X-Server-Timeout"]) >= gc.MIN_SERVER_DEADLINE_S  # the API's minimum
    assert str(seen["mode"]).endswith("ANY") and str(seen["level"]).endswith("LOW")
