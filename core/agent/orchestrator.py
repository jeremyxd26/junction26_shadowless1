"""The answer pipeline, steps 1 to 7 of agent-core.md section 7.1 (step 0 is in api.py).

1  meta: answer id, conversation (bound to one customer), language.   1a  input guard.
2  plan: the model chooses functions (mode ANY). Planner errors: retry once, then the keyword
   planner (rules.py) and a template answer with outcome "fallback".
3  tools: arguments are validated by the registry; a customer key at any depth, an unknown function
   or bad arguments go back to the model as {"error": code}. Valid calls run with a database
   connection held only for the tool, two at a time when a second connection is free at once (else
   one by one). Number ids, cards (at most 3) and audit keys follow the call order, not the order in
   which the tools finish (design section 7.5), so a result is the same as in a sequential run.
4  loop: at most 2 tool rounds and 6 data calls. decline or ask_clarifying_question ends the turn at
   once and no data tool of that turn runs (R6).
5  compose: a fresh, tool-free call that sees model views only (R3).
6  validate (validator.py); on failure retry once with the errors, then the template (R12).
7  deliver: sentence by sentence, a `numbers` event before the first sentence citing a number, then
   `done`; the audit record is written whatever the outcome (R15).
The customer id comes only from the request and never from model output (R4).
A failure inside the stream becomes one `error` event; exception text never leaves the process.
"""

from __future__ import annotations

import dataclasses
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Protocol

import psycopg
from psycopg_pool import PoolTimeout

from core.agent import guard, template
from core.agent.audit import AuditLog
from core.agent.conversation import Conversation, ConversationStore, new_id
from core.agent.model import ComposeInput, FunctionCall, FunctionResponse, Model, PlanInput, PlanResult, Usage
from core.agent.registry import CallRejected, Registry
from core.agent.rules import RuleModel
from core.agent.validator import TOKEN, Allowed, AnswerDraft, allowed_from, check_text, render, validate
from core.app.api import texts as api_texts
from core.tools.context import NumberRegistry, ToolContext
from core.tools.periods import PeriodOutOfRange

log = logging.getLogger("uvicorn.error")

MAX_ROUNDS = 2
MAX_DATA_CALLS = 6
MAX_CARDS = 3
MAX_PARALLEL = 2   # data calls of one turn running at the same time, one pool connection each
# A second lane runs only on a connection that is free at once, so one answer never queues for a
# second connection that another request needs (core/app/db.py holds a small pool).
SPARE_WAIT_S = 0.05

# The `error` event's texts are the API's catalogue (core/app/api/texts.py), so a failure reads the same
# before the stream (503) and inside it.
ERRORS = {code: (api_texts.ERRORS[code], True) for code in ("data_unavailable", "internal")}

Emit = Callable[[str, dict[str, Any]], None]


class LockedNumberRegistry(NumberRegistry):
    """The answer's number registry, safe for tools that run in parallel threads."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()

    def register(self, number):
        with self._lock:
            return super().register(number)


class _InCallOrder(NumberRegistry):
    """One tool call's view of the answer's registry: its first registration waits until the calls
    before it have finished, so ids follow the call order whichever call finishes first."""

    def __init__(self, shared: NumberRegistry, before: threading.Event | None) -> None:
        super().__init__()
        self._shared = shared
        self._before = before

    def register(self, number):
        if self._before is not None:
            self._before.wait()
        return self._shared.register(number)

    def get(self, number_id):
        return self._shared.get(number_id)

    def all(self):
        return self._shared.all()


class DataUnavailable(RuntimeError):
    """The database cannot be reached or is too slow (503 data_unavailable / `error` event)."""


class DataAccess(Protocol):
    def customer_exists(self, customer_id: str) -> bool: ...

    def connection(self) -> AbstractContextManager[Any]: ...

    # Optional: `connection_if_free(wait)` gives a connection only if one is free within `wait`
    # seconds and raises DataUnavailable otherwise. Without it, a turn's calls run one by one.


def error_envelope(code: str, language: str) -> dict[str, Any]:
    texts, retryable = ERRORS[code]
    return {"code": code, "message": template.pick(texts, language), "retryable": retryable}


@dataclass
class AskRequest:
    customer_id: str
    message: str
    language: str = "auto"            # en | fi | auto
    conversation_id: str | None = None


@dataclass
class _Answer:
    """Everything one answer collects for the stream, the conversation and the audit record."""

    started: float
    answer_id: str = ""
    conversation: Conversation | None = None
    language: dict[str, Any] = field(default_factory=dict)
    question: str = ""
    flags: list[str] = field(default_factory=list)
    planner_turns: list[dict[str, Any]] = field(default_factory=list)
    tool_outputs: dict[str, Any] = field(default_factory=dict)
    composer_attempts: list[dict[str, Any]] = field(default_factory=list)
    cards: list[str] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    numbers: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    outcome: str | None = None
    refusal: dict[str, str] | None = None
    clarify: dict[str, Any] | None = None
    text: str | None = None
    text_rendered: str | None = None
    error: str | None = None
    first_card_ms: int | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)  # tools may run in parallel
    usage: dict[str, Any] = field(default_factory=lambda: {"prompt_tokens": 0, "thought_tokens": 0,
                                                           "output_tokens": 0, "cost_usd": 0.0})

    def add_usage(self, usage: Usage) -> dict[str, Any]:
        """Add one model call's usage to the answer's total; returns the call's own record."""
        call = {"prompt_tokens": usage.prompt_tokens, "thought_tokens": usage.thought_tokens,
                "output_tokens": usage.output_tokens, "cost_usd": usage.cost_usd}
        for key, value in call.items():
            self.usage[key] += value
        return call


class Pipeline:
    def __init__(self, registry: Registry, model: Model, data: DataAccess, *, as_of: date,
                 store: ConversationStore | None = None, audit: AuditLog | None = None,
                 fallback: Model | None = None, clock: Callable[[], float] = time.perf_counter) -> None:
        self.registry = registry
        self.model = model
        self.data = data
        self.as_of = as_of
        self.store = store or ConversationStore()
        self.audit = audit or AuditLog()
        self.fallback = fallback or RuleModel()
        self.clock = clock

    # ---- public --------------------------------------------------------------------------------

    def run(self, req: AskRequest, emit: Emit) -> None:
        """Answer one question, calling emit(event, payload) for every stream event. Never raises."""
        a = _Answer(started=self.clock())
        lang = "en"

        def tracked(event: str, payload: dict[str, Any]) -> None:
            if event == "card" and a.first_card_ms is None:
                a.first_card_ms = self._ms(a.started)
            emit(event, payload)

        try:
            lang = self._run(req, tracked, a)
        except DataUnavailable:
            a.outcome, a.error = "error", "data_unavailable"
            tracked("error", {"error": error_envelope("data_unavailable", a.language.get("resolved", lang))})
        except Exception as exc:  # noqa: BLE001 - the class name is logged, never the message
            log.error("ask pipeline failed (%s)", type(exc).__name__)
            a.outcome, a.error = "error", f"internal ({type(exc).__name__})"
            tracked("error", {"error": error_envelope("internal", a.language.get("resolved", lang))})
        finally:
            self._write_audit(req, a)

    # ---- steps ---------------------------------------------------------------------------------

    def _run(self, req: AskRequest, emit: Emit, a: _Answer) -> str:
        conv, reset = self.store.resolve(req.conversation_id, req.customer_id)
        a.conversation = conv
        message = guard.clean(req.message)
        a.question = message
        detected = guard.detect_language(message)
        lang = req.language if req.language in ("en", "fi") else (detected or conv.language or "en")
        a.language = {"requested": req.language, "resolved": lang, "detector": detected}
        conv.language = lang
        a.answer_id = new_id("ans_")
        if reset:
            a.warnings.append("conversation_reset")
        emit("meta", {"answer_id": a.answer_id, "conversation_id": conv.conversation_id, "language": lang,
                      "as_of": self.as_of.isoformat()})
        emit("status", {"stage": "understanding", "tool": None, "label": template.pick(template.STATUS_UNDERSTANDING, lang)})
        a.flags = guard.flags(message)

        # The customer is bound here, from the request, and never from model output (R4).
        ctx = ToolContext(customer_id=req.customer_id, as_of=self.as_of, conn=None, language=lang,
                          numbers=LockedNumberRegistry())
        history = [{"question": t["question"], "calls": t["calls"], "results": t["views"]} for t in conv.turns]
        responses: list[FunctionResponse] = []
        model_turns: list[Any] = []
        views: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        data_calls = 0
        planner_fallback = False

        for rnd in range(1, MAX_ROUNDS + 1):
            t_plan = self.clock()
            plan, source = self._plan(PlanInput(
                question=message, language=lang, as_of=self.as_of.isoformat(), tools=self.registry.schemas(),
                history=history, responses=list(responses), model_turns=list(model_turns), guard_flags=a.flags,
                round=rnd), a)
            calls = plan.calls
            model_turns.append(plan.raw)
            planner_fallback |= source == "fallback"
            turn: dict[str, Any] = {"round": rnd, "mode": "ANY", "source": source, "calls": [],
                                    "latency_ms": self._ms(t_plan), "tokens": a.add_usage(plan.usage)}
            a.planner_turns.append(turn)

            parsed, rejected = [], []
            for call in calls:
                try:
                    kind, args = self.registry.parse(call.name, call.args)
                    parsed.append((call, kind, args))
                except CallRejected as exc:
                    rejected.append((call, exc))
            controls = {call.name: args for call, kind, args in parsed if kind == "control"}

            if "decline" in controls or "ask_clarifying_question" in controls:
                # The turn ends at once: no data tool of this turn runs (R6).
                for call, kind, _ in parsed:
                    turn["calls"].append({"name": call.name, "args": call.args,
                                          "status": "ok" if kind == "control" else "not_run"})
                if "decline" in controls:
                    return self._refuse(controls["decline"].kind.value, lang, emit, a)
                return self._clarify(controls["ask_clarifying_question"], lang, emit, a)

            for call, exc in rejected:
                responses.append(FunctionResponse(call.name, {"error": exc.code}, call.id))
                turn["calls"].append({"name": call.name, "args": call.args, "status": f"rejected: {exc.code}"})
            pending, slots = [], []  # slots keep the model's call order in the audit record
            for call, kind, args in parsed:
                if kind == "control":
                    slots.append({"name": call.name, "args": call.args, "status": "ok"})
                    continue
                if data_calls >= MAX_DATA_CALLS:
                    slots.append({"name": call.name, "args": call.args, "status": "not_run: call limit"})
                    continue
                data_calls += 1
                pending.append((call, args))
                slots.append(None)
            records = self._run_tools(ctx, pending, lang, emit, a)
            done_records = iter(records)
            turn["calls"] += [slot if slot is not None else next(done_records) for slot in slots]
            for (call, args), record in zip(pending, records):
                a.calls.append({"name": call.name, "args": call.args})
                if "view" in record:
                    views.append(record.pop("view"))
                    responses.append(FunctionResponse(call.name, views[-1], call.id))
                else:
                    errors.append({"tool": call.name, "error": record["error"]})
                    responses.append(FunctionResponse(call.name, {"error": record["error"]}, call.id))
            ran_data = any(k == "data" for _, k, _ in parsed)
            if "finish" in controls or data_calls >= MAX_DATA_CALLS or not (ran_data or rejected):
                break

        numbers = ctx.numbers.all()
        allowed = allowed_from(numbers.values(), views, self.as_of)
        prev = conv.turns[-1] if conv.turns else None
        compose_in = ComposeInput(question=message, language=lang, as_of=self.as_of.isoformat(), data=views,
                                  errors=errors, previous_turn={"question": prev["question"], "answer": prev["answer"]} if prev else None)
        draft, used_template = self._compose(compose_in, numbers, allowed, skip_model=planner_fallback, a=a)
        if any(e["error"] == "tool_failed" for e in errors):
            a.warnings.append("tool_failed")
        a.outcome = "fallback" if (used_template or planner_fallback) else "answered"
        if a.outcome == "fallback":
            a.warnings.append("llm_unavailable")
        text = self._deliver(draft.text, numbers, emit)
        a.text, a.text_rendered = text, render(text, numbers)
        cited = list(dict.fromkeys(TOKEN.findall(text)))
        a.numbers = {i: {"value": numbers[i].value, "unit": numbers[i].unit.value, "method": numbers[i].method,
                         "evidence_ref": numbers[i].evidence_ref} for i in cited}
        emit("done", {"answer_id": a.answer_id, "outcome": a.outcome, "text": text, "text_rendered": a.text_rendered,
                      "cited": cited, "follow_ups": template.follow_ups(message, lang),
                      "lesson": template.lesson(draft.lesson_key, lang), "refusal": None, "clarify": None,
                      "warnings": a.warnings})
        self.store.add_turn(conv, {"question": message, "calls": a.calls, "views": views,
                                   "answer": TOKEN.sub("[number]", text)})
        return lang

    def _plan(self, request: PlanInput, a: _Answer) -> tuple[PlanResult, str]:
        for _ in range(2):  # the call and one retry
            t = self.clock()
            try:
                plan = self.model.plan(request)
                if plan.calls:
                    return plan, "model"
                problem = "no function call"
                a.add_usage(plan.usage)
            except Exception as exc:  # noqa: BLE001 - only the class name is kept
                problem = f"model error ({type(exc).__name__})"
            a.planner_turns.append({"round": request.round, "source": "model", "error": problem,
                                    "latency_ms": self._ms(t)})
        return self.fallback.plan(request), "fallback"

    def _run_tools(self, ctx: ToolContext, pending: list[tuple[FunctionCall, Any]], lang: str, emit: Emit,
                   a: _Answer) -> list[dict[str, Any]]:
        """Run one turn's data calls; records come back in call order.

        Lanes take the calls in order. The first lane waits for its connection as usual; up to
        MAX_PARALLEL - 1 more lanes run only on a connection that is free within SPARE_WAIT_S
        (DataAccess.connection_if_free), so the calls run one by one when the pool is busy. A lane takes its connection BEFORE it takes a call:
        a call that waits for the one before it (ids, cards and audit keys follow the call order) then
        always waits on a call that holds a connection and can finish."""
        records: list[dict[str, Any] | None] = [None] * len(pending)
        done = [threading.Event() for _ in pending]
        queue = deque(range(len(pending)))
        lock = threading.Lock()
        failures: list[BaseException] = []
        failed_at: set[int] = set()  # the calls that failed, by index

        def take() -> int | None:
            with lock:
                return queue.popleft() if queue and not failures else None

        def lane(spare: bool) -> None:
            while True:
                with lock:
                    if not queue or failures:
                        return
                try:
                    with (self.data.connection_if_free(SPARE_WAIT_S) if spare else self.data.connection()) as conn:
                        i = take()
                        if i is None:
                            return
                        call, args = pending[i]
                        before = done[i - 1] if i else None
                        try:
                            own = dataclasses.replace(ctx, conn=conn, numbers=_InCallOrder(ctx.numbers, before))
                            records[i] = self._run_tool(own, call, args, lang, emit, a, before,
                                                        lambda i=i: any(j < i for j in failed_at))
                            with a.lock:  # later calls reuse the customer's loaded history
                                if ctx._history is None and own._history is not None:
                                    ctx._history = own._history
                        except BaseException as exc:  # noqa: BLE001 - re-raised by the caller below
                            # Recorded BEFORE done[i] is set, so a later call that waits for this one
                            # sees the failure and sends no card before the `error` event (#168).
                            with lock:
                                failures.append(exc)
                                failed_at.add(i)
                            return
                        finally:
                            if before is not None:
                                before.wait()  # done[i] means that every earlier call has finished too
                            done[i].set()
                except DataUnavailable as exc:
                    if not spare:
                        with lock:
                            failures.append(exc)
                    return  # a spare lane without a free connection: the first lane runs the rest
                except BaseException as exc:  # noqa: BLE001 - re-raised by the caller below
                    with lock:
                        failures.append(exc)
                    return

        lanes = min(MAX_PARALLEL, len(pending)) if hasattr(self.data, "connection_if_free") else 1
        spares = [threading.Thread(target=lane, args=(True,), daemon=True) for _ in range(lanes - 1)]
        for t in spares:
            t.start()
        try:
            lane(False)
        finally:
            for t in spares:
                t.join()
        if failures:
            raise failures[0]
        return [r for r in records if r is not None]

    def _run_tool(self, ctx: ToolContext, call: FunctionCall, args: Any, lang: str, emit: Emit, a: _Answer,
                  before: threading.Event | None = None,
                  failed: Callable[[], bool] = lambda: False) -> dict[str, Any]:
        """Run one call on ctx.conn. Its card and audit entry are recorded only after the calls before
        it (`before`), so the three surviving cards and the audit keys follow the call order. When an
        earlier call failed (`failed`), the answer ends with an `error` event, so this call sends no card."""
        spec = self.registry.tools[call.name]
        emit("status", {"stage": "tool", "tool": call.name, "label": template.pick(spec.status_label, lang)})
        t = self.clock()
        record: dict[str, Any] = {"name": call.name, "args": call.args}
        try:
            result = spec.fn(ctx, args)
        except DataUnavailable:
            raise
        except (psycopg.OperationalError, PoolTimeout):
            raise DataUnavailable() from None
        except PeriodOutOfRange:
            record.update(status="error", error="period_out_of_range")
        except ValueError:
            record.update(status="error", error="invalid_arguments")
        except Exception as exc:  # noqa: BLE001 - one tool failing is a normal answer with a warning
            log.warning("tool %s failed (%s)", call.name, type(exc).__name__)
            record.update(status="error", error="tool_failed")
        else:
            record.update(status="ok", evidence=list(result.evidence))
            record["view"] = result.model_view
            card = spec.card_builder(result)
            if before is not None:
                before.wait()
            stopped = failed()  # an earlier call found the database down: the answer ends with `error`
            with a.lock:
                a.tool_outputs[f"{call.name}#{len(a.tool_outputs) + 1}"] = result.model_view
                send = card is not None and not stopped and len(a.cards) < MAX_CARDS
                if send:
                    a.cards.append(card.card_id)
            if send:  # once the tool and the calls before it have finished, before the composer starts
                emit("card", {"card": card.model_dump(mode="json")})
        finally:
            ctx.conn = None
        record["latency_ms"] = self._ms(t)
        return record

    def _compose(self, request: ComposeInput, numbers, allowed: Allowed, *, skip_model: bool,
                 a: _Answer) -> tuple[AnswerDraft, bool]:
        lang = request.language
        if not skip_model:
            errors: list[str] = []
            for _ in range(2):  # the call and one retry with the errors
                t = self.clock()
                try:
                    result = self.model.compose(ComposeInput(**{**request.__dict__, "validation_errors": errors}))
                except Exception as exc:  # noqa: BLE001
                    errors = [f"the model call failed ({type(exc).__name__})"]
                    a.composer_attempts.append({"raw": None, "validation": errors, "latency_ms": self._ms(t)})
                    continue
                draft, errors = validate(result.text, language=lang, numbers=numbers, allowed=allowed)
                a.composer_attempts.append({"raw": result.text, "validation": "ok" if not errors else errors,
                                            "latency_ms": self._ms(t), "tokens": a.add_usage(result.usage)})
                if not errors:
                    return draft, False
        fallback = template.template_draft(request.data, request.errors, lang, allowed)
        draft, errors = validate(fallback, language=lang, numbers=numbers, allowed=allowed)
        a.composer_attempts.append({"raw": "template", "validation": "ok" if not errors else errors})
        if errors or draft is None:
            draft = AnswerDraft(language=lang, text=template.pick(template.NOTHING, lang), cited=[], lesson_key=None)
        return draft, True

    def _refuse(self, kind: str, lang: str, emit: Emit, a: _Answer) -> str:
        text, refusal = template.refusal(kind, lang)
        text = self._deliver(text, {}, emit)
        a.outcome, a.refusal, a.text, a.text_rendered = "refused", refusal, text, text
        emit("done", {"answer_id": a.answer_id, "outcome": "refused", "text": text, "text_rendered": text, "cited": [],
                      "follow_ups": template.follow_ups(a.question, lang, refused=True), "lesson": None,
                      "refusal": refusal, "clarify": None, "warnings": a.warnings})
        self.store.add_turn(a.conversation, {"question": a.question, "calls": [], "views": [], "answer": text})
        return lang

    def _clarify(self, args: Any, lang: str, emit: Emit, a: _Answer) -> str:
        question, options = args.question, list(args.options)
        # The clarifying question is model text: it passes the same text rules (R1, R9, R7).
        if any(check_text(t, Allowed(frozenset({self.as_of}), frozenset())) for t in [question, *options]):
            question = template.pick(template.CLARIFY["question"], lang)
            options = list(template.pick(template.CLARIFY["options"], lang))
        text = self._deliver(question, {}, emit)
        a.outcome, a.clarify, a.text, a.text_rendered = "clarify", {"question": question, "options": options}, text, text
        emit("done", {"answer_id": a.answer_id, "outcome": "clarify", "text": text, "text_rendered": text, "cited": [],
                      "follow_ups": [], "lesson": None, "refusal": None, "clarify": a.clarify, "warnings": a.warnings})
        self.store.add_turn(a.conversation, {"question": a.question, "calls": [], "views": [], "answer": text})
        return lang

    def _deliver(self, text: str, numbers: dict[str, Any], emit: Emit) -> str:
        """Send the text sentence by sentence; a `numbers` event precedes the first sentence citing a
        number. Returns the delivered text, which equals the concatenated deltas."""
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
        sent: set[str] = set()
        pieces = []
        for i, sentence in enumerate(sentences):
            piece = sentence + (" " if i < len(sentences) - 1 else "")
            new = [n for n in dict.fromkeys(TOKEN.findall(piece)) if n not in sent]
            if new:
                emit("numbers", {"numbers": {n: numbers[n].model_dump(mode="json") for n in new}})
                sent.update(new)
            emit("delta", {"text": piece})
            pieces.append(piece)
        return "".join(pieces)

    # ---- audit ---------------------------------------------------------------------------------

    def _ms(self, since: float) -> int:
        return int((self.clock() - since) * 1000)

    def _write_audit(self, req: AskRequest, a: _Answer) -> None:
        record = {
            "answer_id": a.answer_id or None,
            "conversation_id": a.conversation.conversation_id if a.conversation else None,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "customer_id": req.customer_id,
            "as_of": self.as_of.isoformat(),
            "language": a.language,
            "question": a.question or guard.clean(req.message),
            "guard_flags": a.flags,
            "model": {"id": getattr(self.model, "model_id", type(self.model).__name__),
                      # prompt versions (name@sha8) when the model has them, e.g. the Gemini adapter
                      "planner_prompt": getattr(self.model, "planner_prompt", None),
                      "composer_prompt": getattr(self.model, "composer_prompt", None)},
            "planner_turns": a.planner_turns,
            "tool_outputs": a.tool_outputs,   # model views only: never rows, merchant ids or the customer id
            "numbers": a.numbers,
            "composer_attempts": a.composer_attempts,
            "outcome": a.outcome,
            "refusal": a.refusal,
            "clarify": a.clarify,
            "text": a.text,
            "text_rendered": a.text_rendered,
            "cards": a.cards,
            "warnings": a.warnings,
            "error": a.error,
            "usage": a.usage,                 # tokens and cost summed over the model calls of this answer
            "latency_ms": {"first_card": a.first_card_ms, "done": self._ms(a.started)},
        }
        try:
            self.audit.write(record)
        except Exception as exc:  # noqa: BLE001 - an audit failure must not break the answer
            log.error("audit record not written (%s)", type(exc).__name__)
