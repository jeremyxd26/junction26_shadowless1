"""Layer 1 of the Gemini adapter (issue #66): one Gemini API call, with every SDK detail inside.

Two calls (docs/design/agent-core.md sections 7.1, 7.2 and 12):
- plan: function calling over the tool declarations, mode ANY (the model must call a function),
  automatic function calling off (the pipeline runs the tools itself).
- compose: a tool-free call whose output is JSON constrained by a JSON Schema.

Both set the thinking level explicitly (Gemini 3 models think by default, and thoughts count
against max_output_tokens and are billed as output). The SDK is `google-genai`; parameter names
come from its documentation (Context7 /googleapis/python-genai) and the Gemini API docs, checked
on 2026-11-14.

Around each call:
- one deadline per call; a 429 or 5xx is retried once inside that deadline, a timeout is not
  (the pipeline retries a failed call once, then falls back to the rule planner and the template);
- a response that cannot be used (empty, cut at max_output_tokens, malformed function call)
  raises GeminiError with a short code; no request or response text is ever put in an error;
- an on-disk cache keyed by a hash of the whole request (model, call kind, contents, config). Only
  usable responses are stored. Mode "replay" never reaches the network: a miss raises;
- tokens (prompt, thoughts, output) and the cost in USD of every call, and the live latency (a
  cache hit reports the latency of the call that filled it).
The API key is passed to the SDK client only. It is never logged, cached or part of a cache key.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
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
RETRY_CODES = {429, 500, 502, 503, 504}
RETRY_BACKOFF_S = {429: 1.0}            # other retryable codes wait DEFAULT_BACKOFF_S
DEFAULT_BACKOFF_S = 0.5
MIN_ATTEMPT_S = 1.0                     # a retry needs at least this much of the deadline left
BLOCK_REASONS = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION", "MODEL_ARMOR"}
UNUSABLE_REASONS = {"MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL", "TOO_MANY_TOOL_CALLS",
                    "MISSING_THOUGHT_SIGNATURE", "MALFORMED_RESPONSE"}
CACHE_FORMAT = 1


class GeminiError(RuntimeError):
    """A call that produced nothing usable. `code` is short and never holds request or response text:
    timeout, rate_limited, server, network, http_<status>, empty, truncated, malformed_function_call,
    cache_miss, error."""

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
    cached: bool = False
    blocked: bool = False                # a safety block: no content to use


@dataclass(frozen=True)
class CallRecord:
    """One call, for the latency, token and cost report. Holds no prompt or response text."""

    kind: str                            # plan | compose
    model: str
    latency_ms: int
    cached: bool
    usage: CallUsage
    finish_reason: str | None = None
    error: str | None = None


# (model, contents, config, timeout_s) -> the GenerateContentResponse as JSON data
Transport = Callable[[str, list[dict[str, Any]], dict[str, Any], float], dict[str, Any]]


class SdkTransport:
    """The real transport: google-genai's generate_content. The SDK's own retries stay off."""

    def __init__(self, api_key: str) -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)

    def __call__(self, model: str, contents: list[dict[str, Any]], config: dict[str, Any],
                 timeout_s: float) -> dict[str, Any]:
        from google.genai import types

        cfg = types.GenerateContentConfig.model_validate(
            {**config, "http_options": {"timeout": int(timeout_s * 1000)}})
        response = self._client.models.generate_content(
            model=model, contents=[types.Content.model_validate(c) for c in contents], config=cfg)
        return response.model_dump(mode="json", exclude_none=True)


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


def parse(model: str, raw: dict[str, Any], latency_ms: int, cached: bool = False) -> Reply:
    """A Reply from a GenerateContentResponse as JSON. Raises GeminiError when nothing is usable."""
    usage = _usage(model, raw.get("usage_metadata"))
    if (raw.get("prompt_feedback") or {}).get("block_reason"):
        return Reply({}, [], "", "PROMPT_BLOCKED", usage, latency_ms, cached, blocked=True)
    candidates = raw.get("candidates") or []
    if not candidates:
        raise GeminiError("empty")
    candidate = candidates[0]
    finish = str(candidate.get("finish_reason") or "")
    if finish in BLOCK_REASONS:
        return Reply({}, [], "", finish, usage, latency_ms, cached, blocked=True)
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
    return Reply(content, calls, text, finish, usage, latency_ms, cached)


class GeminiClient:
    """Plan and compose calls against one pinned model id.

    cache: "on" (read and write `cache_dir`), "off", or "replay" (read only; a miss raises
    GeminiError("cache_miss") and the network is never used, for tests and offline runs).
    """

    def __init__(self, model: str, transport: Transport | None, *, cache: str = "on",
                 cache_dir: Path | None = None, plan_timeout_s: float = 10.0, compose_timeout_s: float = 15.0,
                 plan_thinking: str = "low", compose_thinking: str = "low",
                 plan_max_tokens: int = 4096, compose_max_tokens: int = 4096,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.perf_counter) -> None:
        if cache not in ("on", "off", "replay"):
            raise ValueError("cache must be on, off or replay")
        if cache != "off" and cache_dir is None:
            raise ValueError("a cache needs cache_dir")
        if cache != "replay" and transport is None:
            raise ValueError("a transport is needed unless the cache is in replay mode")
        self.model = model
        self.transport = transport
        self.cache = cache
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.plan_timeout_s = plan_timeout_s
        self.compose_timeout_s = compose_timeout_s
        self.plan_thinking = plan_thinking
        self.compose_thinking = compose_thinking
        self.plan_max_tokens = plan_max_tokens
        self.compose_max_tokens = compose_max_tokens
        self.sleep = sleep
        self.clock = clock
        self.calls: list[CallRecord] = []

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

    # ---- internals -------------------------------------------------------------------------------

    def cache_key(self, kind: str, contents: list[dict[str, Any]], config: dict[str, Any]) -> str:
        request = {"format": CACHE_FORMAT, "model": self.model, "kind": kind, "contents": contents, "config": config}
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

    def _write_cache(self, key: str, kind: str, raw: dict[str, Any], latency_ms: int) -> None:
        if self.cache != "on":
            return
        path = self._cache_path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".tmp{os.getpid()}")
            tmp.write_text(json.dumps({"format": CACHE_FORMAT, "model": self.model, "kind": kind,
                                       "latency_ms": latency_ms, "response": raw}, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(tmp, path)
        except OSError:
            log.warning("gemini cache entry not written")

    def _record(self, kind: str, latency_ms: int, cached: bool, usage: CallUsage,
                finish: str | None = None, error: str | None = None) -> None:
        self.calls.append(CallRecord(kind, self.model, latency_ms, cached, usage, finish, error))
        log.info("gemini %s model=%s cached=%s latency_ms=%d tokens prompt=%d thoughts=%d output=%d "
                 "cost_usd=%.6f%s", kind, self.model, cached, latency_ms, usage.prompt_tokens,
                 usage.thought_tokens, usage.output_tokens, usage.cost_usd, f" error={error}" if error else "")

    def _call(self, kind: str, contents: list[dict[str, Any]], config: dict[str, Any], timeout_s: float) -> Reply:
        key = self.cache_key(kind, contents, config)
        entry = self._read_cache(key)
        if entry is not None:
            reply = parse(self.model, entry["response"], int(entry.get("latency_ms") or 0), cached=True)
            self._record(kind, reply.latency_ms, True, reply.usage, reply.finish_reason)
            return reply
        if self.cache == "replay":
            self._record(kind, 0, False, CallUsage(), error="cache_miss")
            raise GeminiError("cache_miss")
        assert self.transport is not None

        started = self.clock()
        attempt = 0
        while True:
            attempt += 1
            t = self.clock()
            remaining = timeout_s - (t - started)
            try:
                raw = self.transport(self.model, contents, config, max(remaining, MIN_ATTEMPT_S))
            except Exception as exc:  # noqa: BLE001 - only a short code leaves this function
                code, status = _error_code(exc)
                wait = RETRY_BACKOFF_S.get(status or 0, DEFAULT_BACKOFF_S)
                left = timeout_s - (self.clock() - started) - wait
                if status in RETRY_CODES and attempt == 1 and left >= MIN_ATTEMPT_S:
                    self._record(kind, int((self.clock() - t) * 1000), False, CallUsage(), error=f"{code} (retrying)")
                    self.sleep(wait)
                    continue
                self._record(kind, int((self.clock() - t) * 1000), False, CallUsage(), error=code)
                raise GeminiError(code) from None
            latency_ms = int((self.clock() - t) * 1000)
            try:
                reply = parse(self.model, raw, latency_ms)
            except GeminiError as exc:
                self._record(kind, latency_ms, False, _usage(self.model, raw.get("usage_metadata")),
                             str((raw.get("candidates") or [{}])[0].get("finish_reason") or ""), exc.code)
                raise
            self._write_cache(key, kind, raw, latency_ms)
            self._record(kind, latency_ms, False, reply.usage, reply.finish_reason)
            return reply


@dataclass
class UsageSummary:
    """Totals over a list of CallRecords, for reports."""

    calls: int = 0
    live_calls: int = 0
    errors: int = 0
    prompt_tokens: int = 0
    thought_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latencies_ms: list[int] = field(default_factory=list)

    @classmethod
    def of(cls, records: list[CallRecord]) -> UsageSummary:
        s = cls()
        for r in records:
            s.calls += 1
            s.live_calls += not r.cached and r.error != "cache_miss"
            s.errors += r.error is not None
            s.prompt_tokens += r.usage.prompt_tokens
            s.thought_tokens += r.usage.thought_tokens
            s.output_tokens += r.usage.output_tokens
            s.cost_usd += r.usage.cost_usd
            if r.error is None:
                s.latencies_ms.append(r.latency_ms)
        return s
