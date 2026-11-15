"""#888 on the shared database, the four personas (one customer per query): the what-if question back offers only
chips the what-if tool estimates for the customer, so no chip leads to "too few transactions". The new Eetu
(CUST00387, #882) took no taxi in the data: his chips leave the taxi out and take the next candidate.
Skipped without DATABASE_URL."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from agent_fakes import AS_OF, run
from test_agent_db import OneConnection, conn  # noqa: F401

from core.agent.audit import AuditLog
from core.agent.orchestrator import Pipeline
from core.agent.rules import WHAT_IF_WHICH, WHAT_IF_WHICH_OPTIONS, RuleModel
from core.agent.toolset import default_registry
from core.tools.context import ToolContext

PERSONAS = ("CUST00860", "CUST00493", "CUST00387", "CUST00849")


def pipeline(conn, tmp_path):  # noqa: F811
    return Pipeline(default_registry(), RuleModel(), OneConnection(conn), as_of=AS_OF, audit=AuditLog(tmp_path))


def taxi(option: str) -> bool:
    return "tax" in option.lower() or "taks" in option.lower()


@pytest.mark.parametrize("lang", ["en", "fi"])
@pytest.mark.parametrize("customer_id", PERSONAS)
def test_every_offered_chip_is_a_what_if_the_tool_estimates(conn, tmp_path, customer_id, lang):  # noqa: F811
    pipe = pipeline(conn, tmp_path)
    i = 1 if lang == "fi" else 0
    asked = SimpleNamespace(question=WHAT_IF_WHICH[i], options=list(WHAT_IF_WHICH_OPTIONS[i]))
    offered = pipe._what_if_chips(ToolContext(customer_id=customer_id, as_of=AS_OF, conn=None, language=lang),
                                  asked, lang).options
    assert len(offered) == 3, offered
    probe = ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn, language=lang)
    assert all(pipe._what_if_estimates(probe, option, lang) for option in offered), offered
    if customer_id == "CUST00387":
        assert not any(taxi(o) for o in offered) and offered[0] == WHAT_IF_WHICH_OPTIONS[i][0], offered
    else:
        assert offered == list(WHAT_IF_WHICH_OPTIONS[i])


def test_eetus_question_back_through_the_pipeline_has_no_taxi_chip(conn, tmp_path):  # noqa: F811
    done = dict(run(pipeline(conn, tmp_path), "What if I spent 20% less on food delivery?", customer_id="CUST00387",
                    language="en"))["done"]
    assert done["outcome"] == "clarify" and done["clarify"]["question"] == WHAT_IF_WHICH[0]
    assert len(done["clarify"]["options"]) == 3 and not any(taxi(o) for o in done["clarify"]["options"])
