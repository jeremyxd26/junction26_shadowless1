"""The tool registry: data tools and control functions the planner may call.

A data tool is registered with its name, argument model, function and card builder. The registry
exposes JSON Schemas for the planner (agent-core.md section 6.1) and enforces, for every tool that
any worker registers, the rules the pipeline relies on:
- R4: an argument model may not have a customer field and must reject unknown fields, and every
  call is checked for a customer key at any depth before it is validated;
- R6: only read and simulate functions are registered (a tool declares `read_only=True`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.tools.context import ToolContext
from core.tools.models import Card, ToolResult

CUSTOMER_KEY_HINTS = ("customer", "cust_id", "user_id", "account")


class RegistryError(ValueError):
    """A tool cannot be registered because it breaks a pipeline rule."""


class CallRejected(ValueError):
    """A planner call cannot run. `code` goes back to the model; the message never contains data."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def _default_card(result: ToolResult) -> Card | None:
    return result.card


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[[ToolContext, BaseModel], ToolResult]
    status_label: tuple[str, str]  # (en, fi) progress text for the `status` event
    card_builder: Callable[[ToolResult], Card | None] = _default_card
    read_only: bool = True


# ---- control functions (agent-core.md section 6.3) ------------------------------------------------

class DeclineKind(str, Enum):
    INVESTMENT_ADVICE = "investment_advice"
    CREDIT_DECISION = "credit_decision"
    OUT_OF_SCOPE = "out_of_scope"
    OTHER_PERSON_DATA = "other_person_data"
    UNSAFE = "unsafe"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeclineArgs(_Strict):
    kind: DeclineKind


class ClarifyArgs(_Strict):
    question: str = Field(min_length=1, max_length=140)
    options: list[str] = Field(default_factory=list, max_length=3)


class FinishArgs(_Strict):
    pass


class AnswerInWordsArgs(_Strict):
    pass


CONTROL = {
    "decline": (DeclineArgs, "End the turn with the fixed refusal template of this kind. Reads no data."),
    "ask_clarifying_question": (ClarifyArgs, "Ask the user one short question back, with up to 3 short options."),
    "finish": (FinishArgs, "Data collection is complete; go on to write the answer."),
}
# #572: a general money question (budgeting, a buffer, saving habits, how a bill, an e-invoice, a due date or a
# reference number works) is answered in plain words, with no tool data and no number. Declared to the planner only
# while the general route is switched on (orchestrator.GENERAL_ON, read once per answer); switched off, the planner's
# declarations are exactly dev's CONTROL, so its model cache and routes stay as they were (review of #618, pass 3).
GENERAL_CONTROL = {
    "answer_in_words": (AnswerInWordsArgs, "Answer a general money question in plain words, with no data and no "
                                           "number: budgeting, a buffer, saving habits, how a bill, an e-invoice, a "
                                           "due date or a reference number works. Never for the user's own figures. "
                                           "Call it alone. Reads no data."),
}


def property_names(schema: Any) -> set[str]:
    """Every property name of a JSON Schema at any depth (the keys of each "properties" object).
    Descriptions and titles are text, not fields, so they are not looked at."""
    names: set[str] = set()
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                names.update(value)
            names |= property_names(value)
    elif isinstance(schema, list):
        for value in schema:
            names |= property_names(value)
    return names


def _schema_mentions_customer(schema: Any) -> bool:
    return any(h in name.lower() for name in property_names(schema) for h in CUSTOMER_KEY_HINTS)


def find_customer_key(args: Any, path: str = "") -> str | None:
    """The path of the first key that looks like a customer selector, at any depth (R4)."""
    if isinstance(args, dict):
        for key, value in args.items():
            here = f"{path}.{key}" if path else str(key)
            if any(h in str(key).lower() for h in CUSTOMER_KEY_HINTS):
                return here
            found = find_customer_key(value, here)
            if found:
                return found
    elif isinstance(args, list):
        for i, value in enumerate(args):
            found = find_customer_key(value, f"{path}[{i}]")
            if found:
                return found
    return None


@dataclass
class Registry:
    tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self.tools or spec.name in CONTROL or spec.name in GENERAL_CONTROL:
            raise RegistryError(f"{spec.name}: already registered")
        if not spec.read_only:
            raise RegistryError(f"{spec.name}: only read and simulate tools may be registered (R6)")
        if spec.args_model.model_config.get("extra") != "forbid":
            raise RegistryError(f"{spec.name}: the argument model must forbid unknown fields (R4)")
        if _schema_mentions_customer(spec.args_model.model_json_schema()):
            raise RegistryError(f"{spec.name}: the argument model must not have a customer field (R4)")
        self.tools[spec.name] = spec

    def names(self) -> list[str]:
        return list(self.tools)

    def is_data_tool(self, name: str) -> bool:
        return name in self.tools

    def schemas(self, general: bool = False) -> list[dict[str, Any]]:
        """Function declarations for the planner: data tools, then the control functions; `general` (the general
        route switched on, #572) adds answer_in_words at the end, and only then."""
        out = [{"name": s.name, "description": s.description,
                "parameters_json_schema": s.args_model.model_json_schema()} for s in self.tools.values()]
        out += [{"name": name, "description": desc, "parameters_json_schema": model.model_json_schema()}
                for name, (model, desc) in CONTROL.items()]
        if general:
            out += [{"name": name, "description": desc, "parameters_json_schema": model.model_json_schema()}
                    for name, (model, desc) in GENERAL_CONTROL.items()]
        return out

    def parse(self, name: str, args: Any) -> tuple[str, BaseModel]:
        """Validate one planner call. Returns ("data" | "control", parsed args) or raises CallRejected."""
        if not isinstance(args, dict):
            raise CallRejected("invalid_arguments", "arguments must be an object")
        key = find_customer_key(args)
        if key is not None:
            raise CallRejected("customer_argument_not_allowed", key)
        if name in CONTROL:
            model = CONTROL[name][0]
            kind = "control"
        elif name in self.tools:
            model = self.tools[name].args_model
            kind = "data"
        else:
            raise CallRejected("unknown_function", name)
        try:
            return kind, model.model_validate(args)
        except ValidationError as exc:
            # Only field locations and error types go back: never the input values.
            detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}" for e in exc.errors())
            raise CallRejected("invalid_arguments", detail) from None
