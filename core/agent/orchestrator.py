"""The answer pipeline, steps 1 to 7 of agent-core.md section 7.1 (step 0 is in api.py).

1  meta: answer id, conversation (bound to one customer), language.   1a  input guard.
2  plan: the model chooses functions (mode ANY); the service's model plans with the rules first
   (gemini.RulesFirstModel). Planner errors: retry once, then the keyword planner (rules.py).
   Whether the language model may be used at all is decided once, before planning, by
   _model_unavailable (#244): a used-up ask window (#232), the switch file, the daily budget, a pause.
   When it may not, the rules plan and the template of the question writes, with no model request.
   Outcome (#244): "answered" whenever a plan was made, the tools ran and the text passed the
   validator, whoever wrote the text; the warning `llm_unavailable` when the model would have been
   used and was not. A question the rules do not recognise, with the model unavailable, gets the
   rules' general clarifying question (outcome "clarify").
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
import json
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, NamedTuple, Protocol

import psycopg
from psycopg_pool import PoolTimeout

from core.agent import guard, template, validator
from core.agent.audit import AuditLog
from core.agent.conversation import Conversation, ConversationStore, new_id
from core.agent.model import ComposeInput, FunctionCall, FunctionResponse, Model, PlanInput, PlanResult, Usage
from core.agent.registry import CallRejected, Registry
from core.agent.rules import RuleModel, human_request, meta_intent, unknown_object
from core.agent.validator import (TOKEN, Allowed, AnswerDraft, allowed_from, check_text, contents_claim, draft_problems,
                                  plain_text, render, repeated_period, unavailable_claim, validate)
from core.answer_text import find_dates, length_problems, scan_numbers
from core.app.api import texts as api_texts
from core.tools import config as tool_config
from core.tools.cache import TOOL_CACHE
from core.tools.context import NumberRegistry, ToolContext
from core.tools.missing import MissingData
from core.tools.periods import MONTHS_EN, PeriodOutOfRange

log = logging.getLogger("uvicorn.error")

MAX_ROUNDS = 2
MAX_DATA_CALLS = 6
MAX_CARDS = 3
MAX_PARALLEL = 2   # data calls of one turn running at the same time, one pool connection each
# A second lane runs only on a connection that is free at once, so one answer never queues for a
# second connection that another request needs (core/app/db.py holds a small pool).
SPARE_WAIT_S = 0.05
# The pending review's card joins an answer whose tools touched the spike's basket or category
# (contracts/api.md section 7.2): any basket or safe-to-spend answer, or a category filter naming it.
SPIKE_TOOLS = frozenset({"get_basket_breakdown", "get_safe_to_spend"})
CATEGORY_TOOLS = frozenset({"get_spending", "run_what_if"})
UNCLASSIFIED = "unclassified"   # the basket of a purchase whose review is pending (core.tools.reviews)

# The `error` event's texts are the API's catalogue (core/app/api/texts.py), so a failure reads the same
# before the stream (503) and inside it.
ERRORS = {code: (api_texts.ERRORS[code], True) for code in ("data_unavailable", "internal")}

Emit = Callable[[str, dict[str, Any]], None]
CYRILLIC = re.compile(r"[\u0400-\u04FF]")  # a message in Russian gets the English introduction (#287)
# A what-if or a cut names an amount too, but it is not a question about one purchase (#341).
WHAT_IF_WORDS = re.compile(r"\bwhat if\b|\bif i\b|\bcut\b|\breduc|\bjos\b|vähent|leikk", re.I)
# The question must point at a purchase ("what was that €1,080?", "mikä se 1080 euron ostos oli?"), not
# only contain the amount ("is 1080 a lot?", "can I afford €1080 rent?" take the normal path).
PURCHASE_REFERENCE = re.compile(
    r"\bwhat\s+(?:was|is|were)\b|\bwhat'?s\b|\bthat\b|\bpurchase\w*|\bpayment\b|\bcharge\b|\bbought\b"
    r"|\bostos\w*|\bmaksu\w*|\bmikä\s+(?:se|oli|tämä|tuo)\b|\bmitä\s+(?:se|oli)\b|\bostin\b", re.I)
# A question about Sentti's own question (#398): "why are you asking me about 1080 euros?", "miksi kysyt
# siitä ostoksesta?". With a pending review it means the review's purchase, with its amount or with none.
SENTTI_QUESTION = re.compile(
    r"\bwhy\s+(?:are|do|did)\s+you\s+ask(?:ing)?\b|\bwhy\s+(?:this|that|the)\s+question\b"
    r"|\bwhat\s+is\s+(?:this|that|the|your)\s+question\b|\bwhat\s+are\s+you\s+asking\b"
    r"|\bmiksi\s+kysy(?:t|tte|it|tit)\b|\bmiksi\s+(?:tämä|tuo|se)\s+kysymys\b"
    r"|\b(?:mitä|mistä)\s+(?:tämä|tuo|se)\s+kysymys\b|\bmitä\s+kysyt\b", re.I)
# After the question phrase and the amount, only these may be left, or the message asks something else
# ("why do you ask, will the bank give me a 1080 euro loan?" takes the normal path; review of #402).
REVIEW_FILLER = re.compile(
    r"(?:about|me|my|this|that|the|it|on|big|large|purchase|question|euro|euros|euroa|eurosta|euron|eur|tulee|iso"
    r"|isosta|minulta|siitä|tästä|tuosta|sitä|tätä|siita|tasta|tuosta|sita|tata|osto\w*|kysym\w*)", re.I)
# The euro words are their exact forms: "eurobonds" or "eurojackpot" is not filler (#447).
# A question about Sentti's question without an amount needs one of these (in the phrase or after it), or
# nothing left but a pointer to the purchase ("why do you ask?", "why are you asking about it?").
REVIEW_ANCHOR = re.compile(r"(?:purchase|question|osto\w*|kysym\w*)", re.I)
REVIEW_BARE = re.compile(r"(?:about|me|this|that|it|minulta|sitä|tätä|siitä|tästä|sita|tata|siita|tasta)", re.I)
_AMOUNT_TEXT = re.compile(r"€?\s?\d[\d\s.,]*\s?€?")
# The #368 path ("what was that €1,080?", "mikä se 1080 euron ostos oli?") also answers only a message about that
# purchase and nothing else (#424): after the purchase reference, the amount and the purchase's own date, only the
# #402 fillers and these purchase-question words may be left ("…and also what is my balance" takes the normal path).
PURCHASE_FILLER = re.compile(
    r"(?:was|is|were|oli|on|se|tämä|tuo|tama|what|again|exactly|hey|hi|so|ok|okay|oh|hmm|um|uh|sorry|wait|please|"
    r"pls|really|actually|just|now|hei|no|siis|taas|nyt|vielä|viela|oikein|tarkalleen|kiitos|mikä|mika)", re.I)
# The small words of a plain question about the purchase, on both paths (review of #519): "the purchase of €1,080",
# "what was that €1,080 charge for?", "a purchase at its own store". A closed list of whole words, as the others.
LINK_FILLER = re.compile(r"(?:of|for|a|an|at|from)", re.I)
# A question about Sentti's question may call the purchase a charge or a payment as well (review of #519): a list of
# its own, so the #402 list keeps the same lines as #437's. The #368 path has these in PURCHASE_REFERENCE.
REVIEW_PURCHASE_WORDS = re.compile(
    r"(?:charge|charges|payment|payments|maksu|maksun|maksua|maksusta|maksuun|maksut|maksuista)", re.I)
# A day and month without a year ("… on 3.5.") and a date with slashes ("28/9/2026", "28/9") are named dates as well,
# read day first: each must be the purchase's own (review of #519). Not inside a longer number or after a currency or
# a letter, so "€1,080.42." or "EUR10.12." stays an amount.
PARTIAL_DATE = re.compile(
    r"(?<![\w.,/€$£])(\d{1,2})(?:\.(\d{1,2})\.(?![\d,])|/(\d{1,2})(?:/(\d{4}))?(?![\d/]))")
REVIEW_AMOUNT_TOLERANCE_EUR = 1.0   # "€1,080" for a purchase of €1,080.42


class _Rest(NamedTuple):
    """What a review-amount message leaves after its question words (#424, review of #519)."""

    alone: bool                   # nothing but filler words is left
    dates: list[date]             # the dates it names: each must be the purchase's
    days: list[tuple[int, int, int | None]]   # "3.5.", "28/9/2026": (day, month, year or None), the purchase's own
    numbers: list[float]          # every number in it, dates aside: each must be the purchase's amount


def _partial_dates(text: str) -> tuple[list[tuple[int, int, int | None]], str]:
    """The dates find_dates leaves ("3.5.", "28/9/2026", "28/9") as (day, month, year or None), and the text with
    them blanked."""
    found: list[tuple[int, int, int | None]] = []

    def blank(m: re.Match) -> str:
        day, month = int(m.group(1)), int(m.group(2) or m.group(3))
        if 1 <= day <= 31 and 1 <= month <= 12:
            found.append((day, month, int(m.group(4)) if m.group(4) else None))
            return " "
        return m.group(0)

    return found, PARTIAL_DATE.sub(blank, text)


def _own_names(card: dict[str, Any]) -> list[re.Pattern]:
    """The pending purchase's own category (in both languages) and merchant label as whole-phrase patterns,
    longest first: naming them points at that purchase, like its own date (review of #519). Another category
    or store is another clause."""
    category = card.get("category") or ""
    labels = {category, *tool_config.CATEGORY_LABELS.get(category, ()), ((card.get("merchant") or {}).get("label") or "")}
    out = []
    for label in sorted((x for x in labels if x), key=len, reverse=True):
        words = re.findall(r"\w+", label)
        if words:
            out.append(re.compile(r"\b" + r"(?:\W+(?:and|ja)\W+|\W+)".join(map(re.escape, words)) + r"\b", re.I))
    return out


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


def _health_what_if(call: FunctionCall) -> bool:
    """A planned what-if on Health or on a code of the health MCC group, alone or in a list (R9, #510)."""
    if call.name != "run_what_if":
        return False
    sel = (call.args or {}).get("selection") or {}
    value = str(sel.get("value") or "")
    if sel.get("kind") == "category":
        return value.strip().lower() == "health"
    if sel.get("kind") == "mcc":
        return bool({c.strip() for c in value.split(",")} & set(tool_config.MCC_GROUPS["health"]))
    return False


class DataUnavailable(RuntimeError):
    """The database cannot be reached or is too slow (503 data_unavailable / `error` event)."""


class DataAccess(Protocol):
    def customer_exists(self, customer_id: str) -> bool: ...

    def connection(self) -> AbstractContextManager[Any]: ...

    # Optional: `connection_if_free(wait)` gives a connection only if one is free within `wait`
    # seconds and raises DataUnavailable otherwise. Without it, a turn's calls run one by one.


def _labels_in(views: Any) -> list[str]:
    """Every label in the tools' model views: the user's own words for their data (#419)."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("label"), str):
                found.append(node["label"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(views)
    return found


def error_envelope(code: str, language: str) -> dict[str, Any]:
    texts, retryable = ERRORS[code]
    return {"code": code, "message": template.pick(texts, language), "retryable": retryable}


@dataclass(frozen=True)
class LabelSteps:
    """The server's own label steps of an answer (#68, #196): the functions the overview uses.

    - `establish(ctx)` runs at a fixed point of every answer, before the model plans anything, so the
      model's plan cannot decide whether a review is created (R6). It finds or creates the pending spike
      review (core.tools.reviews.ensure_pending_for) and fills ctx._labels, which every tool call of the
      answer then shares: no tool call reads the labels again.
    - `card(ctx, review)` builds the pending review's card (core.tools.review_card.build).
    - `enabled()` says whether spike reviews are on (for the audit record).
    No model tool can write a label; only the app's label endpoint does (contract section 10)."""

    establish: Callable[[ToolContext], Any]
    card: Callable[[ToolContext, Any], dict[str, Any] | None]
    enabled: Callable[[], bool]


@dataclass
class AskRequest:
    customer_id: str
    message: str
    language: str = "auto"            # en | fi | auto
    conversation_id: str | None = None
    # The viewer session key (#144, #253): a hash of the viewer cookie, from known_viewer(request). The
    # answer's labels are this viewer's answers; None reads the shared state. Never logged, never in a
    # model view or the audit record.
    viewer: str | None = None
    # False when a model window of /api/ask is used up (#232): the rules plan and the template writes,
    # with the `llm_unavailable` warning, and no model request is made.
    model_allowed: bool = True


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
    introduced: bool = False   # the answer is Sentti's introduction, which itself says Sentti is an AI (#420)
    offer_contact: bool = False   # the rules' "I can't answer that one yet" answer (PlanResult.offer_contact)
    error: str | None = None
    first_card_ms: int | None = None
    label_state: dict[str, Any] | None = None  # counts only, never transaction ids (#196)
    ok_calls: list[dict[str, Any]] = field(default_factory=list)  # the data calls that returned a result
    # Why the language model was not used although it would have been (#244): "model_window" (#232),
    # "no_model" (no key), "off", "budget", "pause" (decided before planning by
    # Pipeline._model_unavailable), or "error" (it was asked and failed).
    model_unavailable: str | None = None
    # Per role (#383): the account-level reason above, or the role's own ("role_paused", "model_refused").
    # The planner's decides whether the model plans; the composer's whether it writes.
    planner_unavailable: str | None = None
    composer_unavailable: str | None = None
    template_failed: bool = False        # the template's text failed the validator: the fixed "nothing" text went out
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
                 fallback: Model | None = None, clock: Callable[[], float] = time.perf_counter,
                 labels: LabelSteps | None = None) -> None:
        self.registry = registry
        self.labels = labels  # None: no label step (tests without a database)
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
        emit = self._with_answer_fields(emit, a)
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
        a.flags = guard.flags(message, raw=req.message)   # #537: the line starts as typed
        # A question about Sentti itself (#287): answered here, with no plan, no tool, no number and no
        # model request, whatever the model's state. A refusal rule always wins (meta_intent checks).
        meta = meta_intent(message)
        foreign = bool(CYRILLIC.search(message))
        if meta is not None:
            return self._introduce(meta, "en" if foreign else lang, emit, a, foreign=foreign)
        if foreign and not re.search(r"[A-Za-z]", message):   # #352: a language Sentti does not speak
            return self._introduce("language", "en", emit, a)
        if human_request(message):   # #352: a human or a hard topic: the refusal with the way to the bank (#420)
            a.planner_turns.append({"round": 1, "source": "rules", "human_request": True})
            return self._refuse("out_of_scope", lang, emit, a)

        # The customer is bound here, from the request, and never from model output (R4).
        # The viewer's labels (#253): ensure_pending_for below reads and creates for this viewer, and
        # every tool call's copy of ctx keeps it.
        ctx = ToolContext(customer_id=req.customer_id, as_of=self.as_of, conn=None, language=lang,
                          numbers=LockedNumberRegistry(), viewer=req.viewer)
        # The label state, as the overview establishes it (#196): before the model plans, once per answer.
        review = self._establish_labels(ctx, a)  # `pending` below is the round's list of calls
        # "What was that €1,080?" (#341): the amount of the pending review's purchase is answered from the
        # review card, with no plan and no model request.
        if review is not None and self._answer_review_amount(ctx, review, message, lang, emit, a):
            return lang
        history = [{"question": t["question"], "calls": t["calls"], "results": t["views"]} for t in conv.turns]
        responses: list[FunctionResponse] = []
        model_turns: list[Any] = []
        views: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        data_calls = 0
        planner_fallback = False
        template_answer = False   # the rule planner asked for its own template answer (#552)
        model_failed = False   # the model was asked to plan and failed, or planned no data call (#341)
        a.model_unavailable = self._model_unavailable(req)
        a.planner_unavailable = a.model_unavailable or self._role_unavailable("plan")
        a.composer_unavailable = a.model_unavailable or self._role_unavailable("compose")

        for rnd in range(1, MAX_ROUNDS + 1):
            t_plan = self.clock()
            plan_in = PlanInput(
                question=message, language=lang, as_of=self.as_of.isoformat(), tools=self.registry.schemas(),
                history=history, responses=list(responses), model_turns=list(model_turns), guard_flags=a.flags,
                round=rnd)
            plan, source = self._plan(plan_in, a)
            if rnd == 1 and source == "model" and plan.calls and all(c.name == "finish" for c in plan.calls):
                # The model planned a question with no data call (#341): the composer could then only
                # introduce Sentti, with no number and no card. The rules plan it instead, and a
                # question they do not recognise gets their general clarifying question.
                a.planner_turns.append({"round": rnd, "source": "model", "error": "no data call",
                                        "latency_ms": self._ms(t_plan), "tokens": a.add_usage(plan.usage)})
                plan, source = self.fallback.plan(plan_in), "rules"
                model_failed = True
            calls = self._unknown_object_guard(message, plan.calls)
            model_turns.append(plan.raw)
            planner_fallback |= source == "fallback"
            # "why is my safe to spend lower?" (#552): the rule planner's own template answer, never the composer's
            template_answer = template_answer or getattr(plan, "template_answer", False)
            model_failed = model_failed or source == "fallback"
            if source == "fallback":
                a.model_unavailable = a.model_unavailable or "error"
            turn: dict[str, Any] = {"round": rnd, "mode": "ANY", "source": source, "calls": [],
                                    "latency_ms": self._ms(t_plan), "tokens": a.add_usage(plan.usage)}
            if calls is not plan.calls:
                turn["guard"] = "unknown_object"   # the planned unfiltered total became the breakdown (B3)
            a.planner_turns.append(turn)

            parsed, rejected = [], []
            for call in calls:
                try:
                    kind, args = self.registry.parse(call.name, call.args)
                    parsed.append((call, kind, args))
                except CallRejected as exc:
                    rejected.append((call, exc))
            controls = {call.name: args for call, kind, args in parsed if kind == "control"}
            if any(_health_what_if(call) for call in calls):
                # A what-if on Health or on any health MCC is declined everywhere, whatever the customer's own
                # history (R9; the coordinator's standing decision, #510): nothing of this turn runs.
                for call in calls:
                    turn["calls"].append({"name": call.name, "args": call.args, "status": "not_run: health"})
                return self._refuse("out_of_scope", lang, emit, a)

            if "decline" in controls or "ask_clarifying_question" in controls:
                # The turn ends at once: no data tool of this turn runs (R6).
                for call, kind, _ in parsed:
                    turn["calls"].append({"name": call.name, "args": call.args,
                                          "status": "ok" if kind == "control" else "not_run"})
                # The rules answered in the model's place: after a planner error, or for a question
                # they do not recognise while the model may not be used (#244).
                in_place = source == "fallback" or (a.planner_unavailable is not None
                                                    and not getattr(plan, "recognised", True))
                if in_place or (model_failed and "decline" not in controls):   # a rules refusal carries none
                    # An empty plan the rules replaced carries the warning like a failed one: the note and the
                    # warning always come together (#383, from the review of #368).
                    self._warn_llm_unavailable(a)
                if "decline" in controls:
                    return self._refuse(controls["decline"].kind.value, lang, emit, a)
                clarify = controls["ask_clarifying_question"]
                if source == "model" and not self._options_work(clarify.options, lang, history, message):
                    # A tapped option is sent as the next message: one the rules do not recognise would
                    # get another clarifying question when the model is off (#304). The rules' own
                    # clarifying question for this message is sent instead.
                    a.planner_turns.append({"round": rnd, "source": "rules", "error": "clarify options not recognised"})
                    clarify = self._rules_clarify(plan_in, lang)
                # The clarifying question says plainly that the question was not worked out, but only when
                # the model was asked and failed: with the model off or over budget the rules' clarifying
                # question is the normal answer (#341).
                a.offer_contact = getattr(plan, "offer_contact", False)   # #420: set by the rule planner only
                return self._clarify(clarify, lang, emit, a, not_worked_out=model_failed)

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
                    a.ok_calls.append({"name": call.name, "args": call.args})
                    views.append(record.pop("view"))
                    responses.append(FunctionResponse(call.name, views[-1], call.id))
                else:
                    errors.append({"tool": call.name, "error": record["error"],
                                   **({"reason": record["reason"]} if record.get("reason") else {}),
                                   **({"details": record["details"]} if record.get("details") else {})})
                    responses.append(FunctionResponse(call.name, {"error": record["error"]}, call.id))
            ran_data = any(k == "data" for _, k, _ in parsed)
            if "finish" in controls or data_calls >= MAX_DATA_CALLS or not (ran_data or rejected):
                break

        numbers = ctx.numbers.all()
        # the dates a tool returned in its missing-data error (the customer's first day of data, the last day)
        # may be named too, exactly as returned (#379 part B)
        allowed = allowed_from(numbers.values(), [*views, *(e["details"] for e in errors if e.get("details"))],
                               self.as_of)
        if review is not None:  # after `numbers`: the card's amount is not the composer's to cite
            self._attach_review(ctx, review, emit, a)
        # The model's planner may plan an unfiltered total for an object no category maps ("gym"): never that
        # total as the answer (#379, review of #443).
        unfiltered = bool(a.calls) and all(c["name"] == "get_spending" and not (c.get("args") or {}).get("filter")
                                           for c in a.calls)
        missing = template.missing_data_answer(views, errors, lang, self.as_of, unknown=unknown_object(message),
                                               unfiltered_spending=unfiltered)
        if missing is not None:
            return self._missing(missing, numbers, lang, emit, a)
        prev = conv.turns[-1] if conv.turns else None
        if len(views) > 1:
            # the national context line only beside a peer comparison alone; with another tool, the answer as on dev
            views = [{k: v for k, v in view.items() if k != "national"} if isinstance(view, dict) else view
                     for view in views]
        compose_in = ComposeInput(question=message, language=lang, as_of=self.as_of.isoformat(), data=views,
                                  errors=errors, previous_turn={"question": prev["question"], "answer": prev["answer"]} if prev else None)
        # Designed template answers: the rule planner's own template (#552/#574) and a peer comparison with the
        # national context line (#569), which the template states with its source and period and compares nothing.
        # The template writes; the model was not needed, it did not fail, so no llm_unavailable warning (the
        # coordinator's decision, one rule for both). The national line only beside a peer comparison alone.
        national = len(views) == 1 and isinstance(views[0], dict) and views[0].get("tool") == "get_peer_benchmark" \
            and bool(views[0].get("national"))
        designed = "rule_template" if template_answer else "national_context" if national else None
        unavailable = planner_fallback or a.composer_unavailable is not None
        draft, used_template = self._compose(compose_in, numbers, allowed, skip_model=unavailable or designed is not None,
                                             a=a)
        # With no key ("no_model") the template writes directly: running the rule model's own template
        # through the model-draft checks would only fill composer_attempts (review of #401). The composer's
        # own state decides, not the planner's (#383).
        if any(e["error"] == "tool_failed" for e in errors):
            a.warnings.append("tool_failed")
        # A plan was made and the tools ran, and the text passed the validator: "answered", whoever wrote
        # it. When even the template's text failed and the fixed "nothing" text went out: "fallback". The
        # template in the model's place carries the warning (#244).
        a.outcome = "fallback" if a.template_failed else "answered"
        if designed and not a.template_failed:
            # a designed template answer never warns, in any model state: the template writes it either way (one
            # rule with #574/#610, agreed with r-w3)
            a.planner_turns.append({"round": len(a.planner_turns) + 1, "source": "template", "designed": designed})
        elif used_template:
            a.model_unavailable = a.model_unavailable or a.composer_unavailable or "error"
            self._warn_llm_unavailable(a)
        elif a.model_unavailable == "no_model":
            self._warn_llm_unavailable(a)   # the rule model's template wrote the text: no model was used
        text = self._deliver(draft.text, numbers, emit)
        a.text, a.text_rendered = text, render(text, numbers)
        cited = list(dict.fromkeys(TOKEN.findall(text)))
        a.numbers = {i: {"value": numbers[i].value, "unit": numbers[i].unit.value, "method": numbers[i].method,
                         "evidence_ref": numbers[i].evidence_ref} for i in cited}
        emit("done", {"answer_id": a.answer_id, "outcome": a.outcome, "text": text, "text_rendered": a.text_rendered,
                      "cited": cited, "follow_ups": template.follow_ups(message, lang, views=views),
                      "lesson": template.lesson(draft.lesson_key, lang), "refusal": None, "clarify": None,
                      "warnings": a.warnings})
        self.store.add_turn(conv, {"question": message, "calls": a.calls, "views": views,
                                   "answer": TOKEN.sub("[number]", text)})
        return lang

    def _establish_labels(self, ctx: ToolContext, a: _Answer) -> Any:
        """The pending review (or None) and the answer's labels on ctx, with one connection."""
        if self.labels is None:
            return None
        try:
            with self.data.connection() as conn:
                ctx.conn = conn
                try:
                    pending = self.labels.establish(ctx)
                finally:
                    ctx.conn = None
        except (psycopg.OperationalError, PoolTimeout):
            raise DataUnavailable() from None
        if ctx._labels is not None:
            # The tool cache (#86) keys results by the label state and would read the labels again for
            # every call whose context has no key; the answer's labels give it the same key at once.
            from core.tools.cache import labels_key_of

            ctx.labels_key = labels_key_of(ctx._labels)
        values = list((ctx._labels or {}).values())
        a.label_state = {"spike_reviews": "on" if self.labels.enabled() else "off",
                         "labels": sum(v != UNCLASSIFIED for v in values),
                         "pending": sum(v == UNCLASSIFIED for v in values)}
        return pending

    def _attach_review(self, ctx: ToolContext, pending: Any, emit: Emit, a: _Answer) -> None:
        """Add the pending review's card when the answer's tools touched the spike's basket or category
        (contract section 7.2). It counts towards the three cards; it is the server's, never the model's."""
        # Only calls that returned a result count (review of #231): a failed call touched nothing.
        names = {c["name"] for c in a.ok_calls}
        filtered = [c for c in a.ok_calls if c["name"] in CATEGORY_TOOLS]
        if len(a.cards) >= MAX_CARDS or not (names & SPIKE_TOOLS or filtered):
            return
        def names_category(category: Any) -> bool:
            return any(json.dumps(category) in json.dumps(c["args"]) for c in filtered)

        category = None
        if not names & SPIKE_TOOLS:
            # The spike's category from the history the tools already loaded, so a card that would not be
            # sent takes no connection and writes no evidence. The history is often not loaded (a what-if
            # by category runs metric SQL only; the label step reads it only when it creates a review):
            # then the card is built and its own category decides, below.
            category = next((t.category for t in ctx._history or [] if t.id == getattr(pending, "tx_id", None)), None)
            if category is not None and not names_category(category):
                return
        try:
            with self.data.connection() as conn:
                ctx.conn = conn
                try:
                    card = self.labels.card(ctx, pending)
                finally:
                    ctx.conn = None
        except (DataUnavailable, psycopg.OperationalError, PoolTimeout):
            log.warning("review card not added (data unavailable)")  # the answer itself stands
            return
        if card is None:
            return
        if not names & SPIKE_TOOLS and category is None and not names_category(card.get("category")):
            return
        a.cards.append(card["card_id"])
        emit("card", {"card": card})

    def _model_unavailable(self, req: AskRequest) -> str | None:
        """Why the language model may not be used for this answer, or None when it may. The one place
        that decides it, before planning (#244); the planner, the composer, the outcome and the warning
        follow from a.model_unavailable:
        - "model_window": the request's model window is used up (AskRequest.model_allowed, #232);
        - "no_model": the service runs the rule model alone (no key); the rule model's own template
          writes, and the answer carries llm_unavailable like any template answer (#244, decision a);
        - the model's own state (Model.unavailable_reason): "off" (switch file), "budget" (daily budget
          0 or used up), "pause" (after a 429, a refused key or model, or failures in a row).
        Another model without unavailable_reason (a scripted model in tests) is always available."""
        if not getattr(req, "model_allowed", True):
            return "model_window"
        if isinstance(self.model, RuleModel):
            return "no_model"   # no language model configured (no key): the rules plan, the template writes
        probe = getattr(self.model, "unavailable_reason", None)
        if not callable(probe):
            return None
        try:
            return probe()
        except Exception as exc:  # noqa: BLE001 - the class name is logged, never the message
            log.warning("model state unreadable (%s); the rules and the template answer", type(exc).__name__)
            return "error"

    def _role_unavailable(self, kind: str) -> str | None:
        """A role's own reason ("role_paused", "model_refused") or None; a model without roles has none."""
        probe = getattr(self.model, "unavailable_reason", None)
        if not callable(probe):
            return None
        try:
            return probe(kind)
        except TypeError:          # a scripted model whose unavailable_reason takes no role
            return None
        except Exception as exc:  # noqa: BLE001 - the class name is logged, never the message
            log.warning("model role state unreadable (%s)", type(exc).__name__)
            return None

    @staticmethod
    def _warn_llm_unavailable(a: _Answer) -> None:
        if "llm_unavailable" not in a.warnings:
            a.warnings.append("llm_unavailable")

    def _plan(self, request: PlanInput, a: _Answer) -> tuple[PlanResult, str]:
        if a.planner_unavailable is not None and a.planner_unavailable != "no_model":
            # The planner may not be used: the rules plan, with no model request (#244, #383).
            return self.fallback.plan(request), "rules"
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
        always waits on a call that holds a connection and can finish.
        Tool results go through the tool cache (#86): the customer's label state is read once per answer
        before the lanes start, and a cached result runs no SQL."""
        if pending and TOOL_CACHE.enabled:
            try:
                TOOL_CACHE.ensure_labels_key(ctx, self.data.connection)   # copied into every call's context
            except (psycopg.OperationalError, PoolTimeout):
                raise DataUnavailable() from None
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
            # Through the tool cache (#86), on the lane's connection: a cached result runs no SQL, and its
            # numbers are registered in call order like a fresh call's.
            result = TOOL_CACHE.run(spec.name, spec.args_model, spec.fn, ctx, args)
        except DataUnavailable:
            raise
        except (psycopg.OperationalError, PoolTimeout):
            raise DataUnavailable() from None
        except PeriodOutOfRange as exc:
            record.update(status="error", error="period_out_of_range", reason=exc.reason,
                          **({"details": exc.details} if getattr(exc, "details", None) else {}))
        except MissingData as exc:   # a category never used, too few purchases (#379)
            # its Numbers are registered here, in call order, whether or not the tool cache ran the tool
            record.update(status="error", error=exc.reason, reason=exc.reason, details=exc.register(ctx.numbers))
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
                if not errors:
                    # The answer-length rule (#288): a longer draft is rejected like any other, so the retry
                    # gets the reason and the template writes after it.
                    errors = length_problems(draft.text, len(set(TOKEN.findall(draft.text))))
                    claim = None if request.errors else unavailable_claim(draft.text)
                    if claim:
                        # Nothing failed, so "not available" describes a wrong plan, not the data (#316).
                        errors.append(f"'{claim}': no calculation failed; say what the data shows instead")
                    inside = contents_claim(draft.text)
                    if inside:
                        # No tool says what a category contains (#395).
                        errors.append(f"'{inside}': name a category only by its label, never what it contains")
                    repeated = repeated_period(draft.text, numbers)
                    if repeated:
                        # "€3,010.59 a month a month": model drafts only. A template that trips it would be
                        # replaced by the "nothing found" text; templates are checked by tests instead.
                        errors.append(f"'{repeated}': the number's display already says how often; write it once")
                    joined = validator.amount_with_bank_product(draft.text, numbers)
                    if joined:
                        # #417: an amount next to the bank's screen or product reads as advice to put it
                        # there. Model drafts only, like the checks above; templates are checked by tests.
                        errors.append(f"'{joined}': never tell the user to put an amount into the bank's "
                                      "screen or product (S-mobiili, monthly saving, a fund); state the amount "
                                      "alone, the card's button opens the screen")
                    # The stand's other composer defects (#398): self-introduction, sums no tool computed, a
                    # count without its noun, a comparison without direction, a fixed bill to cut, wrong words.
                    errors += draft_problems(draft.text, numbers, has_data=bool(request.data),
                                             labels=_labels_in(request.data), views=request.data)
                a.composer_attempts.append({"raw": result.text, "validation": "ok" if not errors else errors,
                                            "latency_ms": self._ms(t), "tokens": a.add_usage(result.usage)})
                if not errors:
                    return draft, False
        fallback = template.template_draft(request.data, request.errors, lang, allowed, request.question)
        draft, errors = validate(fallback, language=lang, numbers=numbers, allowed=allowed)
        a.composer_attempts.append({"raw": "template", "validation": "ok" if not errors else errors})
        if errors or draft is None:
            a.template_failed = True
            draft = AnswerDraft(language=lang, text=template.pick(template.NOTHING, lang), cited=[], lesson_key=None)
        return draft, True

    @staticmethod
    def _with_answer_fields(emit: Emit, a: _Answer) -> Emit:
        """Every `done` event gets `actions` and `ai_disclosure` (#420, contract 0.3.3):
        - a refusal, the rules' "I can't answer that one yet" answer (a.offer_contact) and the "nothing
          found" fallback (outcome `fallback`) carry the way to a human, `open_host_screen` with target
          `contact_bank`; the general clarifying question does not;
        - the first answer of a conversation carries the AI disclosure, unless it is the introduction,
          which says it itself; a later answer never repeats it."""
        def send(event: str, payload: dict[str, Any]) -> None:
            if event == "done":
                lang = a.language.get("resolved") or "en"
                disclose = a.conversation is not None and not a.conversation.disclosed and not a.introduced
                if a.conversation is not None:
                    a.conversation.disclosed = True
                payload = {**payload,
                           "actions": [tool_config.contact_bank_action(lang)]
                           if payload.get("outcome") in ("refused", "fallback") or a.offer_contact
                           else payload.get("actions", []),
                           "ai_disclosure": template.pick(api_texts.AI_DISCLOSURE, lang) if disclose else None}
            emit(event, payload)
        return send

    def _introduce(self, intent: str, lang: str, emit: Emit, a: _Answer, foreign: bool = False) -> str:
        """Sentti's introduction (or a thank-you, the privacy answer, the language line) and the four brief
        questions as chips (done.follow_ups, which the app renders as question chips): outcome "answered",
        nothing cited, no warning. The full introduction comes once per conversation; a later greeting,
        identity, capabilities or help message gets one short sentence (#352). A message in Russian gets the
        English text and the line that Sentti answers in English or Finnish."""
        conv = a.conversation
        text = template.meta_text(intent, lang, introduced=conv is not None and conv.introduced)
        a.introduced = text == template.pick(template.INTRO, lang)
        if a.introduced and conv is not None:
            conv.introduced = True
        if foreign:
            text = f"{text} {template.pick(template.LANGUAGE, 'en')}"
        text = self._deliver(text, {}, emit)
        a.outcome, a.text, a.text_rendered = "answered", text, text
        a.planner_turns.append({"round": 1, "source": "rules", "meta_intent": intent})
        emit("done", {"answer_id": a.answer_id, "outcome": "answered", "text": text, "text_rendered": text, "cited": [],
                      "follow_ups": template.brief_questions(lang), "lesson": None, "refusal": None,
                      "clarify": None, "warnings": a.warnings})
        self.store.add_turn(a.conversation, {"question": a.question, "calls": [], "views": [], "answer": text})
        return lang

    def _unknown_object_guard(self, message: str, calls: list[FunctionCall]) -> list[FunctionCall]:
        """A planner may plan the unfiltered total for a thing no category maps ("how much do I spend on the
        gym?"), alone or beside another tool ("...on Netflix and what is safe to spend?"). Before anything runs,
        the unfiltered totals become one category breakdown for the same period, the other calls stay, and the
        turn finishes: no unfiltered total goes out as the answer to that thing. Alone, the answer is the rule
        path's: the thing named, the customer's largest categories, their chips (#379 part B, review B3; #510)."""
        unfiltered = [c for c in calls if c.name == "get_spending" and not (c.args or {}).get("filter")]
        if not unfiltered or "get_basket_breakdown" not in self.registry.tools or unknown_object(message) is None:
            return calls
        period = (unfiltered[0].args or {}).get("period") or {"preset": "last_6_months"}
        others = [c for c in calls if c not in unfiltered and c.name != "finish"
                  and not (c.name == "get_basket_breakdown" and (c.args or {}).get("period") == period)]
        return [FunctionCall("get_basket_breakdown", {"period": period}, unfiltered[0].id), *others,
                FunctionCall("finish")]

    def _missing(self, missing: tuple[str, list[str]], numbers: dict[str, Any], lang: str, emit: Emit,
                 a: _Answer) -> str:
        """An answer that is only a missing-data reason (#379, the coordinator's decision A): the template
        writes it, whoever planned the tool, with the model on or off; no compose request. Outcome
        "answered"; it cites only numbers the tool registered (too few purchases: the purchases themselves);
        the chips are questions the rules answer for this customer."""
        text = self._deliver(missing[0], numbers, emit)
        a.outcome, a.text, a.text_rendered = "answered", text, render(text, numbers)
        cited = list(dict.fromkeys(TOKEN.findall(text)))
        a.numbers = {i: {"value": numbers[i].value, "unit": numbers[i].unit.value, "method": numbers[i].method,
                         "evidence_ref": numbers[i].evidence_ref} for i in cited}
        a.planner_turns.append({"round": len(a.planner_turns) + 1, "source": "template", "missing_data": True})
        emit("done", {"answer_id": a.answer_id, "outcome": "answered", "text": text, "text_rendered": a.text_rendered,
                      "cited": cited, "follow_ups": missing[1], "lesson": None, "refusal": None, "clarify": None,
                      "warnings": a.warnings})
        self.store.add_turn(a.conversation, {"question": a.question, "calls": a.calls, "views": [], "answer": text})
        return lang

    def _refuse(self, kind: str, lang: str, emit: Emit, a: _Answer) -> str:
        text, refusal = template.refusal(kind, lang, a.question)
        text = self._deliver(text, {}, emit)
        a.outcome, a.refusal, a.text, a.text_rendered = "refused", refusal, text, text
        if kind == "out_of_scope" and template.made_up_request(a.question):
            # #352: no made-up or forecast number; the chips offer the typical income instead
            follow_ups = [template.pick(template.MADE_UP_CHIP, lang), *template.brief_questions(lang)[:2]]
        elif kind == "out_of_scope":
            follow_ups = template.brief_questions(lang)   # the generic decline: the four brief questions (#287)
        else:
            follow_ups = template.follow_ups(a.question, lang, refused=True)
        emit("done", {"answer_id": a.answer_id, "outcome": "refused", "text": text, "text_rendered": text, "cited": [],
                      "follow_ups": follow_ups, "lesson": None,
                      "refusal": refusal, "clarify": None, "warnings": a.warnings})
        self.store.add_turn(a.conversation, {"question": a.question, "calls": [], "views": [], "answer": text})
        return lang

    def _options_work(self, options: list[str], lang: str, history: list[dict[str, Any]], message: str) -> bool:
        """Every option of a model-written clarifying question is a next message the rules recognise
        (a full question such as "Where did my money go?", or "Last month" after this question)."""
        after = history + [{"question": message, "calls": [], "results": []}]
        for option in options:
            plan = self.fallback.plan(PlanInput(question=plain_text(option), language=lang, as_of=self.as_of.isoformat(),
                                                tools=self.registry.schemas(), history=after))
            if not getattr(plan, "recognised", True) or any(c.name == "ask_clarifying_question" for c in plan.calls):
                return False
        return True

    def _rules_clarify(self, plan_in: PlanInput, lang: str) -> Any:
        """The rules' clarifying question for this message, or their general one."""
        for call in self.fallback.plan(plan_in).calls:
            if call.name == "ask_clarifying_question":
                return self.registry.parse(call.name, call.args)[1]
        return dataclasses.make_dataclass("Clarify", ["question", "options"])(
            template.pick(template.CLARIFY_GENERAL["question"], lang),
            list(template.pick(template.CLARIFY_GENERAL["options"], lang)))

    def _clarify(self, args: Any, lang: str, emit: Emit, a: _Answer, not_worked_out: bool = False) -> str:
        # Plain text (#302): a model may write markdown here too.
        question, options = plain_text(args.question), [plain_text(o) for o in args.options]
        # The clarifying question is model text: it passes the same text rules (R1, R9, R7).
        if any(check_text(t, Allowed(frozenset({self.as_of}), frozenset())) for t in [question, *options]):
            question = template.pick(template.CLARIFY["question"], lang)
            options = list(template.pick(template.CLARIFY["options"], lang))
        if not_worked_out:
            question = f"{template.pick(template.NOT_WORKED_OUT, lang)} {question}"
        text = self._deliver(question, {}, emit)
        a.outcome, a.clarify, a.text, a.text_rendered = "clarify", {"question": question, "options": options}, text, text
        emit("done", {"answer_id": a.answer_id, "outcome": "clarify", "text": text, "text_rendered": text, "cited": [],
                      "follow_ups": [], "lesson": None, "refusal": None, "clarify": a.clarify, "warnings": a.warnings})
        self.store.add_turn(a.conversation, {"question": a.question, "calls": [], "views": [], "answer": text})
        return lang

    def _review_card(self, ctx: ToolContext, review: Any) -> dict[str, Any] | None:
        """The pending review's card on one connection, or None (no purchase, data unavailable)."""
        try:
            with self.data.connection() as conn:
                ctx.conn = conn
                try:
                    return self.labels.card(ctx, review)
                finally:
                    ctx.conn = None
        except (DataUnavailable, psycopg.OperationalError, PoolTimeout):
            return None

    @staticmethod
    def _only_about_the_review(message: str, phrase: re.Match, has_amount: bool, lang: str) -> _Rest:
        """The message asks only about Sentti's question: after the question phrase, the amount and any date,
        nothing is left but filler words and punctuation (a confident full match, as the other rules).
        Without an amount it also needs an anchor (a purchase word or "this question", in the phrase or
        after it) or only a pointer left ("why do you ask?", "why are you asking about it?"). Also returns the
        dates and numbers it found: the caller checks they are the purchase's."""
        spans, rest = find_dates(message[:phrase.start()] + " " + message[phrase.end():], blank_all=True)
        days, rest = _partial_dates(rest)
        words = re.findall(r"[\w']+", _AMOUNT_TEXT.sub(" ", rest))
        found = ([span.start for span in spans], days, [v for v, _ in scan_numbers(rest, lang)])
        if any(not (REVIEW_FILLER.fullmatch(w) or LINK_FILLER.fullmatch(w) or REVIEW_PURCHASE_WORDS.fullmatch(w))
               for w in words):
            return _Rest(False, *found)
        if has_amount:
            return _Rest(True, *found)
        anchored = (any(REVIEW_ANCHOR.fullmatch(w) or REVIEW_PURCHASE_WORDS.fullmatch(w) for w in words)
                    or re.search(r"question|kysym", phrase.group(0), re.I) or all(REVIEW_BARE.fullmatch(w) for w in words))
        return _Rest(bool(anchored), *found)

    @staticmethod
    def _only_about_the_purchase(message: str, own: list[re.Pattern], lang: str) -> _Rest:
        """The #368 path's message asks only about the purchase (#424): after the purchase's own category and
        merchant label (`own`), every purchase reference, the amounts and any date, nothing is left but filler
        words. Also returns the dates and numbers it found (the caller checks they are the purchase's)."""
        for name in own:
            message = name.sub(" ", message)
        spans, rest = find_dates(PURCHASE_REFERENCE.sub(" ", message), blank_all=True)
        days, rest = _partial_dates(rest)
        words = re.findall(r"[\w']+", _AMOUNT_TEXT.sub(" ", rest))
        alone = all(REVIEW_FILLER.fullmatch(w) or PURCHASE_FILLER.fullmatch(w) or LINK_FILLER.fullmatch(w)
                    for w in words)
        return _Rest(alone, [span.start for span in spans], days, [v for v, _ in scan_numbers(rest, lang)])

    def _answer_review_amount(self, ctx: ToolContext, review: Any, message: str, lang: str, emit: Emit,
                              a: _Answer) -> bool:
        """Answer "what was that €1,080?" (#341) when an amount in the question is within a euro of the
        pending review's purchase, and "why are you asking me about 1080 euros?" or "why are you asking
        about that purchase?" (#398), a question about Sentti's own question, with the review's amount or
        with none: the purchase's category, date and amount, why Sentti asks, and the review card. False
        (the normal path answers) for any other question."""
        asked = [v for v, mark in scan_numbers(message, lang) if mark != "pct" and v >= 1]
        phrase = SENTTI_QUESTION.search(message)
        rest = self._only_about_the_review(message, phrase, bool(asked), lang) if phrase else None
        about_question = bool(rest and rest.alone)
        if WHAT_IF_WORDS.search(message) or a.flags:
            return False   # a guard flag (an injection marker) goes the normal way, to the planner's checks
        if not about_question and (not asked or not PURCHASE_REFERENCE.search(message)):
            return False
        # A refusal rule always wins, as for the introduction (#287): "should I invest €1,080 in bitcoin?"
        # or "will the bank approve my €1,080 loan?" is refused on the normal path.
        history = [{"question": t["question"], "calls": t["calls"], "results": t["views"]} for t in a.conversation.turns]
        rules = self.fallback.plan(PlanInput(question=message, language=lang, as_of=self.as_of.isoformat(),
                                             tools=self.registry.schemas(), history=history, guard_flags=a.flags))
        if any(c.name == "decline" for c in rules.calls):
            return False
        # A probe on a private registry first, so a question with another amount registers no number.
        probe = self._review_card(dataclasses.replace(ctx, numbers=NumberRegistry()), review)
        if probe is None:
            return False
        if not about_question:
            rest = self._only_about_the_purchase(message, _own_names(probe), lang)
            if not rest.alone:
                return False   # "what was that €1,080 and how much did I spend?": the normal path (#424)
        # Any amount in the question must be the purchase's; a question about Sentti's question may name none.
        amount = float(probe["amount"]["value"])
        if (asked or not about_question) and not any(abs(v - amount) <= REVIEW_AMOUNT_TOLERANCE_EUR for v in asked):
            return False
        if any(abs(v - amount) > REVIEW_AMOUNT_TOLERANCE_EUR for v in rest.numbers):
            return False   # "what is 10% of that €1,080?", "the €500 from the €1,080 purchase": a second number
        bought = date.fromisoformat(probe["date"])
        if any(d != bought for d in rest.dates) or any(
                (day, month, year or bought.year) != (bought.day, bought.month, bought.year) for day, month, year in rest.days):
            return False   # "… my purchase on 3 May 2026" or "… on 3.5.": another purchase than Sentti's
        card = self._review_card(ctx, review)
        if card is None:
            return False
        number_id = card["amount"]["id"]
        numbers = ctx.numbers.all()
        purchase_day = date.fromisoformat(card["date"])
        when = (f"{purchase_day.day}.{purchase_day.month}.{purchase_day.year}" if lang == "fi"
                else f"{purchase_day.day} {MONTHS_EN[purchase_day.month - 1]} {purchase_day.year}")
        category = tool_config.label(tool_config.CATEGORY_LABELS.get(card["category"], (card["category"],) * 2), lang)
        text = template.pick(template.REVIEW_WHY if about_question else template.REVIEW_PURCHASE, lang).format(
            category=category, date=when, amount="{{" + number_id + "}}")
        draft, errors = validate({"language": lang, "text": text, "cited": [number_id], "lesson_key": None},
                                 language=lang, numbers=numbers, allowed=allowed_from(numbers.values(), [], self.as_of))
        if errors or draft is None:
            log.warning("review purchase answer failed the validator (%d problems)", len(errors))
            return False
        a.planner_turns.append({"round": 1, "source": "rules", "review_amount": True})
        a.cards.append(card["card_id"])
        emit("card", {"card": card})
        text = self._deliver(draft.text, numbers, emit)
        a.outcome, a.text, a.text_rendered = "answered", text, render(text, numbers)
        a.numbers = {number_id: {"value": numbers[number_id].value, "unit": numbers[number_id].unit.value,
                                 "method": numbers[number_id].method, "evidence_ref": numbers[number_id].evidence_ref}}
        emit("done", {"answer_id": a.answer_id, "outcome": "answered", "text": text, "text_rendered": a.text_rendered,
                      "cited": [number_id], "follow_ups": template.follow_ups(message, lang), "lesson": None,
                      "refusal": None, "clarify": None, "warnings": a.warnings})
        self.store.add_turn(a.conversation, {"question": message, "calls": [], "views": [],
                                             "answer": TOKEN.sub("[number]", text)})
        return True

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
            "label_state": a.label_state,     # counts of the labels in force (#196), never transaction ids
            "model_unavailable": a.model_unavailable,   # why the language model was not used (#244), or null
            "planner_unavailable": a.planner_unavailable,     # per role (#383)
            "composer_unavailable": a.composer_unavailable,
            "latency_ms": {"first_card": a.first_card_ms, "done": self._ms(a.started)},
        }
        try:
            self.audit.write(record)
        except Exception as exc:  # noqa: BLE001 - an audit failure must not break the answer
            log.error("audit record not written (%s)", type(exc).__name__)
