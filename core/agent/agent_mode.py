"""Agent mode (#937): one Gemini tool-use loop per turn, behind a switch that is off by default.

The switch is read per answer, with no restart:
- the file var/agent-mode-off forces it off;
- else the file var/agent-mode-on turns it on;
- else the process environment variable AGENT_MODE (1, on, true or yes) turns it on.
AGENT_MODE is read from the process environment only (os.environ), not from .env, so on the service it takes a
restart; the two files do not.

When it is off, nothing here runs and the pipeline answers exactly as before. When it is on, the pipeline's three
places that ask a model today (the literacy route, talk mode, the planner for a question the rules do not recognise)
hand the turn to Pipeline._answer_agent after every route, refusal and stand-down check before them. The rules keep
the hard declines, the meta intents and the demo fast paths.

The model sees the last turns of the conversation (question and answer text, numbers masked), a short profile of
the user's spending (labels only, no numbers), finlit fragments and the numbers already shown, and may call the
registry's tools (at most MAX_TOOL_ROUNDS rounds), ask back or answer in words. Every draft passes the cheap checks
(the validator, the talk checks) and then a safety judge (a second small model call); one regenerate with the
reasons, then FALLBACK.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.agent import guard, talk_checks, talk_mode

ROOT = Path(__file__).resolve().parents[2]
ON_SWITCH = ROOT / "var" / "agent-mode-on"
OFF_SWITCH = ROOT / "var" / "agent-mode-off"
ENV_NAME = "AGENT_MODE"
_TRUE = frozenset({"1", "on", "true", "yes"})

HISTORY_TURNS = 8        # the last turns of the conversation the model sees
MAX_TOOL_ROUNDS = 2      # rounds in which the model may call tools; then one round in words only
PROFILE_LABELS = 6       # basket labels in the profile summary
JUDGE_MODEL = "gemini-3.5-flash-lite"
JUDGE_MAX_TOKENS = 512
JUDGE_TIMEOUT_S = 4.0

# The natural fallback after a second failed check: never the old "could not work this out" text
FALLBACK = ("Let me put that another way. What would help you most right now?",
            "Sanon sen toisin. Mikä auttaisi sinua eniten juuri nyt?")

JUDGE_CATEGORIES = ("none", "borrowing", "product", "affordability", "other_people", "shaming")


def enabled() -> bool:
    """The switch, read per answer: the off file wins, then the on file, then AGENT_MODE in the environment."""
    try:
        if OFF_SWITCH.exists():
            return False
        if ON_SWITCH.exists():
            return True
    except OSError:
        return False
    return os.environ.get(ENV_NAME, "").strip().lower() in _TRUE


def fallback_text(lang: str) -> str:
    return FALLBACK[1] if lang == "fi" else FALLBACK[0]


@dataclass
class AgentInput:
    """One request of the agent loop. `rounds` are the earlier rounds of this answer: (model turn as received,
    [FunctionResponse]); `retry_errors` with `retry_turn` asks for the draft again with the reasons."""

    question: str
    language: str
    as_of: str
    tools: list[dict[str, Any]]
    history: list[dict[str, Any]] = field(default_factory=list)
    profile: list[str] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    shown: list[dict[str, Any]] = field(default_factory=list)
    rounds: list[tuple[Any, list[Any]]] = field(default_factory=list)
    round: int = 1
    tools_on: bool = True
    retry_turn: Any = None
    retry_errors: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    calls: list[Any]
    text: str = ""
    raw: Any = None
    usage: Any = None


@dataclass
class JudgeResult:
    ok: bool
    category: str = "none"
    reason: str = ""
    usage: Any = None


def judge_schema() -> dict[str, Any]:
    return {"type": "object",
            "properties": {"verdict": {"type": "string", "enum": ["ok", "hit"]},
                           "category": {"type": "string", "enum": list(JUDGE_CATEGORIES)},
                           "reason": {"type": "string", "description": "One short sentence; empty when ok."}},
            "required": ["verdict", "category"]}


# The cheap layer for a draft that cites the user's own data (tools ran in this turn): the talk checks that do not
# forbid speaking about the data itself. A words answer gets talk_mode.draft_problems in full instead.
_AFFORD = re.compile(r"\byou\s+(?:can|could|can['’]t|cannot)\s+(?:\w+\s+)?afford\b|\bsinulla\s+on\s+varaa\b"
                     r"|\bsinulla\s+ei\s+ole\s+varaa\b|\bvarasi\s+riittä", re.I)


def data_text_problems(text: str) -> list[str]:
    """What a data answer of the agent must not contain, as retry reasons; [] when nothing."""
    problems = []
    copies = talk_checks._general_copies(text) + [guard.fold(text)]
    for rx, why in ((talk_checks.GENERAL_BORROWING, "borrowing: never mention a loan, credit or any borrowing"),
                    (talk_mode._TALK_BORROWING, "borrowing: never suggest paying later, in parts, back, ahead of pay "
                                                "or in the red"),
                    (talk_mode._TALK_OWN_STATE, "the user's own money: state the figures, never say what the user's "
                                                "money is, fits or allows"),
                    (talk_checks._GENERAL_BORROWING_CLASS, "borrowing: never suggest paying later, in parts, in the "
                                                           "red, with an advance or with someone else's money"),
                    (talk_checks._GENERAL_PRODUCT, "a product, bank or investment: name none"),
                    (talk_checks._GENERAL_OTHERS, "other people's money: speak about the user only"),
                    (talk_checks._GENERAL_LINK, "a link, an address or a function name: name none"),
                    (talk_checks._GENERAL_JUDGING, "judging or joking: never judge the user"),
                    (_AFFORD, "affordability: never say what the user can or cannot afford")):
        m = next((found for found in (rx.search(c) for c in copies) if found), None)
        if m:
            problems.append(f"'{m.group(0)}': {why}")
    return problems


def literacy_text_problems(text: str) -> list[str]:
    """A literacy answer reads no data: the data answer's checks, and never a statement about the user's own money."""
    problems = data_text_problems(text)
    copies = talk_checks._general_copies(text) + [guard.fold(text)]
    m = next((found for found in (talk_checks._GENERAL_OWN_STATE.search(c) for c in copies) if found), None)
    if m:
        problems.append(f"'{m.group(0)}': the user's own money: a general answer reads no data, so it never says how "
                        "the user is doing, what they can afford or what their money is")
    return problems


def clarify_problems(texts: list[str]) -> list[str]:
    """The cheap layer for a model's clarifying question and options (the pipeline's text rules run after it)."""
    problems = []
    for text in texts:
        for rx in (talk_checks.GENERAL_BORROWING, talk_checks._GENERAL_BORROWING_CLASS, talk_checks._GENERAL_PRODUCT,
                   talk_checks._GENERAL_OTHERS, _AFFORD):
            if any(rx.search(c) for c in talk_checks._general_copies(text)):
                problems.append(text)
                break
    return problems


def question_stands_down(message: str, literacy: bool = False) -> bool:
    """A question the planner's place keeps on the old path (the rules and the planner's declines): borrowing or
    affordability (talk mode's template), a product, a brand, another topic or other people's money. A concept
    question (literacy) may name interest ("What is compound interest?")."""
    if talk_mode.template_only(message) or talk_mode.TOPIC_STANDS_DOWN.search(guard.fold(message)):
        return True
    checks = [talk_checks.GENERAL_BORROWING, talk_checks._GENERAL_BORROWING_CLASS, talk_checks._GENERAL_PRODUCT,
              talk_checks._GENERAL_BRAND, talk_checks._GENERAL_OTHERS]
    if not literacy:
        checks.append(talk_checks._GENERAL_PRODUCT_CLASS)
    return any(rx.search(message) for rx in checks)


_TIPS = re.compile(r"\btips?\b|\badvice\b|\bsuggest\w*|\bideas?\b|\bhow (?:can|could|do|should) i (?:save|cut|spend less)"
                   r"|\bvinkk\w*|\bneuvo\w*|\behdot\w*|\bideoi\w*|\bmiten (?:voisin|voin|saisin) saast\w*", re.I)


def asks_tips(message: str) -> bool:
    """A request for tips or ideas: talk mode's rule, no number in the answer."""
    return bool(_TIPS.search(guard.fold(message))) or talk_mode.trigger(message) in ("tips", "no_numbers")


def words_only(message: str, turns: list[dict[str, Any]]) -> bool:
    """A question about reasons, tips, ideas or a concept, or an open follow-up after an answer in words: the loop
    answers in words, with no tool and no card (Renat's live probes of #955)."""
    from core.agent import finlit_kb

    if talk_mode.trigger(message) is not None or asks_tips(message):
        return True
    if finlit_kb.question_kind(message) is not None or finlit_kb.overrides_rules(message):
        return True
    # "anything else?", "why?" and the like get words after any answer: never a new card (Renat's live probes)
    return talk_mode.follow_up(message) or talk_mode.why_follow_up(message) or bool(_BARE_WHY.fullmatch(
        guard.fold(message).strip()))


_BARE_WHY = re.compile(r"[\W_]*(?:and |but |so |ja |mutta )?(?:why|how come|miksi|miks|miten niin)[\W_]*", re.I)
