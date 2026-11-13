"""Layer 1 of the Gemini adapter (issue #66): one Gemini API call, with every SDK detail inside.

Two calls (docs/design/agent-core.md sections 7.1, 7.2 and 12):
- plan: function calling over the tool declarations, mode ANY (the model must call a function),
  automatic function calling off (the pipeline runs the tools itself).
- compose: a tool-free call whose output is JSON constrained by a JSON Schema.

Both set the thinking level explicitly (Gemini 3 models think by default, and thoughts count
against max_output_tokens and are billed as output). The SDK is `google-genai`; parameter names
come from its documentation (Context7 /googleapis/python-genai) and the Gemini API docs, checked
on 2026-11-14.

Around each call, within one deadline per call:
- 503 and other 5xx ("model overwhelmed"): up to two retries with a pause, then one attempt on the
  fallback model if one is set (flash <-> pro), then GeminiError and a pause of OVERLOAD_COOLDOWN_S
  (so the pipeline's retry and the next questions do not add requests during an outage);
- 429 (a spending or rate limit): no retry. The client stops calling for RATE_LIMIT_COOLDOWN_S, so
  the pipeline's own retry cannot send a second request; the pipeline falls back to the rule
  planner and the template answer. 401, 403 and 404 (a key or model id the API refuses) pause the
  same way;
- a timeout is not retried here (the pipeline retries a failed call once, then falls back);
- a response that cannot be used (empty, cut at max_output_tokens, malformed function call)
  raises GeminiError with a short code; no request or response text is ever put in an error.
Request budget (the dev service is public): every request that goes to the network is appended to a
ledger (JSON lines under var/, no prompt or response text) and logged with the day's running total. A
request that would pass the daily budget is not sent, and none is sent while the switch file exists
(var/model-off): the call raises GeminiError("budget") or GeminiError("disabled"), and the pipeline
answers from the rule planner and the template. Both are read on every call, so neither needs a
restart; the ledger is a file, so a restart does not reset the count.
Cache: on disk, keyed by a hash of the whole request (model, call kind, contents, config). Only
usable responses are stored, and only their candidates, prompt feedback, usage and model version
(no HTTP headers). Mode "replay" never reaches the network: a miss raises.
Each call reports its tokens (prompt, thoughts, output), its cost in USD and its live latency (a cache
hit reports the latency of the call that filled it). The API key is passed to the SDK client only;
it is never logged, cached, written to the ledger or part of a cache key.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("core.agent.gemini")

# USD per 1M tokens on the paid Standard tier: (input, output). Thinking tokens are billed at the
# output rate. Source: the Gemini API pricing page, checked 2026-11-14. Flash: price through
# 2026-12-31. Pro: prompts up to 200k tokens (ours are far below).
PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.1-pro-preview": (2.00, 12.00),
}
SERVER_RETRY_CODES = {500, 502, 503, 504}
SERVER_RETRY_BACKOFF_S = (0.5, 1.5)     # pauses before the first and the second retry
RATE_LIMIT_COOLDOWN_S = 300.0           # after a 429, no request for this long
OVERLOAD_COOLDOWN_S = 30.0              # after 5xx on every attempt and on the fallback, no request for this long
# A key or model the API refuses (401, 403, 404) will not work on a retry or on the next question:
# no request for this long, so a wrong setting cannot burn the request budget.
CONFIG_ERROR_CODES = {401, 403, 404}
CONFIG_ERROR_COOLDOWN_S = 300.0
MIN_ATTEMPT_S = 1.0                     # an attempt needs at least this much of the deadline left
# The Gemini API rejects a request whose server deadline (the X-Server-Timeout header, which the SDK
# fills from the client timeout) is under 10 s with HTTP 400. The client-side timeout stays ours.
MIN_SERVER_DEADLINE_S = 10
BLOCK_REASONS = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION", "MODEL_ARMOR"}
UNUSABLE_REASONS = {"MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL", "TOO_MANY_TOOL_CALLS",
                    "MISSING_THOUGHT_SIGNATURE", "MALFORMED_RESPONSE"}
STORED_FIELDS = ("candidates", "prompt_feedback", "usage_metadata", "model_version")
CACHE_FORMAT = 1


class GeminiError(RuntimeError):
    """A call that produced nothing usable. `code` is short and never holds request or response text:
    timeout, rate_limited, server, network, http_<status>, empty, truncated, malformed_function_call,
    budget, disabled, cache_miss, error."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CallUsage:
    prompt_tokens: int = 0
    thought_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class Reply:
    """A usable model response as plain JSON data (no SDK objects)."""

    content: dict[str, Any]              # the model turn as received, thought signatures included
    calls: list[dict[str, Any]]          # function calls: {"name", "args", "id"}
    text: str                            # the text parts, thoughts left out
    finish_reason: str
    usage: CallUsage
    latency_ms: int                      # of the live call, also on a cache hit
    model: str = ""                      # the model that answered (the fallback model, if it was used)
    cached: bool = False
    blocked: bool = False                # a safety block: no content to use


@dataclass(frozen=True)
class CallRecord:
    """One attempt, for the latency, token, cost and request-count report. No prompt or response text."""

    kind: str                            # plan | compose
    model: str
    latency_ms: int
    cached: bool
    usage: CallUsage
    finish_reason: str | None = None
    error: str | None = None
    network: bool = False                # a request was sent (counts against the request budget)


# (model, contents, config, timeout_s) -> the GenerateContentResponse as JSON data
Transport = Callable[[str, list[dict[str, Any]], dict[str, Any], float], dict[str, Any]]


class SdkTransport:
    """The real transport: google-genai's generate_content. The SDK's own retries stay off. The client
    gives up after timeout_s; the server deadline is never below MIN_SERVER_DEADLINE_S."""

    def __init__(self, api_key: str) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)

    def __call__(self, model: str, contents: list[dict[str, Any]], config: dict[str, Any],
                 timeout_s: float) -> dict[str, Any]:
        from google.genai import types

        server_deadline = max(MIN_SERVER_DEADLINE_S, math.ceil(timeout_s))
        cfg = types.GenerateContentConfig.model_validate(
            {**config, "http_options": {"timeout": int(timeout_s * 1000),
                                        "headers": {"X-Server-Timeout": str(server_deadline)}}})
        response = self._client.models.generate_content(
            model=model, contents=[types.Content.model_validate(c) for c in contents], config=cfg)
        return response.model_dump(mode="json", exclude_none=True)


class Ledger:
    """Counts the requests sent to the Gemini API per UTC day, in a JSON-lines file shared by every
    process that uses the same path. Each line: time, call kind, model, result, latency, tokens.
    `off_switch`: while this file exists, no request is sent."""

    def __init__(self, path: Path, daily_cap: int | None, off_switch: Path | None = None) -> None:
        self.path = Path(path)
        self.daily_cap = daily_cap
        self.off_switch = Path(off_switch) if off_switch is not None else None
        self._lock = threading.Lock()
        self._sent: tuple[str, int] = ("", 0)   # (UTC day, requests this process sent): the floor of the count

    def disabled(self) -> bool:
        return self.off_switch is not None and self.off_switch.exists()

    def today(self) -> int:
        """Requests today: the ledger file's count, and never less than this process sent, so an
        unwritable or deleted ledger cannot reopen the budget."""
        day = f"{datetime.now(timezone.utc):%Y-%m-%d}"
        prefix = f'{{"ts": "{day}'
        try:
            with self.path.open(encoding="utf-8") as f:
                counted = sum(1 for line in f if line.startswith(prefix))
        except OSError:
            counted = 0
        sent_day, sent = self._sent
        return max(counted, sent if sent_day == day else 0)

    def allow(self) -> bool:
        return self.daily_cap is None or self.today() < self.daily_cap

    def add(self, kind: str, model: str, result: str, latency_ms: int, usage: CallUsage) -> int:
        """Append one request; returns the day's count after it."""
        line = json.dumps({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "kind": kind,
                           "model": model, "result": result, "latency_ms": latency_ms,
                           "tokens": [usage.prompt_tokens, usage.thought_tokens, usage.output_tokens]})
        with self._lock:
            day = f"{datetime.now(timezone.utc):%Y-%m-%d}"
            self._sent = (day, (self._sent[1] if self._sent[0] == day else 0) + 1)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except OSError:
            log.warning("gemini request ledger not written")
        return self.today()


def cost_usd(model: str, prompt: int, thoughts: int, output: int) -> float:
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return round((prompt * price_in + (thoughts + output) * price_out) / 1_000_000, 8)


def _usage(model: str, meta: dict[str, Any] | None) -> CallUsage:
    meta = meta or {}
    prompt = int(meta.get("prompt_token_count") or 0)
    thoughts = int(meta.get("thoughts_token_count") or 0)
    output = int(meta.get("candidates_token_count") or 0)
    return CallUsage(prompt, thoughts, output, cost_usd(model, prompt, thoughts, output))


def _error_code(exc: BaseException) -> tuple[str, int | None]:
    """A short code for an exception from the transport, and its HTTP status if it has one."""
    if isinstance(exc, GeminiError):
        return exc.code, None
    status = getattr(exc, "code", None)
    if isinstance(status, int) and 100 <= status < 600:
        if status == 429:
            return "rate_limited", status
        if status >= 500:
            return "server", status
        return f"http_{status}", status
    name = type(exc).__name__
    if "Timeout" in name or isinstance(exc, TimeoutError):
        return "timeout", None
    if "Connect" in name or "Network" in name or isinstance(exc, ConnectionError):
        return "network", None
    return "error", None


def scrub(raw: dict[str, Any]) -> dict[str, Any]:
    """The parts of a response worth keeping: no HTTP headers, ids or SDK bookkeeping."""
    return {k: raw[k] for k in STORED_FIELDS if k in raw}


def parse(model: str, raw: dict[str, Any], latency_ms: int, cached: bool = False) -> Reply:
    """A Reply from a GenerateContentResponse as JSON. Raises GeminiError when nothing is usable."""
    usage = _usage(model, raw.get("usage_metadata"))
    if (raw.get("prompt_feedback") or {}).get("block_reason"):
        return Reply({}, [], "", "PROMPT_BLOCKED", usage, latency_ms, model, cached, blocked=True)
    candidates = raw.get("candidates") or []
    if not candidates:
        raise GeminiError("empty")
    candidate = candidates[0]
    finish = str(candidate.get("finish_reason") or "")
    if finish in BLOCK_REASONS:
        return Reply({}, [], "", finish, usage, latency_ms, model, cached, blocked=True)
    if finish == "MAX_TOKENS":
        raise GeminiError("truncated")
    if finish in UNUSABLE_REASONS:
        raise GeminiError(finish.lower())
    content = candidate.get("content") or {}
    parts = content.get("parts") or []
    calls = [{"name": p["function_call"].get("name") or "", "args": p["function_call"].get("args") or {},
              "id": p["function_call"].get("id")} for p in parts if p.get("function_call")]
    text = "".join(p.get("text") or "" for p in parts if not p.get("thought"))
    if not calls and not text.strip():
        raise GeminiError("empty")
    return Reply(content, calls, text, finish, usage, latency_ms, model, cached)


class GeminiClient:
    """Plan and compose calls against one pinned model id, with an optional fallback model.

    cache: "on" (read and write `cache_dir`), "off", or "replay" (read only; a miss raises
    GeminiError("cache_miss") and the network is never used, for tests and offline runs).
    """

    def __init__(self, model: str, transport: Transport | None, *, fallback_model: str | None = None,
                 cache: str = "on", cache_dir: Path | None = None, ledger: Ledger | None = None,
                 plan_timeout_s: float = 8.0, compose_timeout_s: float = 10.0,
                 plan_thinking: str = "low", compose_thinking: str = "low",
                 plan_max_tokens: int = 4096, compose_max_tokens: int = 4096,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
        if cache not in ("on", "off", "replay"):
            raise ValueError("cache must be on, off or replay")
        if cache != "off" and cache_dir is None:
            raise ValueError("a cache needs cache_dir")
        if cache != "replay" and transport is None:
            raise ValueError("a transport is needed unless the cache is in replay mode")
        self.model = model
        self.fallback_model = fallback_model if fallback_model != model else None
        self.transport = transport
        self.cache = cache
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.ledger = ledger
        self.plan_timeout_s = plan_timeout_s
        self.compose_timeout_s = compose_timeout_s
        self.plan_thinking = plan_thinking
        self.compose_thinking = compose_thinking
        self.plan_max_tokens = plan_max_tokens
        self.compose_max_tokens = compose_max_tokens
        self.sleep = sleep
        self.clock = clock
        self.calls: list[CallRecord] = []
        self._paused_until = 0.0         # set by a 429 or by an outage (5xx everywhere)
        self._pause_code = "rate_limited"
        self._lock = threading.Lock()

    # ---- the two calls ---------------------------------------------------------------------------

    def plan(self, system: str, contents: list[dict[str, Any]], declarations: list[dict[str, Any]]) -> Reply:
        config = {
            "system_instruction": system,
            "tools": [{"function_declarations": declarations}],
            "tool_config": {"function_calling_config": {"mode": "ANY"}},
            "automatic_function_calling": {"disable": True},
            "thinking_config": {"thinking_level": self.plan_thinking},
            "max_output_tokens": self.plan_max_tokens,
        }
        return self._call("plan", contents, config, self.plan_timeout_s)

    def compose(self, system: str, user_text: str, schema: dict[str, Any]) -> Reply:
        contents = [{"role": "user", "parts": [{"text": user_text}]}]
        config = {
            "system_instruction": system,
            "response_mime_type": "application/json",
            "response_json_schema": schema,
            "thinking_config": {"thinking_level": self.compose_thinking},
            "max_output_tokens": self.compose_max_tokens,
        }
        return self._call("compose", contents, config, self.compose_timeout_s)

    # ---- cache -----------------------------------------------------------------------------------

    def cache_key(self, model: str, kind: str, contents: list[dict[str, Any]], config: dict[str, Any]) -> str:
        request = {"format": CACHE_FORMAT, "model": model, "kind": kind, "contents": contents, "config": config}
        canonical = json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        assert self.cache_dir is not None
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> dict[str, Any] | None:
        if self.cache == "off":
            return None
        try:
            return json.loads(self._cache_path(key).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            log.warning("gemini cache entry unreadable; calling the model")
            return None

    def _write_cache(self, key: str, model: str, kind: str, raw: dict[str, Any], latency_ms: int) -> None:
        if self.cache != "on":
            return
        path = self._cache_path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".tmp{os.getpid()}")
            tmp.write_text(json.dumps({"format": CACHE_FORMAT, "model": model, "kind": kind,
                                       "latency_ms": latency_ms, "response": scrub(raw)}, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            log.warning("gemini cache entry not written")

    # ---- one call --------------------------------------------------------------------------------

    def _record(self, kind: str, model: str, latency_ms: int, usage: CallUsage, *, cached: bool = False,
                finish: str | None = None, error: str | None = None, network: bool = False) -> None:
        self.calls.append(CallRecord(kind, model, latency_ms, cached, usage, finish, error, network))
        if network and self.ledger is not None:
            total = self.ledger.add(kind, model, error or "ok", latency_ms, usage)
            log.info("gemini request %d of %s today (%s %s, %s)", total, self.ledger.daily_cap, kind, model, error or "ok")
        log.info("gemini %s model=%s cached=%s latency_ms=%d tokens prompt=%d thoughts=%d output=%d "
                 "cost_usd=%.6f%s", kind, model, cached, latency_ms, usage.prompt_tokens,
                 usage.thought_tokens, usage.output_tokens, usage.cost_usd, f" error={error}" if error else "")

    def _call(self, kind: str, contents: list[dict[str, Any]], config: dict[str, Any], timeout_s: float) -> Reply:
        key = self.cache_key(self.model, kind, contents, config)
        entry = self._read_cache(key)
        if entry is not None:
            reply = parse(self.model, entry["response"], int(entry.get("latency_ms") or 0), cached=True)
            self._record(kind, self.model, reply.latency_ms, reply.usage, cached=True, finish=reply.finish_reason)
            return reply
        if self.cache == "replay":
            self._record(kind, self.model, 0, CallUsage(), error="cache_miss")
            raise GeminiError("cache_miss")

        deadline = self.clock() + timeout_s
        try:
            return self._attempts(self.model, key, kind, contents, config, deadline,
                                  retries=len(SERVER_RETRY_BACKOFF_S))
        except GeminiError as exc:
            if exc.code != "server":
                raise
            if self.fallback_model is None:
                self._pause(OVERLOAD_COOLDOWN_S, "server")
                raise
        # The primary model stayed overwhelmed: one attempt on the fallback model, same deadline.
        key = self.cache_key(self.fallback_model, kind, contents, config)
        try:
            return self._attempts(self.fallback_model, key, kind, contents, config, deadline, retries=0,
                                  fallback=True)
        except GeminiError as exc:
            if exc.code in {f"http_{c}" for c in CONFIG_ERROR_CODES}:
                # The fallback model is refused (for example an id this key cannot use): stop using it,
                # but do not pause the primary model for longer than an overload.
                log.error("gemini fallback model refused (%s); fallback turned off", exc.code)
                self.fallback_model = None
            self._pause(OVERLOAD_COOLDOWN_S, "server")
            raise GeminiError("server") from None

    def _pause(self, seconds: float, code: str) -> None:
        with self._lock:
            self._paused_until = max(self._paused_until, self.clock() + seconds)
            self._pause_code = code
        log.error("gemini %s: model calls paused for %d s; answers use the rule planner and the template",
                  code, seconds)

    def _attempts(self, model: str, key: str, kind: str, contents: list[dict[str, Any]], config: dict[str, Any],
                  deadline: float, retries: int, fallback: bool = False) -> Reply:
        assert self.transport is not None
        attempt = 0
        while True:
            with self._lock:
                paused, code = self.clock() < self._paused_until, self._pause_code
            if paused:
                self._record(kind, model, 0, CallUsage(), error=f"{code} (paused)")
                raise GeminiError(code)
            if self.ledger is not None and self.ledger.disabled():
                self._record(kind, model, 0, CallUsage(), error="disabled")
                raise GeminiError("disabled")
            if self.ledger is not None and not self.ledger.allow():
                self._record(kind, model, 0, CallUsage(), error="budget")
                log.warning("gemini daily budget of %s requests reached; answers use the template", self.ledger.daily_cap)
                raise GeminiError("budget")
            remaining = deadline - self.clock()
            if remaining < MIN_ATTEMPT_S:
                self._record(kind, model, 0, CallUsage(), error="timeout (no time left)")
                raise GeminiError("timeout")
            t = self.clock()
            try:
                raw = self.transport(model, contents, config, remaining)
            except Exception as exc:  # noqa: BLE001 - only a short code leaves this function
                code, status = _error_code(exc)
                ms = int((self.clock() - t) * 1000)
                if status == 429:
                    self._pause(RATE_LIMIT_COOLDOWN_S, "rate_limited")
                elif status in CONFIG_ERROR_CODES and not fallback:
                    self._pause(CONFIG_ERROR_COOLDOWN_S, code)
                if status in SERVER_RETRY_CODES and attempt < retries:
                    pause = SERVER_RETRY_BACKOFF_S[attempt]
                    if deadline - self.clock() - pause >= MIN_ATTEMPT_S:
                        self._record(kind, model, ms, CallUsage(), error=f"{code} (retrying)", network=True)
                        attempt += 1
                        self.sleep(pause)
                        continue
                self._record(kind, model, ms, CallUsage(), error=code, network=True)
                raise GeminiError(code) from None
            latency_ms = int((self.clock() - t) * 1000)
            try:
                reply = parse(model, raw, latency_ms)
            except GeminiError as exc:
                finish = str((raw.get("candidates") or [{}])[0].get("finish_reason") or "")
                self._record(kind, model, latency_ms, _usage(model, raw.get("usage_metadata")), finish=finish,
                             error=exc.code, network=True)
                raise
            self._write_cache(key, model, kind, raw, latency_ms)
            self._record(kind, model, latency_ms, reply.usage, finish=reply.finish_reason, network=True)
            return reply
