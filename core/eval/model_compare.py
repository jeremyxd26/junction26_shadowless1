"""Compare composer models on the eval set (#169): the service's pipeline with another model writing.

Gemini (any model id, any thinking level):
    SPIKE_REVIEWS=off M169_THINKING=minimal GEMINI_MODEL=gemini-3.5-flash-lite GEMINI_FALLBACK_MODEL=none \\
    MODEL_DAILY_BUDGET=80 M169_OUT=var/m169/flash-lite.jsonl \\
    python core/eval/run.py --source core.eval.model_compare:make_source --case <id> ...
Nemotron on NVIDIA Build, reasoning off (the composer only; the rules plan):
    SPIKE_REVIEWS=off NVIDIA_CAP=72 M169_OUT=var/m169/nemotron.jsonl \\
    python core/eval/run.py --source core.eval.model_compare:make_nemotron_source --case <id> ...
Then: python core/eval/model_compare.py var/m169/flash-lite.jsonl   (validator outcomes and latency)

It runs core/agent/gemini_eval.PipelineSource (rules first, the validator, the template fallback) and
writes one JSON line per answer to M169_OUT: the validation of each composer attempt, each model call's
latency and tokens, and for Nemotron the time to the first content token. Every model goes through the
adapter's GeminiClient, so its response cache (a rerun sends nothing), its ledger (a hard cap on
requests) and its error pauses (a 429 or a refused key stops further requests) apply to all of them.
SPIKE_REVIEWS=off gives the published numbers the eval set expects and keeps the run away from the
spike-review tables. No key is ever logged, cached or written to the output."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from statistics import median
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NEMOTRON_MODEL = "nvidia/nemotron-3.5-super-vl-120b-a12b"   # NVIDIA NIM docs, checked 2026-11-14


# ---- NVIDIA Build as a transport of the Gemini adapter ---------------------------------------------------

class HttpStatusError(Exception):
    """An HTTP error with its status as `.code`, which gemini_client._error_code maps (429: a pause)."""

    def __init__(self, code: int) -> None:
        super().__init__(f"http {code}")
        self.code = code


def strip_fences(text: str) -> str:
    """The JSON inside a ```json fence, if the model added one."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


class NvidiaTransport:
    """A gemini_client Transport for the compose call on an OpenAI-compatible chat completions endpoint.

    Reasoning off: a "/no_think" system line and chat_template_kwargs.enable_thinking=false (without
    them the budget goes into reasoning and the content stays empty). The composer's JSON Schema goes
    as response_format json_schema. Streaming, so the time to the first content token is measured and
    kept in `log` (the cache stores the response, not that time). The answer comes back in the shape of
    a GenerateContentResponse, so the adapter's parsing, cache and ledger work unchanged."""

    def __init__(self, api_key: str, url: str = NVIDIA_URL, opener: Any = None) -> None:
        self._key = api_key
        self.url = url
        self._open = opener or urllib.request.urlopen
        self.log: list[dict[str, Any]] = []

    def __call__(self, model: str, contents: list[dict[str, Any]], config: dict[str, Any],
                 timeout_s: float) -> dict[str, Any]:
        if "response_json_schema" not in config:
            raise HttpStatusError(400)   # the planner needs tool calling, which this transport does not do
        user_text = "".join(p.get("text") or "" for c in contents for p in c.get("parts") or [])
        body = {
            "model": model,
            "messages": [{"role": "system", "content": "/no_think\n" + config.get("system_instruction", "")},
                         {"role": "user", "content": user_text}],
            "max_tokens": int(config.get("max_output_tokens") or 1024),
            "temperature": 0.2,
            "stream": True,
            "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "answer_draft", "schema": config["response_json_schema"]}},
        }
        request = urllib.request.Request(
            self.url, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": "Bearer " + self._key, "Content-Type": "application/json",
                     "Accept": "text/event-stream"})
        t0 = time.perf_counter()
        first, text, finish, usage = None, [], None, {}
        try:
            with self._open(request, timeout=timeout_s) as response:
                for raw in response:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    usage = chunk.get("usage") or usage
                    for choice in chunk.get("choices") or []:
                        piece = (choice.get("delta") or {}).get("content")
                        if piece:
                            first = first if first is not None else int((time.perf_counter() - t0) * 1000)
                            text.append(piece)
                        finish = choice.get("finish_reason") or finish
        except urllib.error.HTTPError as exc:
            raise HttpStatusError(exc.code) from None
        self.log.append({"ttft_ms": first, "total_ms": int((time.perf_counter() - t0) * 1000), "finish": finish})
        reasoning = int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
        return {
            "candidates": [{"content": {"role": "model", "parts": [{"text": strip_fences("".join(text))}]},
                            "finish_reason": "MAX_TOKENS" if finish == "length" else "STOP"}],
            "usage_metadata": {"prompt_token_count": int(usage.get("prompt_tokens") or 0),
                               "thoughts_token_count": reasoning,
                               "candidates_token_count": int(usage.get("completion_tokens") or 0) - reasoning},
            "model_version": model,
        }


# ---- eval sources ------------------------------------------------------------------------------------------

def _recording_source_class():
    from core.agent.gemini_eval import PipelineSource

    class RecordingSource(PipelineSource):
        """PipelineSource that also writes each answer's validation outcomes and timings to `out`."""

        def __init__(self, *a: Any, out: str | None = None, transport: Any = None, **kw: Any) -> None:
            super().__init__(*a, **kw)
            self.out, self.transport = out, transport

        def __call__(self, customer_id: str, question: str, language: str) -> Any:
            n_calls = len(self.model.client.calls)
            n_log = len(self.transport.log) if self.transport else 0
            answer = super().__call__(customer_id, question, language)
            if any(c.error == "rate_limited" for c in self.model.client.calls[n_calls:]):
                sys.exit("stopping: the model answered 429 (rate limited); no retry")
            if self.out:
                record = self.audit.records[-1] if self.audit.records else {}
                row = self.rows[-1]
                line = {
                    "case": row.case, "lang": language, "outcome": row.outcome, "done_ms": row.done_ms,
                    "calls": [{"kind": c.kind, "model": c.model, "ms": c.latency_ms, "cached": c.cached,
                               "error": c.error, "network": c.network, "prompt": c.usage.prompt_tokens,
                               "thought": c.usage.thought_tokens, "output": c.usage.output_tokens}
                              for c in self.model.client.calls[n_calls:]],
                    "composer_attempts": [{"validation": a.get("validation")}
                                          for a in record.get("composer_attempts") or []],
                    "stream": self.transport.log[n_log:] if self.transport else [],
                }
                Path(self.out).parent.mkdir(parents=True, exist_ok=True)
                with open(self.out, "a", encoding="utf-8") as f:
                    f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
            return answer

    return RecordingSource


def _finish(source: Any, doc: dict) -> Any:
    source.case_ids = {(c["persona"], q): c["id"] for c in doc["cases"] for q in c["question"].values()}
    return source


def make_source(doc: dict, args: Any) -> Any:
    """run.py source: the pipeline with GEMINI_MODEL at the thinking level M169_THINKING (default
    minimal; gemini-3.8-flash needs low). GEMINI_MODEL moves the planner too, but on the eval set's
    answered questions the rules plan every one, so only the composer is asked."""
    from core.agent.gemini import make_agent_model

    if not os.environ.get("MODEL_DAILY_BUDGET"):
        sys.exit("set MODEL_DAILY_BUDGET: every comparison run needs an explicit request cap")
    thinking = os.environ.get("M169_THINKING", "minimal")
    model = make_agent_model(plan_thinking=thinking, compose_thinking=thinking)
    source = _recording_source_class()(doc["as_of"], model=model, out=os.environ.get("M169_OUT"),
                                       echo=os.environ.get("GEMINI_EVAL_ECHO", "1") != "0")
    return _finish(source, doc)


def nvidia_key() -> str | None:
    """NVIDIA_API_KEY from the environment, else from the repository's .env. Never printed."""
    key = os.environ.get("NVIDIA_API_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("NVIDIA_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("\"'")
    return key or None


def make_nemotron_source(doc: dict, args: Any) -> Any:
    """run.py source: the rules plan, Nemotron writes (reasoning off), through the adapter's client with
    its own cache (var/nvidia-cache) and ledger (var/nvidia-requests.jsonl, NVIDIA_CAP a day)."""
    from core.agent.gemini import GeminiModel, RulesFirstModel
    from core.agent.gemini_client import GeminiClient, Ledger
    from core.agent.rules import RuleModel

    key = nvidia_key()
    if not key:
        sys.exit("NVIDIA_API_KEY is not set")
    if not os.environ.get("NVIDIA_CAP"):
        sys.exit("set NVIDIA_CAP: every comparison run needs an explicit request cap")
    transport = NvidiaTransport(key)
    client = GeminiClient(os.environ.get("NEMOTRON_MODEL", NEMOTRON_MODEL), transport, fallback_model=None,
                          cache="on", cache_dir=ROOT / "var" / "nvidia-cache",
                          ledger=Ledger(ROOT / "var" / "nvidia-requests.jsonl", int(os.environ["NVIDIA_CAP"])))
    model = RulesFirstModel(RuleModel(), GeminiModel(client))
    model.client = client
    source = _recording_source_class()(doc["as_of"], model=model, out=os.environ.get("M169_OUT"), transport=transport,
                                       echo=os.environ.get("GEMINI_EVAL_ECHO", "1") != "0")
    return _finish(source, doc)


# ---- summary -------------------------------------------------------------------------------------------------

def percentile(values: list[int], q: float) -> int | None:
    v = sorted(values)
    return v[max(0, min(len(v) - 1, round(q * (len(v) - 1))))] if v else None


def violation_kind(problem: str) -> str:
    p = problem.lower()
    for kind, words in (("model call failed", ("model call failed",)), ("number word", ("number word", "in words")),
                        ("markdown", ("markdown",)), ("link", ("link", "url")),
                        ("two number tokens side by side", ("words must stand between",)),
                        ("cited list differs from the tokens", ("cited must list",)),
                        ("malformed number token", ("malformed number token",)),
                        ("digits not from a tool", ("digits", "date '")),
                        ("unknown number id", ("unknown number",))):
        if any(w in p for w in words):
            return kind
    return "other: " + problem[:50]


def summarise(rows: list[dict]) -> dict[str, Any]:
    """Validator outcomes (first draft, retry, template), first-draft violations, latency and tokens."""
    outcomes, by_lang, violations = Counter(), {"en": Counter(), "fi": Counter()}, Counter()
    for r in rows:
        vals = [a.get("validation") for a in r.get("composer_attempts") or []]
        outcome = ("first draft" if vals[:1] == ["ok"] else "retry" if vals[1:2] == ["ok"]
                   else "template" if vals else "no composer")
        outcomes[outcome] += 1
        by_lang.setdefault(r["lang"], Counter())[outcome] += 1
        if vals and vals[0] != "ok":
            for p in vals[0] if isinstance(vals[0], list) else [vals[0]]:
                violations[violation_kind(str(p))] += 1
    compose = [c["ms"] for r in rows for c in r["calls"] if c["kind"] == "compose" and not c["error"]]
    ttft = [s["ttft_ms"] for r in rows for s in r.get("stream") or [] if s.get("ttft_ms") is not None]
    tokens = Counter()
    for r in rows:
        for c in r["calls"]:
            tokens.update({"prompt": c["prompt"], "thought": c["thought"], "output": c["output"],
                           "requests": int(c["network"])})
    return {
        "answers": len(rows), "outcomes": dict(outcomes), "by_language": {k: dict(v) for k, v in by_lang.items()},
        "first_draft_violations": dict(violations),
        "compose_ms": {"median": median(compose) if compose else None, "p90": percentile(compose, 0.9),
                       "max": max(compose) if compose else None},
        "first_token_ms_median": median(ttft) if ttft else None,
        "tokens": dict(tokens),
    }


if __name__ == "__main__":
    for path in sys.argv[1:]:
        lines = [json.loads(line) for line in open(path, encoding="utf-8")]
        print(path, json.dumps(summarise(lines), indent=1))
