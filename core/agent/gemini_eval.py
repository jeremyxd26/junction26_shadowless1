"""The answer pipeline with the Gemini model as an eval source, with timings, tokens and cost (issue #66).

    python core/eval/run.py --source core.agent.gemini_eval:make_source --tag brief --persona CUST00860
    python core/eval/run.py --source core.agent.gemini_eval:make_source --tag red_team
    GEMINI_MODEL=<id> ... overrides the pinned model; GEMINI_PLANNER=model makes Gemini plan every
    question (the service plans recognised questions with the rule planner first).

It runs the same Pipeline and model as POST /api/ask (registry from toolset.py, make_agent_model, the
conversation store, the validator, the template fallback), in process, on one database connection (statement_timeout 60s,
reads of one customer at a time), and builds the eval's Answer the way the API source does. Each
answer also gets a row with:
- first card, first text (the first `delta` event: what the user sees start to appear) and done, in
  ms of wall time in this process;
- the live latency of every model call (a cache hit reports the latency of the call that filled it);
- tokens (prompt, thoughts, output) and the cost in USD.
`stats()` adds averages per answer to the runner's summary line and prints the table first.
A cache hit reports the latency of the request that filled it, so a repeated run reproduces the
model timings without new requests; the database times are always measured anew.
"""

from __future__ import annotations

import os
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "core" / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

from core.agent.conversation import ConversationStore  # noqa: E402
from core.agent.gemini import make_agent_model  # noqa: E402
from core.agent.orchestrator import AskRequest, Pipeline  # noqa: E402
from core.agent.toolset import default_registry  # noqa: E402

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class MemoryAudit:
    """Keeps the audit records of this run in memory (and never writes var/audit)."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def write(self, record: dict[str, Any]) -> None:
        self.records.append(record)


class OneConnection:
    """The pipeline's DataAccess on one connection, opened on first use."""

    def __init__(self) -> None:
        self._conn = None

    @contextmanager
    def connection(self) -> Iterator[Any]:
        if self._conn is None:
            from core.tools import db
            self._conn = db.connect()
        yield self._conn

    def customer_exists(self, customer_id: str) -> bool:  # not used by Pipeline.run
        return True


@dataclass
class Row:
    case: str
    lang: str
    outcome: str
    first_card_ms: int | None
    first_text_ms: int | None
    done_ms: int
    calls: list[tuple[str, int, bool, str | None]] = field(default_factory=list)  # kind, live ms, cached, error
    tools: list[tuple[str, int]] = field(default_factory=list)  # data tool, ms (database and Python time)
    requests: int = 0                    # requests sent to the Gemini API for this answer
    prompt_tokens: int = 0
    thought_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    text: str = ""


def _walk(obj: Any) -> Iterator[Any]:
    if isinstance(obj, dict):
        for v in obj.values():
            yield v
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield v
            yield from _walk(v)


class PipelineSource:
    def __init__(self, as_of: str, model: Any | None = None, echo: bool = True) -> None:
        self.as_of = date.fromisoformat(str(as_of))
        self.model = model or make_agent_model()
        if not hasattr(self.model, "client"):
            sys.exit("GEMINI_API_KEY is not set")
        self.data = OneConnection()
        self.audit = MemoryAudit()
        self.pipeline = Pipeline(default_registry(), self.model, self.data, as_of=self.as_of,
                                 store=ConversationStore(), audit=self.audit)
        self.rows: list[Row] = []
        self.echo = echo
        self.case_ids: dict[tuple[str, str], str] = {}

    def __call__(self, customer_id: str, question: str, language: str):
        from sources import Answer  # core/eval/sources.py; the runner puts core/eval on sys.path

        client = self.model.client
        first_call = len(client.calls)
        events: list[tuple[float, str, dict[str, Any]]] = []
        t0 = time.perf_counter()
        self.pipeline.run(AskRequest(customer_id=customer_id, message=question, language=language),
                          lambda e, p: events.append((time.perf_counter(), e, p)))
        t_done = time.perf_counter()

        def first(name: str) -> int | None:
            return next((int((t - t0) * 1000) for t, e, _ in events if e == name), None)

        done = next((p for _, e, p in events if e == "done"), None)
        error = next((p for _, e, p in events if e == "error"), None)
        numbers: dict[str, Any] = {}
        cards: list[dict[str, Any]] = []
        for _, e, p in events:
            if e == "numbers":
                numbers.update(p["numbers"])
            elif e == "card":
                cards.append(p["card"])
        record = self.audit.records[-1] if self.audit.records else {}

        row = Row(self.case_ids.get((customer_id, question), question[:40]), language, (done or {}).get("outcome") or "error",
                  first("card"), first("delta"), int((t_done - t0) * 1000), text=(done or {}).get("text_rendered") or "")
        for turn in record.get("planner_turns") or []:
            for call in turn.get("calls") or []:
                if "latency_ms" in call and call.get("status") in ("ok", "error"):
                    row.tools.append((call["name"], int(call["latency_ms"])))
        for c in client.calls[first_call:]:
            row.calls.append((c.kind + ("" if c.model == client.model else f"@{c.model}"), c.latency_ms, c.cached,
                              c.error))
            row.requests += c.network
            row.prompt_tokens += c.usage.prompt_tokens
            row.thought_tokens += c.usage.thought_tokens
            row.output_tokens += c.usage.output_tokens
            row.cost_usd += c.usage.cost_usd
        self.rows.append(row)
        if self.echo:
            calls = ", ".join(f"{k} {ms} ms{' (cache)' if cached else ''}{f' {err}' if err else ''}"
                              for k, ms, cached, err in row.calls)
            tools = ", ".join(f"{name} {ms} ms" for name, ms in row.tools) or "no data tool"
            print(f"      [{row.outcome}] first card {row.first_card_ms} ms, first text {row.first_text_ms} ms, "
                  f"done {row.done_ms} ms; {calls}; {tools}; tokens {row.prompt_tokens}/{row.thought_tokens}/"
                  f"{row.output_tokens}; ${row.cost_usd:.5f}\n      {row.text}", flush=True)
            for attempt in record.get("composer_attempts") or []:
                if attempt.get("validation") not in (None, "ok"):
                    print(f"      rejected draft: {attempt.get('validation')}", flush=True)

        if error is not None or done is None:
            return Answer(text="", outcome="error", error=((error or {}).get("error") or {}).get("code", "no done event"))
        cited = {k: v for k, v in numbers.items() if k in done.get("cited", [])}
        dates = {self.as_of.isoformat()}
        dates.update(v for v in _walk([cited, cards]) if isinstance(v, str) and ISO.match(v))
        labels = []
        for card in cards:
            if card.get("type") == "profile":
                labels.append((card.get("profile") or {}).get("key"))
            if card.get("type") == "whatif":
                labels.append((card.get("result") or {}).get("status"))
        tool_calls = [c.get("name") for turn in record.get("planner_turns") or [] for c in turn.get("calls") or []]
        return Answer(text=done.get("text_rendered") or done.get("text") or "", outcome=done.get("outcome"),
                      refusal_kind=(done.get("refusal") or {}).get("kind"), numbers=list(cited.values()),
                      dates=sorted(dates), labels=[x for x in labels if x], tool_calls=tool_calls)

    def stats(self) -> str:
        print(self.table())
        rows = [r for r in self.rows if r.outcome != "error"]
        if not rows:
            return ""
        live = [ms for r in rows for k, ms, cached, err in r.calls if err is None]
        n_calls = sum(len(r.calls) for r in self.rows)
        requests = sum(r.requests for r in self.rows)
        return (f"; model {self.model.model_id}, {n_calls} model calls ({requests} requests sent), per answer: "
                f"{mean(r.prompt_tokens for r in rows):.0f} prompt / {mean(r.thought_tokens for r in rows):.0f} thought / "
                f"{mean(r.output_tokens for r in rows):.0f} output tokens, ${mean(r.cost_usd for r in rows):.5f}; "
                f"model call median {median(live) if live else 0:.0f} ms")

    def table(self) -> str:
        lines = ["\n| case | lang | outcome | first card ms | first text ms | done ms | model calls (live ms) | "
                 "data tools (ms) | tokens prompt/thought/output | cost USD |", "|---|---|---|---|---|---|---|---|---|---|"]
        for r in self.rows:
            calls = ", ".join(f"{k} {ms}{'c' if cached else ''}{'!' + err if err else ''}" for k, ms, cached, err in r.calls)
            lines.append(f"| {r.case} | {r.lang} | {r.outcome} | {r.first_card_ms if r.first_card_ms is not None else '-'} | "
                         f"{r.first_text_ms if r.first_text_ms is not None else '-'} | {r.done_ms} | {calls} | "
                         f"{', '.join(f'{n} {ms}' for n, ms in r.tools) or '-'} | "
                         f"{r.prompt_tokens}/{r.thought_tokens}/{r.output_tokens} | {r.cost_usd:.5f} |")
        return "\n".join(lines)


def make_source(doc: dict, args: Any) -> PipelineSource:
    """Factory for core/eval/run.py --source core.agent.gemini_eval:make_source."""
    source = PipelineSource(doc["as_of"], echo=os.environ.get("GEMINI_EVAL_ECHO", "1") != "0")
    source.case_ids = {(c["persona"], q): c["id"] for c in doc["cases"] for q in c["question"].values()}
    return source
