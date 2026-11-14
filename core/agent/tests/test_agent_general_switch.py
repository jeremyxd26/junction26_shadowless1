"""The general route's switch (#572, review of #618, pass 3): with `var/general-on` absent (the default), what the
planner and the composer are sent is byte for byte dev's: the system prompts, the tool declarations and the request.
With the file present, the declarations add answer_in_words at the end and nothing else changes. No network, no
database: a recording transport behind the real Gemini adapter.

The pinned hashes are dev's at 0384b4ae, computed by the helpers below on a clean export of that commit. A later dev
change to a prompt or a tool declaration changes them legitimately; recompute them on dev then (the same helpers)."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import date

import pytest

from core.agent.conversation import ConversationStore
from core.agent.gemini import PROMPTS_DIR, GeminiModel, compose_text
from core.agent.gemini_client import GeminiClient
from core.agent.model import ComposeInput
from core.agent.orchestrator import AskRequest, Pipeline
from core.agent.tests.test_gemini_client import call_response
from core.agent.toolset import default_registry

DEV_SHA = "0384b4ae"
DEV_PLANNER_REQUEST = "d67c19503457258b049965671ac04e085666c598b4b1e9adc0d30dcb7606f830"
DEV_PROMPTS = "3f1be092a5989bdf4a0c0d8ec3abd3d5d586a0be591f8d889dd8477ddcc31fc8"
DEV_COMPOSE_TEXT = "28af730de4aaba0a63365e116f60438786fd8851353ceb5f91f81b1be03a055b"
QUESTION = "How can I build a saving habit?"


def _sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


class _NoDatabase:
    @contextmanager
    def connection(self):
        yield None

    def connection_if_free(self, wait):
        return self.connection()

    def customer_exists(self, customer_id):
        return True


class _Audit:
    def write(self, record):
        pass


class _Recorder:
    """Records every request the Gemini adapter sends; plans a decline, so no tool and no composer runs."""

    def __init__(self):
        self.requests = []

    def __call__(self, model, contents, config, timeout_s):
        self.requests.append({"model": model, "contents": contents, "config": config})
        return call_response("decline", {"kind": "out_of_scope"})


def planner_requests(question: str = QUESTION) -> list[dict]:
    """The planner requests one answer sends through the real adapter: model, contents and config (system prompt,
    declarations, tool config)."""
    recorder = _Recorder()
    client = GeminiClient("gemini-3.8-flash", recorder, cache="off", sleep=lambda s: None)
    pipe = Pipeline(default_registry(), GeminiModel(client), _NoDatabase(), as_of=date(2026, 9, 30),
                    store=ConversationStore(), audit=_Audit())
    pipe.run(AskRequest(customer_id="CUST00860", message=question, language="en"), lambda e, d: None)
    return [r for r in recorder.requests if "tools" in r["config"]]


def prompt_files() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(PROMPTS_DIR.glob("*.md"))}


def ordinary_compose_text() -> str:
    return compose_text(ComposeInput(question="What can I safely spend?", language="en", as_of="2026-09-30",
                                     data=[{"tool": "get_safe_to_spend", "x": "{{n1}}"}]))


@pytest.fixture
def switch(tmp_path, monkeypatch):
    from core.agent import orchestrator
    path = tmp_path / "general-on"
    monkeypatch.setattr(orchestrator, "GENERAL_ON", path)
    return path


def test_switched_off_the_planner_request_and_the_prompts_are_devs_byte_for_byte(switch):
    assert not switch.exists()
    requests = planner_requests()
    assert len(requests) == 1
    names = [d["name"] for d in requests[0]["config"]["tools"][0]["function_declarations"]]
    assert "answer_in_words" not in names and names[-3:] == ["decline", "ask_clarifying_question", "finish"]
    assert _sha(requests) == DEV_PLANNER_REQUEST, f"dev {DEV_SHA}: the planner request differs"
    assert _sha(prompt_files()) == DEV_PROMPTS, f"dev {DEV_SHA}: a prompt file differs"
    assert _sha(ordinary_compose_text()) == DEV_COMPOSE_TEXT, f"dev {DEV_SHA}: the compose request differs"


def test_switched_on_the_declarations_add_answer_in_words_and_nothing_else(switch):
    off = planner_requests()
    switch.write_text("", encoding="utf-8")
    on = planner_requests()
    off_decl = off[0]["config"]["tools"][0]["function_declarations"]
    on_decl = on[0]["config"]["tools"][0]["function_declarations"]
    assert on_decl[:-1] == off_decl and on_decl[-1]["name"] == "answer_in_words"
    assert on_decl[-1]["parameters_json_schema"].get("properties", {}) == {}
    strip = [{**r, "config": {k: v for k, v in r["config"].items() if k != "tools"}} for r in off]
    assert strip == [{**r, "config": {k: v for k, v in r["config"].items() if k != "tools"}} for r in on]
    assert on[0]["config"]["system_instruction"] == off[0]["config"]["system_instruction"]


def test_the_switch_is_read_once_per_answer_and_removing_it_restores_devs_request(switch):
    off = planner_requests()
    switch.write_text("", encoding="utf-8")
    assert planner_requests() != off
    switch.unlink()
    assert planner_requests() == off
