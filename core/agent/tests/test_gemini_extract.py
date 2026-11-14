"""The bill reading's call kind in the adapter (review of #250). Behaviour only: what is sent and what comes back.

- Only an answer the caller accepts is cached; a cached one it rejects is a miss (fix 1).
- A reading is independent of the answer state of the thread it runs on, both ways (fix 2).
- The extract role has its own model, thinking and cache key, and its own refusal and pause state (decision B).
- A cached reading is served while the model may not be used (decision D).
- A bad BILL_READ_DAILY_BUDGET or extract setting is the default and keeps the model on (decision C).
No key, no database, no real request.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.agent import gemini
from core.agent.gemini import make_model
from core.agent.gemini_client import ANSWER_DEADLINE_S, MAX_REQUESTS_PER_ANSWER, GeminiClient, GeminiError, Ledger
from core.agent.tests.test_gemini_client import PLAN_ARGS, FakeTransport, api_error, call_response, text_response

FLASH, LITE = "gemini-3.8-flash", "gemini-3.5-flash-lite"
PNG = b"\x89PNG\r\n\x1a\n" + b"bill" * 50
GOOD = text_response(json.dumps({"iban": "FI2112345600000785"}))
EXTRACT = ("read the bill", "Read the bill.", PNG, "image/png", {"type": "object"})


def usable(reply) -> bool:
    try:
        return not reply.blocked and bool(json.loads(reply.text))
    except (TypeError, ValueError):
        return False


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(transport, tmp_path=None, **kw):
    if tmp_path is not None:
        kw.setdefault("cache", "on")
        kw.setdefault("cache_dir", tmp_path / "cache")
    else:
        kw.setdefault("cache", "off")
    return GeminiClient(FLASH, transport, sleep=lambda s: None, **kw)


# ---- fix 1: only a usable reading is cached ------------------------------------------------------------------

@pytest.mark.parametrize("bad", [text_response("not json"), text_response("{}"),
                                 {"candidates": [{"finish_reason": "SAFETY", "content": {"parts": []}}]}])
def test_a_bad_first_answer_is_not_cached_and_the_next_read_asks_again(tmp_path, bad):
    first = FakeTransport(bad)
    make(first, tmp_path).extract(*EXTRACT, accept=usable)
    second = FakeTransport(GOOD)
    assert usable(make(second, tmp_path).extract(*EXTRACT, accept=usable)) and len(second.requests) == 1
    third = FakeTransport(GOOD)
    assert make(third, tmp_path).extract(*EXTRACT, accept=usable).cached and third.requests == []


def test_a_cached_answer_the_caller_rejects_is_a_miss(tmp_path):
    make(FakeTransport(text_response("{}")), tmp_path).extract(*EXTRACT)          # cached without a test
    again = FakeTransport(GOOD)
    reply = make(again, tmp_path).extract(*EXTRACT, accept=usable)
    assert usable(reply) and not reply.cached and len(again.requests) == 1


# ---- fix 2: independent of the thread's answer state ---------------------------------------------------------

def test_a_used_up_answer_on_the_thread_does_not_stop_a_reading():
    transport = FakeTransport(call_response())
    c = make(transport)
    c.start_answer(object())
    for _ in range(MAX_REQUESTS_PER_ANSWER):
        c.plan(*PLAN_ARGS)
    with pytest.raises(GeminiError):
        c.plan(*PLAN_ARGS)                                       # this answer has no request left
    transport.steps = [GOOD]
    assert usable(c.extract(*EXTRACT, accept=usable))


def test_a_passed_answer_deadline_does_not_stop_a_reading():
    clock = Clock()
    c = make(FakeTransport(GOOD), clock=clock)
    c.start_answer(object())
    clock.now += ANSWER_DEADLINE_S + 5
    assert usable(c.extract(*EXTRACT, accept=usable))


def test_a_reading_neither_counts_toward_nor_marks_the_threads_answer():
    transport = FakeTransport(call_response())
    c = make(transport)
    c.start_answer(object())
    for _ in range(MAX_REQUESTS_PER_ANSWER - 1):
        c.plan(*PLAN_ARGS)
    transport.steps = [TimeoutError("slow")]
    with pytest.raises(GeminiError):
        c.extract(*EXTRACT)                                      # a timed-out reading
    transport.steps = [GOOD]
    assert usable(c.extract(*EXTRACT, accept=usable))           # a second reading is still sent
    transport.steps = [call_response()]
    assert c.plan(*PLAN_ARGS).calls                              # and the answer's last request is still there


# ---- decision B: the extract role ---------------------------------------------------------------------------

def test_a_reading_uses_its_own_model():
    transport = FakeTransport(GOOD)
    make(transport, extract_model=LITE).extract(*EXTRACT)
    assert [m for m, _ in transport.requests] == [LITE]


def test_a_refused_extract_model_pauses_readings_only():
    seen = []

    def transport(model, contents, config, timeout_s):
        seen.append("tools" in config)
        if "tools" not in config:
            raise api_error(404)
        return call_response()

    c = make(transport)
    with pytest.raises(GeminiError):
        c.extract(*EXTRACT)
    with pytest.raises(GeminiError):
        c.extract(*EXTRACT)                                      # readings wait: no second request
    assert c.plan(*PLAN_ARGS).calls and c.unavailable_reason() is None    # the planner's id is not refused
    assert seen == [False, True]


def test_a_rate_limit_on_a_reading_pauses_every_kind_as_the_key_does():
    transport = FakeTransport(api_error(429), call_response())
    c = make(transport)
    with pytest.raises(GeminiError):
        c.extract(*EXTRACT)
    with pytest.raises(GeminiError):
        c.plan(*PLAN_ARGS)
    assert len(transport.requests) == 1


def test_the_planner_and_composer_settings_never_change_a_readings_cache_key(tmp_path):
    make(FakeTransport(GOOD), tmp_path).extract(*EXTRACT, accept=usable)
    other = FakeTransport(GOOD)
    c = GeminiClient(LITE, other, compose_model=FLASH, plan_thinking="high", compose_thinking="minimal",
                     plan_max_tokens=99, compose_max_tokens=77, extract_model=FLASH, cache="on",
                     cache_dir=tmp_path / "cache", sleep=lambda s: None)
    assert c.extract(*EXTRACT, accept=usable).cached and other.requests == []


# ---- decision D: a cached reading needs no model -------------------------------------------------------------

def test_a_cached_reading_is_served_out_of_budget(tmp_path):
    make(FakeTransport(GOOD), tmp_path).extract(*EXTRACT, accept=usable)
    none = FakeTransport(GOOD)
    spent = make(none, tmp_path, ledger=Ledger(tmp_path / "ledger.jsonl", daily_cap=0))
    assert spent.extract(*EXTRACT, accept=usable).cached and none.requests == []
    with pytest.raises(GeminiError):
        spent.extract("another prompt", *EXTRACT[1:], accept=usable)   # a miss needs the model
    assert none.requests == []


def test_a_cached_reading_is_served_while_the_key_is_paused(tmp_path):
    make(FakeTransport(GOOD), tmp_path).extract(*EXTRACT, accept=usable)
    transport = FakeTransport(api_error(429))
    c = make(transport, tmp_path)
    with pytest.raises(GeminiError):
        c.plan(*PLAN_ARGS)                                       # a 429 pauses every kind
    assert c.extract(*EXTRACT, accept=usable).cached and len(transport.requests) == 1
    with pytest.raises(GeminiError):
        c.extract("another prompt", *EXTRACT[1:], accept=usable)
    assert len(transport.requests) == 1


# ---- decisions B and C: settings ----------------------------------------------------------------------------

def settings(**kw):
    base = dict(gemini_api_key="test-key-not-real", gemini_model=None, gemini_cache="replay",
                gemini_cache_dir="unused", gemini_fallback_model=None, gemini_planner="rules_first", daily_budget=10)
    return SimpleNamespace(**{**base, **kw})


def test_the_extract_model_is_the_pinned_default_whatever_the_planner_uses(monkeypatch):
    monkeypatch.delenv("GEMINI_EXTRACT_MODEL", raising=False)
    c = make_model(settings(gemini_planner_model=LITE, gemini_composer_model=LITE)).client
    assert c.extract_model == gemini.DEFAULT_MODEL and c.model == LITE
    monkeypatch.setenv("GEMINI_EXTRACT_MODEL", f" {LITE} ")
    assert make_model(settings()).client.extract_model == LITE


@pytest.mark.parametrize("name, value, attr, default", [
    ("BILL_READ_DAILY_BUDGET", "abc", "bill_read_budget", gemini.DEFAULT_BILL_READ_BUDGET),
    ("BILL_READ_DAILY_BUDGET", "-3", "bill_read_budget", gemini.DEFAULT_BILL_READ_BUDGET),
    ("GEMINI_EXTRACT_THINKING", "loud", "gemini_extract_thinking", gemini.DEFAULT_THINKING),
    ("GEMINI_EXTRACT_TIMEOUT_S", "99", "gemini_extract_timeout_s", gemini.DEFAULT_EXTRACT_TIMEOUT_S),
    ("GEMINI_EXTRACT_TIMEOUT_S", "soon", "gemini_extract_timeout_s", gemini.DEFAULT_EXTRACT_TIMEOUT_S),
])
def test_a_bad_bill_setting_is_the_default_with_one_log_line_and_the_model_stays_on(monkeypatch, caplog, name,
                                                                                       value, attr, default):
    from core.agent.gemini import make_agent_model
    from core.agent.rules import RuleModel

    gemini._BAD_SETTING_LOGGED.discard(name)
    monkeypatch.setenv(name, value)
    for _ in range(3):
        assert getattr(gemini.GeminiSettings(_env_file=None), attr) == default
    assert sum(name in r.getMessage() for r in caplog.records) == 1
    assert not isinstance(make_agent_model(settings()), RuleModel)


# ---- #511: single flight for a cold miss; cache-only readings ------------------------------------------------

def test_concurrent_cold_readings_of_one_image_send_one_request(tmp_path):
    import threading

    started, release, sent = threading.Event(), threading.Event(), []

    def slow(model, contents, config, timeout_s):
        sent.append(model)
        started.set()
        release.wait(5)
        return GOOD

    c = make(slow, tmp_path)
    replies = []
    threads = [threading.Thread(target=lambda: replies.append(c.extract(*EXTRACT, accept=usable))) for _ in range(5)]
    for t in threads:
        t.start()
    assert started.wait(5)
    release.set()
    for t in threads:
        t.join(10)
    assert len(sent) == 1 and len(replies) == 5 and all(usable(r) for r in replies)
    assert sum(r.cached for r in replies) == 4               # the others answered from the cache it wrote


def test_a_cache_only_reading_never_sends_a_request(tmp_path):
    none = FakeTransport(GOOD)
    c = make(none, tmp_path)
    with pytest.raises(GeminiError) as exc:
        c.extract(*EXTRACT, accept=usable, cache_only=True)
    assert exc.value.code == "cache_miss" and none.requests == []
    c.extract(*EXTRACT, accept=usable)
    assert c.extract(*EXTRACT, accept=usable, cache_only=True).cached and len(none.requests) == 1
