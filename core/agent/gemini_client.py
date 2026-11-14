"""Layer 1 of the Gemini adapter (issue #66): one Gemini API call, with every SDK detail inside.

Two calls (docs/design/agent-core.md sections 7.1, 7.2 and 12):
- plan: function calling over the tool declarations, mode ANY (the model must call a function),
  automatic function calling off (the pipeline runs the tools itself).
- compose: a tool-free call whose output is JSON constrained by a JSON Schema.

Both set the thinking level explicitly (Gemini 3 models think by default, and thoughts count
against max_output_tokens and are billed as output). The SDK is `google-genai`; parameter names
come from its documentation (Context7 /googleapis/python-genai) and the Gemini API docs, checked
on 2026-11-14.

Request policy. The model account is shared and policed, and the dev service is public, so every
request is reserved, bounded and counted:
- One attempt per call on the active model. The pipeline already retries a failed call once, so
  this layer does not retry the same model again: retries are never multiplied at two levels. After a
  timeout, a network error or a 5xx (on the fallback too), the pipeline's retry in that answer sends no
  second request of the same kind: the rules plan, or the template writes at once (#341).
- One answer's time adds up: the planner gets 9 s and the composer 5 s, and every call of the answer
  also ends by its deadline of ANSWER_DEADLINE_S (15 s), so the composer gets whatever is left when
  that is less. A rules-planned answer gives the composer its own 5 s, never the whole rest of the
  15 s: the template writes the same answer in milliseconds, so a slow draft is not worth the wait.
- 5xx ("model overwhelmed"): one attempt on the fallback model (flash <-> pro), if one is set. When
  the fallback answers, the primary model is skipped for PRIMARY_SKIP_S, so an outage of the
  primary costs one request per call, not two. When both fail, that call fails; nothing is paused.
- 429 (a spending or rate limit): no further request for RATE_LIMIT_COOLDOWN_S. 401 and 403 (the key
  is refused): the same pause, for every role. 404 (a model id the key cannot use): that id is refused
  from then on and its roles use their fallback, within the same call; nothing is paused, and the log
  says so once (#383). A refused fallback turns itself off, also while it serves a skip window.
- A timeout, a network error or a 5xx fails that one call and never pauses the model for other users
  (#341): it is usually one slow or unlucky question, not a broken model. The answer it belongs to
  sends no second request of the same kind. Only 429, 401 and 403 (and the failure streak below)
  pause the model for everyone.
- Any other failure (400, an empty or cut response, a malformed call, a composer safety block): after
  FAILURE_STREAK_LIMIT failures in a row in one role, a short pause of FAILURE_STREAK_COOLDOWN_S for that
  role only (a blocked response is usually about one user's question, so it must not stop the model for
  long, and never the other role).
- The planner and the composer may run on different models with their own thinking level and
  timeout (GEMINI_PLANNER_* and GEMINI_COMPOSER_* in gemini.py), for example a fast composer. Each
  role has its own fallback; a fallback model gets the role's thinking level when it supports it,
  else "low". The model and the thinking level are part of the cache key.
- Per answer: at most MAX_REQUESTS_PER_ANSWER requests and one deadline of ANSWER_DEADLINE_S for
  every model call of the answer (the model starts an answer with start_answer). Past either, the
  call raises at once and the pipeline answers from the rule planner and the template.
- The ledger (JSON lines under var/, no prompt or response text) reserves a slot before a request is
  sent and records it after: at most `daily_cap` requests in any rolling 24 hours and at most
  MAX_IN_FLIGHT at the same time. While the switch file exists (var/model-off), nothing is sent.
  Each request is logged with the running total on the service's log ("uvicorn.error").
Every refusal raises GeminiError with a short code; no request or response text is ever put in an
error, and the pipeline then answers from the rule planner and the template.

Cache: on disk, keyed by a hash of the whole request (model, call kind, contents, config). It keeps
usable responses and safety blocks (so a repeated blocked request costs nothing), and only their
candidates, prompt feedback, usage and model version (no HTTP headers). Mode "replay" never reaches
the network: a miss raises.
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
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("core.agent.gemini")
# The service's own log: uvicorn configures this logger with a handler at INFO, so the running
# total of requests and every pause are visible in the service log (our live view of the budget).
ops_log = logging.getLogger("uvicorn.error")

# USD per 1M tokens on the paid Standard tier: (input, output). Thinking tokens are billed at the
# output rate. Source: the Gemini API pricing page, checked 2026-11-14. Flash: price through
# 2026-12-31. Pro: prompts up to 200k tokens (ours are far below).
PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.1-pro-preview": (2.00, 12.00),
    "gemini-3.5-flash-lite": (0.30, 2.50),     # stable since 2026-07-21; the composer candidate (#341, #169)
}
# The thinking levels each model accepts (the vendor's thinking page, checked 2026-11-14). A level a model
# rejects is a 400, so a fallback model gets "low" instead. "default" sends no thinking setting at all.
THINKING_LEVELS = {
    "gemini-3.8-flash": {"low", "medium", "high"},
    "gemini-3.1-pro-preview": {"low", "medium", "high"},
    "gemini-3.5-flash-lite": {"minimal", "low", "medium", "high"},
}
THINKING_CHOICES = ("default", "minimal", "low", "medium", "high")
SERVER_ERROR_CODES = {500, 502, 503, 504}
RATE_LIMIT_COOLDOWN_S = 300.0           # after a 429, no request for this long
PRIMARY_SKIP_S = 180.0                  # after the fallback answered, call it directly for this long
CONFIG_ERROR_CODES = {401, 403, 404}    # a key or model the API refuses: no retry will help
CONFIG_ERROR_COOLDOWN_S = 300.0
FAILURE_STREAK_LIMIT = 3                # other failures in a row before a pause
FAILURE_STREAK_COOLDOWN_S = 30.0        # short: the same harm to other users as a timeout (#341)
TRANSIENT_CODES = {"timeout", "network"}   # slow or unreachable: fails one call, pauses no one (#341)
NO_RETRY_CODES = TRANSIENT_CODES | {"server"}
# The HTTP client's transport errors that the SDK lets through (#383): the connection broke, nothing to pause.
NETWORK_ERROR_NAMES = {"ReadError", "WriteError", "RemoteProtocolError", "LocalProtocolError", "ProtocolError",
                       "CloseError"}   # after these, no second request of the kind in the answer
MAX_REQUESTS_PER_ANSWER = 8             # every request of one answer, planner and composer together
ANSWER_DEADLINE_S = 15.0                # every model call of one answer must end within this (design: 15 s)
MAX_IN_FLIGHT = 4                       # requests in flight at the same time, per process
LEDGER_WINDOW = timedelta(hours=24)     # the daily budget is a rolling 24 hours
MIN_ATTEMPT_S = 1.0                     # an attempt needs at least this much of a deadline left
# The Gemini API rejects a request whose server deadline (the X-Server-Timeout header, which the SDK
# fills from the client timeout) is under 10 s with HTTP 400. The client-side timeout stays ours.
MIN_SERVER_DEADLINE_S = 10
BLOCK_REASONS = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION", "MODEL_ARMOR"}
UNUSABLE_REASONS = {"MALFORMED_FUNCTION_CALL", "UNEXPECTED_TOOL_CALL", "TOO_MANY_TOOL_CALLS",
                    "MISSING_THOUGHT_SIGNATURE", "MALFORMED_RESPONSE"}
STORED_FIELDS = ("candidates", "prompt_feedback", "usage_metadata", "model_version")
# The API version per model, where the SDK's default (v1) does not serve it: the preview model is only
# on v1beta (v1 answered HTTP 404 for it; v1beta answered on 2026-11-14).
API_VERSIONS = {"gemini-3.1-pro-preview": "v1beta"}
CACHE_FORMAT = 1


class GeminiError(RuntimeError):
    """A call that produced nothing usable. `code` is short and never holds request or response text:
    timeout, rate_limited, server, network, http_<status>, empty, truncated, malformed_function_call,
    blocked, budget, busy, disabled, answer_budget, deadline, cache_miss, error."""

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
    gives up after timeout_s; the server deadline is never below MIN_SERVER_DEADLINE_S. A model listed in
    API_VERSIONS is called on that API version."""

    def __init__(self, api_key: str) -> None:
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        self._clients = {None: self._client}
        self._api_key = api_key          # kept only to open a client on another API version

    def _client_for(self, model: str):
        version = API_VERSIONS.get(model)
        if version not in self._clients:
            self._clients[version] = self._genai.Client(api_key=self._api_key, http_options={"api_version": version})
        return self._clients[version]

    def __call__(self, model: str, contents: list[dict[str, Any]], config: dict[str, Any],
                 timeout_s: float) -> dict[str, Any]:
        from google.genai import types

        server_deadline = max(MIN_SERVER_DEADLINE_S, math.ceil(timeout_s))
        cfg = types.GenerateContentConfig.model_validate(
            {**config, "http_options": {"timeout": int(timeout_s * 1000),
                                        "headers": {"X-Server-Timeout": str(server_deadline)}}})
        response = self._client_for(model).models.generate_content(
            model=model, contents=[types.Content.model_validate(c) for c in contents], config=cfg)
        return response.model_dump(mode="json", exclude_none=True)


class Ledger:
    """Counts the requests sent to the Gemini API in a rolling 24 hours, in a JSON-lines file shared by
    every process that uses the same path. Each line: time, call kind, model, result, latency, tokens.

    reserve() takes a slot before a request is sent and add() records it after, so simultaneous calls
    cannot overshoot the cap. The count is never below what this process sent itself, so an unwritable
    or deleted ledger cannot reopen the budget. `off_switch`: while this file exists, nothing is sent."""

    def __init__(self, path: Path, daily_cap: int | None, off_switch: Path | None = None,
                 max_in_flight: int = MAX_IN_FLIGHT) -> None:
        self.path = Path(path)
        self.daily_cap = daily_cap
        self.off_switch = Path(off_switch) if off_switch is not None else None
        self.max_in_flight = max_in_flight
        self._lock = threading.Lock()
        self._sent: deque[datetime] = deque()   # requests this process sent: the floor of the count
        self._in_flight = 0

    def disabled(self) -> bool:
        return self.off_switch is not None and self.off_switch.exists()

    def _counted(self, since: datetime) -> int:
        n = 0
        try:
            with self.path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        if datetime.fromisoformat(json.loads(line)["ts"]) >= since:
                            n += 1
                    except (ValueError, KeyError, TypeError):
                        continue
        except OSError:
            pass
        return n

    def count(self) -> int:
        """Requests sent in the last 24 hours, plus the ones in flight."""
        since = datetime.now(timezone.utc) - LEDGER_WINDOW
        while self._sent and self._sent[0] < since:
            self._sent.popleft()
        return max(self._counted(since), len(self._sent)) + self._in_flight

    today = count                         # the name the budget had when it was a calendar day

    def reserve(self) -> str | None:
        """Take a slot for one request. None when granted, else the refusal: disabled, busy or budget."""
        with self._lock:
            if self.disabled():
                return "disabled"
            if self._in_flight >= self.max_in_flight:
                return "busy"
            if self.daily_cap is not None and self.count() >= self.daily_cap:
                return "budget"
            self._in_flight += 1
            return None

    def allow(self) -> bool:
        return self.daily_cap is None or self.count() < self.daily_cap

    def add(self, kind: str, model: str, result: str, latency_ms: int, usage: CallUsage) -> int:
        """Record one sent request (and free its slot); returns the count after it."""
        now = datetime.now(timezone.utc)
        line = json.dumps({"ts": now.isoformat(timespec="seconds"), "kind": kind, "model": model,
                           "result": result, "latency_ms": latency_ms,
                           "tokens": [usage.prompt_tokens, usage.thought_tokens, usage.output_tokens]})
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._sent.append(now)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                ops_log.warning("gemini request ledger not written")
            return self.count()


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
    if "Connect" in name or "Network" in name or name in NETWORK_ERROR_NAMES or isinstance(exc, ConnectionError):
        return "network", None
    return "error", None


def _thinking(level: str) -> dict[str, Any]:
    """The thinking setting of a request: none for "default" (the model's own), else the level."""
    return {} if level == "default" else {"thinking_config": {"thinking_level": level}}


def effective_thinking(model: str, level: str) -> str:
    """The level sent to this model: one it rejects (for example "minimal" on 3.8-flash) becomes "low".
    "default" and the levels of unknown models are sent as set."""
    allowed = THINKING_LEVELS.get(model)
    return level if level == "default" or allowed is None or level in allowed else "low"


def _for_model(model: str, config: dict[str, Any]) -> dict[str, Any]:
    """The config with a thinking level this model accepts, for a fallback model standing in for a
    role whose level it rejects."""
    level = (config.get("thinking_config") or {}).get("thinking_level")
    if level is None or effective_thinking(model, level) == level:
        return config
    return {**config, "thinking_config": {**config["thinking_config"], "thinking_level": effective_thinking(model, level)}}


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
                 compose_model: str | None = None, compose_fallback_model: str | None = None,
                 cache: str = "on", cache_dir: Path | None = None, ledger: Ledger | None = None,
                 plan_timeout_s: float = 9.0, compose_timeout_s: float = 5.0,
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
        # The composer's own model and fallback (#341); by default the planner's.
        self.compose_model = compose_model or model
        if compose_model is None or compose_model == model:
            compose_fallback_model = self.fallback_model if compose_fallback_model is None else compose_fallback_model
        self.compose_fallback_model = compose_fallback_model if compose_fallback_model != self.compose_model else None
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
        self._lock = threading.Lock()
        self._paused_until = 0.0         # set by a 429, a refused key or model, an outage or a failure streak
        self._pause_code = "rate_limited"
        self._skip_primary_until: dict[str, float] = {}   # per primary model: its fallback answered an outage
        self._failures: dict[str, int] = {}           # per call kind: failures in a row
        self._role_paused_until: dict[str, float] = {}  # per call kind: a short pause after a failure streak
        self._refused: set[str] = set()   # model ids the API answered with 404: their roles use the fallback
        self._answer = threading.local() # per answer (one answer runs in one thread): requests, deadline

    # ---- answers ---------------------------------------------------------------------------------

    def start_answer(self, key: Any) -> None:
        """Start the request count and the deadline of one answer. `key` identifies the answer's first
        planner request; the pipeline's retry passes the same object, which does not restart the count."""
        if getattr(self._answer, "key", None) is key:
            return
        self._answer.key = key
        self._answer.requests = 0
        self._answer.deadline = self.clock() + ANSWER_DEADLINE_S
        self._answer.given_up = {}       # call kind -> the code it failed with in this answer (#341)

    def _answer_left(self) -> tuple[int | None, float | None]:
        """Requests and seconds left for the current answer, or (None, None) outside an answer."""
        if getattr(self._answer, "key", None) is None:
            return None, None
        return MAX_REQUESTS_PER_ANSWER - self._answer.requests, self._answer.deadline - self.clock()

    def unavailable_reason(self) -> str | None:
        """Why no request may be sent now, or None: "off" (the switch file), "budget" (the daily budget is
        0 or used up in the rolling 24 hours), "pause" (after a 429, a refused key or model, an outage or
        failures in a row). The pipeline asks this once per answer before planning (#244)."""
        if self.ledger is not None:
            if self.ledger.disabled():
                return "off"
            if self.ledger.daily_cap is not None and self.ledger.count() >= self.ledger.daily_cap:
                return "budget"
        with self._lock:
            if self.clock() < self._paused_until:
                return "pause"
        return None

    # ---- the two calls ---------------------------------------------------------------------------

    def plan(self, system: str, contents: list[dict[str, Any]], declarations: list[dict[str, Any]]) -> Reply:
        config = {
            "system_instruction": system,
            "tools": [{"function_declarations": declarations}],
            "tool_config": {"function_calling_config": {"mode": "ANY"}},
            "automatic_function_calling": {"disable": True},
            "max_output_tokens": self.plan_max_tokens,
            **_thinking(self.plan_thinking),
        }
        return self._call("plan", contents, config, self.plan_timeout_s)

    def compose(self, system: str, user_text: str, schema: dict[str, Any]) -> Reply:
        contents = [{"role": "user", "parts": [{"text": user_text}]}]
        config = {
            "system_instruction": system,
            "response_mime_type": "application/json",
            "response_json_schema": schema,
            "max_output_tokens": self.compose_max_tokens,
            **_thinking(self.compose_thinking),
        }
        reply = self._call("compose", contents, config, self.compose_timeout_s)
        if reply.blocked and not reply.cached:
            self._failed("blocked", "compose")   # a blocked composer leads to a retry: it counts as a failure
        return reply

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

    # ---- state -----------------------------------------------------------------------------------

    def _record(self, kind: str, model: str, latency_ms: int, usage: CallUsage, *, cached: bool = False,
                finish: str | None = None, error: str | None = None, network: bool = False) -> None:
        self.calls.append(CallRecord(kind, model, latency_ms, cached, usage, finish, error, network))
        if network and self.ledger is not None:
            total = self.ledger.add(kind, model, error or "ok", latency_ms, usage)
            ops_log.info("gemini request %d of %s in 24 h (%s %s %s, %d ms)", total, self.ledger.daily_cap,
                         kind, model, error or "ok", latency_ms)
        log.info("gemini %s model=%s cached=%s latency_ms=%d tokens prompt=%d thoughts=%d output=%d "
                 "cost_usd=%.6f%s", kind, model, cached, latency_ms, usage.prompt_tokens,
                 usage.thought_tokens, usage.output_tokens, usage.cost_usd, f" error={error}" if error else "")

    def _pause(self, seconds: float, code: str) -> None:
        with self._lock:
            self._paused_until = max(self._paused_until, self.clock() + seconds)
            self._pause_code = code
        ops_log.error("gemini %s: model calls paused for %d s; answers use the rule planner and the template",
                      code, seconds)

    def _failed(self, code: str, kind: str) -> None:
        """A malformed, empty or blocked response: after a streak in one role, that role pauses briefly; the
        other role is not touched (#383)."""
        with self._lock:
            self._failures[kind] = self._failures.get(kind, 0) + 1
            streak = self._failures[kind]
        if streak >= FAILURE_STREAK_LIMIT:
            with self._lock:
                self._role_paused_until[kind] = self.clock() + FAILURE_STREAK_COOLDOWN_S
                self._failures[kind] = 0
            ops_log.error("gemini %s (%d failures in a row): %s calls paused for %d s", code, streak, kind,
                          FAILURE_STREAK_COOLDOWN_S)

    def _refuse_model(self, model: str, kind: str) -> None:
        """A model id the API refuses (404): its roles use their fallback from now on, and nothing is paused.
        The log line says it plainly, once per id."""
        with self._lock:
            new = model not in self._refused
            self._refused.add(model)
        if new:
            _, fallback = self.models_for(kind)
            ops_log.error("gemini model id %s refused (404); the %s uses %s from now on", model, kind,
                          fallback or "the rules and the template")

    def _give_up(self, kind: str, code: str) -> None:
        """After a timeout, a network error or a 5xx, this answer sends no second request of the kind."""
        if code in NO_RETRY_CODES and getattr(self._answer, "key", None) is not None:
            self._answer.given_up[kind] = code

    def _succeeded(self, kind: str) -> None:
        with self._lock:
            self._failures[kind] = 0

    # ---- one call --------------------------------------------------------------------------------

    def models_for(self, kind: str) -> tuple[str, str | None]:
        """(model, fallback model) of a call kind: the composer's own pair, else the planner's. A model the API
        refused (404) gives way to the fallback (#383)."""
        primary, fallback = (self.compose_model, self.compose_fallback_model) if kind == "compose" \
            else (self.model, self.fallback_model)
        if fallback in self._refused:
            fallback = None
        if primary in self._refused and fallback is not None:
            return fallback, None
        return primary, fallback

    def _call(self, kind: str, contents: list[dict[str, Any]], config: dict[str, Any], timeout_s: float) -> Reply:
        primary, fallback = self.models_for(kind)
        skip_primary = fallback is not None and self.clock() < self._skip_primary_until.get(primary, 0.0)
        model = fallback if skip_primary else primary
        config = _for_model(model, config)
        key = self.cache_key(model, kind, contents, config)
        entry = self._read_cache(key)
        if entry is not None:
            reply = parse(model, entry["response"], int(entry.get("latency_ms") or 0), cached=True)
            self._record(kind, model, reply.latency_ms, reply.usage, cached=True, finish=reply.finish_reason)
            return reply
        if self.cache == "replay":
            self._record(kind, model, 0, CallUsage(), error="cache_miss")
            raise GeminiError("cache_miss")

        deadline = self.clock() + timeout_s
        given_up = getattr(self._answer, "given_up", {}).get(kind)
        if given_up is not None:
            # A call of this kind already timed out or failed in this answer (the model thinks long on
            # this question, or it is unreachable): a second one would most likely fail too and spend
            # the answer's deadline. The rules plan instead, or the template writes.
            self._record(kind, model, 0, CallUsage(), error=f"{given_up} (not retried)")
            raise GeminiError(given_up)
        try:
            return self._attempt(model, key, kind, contents, config, deadline, fallback=skip_primary)
        except GeminiError as exc:
            if skip_primary and exc.code in {f"http_{c}" for c in CONFIG_ERROR_CODES}:
                # The fallback serving the skip window is refused: drop it, so the next call goes back to the
                # primary instead of calling a refused model for the rest of the window (#383).
                self._drop_fallback(model)
                with self._lock:
                    self._skip_primary_until.pop(primary, None)
            if exc.code not in ("server", "http_404") or skip_primary or fallback is None:
                self._give_up(kind, exc.code)   # a 5xx with no fallback left fails this call only (#341)
                raise
            first_code = exc.code
        # The primary model is overwhelmed: one attempt on the fallback model, within the same deadline.
        config = _for_model(fallback, config)
        try:
            reply = self._attempt(fallback, self.cache_key(fallback, kind, contents, config), kind, contents,
                                  config, deadline, fallback=True)
        except GeminiError as exc:
            if exc.code in {f"http_{c}" for c in CONFIG_ERROR_CODES}:
                # The fallback model is refused (for example an id this key cannot use): stop using it,
                # and do not pause the primary model.
                ops_log.error("gemini fallback model refused (%s); fallback turned off", exc.code)
                self._drop_fallback(fallback)
            self._give_up(kind, "server")
            raise GeminiError(first_code) from None   # both failed: this call fails, nothing is paused (#341)
        if first_code == "server":
            with self._lock:
                self._skip_primary_until[primary] = self.clock() + PRIMARY_SKIP_S
            ops_log.warning("gemini %s overloaded; calling %s directly for %d s", primary, fallback, PRIMARY_SKIP_S)
        return reply

    def _drop_fallback(self, model: str) -> None:
        """A refused fallback model is turned off for every role that uses it."""
        if self.fallback_model == model:
            self.fallback_model = None
        if self.compose_fallback_model == model:
            self.compose_fallback_model = None

    def _attempt(self, model: str, key: str, kind: str, contents: list[dict[str, Any]], config: dict[str, Any],
                 deadline: float, fallback: bool = False) -> Reply:
        """One request, after every check: pause, per-answer requests and deadline, ledger slot."""
        assert self.transport is not None
        with self._lock:
            paused, pause_code = self.clock() < self._paused_until, self._pause_code
            role_paused = self.clock() < self._role_paused_until.get(kind, 0.0)
            refused = model in self._refused
        if paused:
            self._record(kind, model, 0, CallUsage(), error=f"{pause_code} (paused)")
            raise GeminiError(pause_code.split(" ")[0])
        if role_paused:
            self._record(kind, model, 0, CallUsage(), error="failures (role paused)")
            raise GeminiError("paused")
        if refused:
            self._record(kind, model, 0, CallUsage(), error="http_404 (refused id)")
            raise GeminiError("http_404")
        requests_left, answer_left = self._answer_left()
        if requests_left is not None and requests_left <= 0:
            self._record(kind, model, 0, CallUsage(), error="answer_budget")
            raise GeminiError("answer_budget")
        timeout = deadline - self.clock()
        if answer_left is not None:
            timeout = min(timeout, answer_left)
        if timeout < MIN_ATTEMPT_S:
            self._record(kind, model, 0, CallUsage(), error="deadline")
            raise GeminiError("deadline")
        if self.ledger is not None:
            refused = self.ledger.reserve()
            if refused is not None:
                self._record(kind, model, 0, CallUsage(), error=refused)
                if refused == "budget":
                    ops_log.warning("gemini budget of %s requests in 24 h reached; answers use the template",
                                    self.ledger.daily_cap)
                raise GeminiError(refused)
        if requests_left is not None:
            self._answer.requests += 1

        t = self.clock()
        try:
            raw = self.transport(model, contents, config, timeout)
        except Exception as exc:  # noqa: BLE001 - only a short code leaves this function
            code, status = _error_code(exc)
            self._record(kind, model, int((self.clock() - t) * 1000), CallUsage(), error=code, network=True)
            if status == 429:
                self._pause(RATE_LIMIT_COOLDOWN_S, "rate_limited")   # the account's limit: every role
            elif status == 404:
                self._refuse_model(model, kind)    # this model id only: its roles use the fallback (#383)
            elif status in CONFIG_ERROR_CODES and not fallback:
                self._pause(CONFIG_ERROR_COOLDOWN_S, code)   # 401, 403: the key itself is refused
            elif code in TRANSIENT_CODES:
                pass   # a timeout or network error fails this call only (#341)
            elif status not in SERVER_ERROR_CODES:
                self._failed(code, kind)
            raise GeminiError(code) from None
        latency_ms = int((self.clock() - t) * 1000)
        try:
            reply = parse(model, raw, latency_ms)
        except GeminiError as exc:
            finish = str((raw.get("candidates") or [{}])[0].get("finish_reason") or "")
            self._record(kind, model, latency_ms, _usage(model, raw.get("usage_metadata")), finish=finish,
                         error=exc.code, network=True)
            self._failed(exc.code, kind)
            raise
        self._write_cache(key, model, kind, raw, latency_ms)
        self._record(kind, model, latency_ms, reply.usage, finish=reply.finish_reason, network=True)
        if not reply.blocked:
            self._succeeded(kind)
        return reply
