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

class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_503_without_a_fallback_is_not_retried_here_and_pauses_no_one():
    transport = FakeTransport(api_error(503), call_response())
    c = client(transport)
    answer = object()
    c.start_answer(answer)
    with pytest.raises(GeminiError) as exc:
        c.plan(*PLAN_ARGS)
    assert exc.value.code == "server" and len(transport.requests) == 1
    with pytest.raises(GeminiError):
        c.plan(*PLAN_ARGS)                              # the pipeline's retry in the same answer: no request
    assert len(transport.requests) == 1 and c.unavailable_reason() is None
    c.start_answer(object())                            # the next answer (any user) is not paused (#341)
    assert c.plan(*PLAN_ARGS).calls and len(transport.requests) == 2


def test_an_overwhelmed_model_falls_back_once_and_then_skips_the_primary_for_a_while():
    clock = Clock()
    transport = FakeTransport(api_error(503), call_response())
    c = GeminiClient(FLASH, transport, cache="off", fallback_model=PRO, sleep=lambda s: None, clock=clock)
    reply = c.plan(*PLAN_ARGS)
    assert [m for m, _ in transport.requests] == [FLASH, PRO]
    assert reply.model == PRO
    assert reply.usage.cost_usd == pytest.approx((1000 * 2.00 + 50 * 12.00) / 1e6)  # priced as pro
    c.plan(*PLAN_ARGS)
    assert [m for m, _ in transport.requests][-1] == PRO   # one request per call while flash is skipped
    clock.now += gc.PRIMARY_SKIP_S + 1
    c.plan(*PLAN_ARGS)
    assert [m for m, _ in transport.requests][-1] == FLASH


def test_an_outage_everywhere_fails_the_call_and_pauses_no_one():
    transport = FakeTransport(api_error(503))
    c = client(transport, fallback_model=PRO)
    c.start_answer(object())
    with pytest.raises(GeminiError) as exc:
        c.plan(*PLAN_ARGS)
    assert exc.value.code == "server" and len(transport.requests) == 2
    with pytest.raises(GeminiError):
        c.plan(*PLAN_ARGS)                       # the pipeline's retry in the same answer adds no request
    assert len(transport.requests) == 2 and c.unavailable_reason() is None
    with pytest.raises(GeminiError):
        c.compose("s", "u", {"type": "object"})  # the composer is still asked: flash, then pro
    assert len(transport.requests) == 4


def test_a_refused_fallback_model_is_turned_off_and_the_primary_is_not_paused():
    clock = Clock()
    transport = FakeTransport(api_error(503), api_error(404), call_response())
    c = GeminiClient(FLASH, transport, cache="off", fallback_model=PRO, sleep=lambda s: None, clock=clock)
    with pytest.raises(GeminiError) as exc:
        c.plan(*PLAN_ARGS)
    assert exc.value.code == "server" and c.fallback_model is None
    assert [m for m, _ in transport.requests] == [FLASH, PRO]
    assert c.unavailable_reason() is None                 # no pause at all (#341), not the 5 minutes of a 404
    assert c.plan(*PLAN_ARGS).calls
    assert [m for m, _ in transport.requests][-1] == FLASH


@pytest.mark.parametrize("failure", [api_error(400), {"candidates": []},
                                     {"candidates": [{"finish_reason": "MAX_TOKENS", "content": {"parts": []}}]}],
                         ids=["400", "empty", "cut"])
def test_three_failures_in_a_row_pause_further_requests(failure):
    clock = Clock()
    transport = FakeTransport(failure, failure, failure, call_response())
    c = GeminiClient(FLASH, transport, cache="off", sleep=lambda s: None, clock=clock)
    for _ in range(3):
        with pytest.raises(GeminiError):
            c.plan(*PLAN_ARGS)
    with pytest.raises(GeminiError):
        c.plan(*PLAN_ARGS)
    assert len(transport.requests) == 3                 # the fourth call sent nothing
    clock.now += gc.FAILURE_STREAK_COOLDOWN_S + 1
    assert c.plan(*PLAN_ARGS).calls and len(transport.requests) == 4


@pytest.mark.parametrize("failure", [TimeoutError(), ConnectionError(), api_error(503)],
                         ids=["timeout", "network", "5xx"])
def test_timeouts_network_errors_and_5xx_pause_no_one(failure):
    """Three slow or failed questions in a row (from one user or several) must not pause the model for
    every user (#341, the dev incident: three planner timeouts paused it for five minutes)."""
    transport = FakeTransport(failure, failure, failure, call_response())
    c = client(transport)
    for _ in range(3):
        c.start_answer(object())
        with pytest.raises(GeminiError):
            c.plan(*PLAN_ARGS)
    assert c.unavailable_reason() is None
    c.start_answer(object())
    assert c.plan(*PLAN_ARGS).calls and len(transport.requests) == 4


def test_one_or_two_timeouts_pause_nothing_and_do_not_feed_the_failure_streak():
    """400, 400, timeout: two failures and one timeout, no pause; a timeout never completes a streak of
    other failures, and a lone timeout pauses no one."""
    transport = FakeTransport(api_error(400), api_error(400), TimeoutError(), TimeoutError(), call_response())
    c = client(transport)
    for _ in range(4):
        with pytest.raises(GeminiError):
            c.plan(*PLAN_ARGS)
    assert c.unavailable_reason() is None
    assert c.plan(*PLAN_ARGS).calls and len(transport.requests) == 5


def test_a_success_resets_the_failure_streak():
    transport = FakeTransport(api_error(400), api_error(400), call_response(), api_error(400), api_error(400),
                              call_response())
    c = client(transport)
    for step in range(6):
        if step in (2, 5):
            assert c.plan(*PLAN_ARGS).calls
        else:
            with pytest.raises(GeminiError):
                c.plan(*PLAN_ARGS)
    assert len(transport.requests) == 6                 # never paused


def test_composer_safety_blocks_count_as_failures():
    blocked = {"candidates": [{"finish_reason": "SAFETY", "content": {"parts": []}}]}
    transport = FakeTransport(blocked, blocked, blocked, text_response("{}"))
    c = client(transport)
    for _ in range(3):
        assert c.compose("s", "u", {"type": "object"}).blocked
    with pytest.raises(GeminiError):
        c.compose("s", "u", {"type": "object"})
    assert len(transport.requests) == 3


# ---- one answer: request cap and deadline -----------------------------------------------------------

def test_one_answer_sends_at_most_eight_requests():
    transport = FakeTransport(call_response())
    c = client(transport)
    answer = object()
    c.start_answer(answer)
    for _ in range(gc.MAX_REQUESTS_PER_ANSWER):
        c.plan(*PLAN_ARGS)
    c.start_answer(answer)                              # the pipeline's retry: the same answer goes on
    with pytest.raises(GeminiError) as exc:
        c.plan(*PLAN_ARGS)
    assert exc.value.code == "answer_budget" and len(transport.requests) == gc.MAX_REQUESTS_PER_ANSWER
    c.start_answer(object())                            # the next answer starts a new count
    assert c.plan(*PLAN_ARGS).calls


def test_every_call_of_an_answer_ends_within_its_deadline():
    clock = Clock()
    timeouts: list[float] = []

    def hang(model, contents, config, timeout_s):       # a provider that never answers
        timeouts.append(timeout_s)
        clock.now += timeout_s
        raise TimeoutError()

    # An 8 s composer, so the planner after it gets only the 7 s left of the answer's 15 s.
    c = GeminiClient(FLASH, hang, cache="off", compose_timeout_s=8.0, sleep=lambda s: None, clock=clock)
    started = clock.now
    c.start_answer(object())
    calls = [lambda: c.compose("s", "u", {"type": "object"}), lambda: c.plan(*PLAN_ARGS)] * 2
    for call in calls:                                  # a call of each kind times out once per answer (#341)
        with pytest.raises(GeminiError):
            call()
    assert sum(timeouts) <= gc.ANSWER_DEADLINE_S and clock.now - started <= gc.ANSWER_DEADLINE_S
    assert timeouts == [c.compose_timeout_s, gc.ANSWER_DEADLINE_S - c.compose_timeout_s]


# ---- the ledger: reservation, concurrency, rolling window, live log ------------------------------

def test_simultaneous_calls_cannot_overshoot_the_cap(tmp_path):
    import threading
    import time as _time

    ledger = Ledger(tmp_path / "requests.jsonl", daily_cap=3, max_in_flight=100)
    sent = []

    def slow(model, contents, config, timeout_s):
        sent.append(model)
        _time.sleep(0.05)
        return call_response()

    c = GeminiClient(FLASH, slow, cache="off", ledger=ledger, sleep=lambda s: None)
    barrier = threading.Barrier(10)
    errors = []

    def worker():
        barrier.wait()
        try:
            c.plan(*PLAN_ARGS)
        except GeminiError as exc:
            errors.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(sent) == 3 and errors.count("budget") == 7 and ledger.count() == 3


def test_requests_in_flight_are_bounded(tmp_path):
    import threading

    ledger = Ledger(tmp_path / "requests.jsonl", daily_cap=None, max_in_flight=2)
    release = threading.Event()
    sent = []

    def blocking(model, contents, config, timeout_s):
        sent.append(model)
        release.wait(5)
        return call_response()

    c = GeminiClient(FLASH, blocking, cache="off", ledger=ledger, sleep=lambda s: None)
    errors = []

    def worker():
        try:
            c.plan(*PLAN_ARGS)
        except GeminiError as exc:
            errors.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    while len(sent) < 2:
        pass
    worker()                                            # a third call while two are in flight
    release.set()
    for t in threads:
        t.join()
    assert errors == ["busy"] and len(sent) == 2


def test_the_budget_is_a_rolling_24_hours(tmp_path):
    from datetime import datetime, timedelta, timezone

    path = tmp_path / "requests.jsonl"
    now = datetime.now(timezone.utc)
    lines = [{"ts": (now - timedelta(hours=25)).isoformat(timespec="seconds"), "kind": "plan"},
             {"ts": (now - timedelta(hours=23)).isoformat(timespec="seconds"), "kind": "plan"},
             {"ts": (now - timedelta(minutes=5)).isoformat(timespec="seconds"), "kind": "compose"}]
    path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    assert Ledger(path, daily_cap=10).count() == 2


def test_each_request_is_logged_with_the_running_total_on_the_service_log(tmp_path, caplog):
    import logging

    c = client(FakeTransport(call_response()), ledger=Ledger(tmp_path / "requests.jsonl", daily_cap=200))
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        c.plan(*PLAN_ARGS)
    lines = [r.getMessage() for r in caplog.records if r.name == "uvicorn.error"]
    assert any(line.startswith("gemini request 1 of 200 in 24 h") for line in lines)
    assert all("planner prompt" not in line for line in lines)


def test_an_unwritable_ledger_still_enforces_the_budget(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    ledger = Ledger(blocker / "requests.jsonl", daily_cap=2)    # its parent is a file: every write fails
    transport = FakeTransport(call_response())
    c = client(transport, ledger=ledger)
    c.plan(*PLAN_ARGS)
    c.plan(*PLAN_ARGS)
    with pytest.raises(GeminiError) as exc:
        c.plan(*PLAN_ARGS)
    assert exc.value.code == "budget" and len(transport.requests) == 2


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


def test_sdk_transport_calls_the_preview_model_on_v1beta(monkeypatch):
    from google import genai

    opened = []
    real_client = genai.Client

    def spy(*args, **kwargs):
        opened.append((kwargs.get("http_options") or {}).get("api_version"))
        return real_client(*args, **kwargs)

    monkeypatch.setattr(genai, "Client", spy)
    transport = SdkTransport("test-key-not-real")
    assert transport._client_for(FLASH) is transport._client
    pro_client = transport._client_for(PRO)
    assert pro_client is not transport._client and transport._client_for(PRO) is pro_client
    assert opened == [None, "v1beta"]


def test_the_planner_gets_nine_seconds_and_no_second_request_after_a_timeout():
    clock = Clock()
    timeouts: list[float] = []

    def slow(model, contents, config, timeout_s):
        timeouts.append(timeout_s)
        clock.now += timeout_s
        raise TimeoutError()

    c = GeminiClient(FLASH, slow, cache="off", sleep=lambda s: None, clock=clock)
    assert c.plan_timeout_s == 9.0
    answer = object()
    c.start_answer(answer)
    for _ in range(2):                                    # the call and the pipeline's retry
        with pytest.raises(GeminiError) as exc:
            c.plan(*PLAN_ARGS)
        assert exc.value.code == "timeout"
    assert timeouts == [9.0]                              # the retry sent nothing
    c.start_answer(object())                              # the next answer may ask the planner again
    with pytest.raises(GeminiError):
        c.plan(*PLAN_ARGS)
    assert len(timeouts) == 2


# ---- #341: one answer's time budget ---------------------------------------------------------------------

def test_after_a_composer_timeout_the_answer_sends_no_second_composer_request():
    """As for the planner: the composer's retry in the same answer raises at once, so the template
    writes without another wait. The next answer may call the composer again."""
    clock = Clock()
    timeouts: list[float] = []

    def slow(model, contents, config, timeout_s):
        timeouts.append(timeout_s)
        clock.now += timeout_s
        raise TimeoutError()

    c = GeminiClient(FLASH, slow, cache="off", sleep=lambda s: None, clock=clock)
    answer = object()
    c.start_answer(answer)
    for _ in range(2):                                      # the call and the pipeline's retry
        with pytest.raises(GeminiError) as exc:
            c.compose("s", "u", {"type": "object"})
        assert exc.value.code == "timeout"
    assert timeouts == [c.compose_timeout_s]                # the retry sent nothing
    c.start_answer(object())
    with pytest.raises(GeminiError):
        c.compose("s", "u", {"type": "object"})
    assert len(timeouts) == 2


def test_a_planner_timeout_leaves_the_composer_the_rest_of_the_answers_fifteen_seconds():
    """9 s planner + 5 s composer + the tools can pass 15 s: the answer's deadline cuts the composer's
    share, so every model call of one answer ends within 15 s in total."""
    clock = Clock()
    timeouts: list[float] = []

    def slow(model, contents, config, timeout_s):
        timeouts.append(timeout_s)
        clock.now += timeout_s
        raise TimeoutError()

    c = GeminiClient(FLASH, slow, cache="off", sleep=lambda s: None, clock=clock)
    started = clock.now
    c.start_answer(object())
    with pytest.raises(GeminiError):
        c.plan(*PLAN_ARGS)
    clock.now += 1.5                                        # the rules plan and the tools run
    with pytest.raises(GeminiError):
        c.compose("s", "u", {"type": "object"})
    assert c.plan_timeout_s == 9.0 and c.compose_timeout_s == 5.0
    assert timeouts[0] == 9.0 and timeouts[1] == pytest.approx(gc.ANSWER_DEADLINE_S - 9.0 - 1.5)
    assert clock.now - started <= gc.ANSWER_DEADLINE_S


def test_a_rules_planned_answer_gives_the_composer_five_seconds_not_the_rest_of_fifteen():
    """#341: an answer the rules planned makes no planner call; its composer still gets only its own
    deadline, because the template writes the same answer at once."""
    clock = Clock()
    timeouts: list[float] = []

    def slow(model, contents, config, timeout_s):
        timeouts.append(timeout_s)
        clock.now += timeout_s
        raise TimeoutError()

    c = GeminiClient(FLASH, slow, cache="off", sleep=lambda s: None, clock=clock)
    c.start_answer(object())
    with pytest.raises(GeminiError):
        c.compose("s", "u", {"type": "object"})
    assert timeouts == [5.0]


# ---- #341: the planner and the composer on their own models ---------------------------------------------

LITE = "gemini-3.5-flash-lite"


def test_the_composer_runs_on_its_own_model_and_the_planner_keeps_its_own():
    transport = FakeTransport(call_response(), text_response("{}"))
    c = GeminiClient(FLASH, transport, cache="off", fallback_model=PRO, compose_model=LITE,
                     compose_fallback_model=FLASH, sleep=lambda s: None)
    c.plan(*PLAN_ARGS)
    reply = c.compose("s", "u", {"type": "object"})
    assert [m for m, _ in transport.requests] == [FLASH, LITE] and reply.model == LITE
    assert reply.usage.cost_usd > 0                         # flash-lite has a price row


def test_a_fallback_model_gets_a_thinking_level_it_accepts():
    """The composer on flash-lite at "minimal"; when it fails with a 5xx, flash stands in, and flash
    rejects "minimal" (a 400), so it gets "low"."""
    seen = []

    def transport(model, contents, config, timeout_s):
        seen.append((model, config["thinking_config"]["thinking_level"]))
        if model == LITE:
            raise api_error(503)
        return text_response("{}")

    c = GeminiClient(FLASH, transport, cache="off", compose_model=LITE, compose_fallback_model=FLASH,
                     compose_thinking="minimal", sleep=lambda s: None)
    c.compose("s", "u", {"type": "object"})
    assert seen == [(LITE, "minimal"), (FLASH, "low")]


def test_thinking_default_sends_no_thinking_setting():
    seen = {}

    def transport(model, contents, config, timeout_s):
        seen.update(config)
        return text_response("{}")

    GeminiClient(LITE, transport, cache="off", compose_thinking="default").compose("s", "u", {"type": "object"})
    assert "thinking_config" not in seen


def test_switching_the_composer_model_or_level_never_serves_another_cached_text(tmp_path):
    transport = FakeTransport(text_response('{"n": 1}'), text_response('{"n": 2}'), text_response('{"n": 3}'))
    first = client(transport, tmp_path, compose_model=FLASH).compose("s", "u", {"type": "object"})
    other_model = client(transport, tmp_path, compose_model=LITE).compose("s", "u", {"type": "object"})
    other_level = client(transport, tmp_path, compose_model=LITE, compose_thinking="minimal").compose(
        "s", "u", {"type": "object"})
    assert not (first.cached or other_model.cached or other_level.cached) and len(transport.requests) == 3
    again = client(transport, tmp_path, compose_model=LITE).compose("s", "u", {"type": "object"})
    assert again.cached and json.loads(again.text) == {"n": 2} and len(transport.requests) == 3


def test_a_failure_streak_pauses_for_thirty_seconds_only():
    """#341: three malformed, empty or blocked responses in a row pause the model briefly; the long
    pause is kept for 429, 401, 403 and 404."""
    assert gc.FAILURE_STREAK_COOLDOWN_S == 30.0 and gc.RATE_LIMIT_COOLDOWN_S == gc.CONFIG_ERROR_COOLDOWN_S == 300.0


# ---- #250: reading an image (one request, no fallback, no bytes in the cache key) --------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic-bill-image" * 50
SCHEMA = {"type": "object", "properties": {"iban": {"type": "string"}}, "additionalProperties": False}


def test_extract_sends_one_inline_image_with_a_schema_and_no_tools():
    seen = {}

    def transport(model, contents, config, timeout_s):
        seen.update(contents=contents, config=config)
        return text_response('{"iban": "FI2112345600000785"}')

    c = GeminiClient(FLASH, transport, cache="off", fallback_model=PRO, sleep=lambda s: None)
    reply = c.extract("read the bill", "Read this bill.", PNG, "image/png", SCHEMA)
    assert reply.text == '{"iban": "FI2112345600000785"}'
    parts = seen["contents"][0]["parts"]
    assert parts[1]["inline_data"] == {"mime_type": "image/png", "data": PNG}
    assert "tools" not in seen["config"] and seen["config"]["response_json_schema"] == SCHEMA


def test_extract_caches_by_the_image_hash_and_never_stores_the_bytes(tmp_path):
    transport = FakeTransport(text_response('{"iban": "x"}'))
    c = client(transport, tmp_path)
    c.extract("s", "t", PNG, "image/png", SCHEMA)
    assert c.extract("s", "t", PNG, "image/png", SCHEMA).cached          # the same image: no request
    c.extract("s", "t", PNG + b"!", "image/png", SCHEMA)                  # another image: a request
    assert len(transport.requests) == 2
    for f in (tmp_path / "cache").glob("*.json"):
        assert b"synthetic-bill-image" not in f.read_bytes()


def test_extract_makes_one_request_without_the_fallback_model():
    transport = FakeTransport(api_error(503), text_response("{}"))
    c = client(transport, fallback_model=PRO)
    with pytest.raises(GeminiError) as exc:
        c.extract("s", "t", PNG, "image/png", SCHEMA)
    assert exc.value.code == "server" and [m for m, _ in transport.requests] == [FLASH]


@pytest.mark.parametrize("image, mime", [(b"", "image/png"), (PNG, "application/pdf"),
                                         (b"x" * (gc.MAX_INLINE_IMAGE_BYTES + 1), "image/png")])
def test_an_image_too_large_or_of_another_type_is_refused_before_sending(image, mime):
    transport = FakeTransport(text_response("{}"))
    with pytest.raises(GeminiError) as exc:
        client(transport).extract("s", "t", image, mime, SCHEMA)
    assert exc.value.code == "image" and transport.requests == []


def test_bill_readings_have_their_own_share_of_the_daily_budget(tmp_path):
    ledger = Ledger(tmp_path / "requests.jsonl", daily_cap=10, kind_caps={"extract": 2})
    transport = FakeTransport(text_response("{}"))
    c = client(transport, ledger=ledger)
    c.extract("s", "t", PNG, "image/png", SCHEMA)
    c.extract("s", "t", PNG + b"1", "image/png", SCHEMA)
    with pytest.raises(GeminiError) as exc:
        c.extract("s", "t", PNG + b"2", "image/png", SCHEMA)
    assert exc.value.code == "budget"
    assert client(FakeTransport(call_response()), ledger=ledger).plan(*PLAN_ARGS).calls   # answers still allowed
    assert ledger.count("extract") == 2 and ledger.count() == 3
