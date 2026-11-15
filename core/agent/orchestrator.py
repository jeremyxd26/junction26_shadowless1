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
import hashlib
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
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, NamedTuple, Protocol

import psycopg
from psycopg_pool import PoolTimeout

from core.agent import (agent_mode, explain_number, finlit_kb, glossary, guard, offers, sbank_kb, talk_checks, talk_mode, template,
                        validator, why_review)
from core.agent.audit import AuditLog
from core.agent.conversation import Conversation, ConversationStore, new_id
from core.agent.model import ComposeInput, FunctionCall, FunctionResponse, Model, PlanInput, PlanResult, Usage
from core.agent.registry import CONTROL, CallRejected, Registry
from core.agent.rules import HEALTH as RULE_HEALTH
from core.agent.rules import WHAT_IF_MORE_OPTIONS, WHAT_IF_WHICH_OPTIONS, what_if_which_question
from core.agent.rules import RuleModel, goodbye_greeting, human_request, meta_intent, unknown_object
from core.agent.rules import conversation_feedback, garbled_input
from core.agent.validator import (TOKEN, Allowed, AnswerDraft, allowed_from, check_text, contents_claim, draft_problems,
                                  plain_text, render, repeated_period, unavailable_claim, validate)
from core.answer_text import answer_kind, find_dates, length_problems, scan_numbers
from core.app.api import texts as api_texts
from core.tools import config as tool_config
from core.tools import evidence as tool_evidence
from core.tools import periods as tool_periods
from core.tools.cache import TOOL_CACHE
from core.tools.context import NumberRegistry, ToolContext
from core.tools.formatting import display as format_display
from core.tools.missing import MissingData
from core.tools.models import Action, Card, Number, Period, Unit
from core.tools.numbers import model_number
from core.tools.periods import MONTHS_EN, PeriodOutOfRange
from core.tools.selection import Selection

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
# A greeting or a thank-you too short for the detector, in Finnish ("moi", "kiitti"): the answer is Finnish.
SHORT_FI = re.compile(r"(moi|moikka|moro|hei|heippa|terve|kiitos|kiitti|kiitoksia|selva|selv\u00E4|joo|okei|kylla|kyll\u00E4)\W*", re.I)


def short_language(message: str) -> str | None:
    """'fi' for a whole message that is a short Finnish greeting or thanks, else None (the detector is unsure)."""
    return "fi" if SHORT_FI.fullmatch(message.strip()) else None
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


def _words_answer(turn: dict[str, Any]) -> bool:
    """An answer in words (talk mode, the literacy answers, the bank's help), not a number answer."""
    return bool(turn.get("talk") or turn.get("words"))


def _not_a_question(question: str) -> bool:
    """A meta message or feedback, which "answer my previous question" skips."""
    return meta_intent(question) is not None or conversation_feedback(question) is not None


def _last_data_turn(turns: list[dict[str, Any]]) -> dict[str, Any]:
    """The conversation's last turn with data: a question back, a greeting or a refusal in between ran no tool and
    gave no number, so "Mitä tää numero tarkoittaa?" after "Selitä yksinkertaisemmin" got its general question back
    still means the last answer's number. {} when no turn ran a tool."""
    return next((t for t in reversed(turns) if t.get("calls") or t.get("views") or t.get("explain")), {})


def _main_number(numbers: dict[str, Number], cited: list[str]) -> Number | None:
    """The answer's main number for "what does this number mean?" (#821): the first it cites with an evidence ref,
    else the first registered (the card's headline)."""
    return next((numbers[i] for i in [*cited, *numbers] if i in numbers and numbers[i].evidence_ref), None)


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


HEALTH_MERCHANT = tuple(f"{kind.lower()} " for kind in tool_config.MERCHANT_KIND_BY_CATEGORY["Health"])


def _health_spending(call: dict[str, Any] | FunctionCall) -> bool:
    """A get_spending call filtered on Health, on the health MCC group or on a health merchant's alias ("Health
    service A", "Terveyspalvelu A") (#598); a planned call or a call record of the answer (#571)."""
    name, args = (call.name, call.args) if isinstance(call, FunctionCall) else (call["name"], call.get("args"))
    flt = (args or {}).get("filter") or {}
    return name == "get_spending" and ("Health" in (flt.get("categories") or [])
                                       or "health" in (flt.get("mcc_groups") or [])
                                       or str(flt.get("merchant") or "").strip().lower().startswith(HEALTH_MERCHANT))


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
    # "text" (default) or "voice" (#873): on voice an open follow-up after any data answer takes talk mode
    channel: str = "text"


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
    sources: list[dict[str, Any]] | None = None   # done.sources (#884, contract 0.3.19): the official sources used
    kind: str = "ordinary"               # the length rule's kind (answer_text.answer_kind): ordinary or why (#572)
    # #598: the model planned a Health total ("the gym" mapped to Health); the call was dropped before it ran and the
    # thing is answered as an unknown one. The user's word, "" when there is none to quote.
    health_dropped: str | None = None
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
                 labels: LabelSteps | None = None, finlit: Any | None = None) -> None:
        self.registry = registry
        self.finlit = finlit  # finlit_kb.FinlitSource, or None: no literacy route (tests, no key, FINLIT_RAG=off)
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
        # The answer speaks the question's language, not the app setting ("moi" with the UI in English gets
        # Finnish), when that language is clear; a very short or unsure message keeps the previous turn's
        # language, else the app's.
        question_lang = short_language(message) or guard.confident_language(message)
        if question_lang in ("en", "fi"):
            lang = question_lang
        elif conv.turns and conv.language in ("en", "fi"):
            lang = conv.language
        else:
            lang = req.language if req.language in ("en", "fi") else (conv.language or "en")
        a.language = {"requested": req.language, "resolved": lang, "detector": detected}
        conv.language = lang
        a.answer_id = new_id("ans_")
        if reset:
            a.warnings.append("conversation_reset")
        emit("meta", {"answer_id": a.answer_id, "conversation_id": conv.conversation_id, "language": lang,
                      "as_of": self.as_of.isoformat()})
        emit("status", {"stage": "understanding", "tool": None, "label": template.pick(template.STATUS_UNDERSTANDING, lang)})
        a.flags = guard.flags(message, raw=req.message)   # #537: the line starts as typed
        a.kind = answer_kind(message)   # a why/how answer may be longer (#572)
        # A question about Sentti itself (#287): answered here, with no plan, no tool, no number and no
        # model request, whatever the model's state. A refusal rule always wins (meta_intent checks).
        meta = meta_intent(message)
        if meta == "greeting" and conv.turns and goodbye_greeting(message):
            meta = "thanks"   # "moi moi" after an answer is a goodbye: the closing line, never a new greeting (#630)
        foreign = bool(CYRILLIC.search(message))
        if meta == "confused" and template.previous_turn(conv.turns, _not_a_question) is not None:
            # "wait what", "täh": what was unclear, with the simpler explanation of the last answer as the chip
            return self._say(template.pick(template.CONFUSED, lang), lang, emit, a, "confused",
                             [template.pick(template.CONFUSED_CHIP, lang)])
        if meta == "confused":
            meta = "greeting"   # nothing said yet: the greeting-style reply
        if meta == "feelings":   # "I'm tired", "väsyttää": one kind line and a soft offer, never a refusal
            return self._say(template.pick(template.FEELINGS, lang), lang, emit, a, "feelings",
                             [template.pick(template.FEELINGS_CHIP, lang)])
        if meta == "recall":   # "What did I ask? Remind me": from the conversation, no tool and no model
            return self._recall(conv.turns, lang, emit, a)
        if meta == "context":
            found = template.context_topic(conv.turns)
            if found is not None:
                return self._context(found, lang, emit, a)
            meta = "greeting"   # nothing talked about yet: the greeting-style reply
        if meta is not None:
            return self._introduce(meta, "en" if foreign else lang, emit, a, foreign=foreign)
        if foreign and not re.search(r"[A-Za-z]", message):   # #352: a language Sentti does not speak
            return self._introduce("language", "en", emit, a)
        # Feedback on the conversation (Renat's FI transcript): no plan, no tool and no model.
        feedback = conversation_feedback(message)
        if feedback == "brief":
            conv.brief = True
            return self._say(template.pick(template.BRIEF_ACK, lang), lang, emit, a, "brief",
                             template.meta_follow_ups("greeting", lang))
        if feedback in ("misunderstood", "previous"):
            prev = template.previous_turn(conv.turns, _not_a_question)
            if feedback == "misunderstood":
                chips = [prev["question"]] if prev else template.meta_follow_ups("greeting", lang)
                return self._say(template.pick(template.MISUNDERSTOOD, lang), lang, emit, a, "misunderstood", chips)
            if prev is None:
                return self._say(template.pick(template.RECALL_NOTHING, lang), lang, emit, a, "previous",
                                 template.meta_follow_ups("greeting", lang))
            if prev.get("unclear"):   # never an older, different topic in its place
                return self._say(template.pick(template.PREVIOUS_UNCLEAR, lang), lang, emit, a, "previous",
                                 template.meta_follow_ups("greeting", lang))
            # "Answer my previous question": that question is answered again, as if asked now.
            a.planner_turns.append({"round": 0, "source": "rules", "meta_intent": "previous"})
            message = str(prev["question"])
            a.flags = guard.flags(message, raw=message)
            a.kind = answer_kind(message)
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
        if self._answer_finlit(req, ctx, review, message, lang, emit, a):   # "Mitä on korkoa korolle?" (#884)
            return lang
        if self._answer_glossary(ctx, review, message, lang, emit, a):   # "What is a buffer?" (#568)
            return lang
        if self._answer_sbank_kb(ctx, review, message, lang, emit, a):   # "How do I block my card?" (#791)
            return lang
        if self._answer_explain_number(ctx, message, lang, emit, a):   # "What does this number mean?" (#821)
            return lang
        if self._answer_kb_simpler(message, lang, emit, a):   # "Explain it more simply" after an S-Bank help answer
            return lang
        if self._answer_talk(ctx, req, message, lang, emit, a):   # "why does it matter?", "any tips?" (#873)
            return lang
        # a talk answer (#873) ran no tool: the planner's history is the data turns, so "and last month?" after it
        # still follows the last data answer
        history = [{"question": t["question"], "calls": t["calls"], "results": t["views"]} for t in conv.turns
                   if not t.get("talk")]
        if self._garbled(message, lang, history, a):   # "onks se sopuudlikaa": ask again, no card and no model
            fi, en = guard.language_scores(message)
            said = "fi" if fi >= 1 and en == 0 else "en" if en >= 1 and fi == 0 else lang
            return self._say(template.pick(template.DIDNT_CATCH, said), said, emit, a, "garbled",
                             template.brief_questions(said), unclear=True)
        if self._agent_usable(req, a) and self._agent_takes(message, lang, history) \
                and self._answer_agent(req, ctx, review, message, lang, emit, a, "planner"):
            return lang   # agent mode (#937): the loop answers what the rules do not recognise
        responses: list[FunctionResponse] = []
        model_turns: list[Any] = []
        views: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        data_calls = 0
        planner_fallback = False
        template_answer = False   # the rule planner asked for its own template answer (#552)
        bonus_received = False    # the S-Bonus received: the estimate after a designed lead (#639)
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
            guarded_calls = self._health_filter_guard(message, plan.calls, source, a)
            calls = guarded_calls if guarded_calls is not plan.calls else self._unknown_object_guard(message, plan.calls)
            model_turns.append(plan.raw)
            planner_fallback |= source == "fallback"
            # "why is my safe to spend lower?" (#552): the rule planner's own template answer, never the composer's
            template_answer = template_answer or getattr(plan, "template_answer", False)
            if getattr(plan, "template_answer", False) is True and getattr(plan, "offer_contact", False) is True:
                a.offer_contact = True   # #806: the budget side of a borrowing question offers the way to the bank
            bonus_received = bonus_received or getattr(plan, "bonus_received", False)   # #639
            model_failed = model_failed or source == "fallback"
            if source == "fallback":
                a.model_unavailable = a.model_unavailable or "error"
            turn: dict[str, Any] = {"round": rnd, "mode": "ANY", "source": source, "calls": [],
                                    "latency_ms": self._ms(t_plan), "tokens": a.add_usage(plan.usage)}
            if calls is not plan.calls:
                # the planned unfiltered total became the breakdown (B3), or a planned Health total was dropped (#598)
                turn["guard"] = "health_filter" if guarded_calls is not plan.calls else "unknown_object"
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
                clarify = self._what_if_chips(ctx, clarify, lang)   # #888: no chip leads to a dead end
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

        if template_answer:   # "why lower" names the review purchase that moved safe to spend (#575)
            views = [why_review.with_effect(self.data, self.labels, ctx, review, v) for v in views]
        numbers = ctx.numbers.all()
        # the dates a tool returned in its missing-data error (the customer's first day of data, the last day)
        # may be named too, exactly as returned (#379 part B)
        allowed = allowed_from(numbers.values(), [*views, *(e["details"] for e in errors if e.get("details"))],
                               self.as_of)
        review_card = False   # whether this answer carries the pending review's card (#572: then no offer)
        if review is not None:  # after `numbers`: the card's amount is not the composer's to cite
            cards_before = len(a.cards)
            self._attach_review(ctx, review, emit, a)
            review_card = len(a.cards) > cards_before
        # The model's planner may plan an unfiltered total for an object no category maps ("gym"): never that
        # total as the answer (#379, review of #443).
        unfiltered = bool(a.calls) and all(c["name"] == "get_spending" and not (c.get("args") or {}).get("filter")
                                           for c in a.calls)
        missing = template.missing_data_answer(views, errors, lang, self.as_of, unknown=unknown_object(message),
                                               unfiltered_spending=unfiltered)
        if missing is not None:
            return self._missing(missing, numbers, lang, emit, a, views=views)
        prev = conv.turns[-1] if conv.turns else None
        if len(views) > 1:
            # the national context line only beside a peer comparison alone; with another tool, the answer as on dev
            views = [{k: v for k, v in view.items() if k not in ("national", "age_band")} if isinstance(view, dict)
                     else view for view in views]   # and the age band's line likewise (#883)
        compose_in = ComposeInput(question=message, language=lang, as_of=self.as_of.isoformat(), data=views,
                                  errors=errors, previous_turn={"question": prev["question"], "answer": prev["answer"]} if prev else None)
        # Designed template answers, one rule for all (the coordinator's decision): the rule planner's own template
        # (#552/#574); a model-planned Health total that was dropped before it ran (#598): the template says the thing
        # can't be seen on its own, then answers the other question; a Health total that ran, the per-tool template
        # with the other tool's sentence (#571, R9); a peer comparison with the national context line (#569), only when
        # it is the answer's only data tool. The template writes, never the composer, and as the model was not needed,
        # it did not fail: no llm_unavailable warning, in any model state.
        national = len(views) == 1 and isinstance(views[0], dict) and views[0].get("tool") == "get_peer_benchmark" \
            and bool(views[0].get("national"))
        # #883: the age band's line beside a comparison of total spending, the same rule as the national line
        age_band = len(views) == 1 and isinstance(views[0], dict) and views[0].get("tool") == "get_peer_benchmark" \
            and bool(views[0].get("age_band"))
        dropped = a.health_dropped is not None
        health_total = any(_health_spending(c) for c in a.calls)
        designed = ("rule_template" if template_answer else "health_filter_dropped" if dropped
                    else "health" if health_total else "national_context" if national
                    else "age_band_context" if age_band
                    else "bonus_received" if bonus_received else None)
        unavailable = planner_fallback or a.composer_unavailable is not None
        lead = (template.unknown_lead(a.health_dropped, lang) if dropped
                else template.pick(template.BONUS_RECEIVED_LEAD, lang) if designed == "bonus_received" else None)
        draft, used_template = self._compose(compose_in, numbers, allowed, skip_model=unavailable or designed is not None,
                                             a=a, lead=lead)
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
            # a designed template answer never warns, in any model state: the template writes it either way; the planner
            # turns record the template and why (#552, #598, #571, #569; one rule, #610 and #585)
            a.planner_turns.append({"round": len(a.planner_turns) + 1, "source": "template", "designed": designed})
        elif used_template:
            a.model_unavailable = a.model_unavailable or a.composer_unavailable or "error"
            self._warn_llm_unavailable(a)
        elif a.model_unavailable == "no_model":
            self._warn_llm_unavailable(a)   # the rule model's template wrote the text: no model was used
        if conv.brief:   # "you talk too much": the first sentence, and an estimate's caveat, if that still passes
            draft = self._briefer(draft, lang, numbers, allowed)
        text = self._deliver(draft.text, numbers, emit)
        a.text, a.text_rendered = text, render(text, numbers)
        cited = list(dict.fromkeys(TOKEN.findall(text)))
        a.numbers = {i: {"value": numbers[i].value, "unit": numbers[i].unit.value, "method": numbers[i].method,
                         "evidence_ref": numbers[i].evidence_ref} for i in cited}
        # #572: the answer's next step, the listed offer's question, comes first among the chips
        follow_ups = offers.next_step(template.follow_ups(message, lang, views=views), views=views, language=lang,
                                      question=message, outcome=a.outcome, review_pending=review_card)
        emit("done", {"answer_id": a.answer_id, "outcome": a.outcome, "text": text, "text_rendered": a.text_rendered,
                      "cited": cited, "follow_ups": follow_ups,
                      "lesson": template.lesson(draft.lesson_key, lang), "refusal": None, "clarify": None,
                      "warnings": a.warnings})
        self.store.add_turn(conv, {"question": message, "calls": a.calls, "views": views,
                                   "answer": TOKEN.sub("[number]", text), "explain": _main_number(numbers, cited),
                                   "shown": [numbers[i] for i in cited if i in numbers]})   # talk mode may cite them (#873)
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
            details = exc.register(ctx.numbers)
            record.update(status="error", error=exc.reason, reason=exc.reason, details=details)
            # The audit's tool outputs list what the call returned (#609): its reason and the model view of each
            # Number the missing-data answer may cite, so a cited number is one a tool of the answer returned.
            if before is not None:
                before.wait()
            with a.lock:
                a.tool_outputs[f"{call.name}#{len(a.tool_outputs) + 1}"] = {
                    "error": exc.reason, **{key: model_number(ctx.numbers.get(details[key])) for key in exc.numbers}}
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
                 a: _Answer, lead: str | None = None) -> tuple[AnswerDraft, bool]:
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
                    errors = length_problems(draft.text, len(set(TOKEN.findall(draft.text))), kind=a.kind)
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
                        errors.append(f"'{repeated}': the number's display already says how often; write the "
                                      "number alone, with no period phrase after it and no 'a typical month of' or "
                                      "'tavallisena kuukautena' before it")
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
        if lead:   # #598: the sentence on the thing that can't be seen on its own, before the other answer
            fallback = {**fallback, "text": f"{lead} {fallback['text']}".strip()}
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
                           "ai_disclosure": template.pick(api_texts.AI_DISCLOSURE, lang) if disclose else None,
                           **({"sources": a.sources} if a.sources else {})}
            emit(event, payload)
        return send

    def _introduce(self, intent: str, lang: str, emit: Emit, a: _Answer, foreign: bool = False) -> str:
        """Sentti's introduction (or a thank-you, the privacy answer, the language line) and the four brief
        questions as chips (done.follow_ups, which the app renders as question chips): outcome "answered",
        nothing cited, no warning. The full introduction comes once per conversation; a later greeting,
        identity, capabilities or help message gets one short sentence (#352). A message in Russian gets the
        English text and the line that Sentti answers in English or Finnish."""
        conv = a.conversation
        text = template.meta_text(intent, lang, introduced=conv is not None and conv.introduced,
                                  turn=len(conv.turns) if conv is not None else 0)
        a.introduced = text == template.pick(template.INTRO, lang)
        if a.introduced and conv is not None:
            conv.introduced = True
        if foreign:
            text = f"{text} {template.pick(template.LANGUAGE, 'en')}"
        text = self._deliver(text, {}, emit)
        a.outcome, a.text, a.text_rendered = "answered", text, text
        a.planner_turns.append({"round": 1, "source": "rules", "meta_intent": intent})
        emit("done", {"answer_id": a.answer_id, "outcome": "answered", "text": text, "text_rendered": text, "cited": [],
                      "follow_ups": template.meta_follow_ups(intent, lang), "lesson": None, "refusal": None,
                      "clarify": None, "warnings": a.warnings})
        self.store.add_turn(a.conversation, {"question": a.question, "calls": [], "views": [], "answer": text})
        return lang

    def _answer_kb_simpler(self, message: str, lang: str, emit: Emit, a: _Answer) -> bool:
        """"Explain it more simply" right after an S-Bank help answer (r-coord's live check of #921): that entry in
        short, its first sentence after "In short:", with its source line, and the full question as the chip. No
        model. False unless the last turn was a help answer from an entry."""
        turns = a.conversation.turns if a.conversation is not None else []
        entry_id = turns[-1].get("kb") if turns else None
        if not entry_id or a.flags or not explain_number.asks_simpler(message):
            return False
        entry = next((e for e in sbank_kb.ENTRIES if e.id == entry_id), None)
        if entry is None:
            return False
        i = 1 if lang == "fi" else 0
        body = entry.answer(lang)
        first = (re.split(r"(?<=[.!?])\s+", body.strip()) or [body])[0]
        text = f"{template.pick(template.KB_SIMPLER, lang).format(first=first)} " \
               f"{sbank_kb.SOURCE_LINE[i].format(url=entry.source_url)}"
        question = str(turns[-1].get("question") or "")
        self._say(text, lang, emit, a, "kb_simpler", [question] if question else [])
        # the short answer is a help answer too: "simpler" again gets the same entry
        a.conversation.turns[-1].update({"words": True, "kb": entry_id})
        return True

    def _say(self, text: str, lang: str, emit: Emit, a: _Answer, intent: str, follow_ups: list[str],
             unclear: bool = False) -> str:
        """A fixed reply with no plan, no tool, no number and no model request (garbled input, feedback)."""
        text = self._deliver(text, {}, emit)
        a.outcome, a.text, a.text_rendered = "answered", text, text
        a.planner_turns.append({"round": 1, "source": "rules", "meta_intent": intent})
        emit("done", {"answer_id": a.answer_id, "outcome": "answered", "text": text, "text_rendered": text, "cited": [],
                      "follow_ups": follow_ups, "lesson": None, "refusal": None, "clarify": None,
                      "warnings": a.warnings})
        turn = {"question": a.question, "calls": [], "views": [], "answer": text}
        if unclear:
            turn["unclear"] = True   # "answer my previous question" then asks for it again
        self.store.add_turn(a.conversation, turn)
        return lang

    def _garbled(self, message: str, lang: str, history: list[dict[str, Any]], a: _Answer) -> bool:
        """A short message that reads as noise and that the rules do not recognise (see rules.garbled_input)."""
        if a.flags or not garbled_input(message):
            return False
        plan = self.fallback.plan(PlanInput(question=message, language=lang, as_of=self.as_of.isoformat(),
                                            tools=self.registry.schemas(), history=history, guard_flags=a.flags))
        data = [c for c in plan.calls if c.name not in ("ask_clarifying_question", "finish")]
        return not getattr(plan, "recognised", False) and not data

    @staticmethod
    def _briefer(draft: Any, lang: str, numbers: dict[str, Any], allowed: Allowed) -> Any:
        """The answer's first sentence, with a sentence that says it is an estimate, when that text passes the
        validator; else the answer as it was."""
        sentences = [s for s in re.split(r"(?<=[.!?])\s+", draft.text.strip()) if s]
        if len(sentences) < 2:
            return draft
        keep = [sentences[0]] + [s for s in sentences[1:] if re.search(r"estimate|not a promise|arvio|ei lupaus", s, re.I)]
        text = " ".join(keep)
        if text == draft.text.strip():
            return draft
        short, errors = validate({"language": lang, "text": text, "cited": list(dict.fromkeys(TOKEN.findall(text))),
                                  "lesson_key": getattr(draft, "lesson_key", None)},
                                 language=lang, numbers=numbers, allowed=allowed)
        return short if not errors and short is not None else draft

    def _recall(self, turns: list[dict[str, Any]], lang: str, emit: Emit, a: _Answer) -> str:
        """"What did I ask? Can you remind me?": the previous question and the topic of its answer, then "Want to
        continue?", with that question as the chip; with nothing asked yet, "We haven't talked about anything yet.
        What would you like to know?" No plan, no tool, no number and no model request."""
        text, question = template.recall_text(turns, lang, lambda q: meta_intent(q) is not None)
        text = self._deliver(text, {}, emit)
        a.outcome, a.text, a.text_rendered = "answered", text, text
        a.planner_turns.append({"round": 1, "source": "rules", "meta_intent": "recall"})
        emit("done", {"answer_id": a.answer_id, "outcome": "answered", "text": text, "text_rendered": text, "cited": [],
                      "follow_ups": [question] if question else template.meta_follow_ups("greeting", lang),
                      "lesson": None, "refusal": None, "clarify": None, "warnings": a.warnings})
        self.store.add_turn(a.conversation, {"question": a.question, "calls": [], "views": [], "answer": text})
        return lang

    def _context(self, found: tuple[tuple[str, str], str], lang: str, emit: Emit, a: _Answer) -> str:
        """"Do you understand what we're talking about?": "Yes — we talked about <topic>. Want me to explain it more
        simply?", with the previous question as the chip. No plan, no tool, no number and no model request."""
        (topic, question) = found
        text = self._deliver(template.pick(template.CONTEXT_REPLY, lang).format(topic=template.pick(topic, lang)), {}, emit)
        a.outcome, a.text, a.text_rendered = "answered", text, text
        a.planner_turns.append({"round": 1, "source": "rules", "meta_intent": "context"})
        emit("done", {"answer_id": a.answer_id, "outcome": "answered", "text": text, "text_rendered": text, "cited": [],
                      "follow_ups": [question] if question else template.meta_follow_ups("greeting", lang), "lesson": None,
                      "refusal": None, "clarify": None, "warnings": a.warnings})
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

    def _health_filter_guard(self, message: str, calls: list[FunctionCall], source: str,
                             a: _Answer) -> list[FunctionCall]:
        """#598: a Health total the model planned runs only when the question itself names health (the rules' HEALTH
        words, #571); "the gym", "yoga", "a massage" are no health spending. Otherwise the call is dropped before
        anything runs and the thing is answered as the rules answer an unknown thing: beside another question, the
        other calls still run and the template says Sentti can't see the thing on its own; alone, the call becomes the
        category breakdown of the same period, the rule path's answer. Never a Health card for such a word."""
        health = [c for c in calls if _health_spending(c)]
        if source != "model" or not health or re.search(RULE_HEALTH, guard.fold(message)):
            return calls
        a.health_dropped = unknown_object(message) or ""
        others = [c for c in calls if c not in health]
        if any(c.name not in CONTROL for c in others) or "get_basket_breakdown" not in self.registry.tools:
            return others or [FunctionCall("finish")]
        period = (health[0].args or {}).get("period") or {"preset": "last_6_months"}
        return [FunctionCall("get_basket_breakdown", {"period": period}, health[0].id),
                *[c for c in others if c.name != "finish"], FunctionCall("finish")]

    def _missing(self, missing: tuple[str, list[str]], numbers: dict[str, Any], lang: str, emit: Emit,
                 a: _Answer, views: list[dict[str, Any]] = ()) -> str:
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
                      "cited": cited, "follow_ups": offers.missing_step(   # #572: the breakdown is the next step
                          missing[1], lang, breakdown_answered=any(isinstance(v, dict) and
                                                                   v.get("tool") == "get_basket_breakdown"
                                                                   for v in views)),
                      "lesson": None, "refusal": None, "clarify": None, "warnings": a.warnings})
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

    def _what_if_chips(self, ctx: ToolContext, clarify: Any, lang: str) -> Any:
        """The what-if question back's chips follow the customer's data (#888): a chip is offered only when the
        what-if tool gives this customer an estimate for it (the tool's own check: enough purchases in the last six
        complete months and a saving above zero), and the next candidate takes a dropped chip's place, so "What if
        I took fewer taxis?" never leads to "too few transactions". The question's examples are the offered chips, so
        its text never names a category the chips leave out. Any other question back, or any error, keeps its text and
        chips as they are."""
        i = 1 if lang == "fi" else 0
        defaults = list(WHAT_IF_WHICH_OPTIONS[i])
        if [plain_text(o) for o in getattr(clarify, "options", None) or []] != defaults:
            return clarify
        try:
            with self.data.connection() as conn:
                probe = dataclasses.replace(ctx, conn=conn, numbers=NumberRegistry())
                keep: list[str] = []
                for option in (*defaults, *WHAT_IF_MORE_OPTIONS[i]):
                    if len(keep) == len(defaults):
                        break
                    if self._what_if_estimates(probe, option, lang):
                        keep.append(option)
        except Exception as exc:  # noqa: BLE001 - the chips as they were, never a failed answer
            log.warning("what-if chips not checked (%s)", type(exc).__name__)
            return clarify
        return SimpleNamespace(question=what_if_which_question(keep, lang), options=keep)

    def _what_if_estimates(self, probe: ToolContext, option: str, lang: str) -> bool:
        """Whether the chip, sent with a cut, is a what-if the tool estimates for this customer."""
        asked = option.rstrip("?") + (" 10 %?" if lang == "fi" else " by 10%?")
        plan = self.fallback.plan(PlanInput(question=asked, language=lang, as_of=self.as_of.isoformat(),
                                            tools=self.registry.schemas()))
        call = next((c for c in plan.calls if c.name == "run_what_if"), None)
        if call is None or "run_what_if" not in self.registry.tools:
            return False
        try:
            _, args = self.registry.parse(call.name, call.args)
            data = self.registry.tools[call.name].fn(probe, args).data
        except (MissingData, ValueError, CallRejected):   # too few purchases, nothing to cut, a refused selection
            return False
        return data.status in ("estimate", "estimate_with_caveat") and Decimal(str(data.saving_per_month.value)) > 0

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

    def _answer_glossary(self, ctx: ToolContext, review: Any, message: str, lang: str, emit: Emit, a: _Answer) -> bool:
        """Answer "What is a buffer?" / "Mitä tarkoittaa eräpäivä?" (#568): our fixed definition of one term and,
        when an existing Number means exactly what its sentence says, the customer's own Number from the existing
        tool (its method id and evidence, through the tool cache as for any call). No plan, no composer, no model
        request. False (the normal path answers) unless the whole message asks about exactly one term, no guard
        flag is set and no refusal rule of the rule model (people included) declines it."""
        term = glossary.match(message)
        if term is None or a.flags:
            return False
        history = [{"question": t["question"], "calls": t["calls"], "results": t["views"]} for t in a.conversation.turns]
        rules = self.fallback.plan(PlanInput(question=message, language=lang, as_of=self.as_of.isoformat(),
                                             tools=self.registry.schemas(), history=history, guard_flags=a.flags))
        if any(c.name == "decline" for c in rules.calls):
            return False
        calls: list[dict[str, Any]] = []
        views: list[dict[str, Any]] = []
        number_id = None
        own = glossary.OWN.get(term.key)
        if own is not None:
            call = FunctionCall(own.tool, dict(own.args))
            try:
                records = self._run_tools(ctx, [(call, self.registry.parse(call.name, call.args)[1])], lang, emit, a)
            except (DataUnavailable, CallRejected, ValueError):
                records = []   # the definition alone: it needs no data
            calls.append({"name": call.name, "args": call.args})
            for record in records:
                if record.get("status") == "ok":
                    views.append(record["view"])
                    a.ok_calls.append({"name": call.name, "args": call.args})   # for the review card, below
                    number_id = glossary.own_number_id(term.key, record["view"])
        numbers = ctx.numbers.all()
        allowed = allowed_from(numbers.values(), views, self.as_of)
        draft = None
        for nid in dict.fromkeys([number_id, None]):   # with the Number, else the definition alone
            text = glossary.answer_text(term.key, lang, nid)
            draft, errors = validate({"language": lang, "text": text, "cited": [nid] if nid else [], "lesson_key": None},
                                     language=lang, numbers=numbers, allowed=allowed)
            if not errors and draft is not None and repeated_period(draft.text, numbers) is None:
                break
            log.warning("glossary answer %s failed the validator (%d problems)", term.key, len(errors))
            draft = None
        if draft is None:
            return False
        a.calls = calls
        a.planner_turns.append({"round": 1, "source": "rules", "glossary": term.key, "calls": calls})
        if review is not None:  # the pending review's card, as on the normal path (#581 review)
            self._attach_review(ctx, review, emit, a)
        text = self._deliver(draft.text, numbers, emit)
        cited = list(dict.fromkeys(TOKEN.findall(text)))
        a.outcome, a.text, a.text_rendered = "answered", text, render(text, numbers)
        a.numbers = {i: {"value": numbers[i].value, "unit": numbers[i].unit.value, "method": numbers[i].method,
                         "evidence_ref": numbers[i].evidence_ref} for i in cited}
        emit("done", {"answer_id": a.answer_id, "outcome": "answered", "text": text, "text_rendered": a.text_rendered,
                      "cited": cited, "follow_ups": offers.glossary_step(term.key, template.brief_questions(lang), lang),
                      "lesson": None,
                      "refusal": None, "clarify": None, "warnings": a.warnings})
        self.store.add_turn(a.conversation, {"question": message, "calls": calls, "views": views,
                                             "answer": TOKEN.sub("[number]", text)})
        return True

    def _answer_explain_number(self, ctx: ToolContext, message: str, lang: str, emit: Emit, a: _Answer) -> bool:
        """Answer "What does this number mean?" / "Mitä tää numero tarkoittaa?" right after an answer (#821): the
        previous answer's main number (the first it cited) by template, with its label and period, the method's
        summary as the evidence sheet shows it and the transactions it rests on, and a card whose action opens its
        evidence. With no previous answer that cited a number: which number? No plan, no composer, no model request.
        False (the normal path answers) unless explain_number matches the whole message, no guard flag is set and the
        rule model neither declines the message nor answers it with a rule of its own."""
        if a.flags or not explain_number.matches(message):
            return False
        turns = a.conversation.turns if a.conversation is not None else []
        if explain_number.asks_simpler(message) and turns and _words_answer(turns[-1]):
            return False   # the last answer was words (talk, literacy, the bank's help): talk mode says it simpler
        history = [{"question": t["question"], "calls": t["calls"], "results": t["views"]} for t in turns]
        rules = self.fallback.plan(PlanInput(question=message, language=lang, as_of=self.as_of.isoformat(),
                                             tools=self.registry.schemas(), history=history, guard_flags=a.flags))
        if any(c.name == "decline" for c in rules.calls) or getattr(rules, "recognised", False):
            return False
        prev = _last_data_turn(turns)
        main = prev.get("explain")
        if not isinstance(main, Number) or not main.evidence_ref:
            a.planner_turns.append({"round": 1, "source": "rules", "explain_number": "which"})
            self._clarify(SimpleNamespace(question=template.pick(explain_number.WHICH, lang), options=[]), lang, emit, a)
            return True
        number = ctx.numbers.register(main.model_copy(update={"id": None}))
        count = self._explain_count(ctx, number, lang)
        numbers = ctx.numbers.all()
        name, translated = explain_number.label_for(number, lang)   # #833: a follow-up in the other language
        label = explain_number.label_text(name)
        lead = (template.pick(explain_number.LEAD_ONLY_LABEL, lang).format(label=label) if translated
                else template.pick(explain_number.LEAD, lang).format(label=label, period=number.period.label))
        bare = template.pick(explain_number.LEAD_ONLY_LABEL, lang).format(label=label)   # the card names the period
        info = api_texts.method_info(number.method)
        summary = api_texts.pick(explain_number.SUMMARIES.get(number.method) or info.summary, lang).strip() \
            if info.summary else ""
        summary = summary if not summary or summary[-1] in ".!?" else summary + "."
        rests = (template.pick(explain_number.COUNT, lang)[0 if count.value == 1 else 1].format(
            count="{{" + count.id + "}}") if count is not None else "")
        allowed = allowed_from(numbers.values(), [], self.as_of)
        draft = None
        variants = [(first, *rest) for first in (lead, bare) for rest in ((summary, rests), (rests,), (summary,), ())]
        for text in dict.fromkeys(" ".join(p for p in parts if p) for parts in variants):
            draft, errors = validate({"language": lang, "text": text, "cited": list(dict.fromkeys(TOKEN.findall(text))),
                                      "lesson_key": None}, language=lang, numbers=numbers, allowed=allowed)
            if not errors and draft is not None:
                break
            draft = None
        if draft is None:
            log.warning("explain-number answer failed the validator (%d problems)", len(errors))
            return False
        ref = number.evidence_ref
        card = Card(card_id="card_" + hashlib.sha256(f"explain_number|{ref}".encode()).hexdigest()[:12], type="metric",
                    title=number.label, subtitle=number.period.label, evidence_ref=ref,
                    actions=[Action(type="open_evidence", label=template.pick(explain_number.ACTION, lang),
                                    evidence_ref=ref)],
                    status=None, primary=number, secondary=[count] if count is not None else [], comparison=None,
                    components=[])
        a.planner_turns.append({"round": 1, "source": "rules", "explain_number": number.method})
        a.cards.append(card.card_id)
        emit("card", {"card": card.model_dump(mode="json")})
        text = self._deliver(draft.text, numbers, emit)
        cited = list(dict.fromkeys(TOKEN.findall(text)))
        a.outcome, a.text, a.text_rendered = "answered", text, render(text, numbers)
        a.numbers = {i: {"value": numbers[i].value, "unit": numbers[i].unit.value, "method": numbers[i].method,
                         "evidence_ref": numbers[i].evidence_ref} for i in cited}
        emit("done", {"answer_id": a.answer_id, "outcome": "answered", "text": text, "text_rendered": a.text_rendered,
                      "cited": cited, "follow_ups": template.follow_ups(message, lang), "lesson": None,
                      "refusal": None, "clarify": None, "warnings": a.warnings})
        # the previous turn's calls and results stay the conversation's last data, so "and last month?" after the
        # explanation still reads them (#300), and the same number can be explained again
        self.store.add_turn(a.conversation, {"question": message, "calls": prev.get("calls") or [],
                                             "views": prev.get("views") or [], "answer": TOKEN.sub("[number]", text),
                                             "explain": main, "shown": [numbers[i] for i in cited if i in numbers]})
        return True

    # ---- agent mode (#937) ------------------------------------------------------------------------------------------

    def _agent_usable(self, req: AskRequest, a: _Answer) -> bool:
        """Whether this turn may go to agent mode's loop: the switch is on (read per answer), no guard flag, a model
        with the loop and the judge, and the model, its agent role and the judge all available."""
        if not agent_mode.enabled() or a.flags:
            return False
        if not callable(getattr(self.model, "agent_turn", None)) or not callable(getattr(self.model, "judge", None)):
            why = "no_loop_model"
        else:
            judge = self._role_unavailable("judge")
            why = (self._model_unavailable(req) or self._role_unavailable("agent")
                   or (f"judge_{judge}" if judge else None))
        if why:
            # why the loop sent no request (#937 live check): "model_window" is /api/ask's per-minute model window
            # (ASK_RATE_LIMIT_*), which answers with the rules and llm_unavailable whether agent mode is on or off
            log.info("agent mode on but skipped (%s); the old path answers", why)
            a.planner_turns.append({"source": "agent", "skipped": why})
            return False
        return True

    def _agent_takes(self, message: str, lang: str, history: list[dict[str, Any]]) -> bool:
        """The planner's place: the loop takes a question the rule planner does not recognise, with no decline, no
        designed template and no contact offer of the rules, and no health topic (R9). Every rule-claimed question
        (the demo fast paths) and every refusal stays the rules'."""
        if re.search(RULE_HEALTH, guard.fold(message)) or talk_checks._GENERAL_HEALTH.search(message):
            return False
        if agent_mode.question_stands_down(message, literacy=finlit_kb.question_kind(message) == "literacy"):
            return False
        # talk triggers and literacy questions keep their own routes (Renat's live probes of #955): the loop takes only
        # what nobody else claims
        if talk_mode.trigger(message) is not None or finlit_kb.question_kind(message) is not None \
                or finlit_kb.invest_general(message):
            return False
        plan = self.fallback.plan(PlanInput(question=message, language=lang, as_of=self.as_of.isoformat(),
                                            tools=self.registry.schemas(), history=history, guard_flags=[], round=1))
        if any(c.name == "decline" for c in plan.calls):
            return False
        if getattr(plan, "template_answer", False) or getattr(plan, "offer_contact", False):
            return False
        return not getattr(plan, "recognised", True)

    def _agent_profile(self, ctx: ToolContext) -> list[str]:
        """The user's largest baskets as labels only, from the basket breakdown through the tool cache, with its own
        registry so no number of it can be cited. [] when the tool is not registered or fails."""
        spec = self.registry.tools.get("get_basket_breakdown")
        if spec is None:
            return []
        try:
            _, args = self.registry.parse(spec.name, {})
            if TOOL_CACHE.enabled:
                TOOL_CACHE.ensure_labels_key(ctx, self.data.connection)
            with self.data.connection() as conn:
                own = dataclasses.replace(ctx, conn=conn, numbers=NumberRegistry())
                view = TOOL_CACHE.run(spec.name, spec.args_model, spec.fn, own, args).model_view
            return list(dict.fromkeys(_labels_in(view)))[:agent_mode.PROFILE_LABELS]
        except Exception as exc:  # noqa: BLE001 - the loop runs without the profile
            log.warning("agent mode: profile not read (%s)", type(exc).__name__)
            return []

    def _agent_check(self, text: str | None, lang: str, numbers: dict[str, Any], allowed: Allowed, shown: set[str],
                     views: list[dict[str, Any]], literacy: bool, a: _Answer) -> tuple[Any, list[str]]:
        """The cheap layer on one draft: the validator (every figure a registered number of this conversation, no
        digit outside a token), then the talk checks (words) or the composer's model-draft checks and the talk
        checks that allow the user's own data (tools ran)."""
        text = (text or "").strip()
        raw = {"language": lang, "text": text, "cited": list(dict.fromkeys(TOKEN.findall(text))), "lesson_key": None}
        if not views and literacy and not raw["cited"]:
            draft, errors = finlit_kb.draft_problems(raw, lang)
            return draft, errors + agent_mode.literacy_text_problems(text)
        draft, errors = validate(raw, language=lang, numbers=numbers, allowed=allowed)
        if errors or draft is None:
            return draft, errors or ["no draft"]
        if not views:
            return draft, talk_mode.draft_problems(draft.text, numbers, shown, lang)
        errors = length_problems(draft.text, len(set(TOKEN.findall(draft.text))), kind=a.kind)
        errors += draft_problems(draft.text, numbers, has_data=True, labels=_labels_in(views), views=views)
        joined = validator.amount_with_bank_product(draft.text, numbers)
        if joined:
            errors.append(f"'{joined}': never tell the user to put an amount into the bank's screen or product")
        errors += agent_mode.data_text_problems(TOKEN.sub(" ", draft.text))
        return draft, errors

    def _agent_judge(self, message: str, text: str, lang: str, a: _Answer) -> str | None:
        """The safety judge on one draft: None when it passes, else the reason. A failed, timed-out, blocked or
        unreadable judge call is a hit."""
        t = self.clock()
        try:
            verdict = self.model.judge(message, text, lang)
        except Exception as exc:  # noqa: BLE001 - only the class name is kept
            a.planner_turns.append({"source": "judge", "verdict": "error", "error": type(exc).__name__,
                                    "latency_ms": self._ms(t)})
            return "the safety check could not run: write a shorter, plainer answer"
        usage = getattr(verdict, "usage", None)
        a.planner_turns.append({"source": "judge", "verdict": "ok" if verdict.ok else "hit",
                                "category": verdict.category, "latency_ms": self._ms(t),
                                **({"tokens": a.add_usage(usage)} if usage is not None else {})})
        if verdict.ok:
            return None
        return f"safety check ({verdict.category}): {verdict.reason or 'rewrite without it'}"

    def _answer_agent(self, req: AskRequest, ctx: ToolContext, review: Any, message: str, lang: str, emit: Emit,
                      a: _Answer, route: str) -> bool:
        """Agent mode's turn (#937): one model loop with the conversation, the profile, finlit fragments and the
        tool declarations. The model answers in words, asks back (the clarify mechanism) or calls tools through the
        registry's checks, at most MAX_TOOL_ROUNDS rounds. Every draft passes the cheap layer and the judge; one
        regenerate with the reasons, then agent_mode's natural fallback. False (the old path answers, as with the
        switch off) when the loop's first call fails before any tool ran."""
        conv = a.conversation
        turns = conv.turns if conv is not None else []
        shown: dict[str, Number] = {}
        for number in [n for t in turns for n in (t.get("shown") or [])][-8:]:
            registered = ctx.numbers.register(number)
            shown[registered.id] = registered
        prev = turns[-1] if turns else None
        history = [{"question": t.get("question"), "answer": t.get("answer")}
                   for t in turns[-agent_mode.HISTORY_TURNS:]]
        fragments = (self.finlit_fragments(ctx.customer_id, message, lang) if route == "finlit"
                     else self._talk_fragments(ctx, message, prev, lang))
        credited = finlit_kb.named(fragments)
        base = agent_mode.AgentInput(question=message, language=lang, as_of=self.as_of.isoformat(),
                                     tools=self.registry.schemas(), history=history, profile=self._agent_profile(ctx),
                                     sources=[f.data(include_text=f in credited) for f in fragments],
                                     shown=[model_number(n) for n in shown.values()])
        literacy = finlit_kb.question_kind(message) == "literacy"
        words_only = agent_mode.words_only(message, turns)
        if words_only:
            base = dataclasses.replace(base, shown=[] if agent_mode.asks_tips(message) else base.shown)
            if agent_mode.asks_tips(message):
                shown = {}
        planner_history = [{"question": t["question"], "calls": t["calls"], "results": t["views"]} for t in turns
                           if not t.get("talk")]
        rounds: list[tuple[Any, list[FunctionResponse]]] = []
        views: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        data_calls = 0
        text, raw_last = None, None
        self._start_compose_answer(object())   # this answer's own request count and deadline (#884), after retrieval
        for rnd in range(1, agent_mode.MAX_TOOL_ROUNDS + 2):
            t_round = self.clock()
            request = dataclasses.replace(base, rounds=list(rounds), round=rnd,
                                          tools_on=rnd <= agent_mode.MAX_TOOL_ROUNDS and not words_only)
            try:
                result = self.model.agent_turn(request)
            except Exception as exc:  # noqa: BLE001 - only the class name is kept
                a.planner_turns.append({"round": rnd, "source": "agent", "error": type(exc).__name__,
                                        "latency_ms": self._ms(t_round)})
                if not a.calls:
                    return False   # no tool ran yet, nothing was sent: the old path answers
                break
            turn: dict[str, Any] = {"round": rnd, "source": "agent", "route": route, "calls": [],
                                    "latency_ms": self._ms(t_round),
                                    **({"tokens": a.add_usage(result.usage)} if result.usage is not None else {})}
            a.planner_turns.append(turn)
            if not result.calls:
                text, raw_last = result.text, result.raw
                break
            if words_only and any(c.name not in ("decline", "ask_clarifying_question") for c in result.calls):
                # a words question never runs a tool (no card, no figure): the old path answers instead
                turn["calls"] = [{"name": c.name, "args": c.args, "status": "not_run: words only"}
                                 for c in result.calls]
                return False
            guarded = self._health_filter_guard(message, result.calls, "model", a)
            calls = guarded if guarded is not result.calls else self._unknown_object_guard(message, result.calls)
            parsed, rejected = [], []
            for call in calls:
                try:
                    kind, args = self.registry.parse(call.name, call.args)
                    parsed.append((call, kind, args))
                except CallRejected as exc:
                    rejected.append((call, exc))
            controls = {call.name: args for call, kind, args in parsed if kind == "control"}
            if any(_health_what_if(call) for call in calls):
                self._refuse("out_of_scope", lang, emit, a)
                return True
            if "decline" in controls or "ask_clarifying_question" in controls:
                turn["calls"] = [{"name": c.name, "args": c.args, "status": "ok" if k == "control" else "not_run"}
                                 for c, k, _ in parsed]
            if "decline" in controls:
                self._refuse(controls["decline"].kind.value, lang, emit, a)
                return True
            if "ask_clarifying_question" in controls:
                clarify = controls["ask_clarifying_question"]
                plan_in = PlanInput(question=message, language=lang, as_of=self.as_of.isoformat(),
                                    tools=self.registry.schemas(), history=planner_history, guard_flags=a.flags)
                if agent_mode.clarify_problems([clarify.question, *clarify.options]) \
                        or not self._options_work(clarify.options, lang, planner_history, message):
                    a.planner_turns.append({"round": rnd, "source": "rules", "error": "agent clarify replaced"})
                    clarify = self._rules_clarify(plan_in, lang)
                clarify = self._what_if_chips(ctx, clarify, lang)
                self._clarify(clarify, lang, emit, a)
                return True
            responses: list[FunctionResponse] = []
            for call, exc in rejected:
                responses.append(FunctionResponse(call.name, {"error": exc.code}, call.id))
                turn["calls"].append({"name": call.name, "args": call.args, "status": f"rejected: {exc.code}"})
            pending = []
            for call, kind, args in parsed:
                if kind == "control":
                    turn["calls"].append({"name": call.name, "args": call.args, "status": "ok"})
                elif data_calls >= MAX_DATA_CALLS:
                    turn["calls"].append({"name": call.name, "args": call.args, "status": "not_run: call limit"})
                else:
                    data_calls += 1
                    pending.append((call, args))
            records = self._run_tools(ctx, pending, lang, emit, a)
            for (call, args), record in zip(pending, records):
                a.calls.append({"name": call.name, "args": call.args})
                if "view" in record:
                    a.ok_calls.append({"name": call.name, "args": call.args})
                    views.append(record.pop("view"))
                    responses.append(FunctionResponse(call.name, views[-1], call.id))
                else:
                    errors.append({"tool": call.name, "error": record["error"]})
                    responses.append(FunctionResponse(call.name, {"error": record["error"]}, call.id))
                turn["calls"].append(record)
            rounds.append((result.raw, responses))

        numbers = ctx.numbers.all()
        allowed = allowed_from(numbers.values(), views, self.as_of)
        draft = None
        problems: list[str] = []
        for attempt in range(2):   # the draft and one regenerate with the reasons
            if attempt == 1:
                if text is None:
                    break
                t_retry = self.clock()
                try:
                    result = self.model.agent_turn(dataclasses.replace(
                        base, rounds=list(rounds), round=len(rounds) + 1, tools_on=False, retry_turn=raw_last,
                        retry_errors=problems))
                except Exception as exc:  # noqa: BLE001
                    a.planner_turns.append({"round": len(rounds) + 1, "source": "agent", "retry": True,
                                            "error": type(exc).__name__, "latency_ms": self._ms(t_retry)})
                    break
                a.planner_turns.append({"round": len(rounds) + 1, "source": "agent", "retry": True,
                                        "latency_ms": self._ms(t_retry),
                                        **({"tokens": a.add_usage(result.usage)} if result.usage is not None else {})})
                if result.calls:
                    break
                text, raw_last = result.text, result.raw
            if text is None:
                break
            candidate, problems = self._agent_check(text, lang, numbers, allowed, set(shown), views, literacy, a)
            if not problems and candidate is not None:
                reason = self._agent_judge(message, render(candidate.text, numbers), lang, a)
                problems = [reason] if reason else []
            a.composer_attempts.append({"raw": text, "source": "agent", "validation": "ok" if not problems else problems})
            if not problems and candidate is not None:
                draft = candidate
                break
        from_model = draft is not None
        if draft is None:   # the natural fallback, never the old "could not work this out" text
            draft = AnswerDraft(language=lang, text=agent_mode.fallback_text(lang), cited=[], lesson_key=None)
            a.planner_turns.append({"source": "agent", "fallback": True})
        if review is not None and views:   # cards only when tools ran on the user's own data in this turn
            self._attach_review(ctx, review, emit, a)
        if conv is not None and conv.brief and from_model:
            draft = self._briefer(draft, lang, numbers, allowed)
        if credited and from_model:   # the Sources row under the answer; the text carries no link (#884)
            a.sources = finlit_kb.sources_field(fragments, lang) or None
        if any(e["error"] == "tool_failed" for e in errors):
            a.warnings.append("tool_failed")
        text = self._deliver(draft.text, numbers, emit)
        cited = list(dict.fromkeys(TOKEN.findall(text)))
        a.outcome, a.text, a.text_rendered = "answered", text, render(text, numbers)
        a.numbers = {i: {"value": numbers[i].value, "unit": numbers[i].unit.value, "method": numbers[i].method,
                         "evidence_ref": numbers[i].evidence_ref} for i in cited}
        follow_ups = (template.follow_ups(message, lang, views=views) if from_model
                      else template.brief_questions(lang))
        emit("done", {"answer_id": a.answer_id, "outcome": "answered", "text": text, "text_rendered": a.text_rendered,
                      "cited": cited, "follow_ups": follow_ups, "lesson": None, "refusal": None, "clarify": None,
                      "warnings": a.warnings})
        record: dict[str, Any] = {"question": message, "calls": a.calls, "views": views,
                                  "answer": TOKEN.sub("[number]", text), "agent": True,
                                  "shown": [numbers[i] for i in cited if i in numbers]}
        if views:
            record["explain"] = _main_number(numbers, cited)
        else:   # an answer in words: the planner's history skips it, "explain it simpler" stays in words
            record.update({"words": True, "talk": {"kind": "agent", "tips_given": 0, "practices_given": 0,
                                                   "tip": None}})
        self.store.add_turn(conv, record)
        return True

    # ---- talk mode (#873) ------------------------------------------------------------------------------------------

    def _talk_stands_down(self, message: str, lang: str, a: _Answer) -> str | None:
        """Why a talk question takes the normal path instead, or None: a guard flag, health, a rules refusal or
        designed template answer ("what should I do about bitcoin?" keeps the rules' decline; hard declines always
        win), then a product, a brand or another topic in the question. A borrowing or affordability question that
        no hard decline took stays in talk mode, on the template only (talk_mode.template_only)."""
        folded = guard.fold(message)
        if a.flags:
            return "guard"
        if re.search(RULE_HEALTH, folded) or talk_checks._GENERAL_HEALTH.search(message):
            return "health"
        plan = self.fallback.plan(PlanInput(question=message, language=lang, as_of=self.as_of.isoformat(),
                                            tools=self.registry.schemas(), guard_flags=a.flags, round=1))
        if any(c.name == "decline" for c in plan.calls):
            return "decline"
        if getattr(plan, "template_answer", False) or getattr(plan, "offer_contact", False):
            return "template"
        if talk_mode.template_only(message):
            return None
        if talk_mode.TOPIC_STANDS_DOWN.search(folded) or talk_checks._GENERAL_OTHERS.search(message):
            return "topic"
        if any(rx.search(message) for rx in (talk_checks._GENERAL_PRODUCT, talk_checks._GENERAL_PRODUCT_CLASS,
                                             talk_checks._GENERAL_BRAND)):
            return "product"
        return None

    def _talk_levers(self, ctx: ToolContext) -> list[dict[str, Any]]:
        """The savings plan's and the small purchases' model views for a tips question in a conversation that has
        computed no lever yet, run without a card and with their own registry, so none of their numbers can be cited
        (none was shown). [] when a tool is not registered or fails."""
        views: list[dict[str, Any]] = []
        for name in ("get_savings_plan", "get_small_purchases"):
            spec = self.registry.tools.get(name)
            if spec is None:
                continue
            try:
                _, args = self.registry.parse(name, {})
                if TOOL_CACHE.enabled:
                    TOOL_CACHE.ensure_labels_key(ctx, self.data.connection)
                with self.data.connection() as conn:
                    own = dataclasses.replace(ctx, conn=conn, numbers=NumberRegistry())
                    views.append(TOOL_CACHE.run(spec.name, spec.args_model, spec.fn, own, args).model_view)
            except Exception as exc:  # noqa: BLE001 - the talk answer stands without the lever
                log.warning("talk-mode lever %s not read (%s)", name, type(exc).__name__)
        return views

    def _answer_talk(self, ctx: ToolContext, req: AskRequest, message: str, lang: str, emit: Emit, a: _Answer) -> bool:
        """Talk mode (#873, the answer_in_words route): 2 to 4 plain sentences from the composer that reason about the
        previous answer, citing at most one number already shown in this conversation; no card, one next-step chip.
        False (the normal path answers) unless talk_mode names the message, or it is an open follow-up after a talk
        answer (after any data answer on the voice channel), and no guard, refusal rule or product question stands it
        down. On a failed check, after one retry, the template reasons without a number."""
        conv = a.conversation
        turns = conv.turns if conv is not None else []
        voice = getattr(req, "channel", "text") == "voice"
        last_talk = next((t["talk"] for t in reversed(turns) if t.get("talk")), None)
        prev_talk = bool(turns) and bool(turns[-1].get("talk"))
        data_turn = _last_data_turn(turns)
        kind = talk_mode.trigger(message)
        if kind is None and talk_mode.explain_beside(message) and (data_turn or prev_talk):
            kind = "explain"
        if kind is None and (prev_talk or (voice and data_turn)) and talk_mode.follow_up(message):
            kind = "follow_up"
        if kind is None and prev_talk and talk_mode.why_follow_up(message):
            kind = "why"   # "why should I save money?" after a talk answer: reasons, not numbers (#889)
        if kind is None and prev_talk and talk_mode.asks_why_tips(message):
            kind = "why"   # "miksi se auttaa?" after a talk answer (#919)
        if kind is None and turns and _words_answer(turns[-1]) and explain_number.asks_simpler(message):
            kind = "understand"   # "Selitä yksinkertaisemmin" after an answer in words: that answer, simpler (test 11)
        if kind is None:
            return False
        why_not = self._talk_stands_down(message, lang, a)
        if why_not is not None:
            a.planner_turns.append({"round": 1, "source": "rules", "talk": f"stood down: {why_not}"})
            return False
        views_all = [v for t in turns for v in (t.get("views") or []) if isinstance(v, dict)]
        tools = [c.get("name") for c in (data_turn.get("calls") or []) if isinstance(c, dict)]
        # the numbers already shown in this conversation, latest last, re-registered for this answer
        shown: dict[str, Number] = {}
        for number in [n for t in turns for n in (t.get("shown") or [])][-8:]:
            registered = ctx.numbers.register(number)
            shown[registered.id] = registered
        numbers = ctx.numbers.all()
        given = (last_talk or {}).get("tips_given", 0)
        ranking = talk_mode.rank_tips(views_all, lang)
        tips_kind = kind in ("tips", "no_numbers")
        # "why?" right after a tips answer explains those tips (#919): the tips that answer gave, with their sources
        gave_before = (turns[-1]["talk"].get("gave") or {}) if prev_talk else {}
        explain = bool(talk_mode.tip_keys(gave_before)) and talk_mode.asks_why_tips(message)
        more = (prev_talk and talk_mode.wants_more_tips(message) and (tips_kind or kind == "follow_up")
                and not explain)
        if (tips_kind or more) and not any(v.get("tool") == "get_savings_plan" for v in views_all):
            # the plan's levers always enter the ranking (fetched again for "any more tips?": the same order)
            ranking = talk_mode.rank_tips(views_all + self._talk_levers(ctx), lang)
        tip, exhausted = None, False
        if tips_kind or more:
            index = given if more else 0
            tip = ranking[index] if index < len(ranking) else None
            exhausted = tip is None and index > 0
            given = index + 1 if tip is not None else given
        # a first tips answer, or "anything else?", carries the next two general practices beside the lever (#889);
        # "any more tips?" stays one lever per turn, and once no further lever passes the bar it gives the next two
        # practices not given yet in this conversation (#907)
        used = (last_talk or {}).get("practices_given", 0)
        extra = (talk_mode.practices(used, lang)
                 if (tips_kind and not more) or (more and (kind == "follow_up" or tip is None)) else [])
        first_practice = used
        used += len(extra)
        # no lever and no practice left: a warm closing, never "no further tips" (#907)
        closing = (tips_kind or more) and tip is None and not extra
        previous_tip = (last_talk or {}).get("tip") if (tip is None and prev_talk) else None
        prev = turns[-1] if turns else None
        prev_main = getattr((prev or {}).get("explain"), "evidence_ref", None) or next(
            (getattr(n, "evidence_ref", None) for n in ((prev or {}).get("shown") or [])), None)
        # official sources for the reasoning (#884): only when the model may write the talk text
        # on "why?" after tips, the sources that tips answer named (kept on its turn), never a new search (#919)
        fragments = ([] if talk_mode.template_only(message) or talk_mode.model_switched_off()
                     else [finlit_kb.Fragment(**r) for r in (prev or {}).get("finlit") or [] if isinstance(r, dict)]
                     if explain
                     else self._talk_fragments(ctx, message, prev, lang))
        # the closing is the template's unless finlit fragments give the composer something to write from (#907)
        designed_closing = closing and not fragments
        talk = {"kind": kind, "channel": "voice" if voice else "text",
                "previous_question": prev["question"] if prev else None,
                "previous_answer": prev["answer"] if prev else None,
                "previous_tools": tools,
                "shown_numbers": [model_number(n) for n in shown.values()],
                "tip": {"rank": ranking.index(tip) + 1, "lever": talk_mode.lower(tip["label"])} if tip else None,
                "previous_tip": previous_tip,
                "tips_ranked": [{"rank": i + 1, "lever": talk_mode.lower(t["label"])} for i, t in enumerate(ranking)],
                "practices": extra,
                # True only with nothing else to give (#907): with practices or fragments there are more tips
                "no_more_tips": exhausted and not extra and not fragments,
                # only on "why?" after tips (#919), so every other talk request stays the same
                **({"explain_tips": talk_mode.tips_to_explain(gave_before, lang)} if explain else {})}
        credited = finlit_kb.named(fragments)
        compose_in = ComposeInput(question=message, language=lang, as_of=self.as_of.isoformat(),
                                  data=[{"tool": "answer_in_words", "talk": talk}], errors=[],
                                  previous_turn={"question": prev["question"], "answer": prev["answer"]} if prev else None,
                                  sources=[f.data(include_text=f in credited) for f in fragments] or None)
        unavailable = self._model_unavailable(req) or self._role_unavailable("compose")
        # Renat's decision for #889: borrowing and affordability always get the template, whatever the switch; the
        # switch file (talk_mode.MODEL_OFF_SWITCH, read per answer) turns the model's talk text off
        forced = talk_mode.template_only(message)
        switched_off = talk_mode.model_switched_off()
        allowed = Allowed(dates=frozenset(), periods=frozenset())
        draft = None
        errors: list[str] = []
        self._start_compose_answer(compose_in)   # no planner ran in this answer: start its deadline (#884)
        if unavailable is None and not forced and not switched_off and not designed_closing:
            for _ in range(2):   # the call and one retry with the reasons
                t = self.clock()
                try:
                    result = self.model.compose(ComposeInput(**{**compose_in.__dict__, "validation_errors": errors}))
                except Exception as exc:  # noqa: BLE001
                    errors = [f"the model call failed ({type(exc).__name__})"]
                    a.composer_attempts.append({"raw": None, "validation": errors, "latency_ms": self._ms(t)})
                    continue
                draft, errors = validate(result.text, language=lang, numbers=numbers, allowed=allowed)
                if draft is not None and not errors:
                    errors = talk_mode.draft_problems(draft.text, numbers, set(shown), lang)
                if draft is not None and not errors and explain:   # it names the tips it explains (#919)
                    errors = talk_mode.explain_problems(draft.text, gave_before, lang)
                if draft is not None and not errors and prev is not None:
                    # the repetition guard (#889): never the previous answer again, nor its main figure
                    again = set(TOKEN.findall(draft.text)) & {i for i, n in numbers.items() if n.evidence_ref
                                                             and n.evidence_ref == prev_main}
                    if again or talk_mode.repeats(draft.text, prev.get("answer")):
                        errors = (["this repeats the previous answer: explain why each of those tips helps, in new "
                                   "words, and do not repeat its main number"] if explain else
                                  ["this repeats the previous answer: say something new (another reason or the next "
                                   "lever), and do not repeat its main number"])
                a.composer_attempts.append({"raw": result.text, "validation": "ok" if not errors else errors,
                                            "latency_ms": self._ms(t), "tokens": a.add_usage(result.usage)})
                if not errors:
                    break
                draft = None
        from_model = draft is not None
        if draft is None:   # the template in the model's place reasons without a number
            if (not forced and not explain and tip is None and not exhausted and errors
                    and errors[0].startswith("this repeats")):
                # the model repeated itself twice: the next lever of the ranking, in the template (#889)
                index = given if given < len(ranking) else None
                tip = ranking[index] if index is not None else None
                given = index + 1 if tip is not None else given
            text = (template.pick(talk_mode.BORROWING, lang) if forced
                    else talk_mode.explain_tips(gave_before, lang) if explain
                    else talk_mode.closing(lang, previous=(prev or {}).get("answer")) if closing and tip is None
                    else talk_mode.three_tips(tip, extra, lang, more=bool(more)) if extra
                    else talk_mode.template_text(kind, tip, exhausted, tools, lang, previous_tip=previous_tip,
                                                 previous=(prev or {}).get("answer")))
            draft, errors = validate({"language": lang, "text": text, "cited": [], "lesson_key": None},
                                     language=lang, numbers=numbers, allowed=allowed)
            a.composer_attempts.append({"raw": "template", "validation": "ok" if not errors else errors})
            if draft is None:
                draft = AnswerDraft(language=lang, text=text, cited=[], lesson_key=None)
            if forced:
                a.offer_contact = True   # a designed template: the way to the bank, and no llm_unavailable warning
            elif designed_closing:
                pass   # the designed closing (#907): no model was asked for it, so no llm_unavailable warning
            else:
                a.model_unavailable = a.model_unavailable or unavailable or ("talk_model_off" if switched_off else "error")
                self._warn_llm_unavailable(a)
        talk_template = ("borrowing_or_afford" if forced else "switch" if switched_off
                         else "closing" if designed_closing else None)
        a.planner_turns.append({"round": 1, "source": "rules", "talk": kind, **({"tip": tip["key"]} if tip else {}),
                                **({"explain_tips": talk_mode.tip_keys(gave_before)} if explain else {}),
                                **({"talk_template": talk_template} if talk_template else {}),
                                **({"finlit": [f.source_id for f in fragments]} if credited and from_model else {})})
        if credited and from_model:   # the Sources row under the answer; the text carries no link (#884)
            a.sources = finlit_kb.sources_field(fragments, lang) or None
        text = self._deliver(draft.text, numbers, emit)
        cited = list(dict.fromkeys(TOKEN.findall(text)))
        a.outcome, a.text, a.text_rendered = "answered", text, render(text, numbers)
        a.numbers = {i: {"value": numbers[i].value, "unit": numbers[i].unit.value, "method": numbers[i].method,
                         "evidence_ref": numbers[i].evidence_ref} for i in cited}
        # "Any more tips?" while a lever, or after a tips answer a practice, is left; else the saving question (#907)
        more_left = given < len(ranking) or ((tips_kind or more) and used < len(talk_mode.PRACTICES))
        chip = template.pick(talk_mode.CHIP_MORE if more_left else talk_mode.CHIP_SAVE, lang)
        emit("done", {"answer_id": a.answer_id, "outcome": "answered", "text": text, "text_rendered": a.text_rendered,
                      "cited": cited, "follow_ups": [chip], "lesson": None, "refusal": None, "clarify": None,
                      "warnings": a.warnings})
        # what this answer gave, for "why?" next (#919): the lever and the practices, unless a designed text answered
        gave = ({} if forced or explain else
                {"levers": [{"key": tip["key"], "label": talk_mode.lower(tip["label"]), "rank": ranking.index(tip) + 1}]
                 if tip else [], "practices": list(range(first_practice, first_practice + len(extra)))})
        # no calls and no views: "what does this number mean?" and the planner's history still read the last data
        # turn; the talk record keeps the ranking's place for "any more tips?"
        self.store.add_turn(conv, {"question": message, "calls": [], "views": [],
                                   "answer": TOKEN.sub("[number]", text),
                                   "talk": {"kind": kind, "tips_given": given, "practices_given": used,
                                            "tip": ({"lever": talk_mode.lower(tip["label"])} if tip else previous_tip),
                                            "gave": gave},
                                   "shown": [numbers[i] for i in cited if i in numbers],
                                   # the sources this answer named, for "why?" next (#919)
                                   **({"finlit": [f.record() for f in fragments]} if credited and from_model else {})})
        return True

    def _explain_count(self, ctx: ToolContext, number: Number, lang: str) -> Number | None:
        """The transactions a number rests on, as its evidence sheet counts them (core/app/api/evidence.py): the
        row count of its selection, a Number with its own evidence ref. None for a number that is not a sum over
        transactions (a composite such as safe to spend) or when the data cannot be read: the sentence is left out."""
        try:
            with self.data.connection() as conn:
                res = tool_evidence.resolve(conn, number.evidence_ref, ctx.customer_id, limit=1, language=lang)
                if res.kind != "transactions" or res.row_count is None:
                    return None
                spec = res.spec if res.spec is not None else tool_evidence.load(conn, res.ref)[1]
                sel = spec["selection"]
                value = Decimal(res.row_count)
                rc_spec = tool_evidence.transactions_spec(ctx.customer_id, date.fromisoformat(spec["as_of"]),
                                                          tool_config.METHODS["row_count"], Selection.from_spec(sel),
                                                          value, label_set=spec.get("labels"))
                rc_ref = tool_evidence.make_ref(rc_spec)
                tool_evidence.write(conn, {rc_ref: rc_spec})
            start, end = date.fromisoformat(sel["period"]["start"]), date.fromisoformat(sel["period"]["end"])
        except Exception as exc:   # the explanation stands without the count
            log.warning("explain-number count not read (%s)", type(exc).__name__)
            return None
        period = Period(start=start, end=end, label=tool_periods.period_label(start, end, lang))
        return ctx.numbers.register(Number(value=int(value), unit=Unit.COUNT, period=period,
                                           method=tool_config.METHODS["row_count"], evidence_ref=rc_ref,
                                           label=api_texts.pick(api_texts.ROW_COUNT_LABEL, lang),
                                           display=format_display(value, Unit.COUNT, lang)))

    def _answer_sbank_kb(self, ctx: ToolContext, review: Any, message: str, lang: str, emit: Emit, a: _Answer) -> bool:
        """Answer a question about S-Bank or S-mobiili from the knowledge base (#791): the entry's fixed text
        (ours, from S-Bank's public help pages), its source line and the way to the bank (`contact_bank`); a
        message clearly about S-Bank that matches no entry gets "I don't know that one; the bank can tell you."
        No plan, no tool, no number, no model request. False (the normal path answers) when sbank_kb leaves the
        message (the customer's own figures, a recommendation), a guard flag is set, or the rule model declines
        it or claims it for one of its own answers (a data rule, a decline, "I can't answer that one yet").
        Exception (#808): an e-invoice how-to entry answers before the bills rule alone or the rules' "I can't
        answer that one yet" ("Miten tilaan e-laskun?").
        The answer is in the question's language (sbank_kb.answer_language), also when the app asked in the other."""
        if a.flags:
            return False
        kb = sbank_kb.answer_for(message, lang)
        if kb is None:
            return False
        history = [{"question": t["question"], "calls": t["calls"], "results": t["views"]} for t in a.conversation.turns]
        rules = self.fallback.plan(PlanInput(question=message, language=lang, as_of=self.as_of.isoformat(),
                                             tools=self.registry.schemas(), history=history, guard_flags=a.flags))
        if any(c.name == "decline" for c in rules.calls):
            return False
        data = {c.name for c in rules.calls if c.name not in ("finish", "ask_clarifying_question")}
        if rules.recognised and not (kb.entry_id in sbank_kb.OVER_BILLS_RULE and data <= {"get_recurring_bills"}):
            return False
        lang = kb.lang
        numbers = ctx.numbers.all()
        # The validator checks the entry's text. The source line after it is fixed here from the file's
        # source_url (an s-pankki.fi help page, held by the tests); the no-URL rule is for model drafts. An
        # entry marked `digits` (the published contact numbers and hours, step numbers) is checked without
        # its digits, which the tests pin to that entry's published ones.
        body = re.sub(r"\d", "", kb.body) if kb.digits else kb.body
        draft, errors = validate({"language": lang, "text": body, "cited": [], "lesson_key": None},
                                 language=lang, numbers=numbers, allowed=allowed_from(numbers.values(), [], self.as_of))
        if errors or draft is None:
            log.warning("knowledge-base answer %s failed the validator (%d problems)", kb.entry_id, len(errors))
            return False
        if lang != a.language.get("resolved"):   # the contact button's label follows the answer's language
            a.language = {**a.language, "resolved": lang}
        a.offer_contact = True   # the way to the bank: open_host_screen contact_bank (#420)
        a.planner_turns.append({"round": 1, "source": "rules", "sbank_kb": kb.entry_id or "unknown", "calls": []})
        if review is not None:  # the pending review's card, as on the normal path
            self._attach_review(ctx, review, emit, a)
        text = self._deliver(kb.text if kb.digits else f"{draft.text} {kb.source}".strip(), numbers, emit)
        a.outcome, a.text, a.text_rendered = "answered", text, render(text, numbers)
        emit("done", {"answer_id": a.answer_id, "outcome": "answered", "text": text, "text_rendered": a.text_rendered,
                      "cited": [], "follow_ups": template.follow_ups(message, lang), "lesson": None,
                      "refusal": None, "clarify": None, "warnings": a.warnings})
        self.store.add_turn(a.conversation, {"question": message, "calls": [], "views": [], "answer": text,
                                             "words": True, "kb": kb.entry_id})
        return True

    def finlit_fragments(self, customer_id: str, message: str, lang: str) -> list[Any]:
        """Up to three finlit fragments for a message (#884), in its language and the customer's age band; [] when
        the route is off or anything fails. The talk mode (#873) puts them in its compose request too."""
        if self.finlit is None:
            return []
        band = None
        try:
            with self.data.connection() as conn:
                row = conn.execute("SELECT age FROM customers WHERE customer_id = %s", (customer_id,)).fetchone()
            band = finlit_kb.age_band(row[0]) if row else None
        except Exception as exc:  # noqa: BLE001 - without the band, texts for every age; facts are not used
            log.warning("finlit: age not read (%s)", type(exc).__name__)
        return self.finlit.fragments(message, lang, band)

    def _start_compose_answer(self, key: Any) -> None:
        """Start the model client's per-answer request count and deadline for an answer that calls only the composer
        (the literacy route, the talk mode). Only the planner's first call starts it otherwise, so the worker thread
        would carry the previous answer's expired deadline and the composer call would fail with "deadline" before
        sending any request (seen on the stand, #884)."""
        start = getattr(getattr(self.model, "client", None), "start_answer", None)
        if callable(start):
            try:
                start(key)
            except Exception as exc:  # noqa: BLE001 - the answer goes on; the client keeps its own limits
                log.warning("model answer state not started (%s)", type(exc).__name__)

    def _talk_fragments(self, ctx: ToolContext, message: str, prev: dict[str, Any] | None, lang: str) -> list[Any]:
        """Finlit fragments for a talk answer (#884): searched with the message when it names a money topic, else with
        the previous question and the message ("Where did my money go? why does it matter?"); none when neither names
        one (a bare "why?" would only retrieve noise and cost an embedding request)."""
        if self.finlit is None:
            return []
        if finlit_kb.has_money_topic(message):
            query = message
        elif prev and finlit_kb.has_money_topic(prev.get("question") or ""):
            query = f"{prev['question']} {message}"
        else:
            return []
        return self.finlit_fragments(ctx.customer_id, query, lang)

    def _answer_finlit(self, req: AskRequest, ctx: ToolContext, review: Any, message: str, lang: str, emit: Emit,
                       a: _Answer) -> bool:
        """A general financial-literacy question in plain words, grounded in official sources (#884): the composer
        writes two to four sentences with the retrieved fragments in its request, the code adds the source line.
        No tool, no number, no card. False (the usual path answers) when the route is off, the message is not a
        literacy question (finlit_kb.question_kind), a guard flag is set, S-Bank's knowledge base or a glossary term
        other than budget and interest owns it, the rules claim it, the model may not write, nothing is retrieved, or
        no draft passes the checks. Tips asked in a running conversation are the talk mode's (#873)."""
        investing = finlit_kb.invest_general(message)   # R7 narrowed: the general order, never a pick (#884)
        if self.finlit is None or (not investing and finlit_kb.question_kind(message) != "literacy"):
            return False
        if re.search(RULE_HEALTH, guard.fold(message)):
            return False   # a health topic gets no tip and no comment (R9)
        if not finlit_kb.flags_allow(message, req.message, investing=investing):
            return False
        conv = a.conversation
        if not investing and (talk_mode.trigger(message) is not None or (conv is not None and conv.turns
                                                                         and finlit_kb.TIPS.search(guard.fold(message)))):
            return False   # tips / explain / no numbers: the talk mode's, with the customer's levers and fragments (#873)
        term = glossary.match(message)
        if term is not None and term.key not in finlit_kb.GLOSSARY_TERMS:
            return False
        if sbank_kb.answer_for(message, lang) is not None:
            return False
        if term is None:
            history = [{"question": t["question"], "calls": t["calls"], "results": t["views"]}
                       for t in (conv.turns if conv is not None else [])]
            rules = self.fallback.plan(PlanInput(question=message, language=lang, as_of=self.as_of.isoformat(),
                                                 tools=self.registry.schemas(), history=history, guard_flags=a.flags))
            why = investing or finlit_kb.overrides_rules(message)   # words, never a plan's figures
            # borrowing never reaches here (finlit_kb's gate), so the rules' "I can't answer that one yet" with the
            # contact offer does not stop a why question. A general investing question passes the rules' investment
            # decline only (R7 narrowed); every other decline (credit, health, another person) still wins
            declined = [c for c in rules.calls if c.name == "decline"
                        and not (investing and (c.args or {}).get("kind") == "investment_advice")]
            if declined or getattr(rules, "template_answer", False) or (rules.recognised and not why):
                return False
        if self._model_unavailable(req) is not None or self._role_unavailable("compose") is not None:
            return False
        fragments = self.finlit_fragments(ctx.customer_id, message, lang)
        if not fragments and term is not None:
            return False   # no source close enough: the glossary's own definition answers
        # with no source close enough (the relevance floor), the answer is plain words with no source line
        credited = finlit_kb.named(fragments)
        sources = [f.data(include_text=f in credited) for f in fragments]
        if term is not None:   # the glossary's definition keeps the grounded answer consistent with Sentti's words
            sources.insert(0, {"source": "Sentti", "title": "definition", "text": template.pick(term.text, lang)})
        prev = conv.turns[-1] if conv is not None and conv.turns else None
        request = ComposeInput(question=message, language=lang, as_of=self.as_of.isoformat(), data=[], errors=[],
                               previous_turn={"question": prev["question"], "answer": prev["answer"]} if prev else None,
                               sources=sources or None, literacy=True, investing=investing)
        self._start_compose_answer(request)
        body: str | None = None
        errors: list[str] = []
        for _ in range(2):  # the call and one retry with the reasons
            t = self.clock()
            try:
                result = self.model.compose(ComposeInput(**{**request.__dict__, "validation_errors": errors}))
            except Exception as exc:  # noqa: BLE001
                errors = [f"the model call failed ({type(exc).__name__})"]
                a.composer_attempts.append({"raw": None, "validation": errors, "latency_ms": self._ms(t)})
                continue
            draft, errors = finlit_kb.draft_problems(result.text, lang, investing=investing)
            a.composer_attempts.append({"raw": result.text, "validation": "ok" if not errors else errors,
                                        "latency_ms": self._ms(t), "tokens": a.add_usage(result.usage)})
            if not errors and draft is not None:
                body = draft.text
                break
        fixed = False
        if body is None:
            # the attempts stay in the audit record (their tokens were spent). "Why should I save?" gets the fixed
            # reasons of ours (no source named, no card); any other question goes the usual path
            body = (template.pick(finlit_kb.INVEST_TEXT, lang) if investing
                    else finlit_kb.why_fallback(message, lang))
            log.warning("finlit answer failed the checks (%d problems); %s", len(errors),
                        "the fixed reasons answer" if body else "the usual path answers")
            if body is None:
                return False
            fixed, credited = True, []
        a.kind = "general"
        a.planner_turns.append({"round": 1, "source": "rules",
                                "finlit": "fixed_reasons" if fixed else ([f.source_id for f in fragments] or "no_source"),
                                "calls": []})
        if review is not None:  # the pending review's card, as on the normal path
            self._attach_review(ctx, review, emit, a)
        if credited:   # the Sources row under the answer; the text carries no link (#884)
            a.sources = finlit_kb.sources_field(fragments, lang) or None
        if investing:   # never a product: the fixed line and the way to the bank's adviser (R7 narrowed)
            body = f"{body} {template.pick(finlit_kb.INVEST_LINE, lang)}"
            a.offer_contact = True
            a.planner_turns.append({"round": 1, "source": "rules", "invest_general": True})
        text = self._deliver(body, {}, emit)
        a.outcome, a.text, a.text_rendered = "answered", text, text
        emit("done", {"answer_id": a.answer_id, "outcome": "answered", "text": text, "text_rendered": text,
                      "cited": [], "follow_ups": template.follow_ups(message, lang), "lesson": None,
                      "refusal": None, "clarify": None, "warnings": a.warnings})
        self.store.add_turn(a.conversation, {"question": message, "calls": [], "views": [], "answer": text,
                                             "words": True,
                                             "finlit": [f.record() for f in fragments]})   # for a follow-up's reuse
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
