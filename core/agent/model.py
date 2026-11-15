"""The AI model behind two calls (agent-core.md sections 7.1 and 7.2). FROZEN INTERFACE: a Gemini
adapter (issue #66) implements `Model`; change these shapes only together with it.

- plan(PlanInput) -> PlanResult: the planner. It sees the question as data, the history (the earlier
  questions, its earlier function calls and their model views, numbers not masked), the tool
  declarations (Registry.schemas()) and, from round 2 on, the function responses of this answer.
  Mode ANY: it must return at least one FunctionCall (data tool or control function).
- compose(ComposeInput) -> ComposeResult: the composer, a fresh tool-free call that returns the JSON
  text of an AnswerDraft (validator.py) and cites numbers only as {{nK}} tokens. Of the history it
  sees only the previous question and the previous answer with its numbers masked as [number].

Both inputs hold model views only, never tool data, cards, evidence refs or the customer id (R3, R4).
A call that fails raises ModelError (or any exception): the pipeline retries once, then falls back.
Each result reports its token usage, which goes into the audit record per model call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol


class ModelError(RuntimeError):
    """The model call failed (network, quota, timeout, safety block or an unusable response)."""


@dataclass(frozen=True)
class Usage:
    """Tokens and cost of one model call. The scripted and rule models report zeros."""

    prompt_tokens: int = 0
    thought_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class FunctionCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    id: str | None = None             # the provider's call id, if it has one


@dataclass(frozen=True)
class FunctionResponse:
    """What the planner gets back for one call: the tool's model view, or {"error": code}."""

    name: str
    response: dict[str, Any]
    id: str | None = None             # the id of the FunctionCall it answers


@dataclass(frozen=True)
class PlanInput:
    question: str
    language: str                      # "en" | "fi"
    as_of: str                         # ISO date, DEMO_TODAY
    tools: list[dict[str, Any]]        # function declarations: {name, description, parameters_json_schema}
    history: list[dict[str, Any]] = field(default_factory=list)      # earlier turns: question, calls, results
    responses: list[FunctionResponse] = field(default_factory=list)  # this answer's calls so far, in order
    model_turns: list[Any] = field(default_factory=list)  # PlanResult.raw of earlier rounds, to replay verbatim
    guard_flags: list[str] = field(default_factory=list)
    round: int = 1


@dataclass(frozen=True)
class PlanResult:
    calls: list[FunctionCall]
    usage: Usage = Usage()
    raw: Any = None                    # the provider's model turn (e.g. with thought signatures), opaque
    # False when a rule planner did not recognise the question: its calls are then only a default
    # (a clarifying question), and a rules-first wrapper should ask the model's planner instead.
    recognised: bool = True
    # True only when the rule planner chose its "I can't answer that one yet" answer: the answer then
    # offers the way to a human at the bank (#420). No model adapter sets it.
    offer_contact: bool = False
    # True only when the rule planner's answer is the template's own words, never the composer model's: "why is
    # my safe to spend lower?" names the limit that binds from the data (#552). No model adapter sets it.
    template_answer: bool = False
    # True only when the rule planner answers a question about the S-Bonus RECEIVED with the estimate: the template
    # then says first that the Bonus received is not in this account's data (#639). No model adapter sets it.
    bonus_received: bool = False


@dataclass(frozen=True)
class ComposeInput:
    question: str
    language: str
    as_of: str
    data: list[dict[str, Any]]                        # model views of the successful tools
    errors: list[dict[str, Any]] = field(default_factory=list)  # {"tool": name, "error": code}
    previous_turn: dict[str, Any] | None = None       # question and answer, numbers masked as [number]
    validation_errors: list[str] = field(default_factory=list)  # set on the retry
    # #884: fragments from official sources (finlit_kb.Fragment.data: source, title, open text with digits masked),
    # and whether the answer is a literacy answer in plain words with no data. Only a request that carries them gets
    # their blocks, so every other composer request keeps its cache key.
    sources: list[dict[str, Any]] | None = None
    literacy: bool = False


@dataclass(frozen=True)
class ComposeResult:
    text: str                          # the JSON text of an AnswerDraft
    usage: Usage = Usage()


class Model(Protocol):
    model_id: str

    def plan(self, request: PlanInput) -> PlanResult: ...

    def compose(self, request: ComposeInput) -> ComposeResult: ...


class ScriptedModel:
    """A fake model that replays a script. For tests.

    `plans` is a list of planner turns; each is a list of FunctionCall, or an Exception to raise.
    `drafts` is a list of composer outputs; each is a dict (sent as JSON), a raw string, a callable
    taking the ComposeInput, or an Exception to raise. The inputs it received are kept for assertions.
    """

    model_id = "scripted"

    def __init__(self, plans: list[Any] | None = None, drafts: list[Any] | None = None) -> None:
        self.plans = list(plans or [])
        self.drafts = list(drafts or [])
        self.plan_inputs: list[PlanInput] = []
        self.compose_inputs: list[ComposeInput] = []

    def plan(self, request: PlanInput) -> PlanResult:
        self.plan_inputs.append(request)
        if not self.plans:
            raise ModelError("script exhausted")
        step = self.plans.pop(0)
        if isinstance(step, Exception):
            raise step
        return PlanResult(calls=list(step))

    def compose(self, request: ComposeInput) -> ComposeResult:
        self.compose_inputs.append(request)
        if not self.drafts:
            raise ModelError("script exhausted")
        step = self.drafts.pop(0)
        if isinstance(step, Exception):
            raise step
        if callable(step):
            step = step(request)
        return ComposeResult(text=step if isinstance(step, str) else json.dumps(step, ensure_ascii=False))
