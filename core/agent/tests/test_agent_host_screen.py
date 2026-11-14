"""#267: an answer about saving carries the safe-to-save card with its `open_host_screen` action, and the
action survives the /api/ask response unchanged. Scripted model, no database: the card comes from the
real card builder (core.tools.safe_to_save.build) on Sanna's row of 03_safe_to_spend.sql."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest
from agent_fakes import AS_OF, FakeArgs, FakeData, registry
from fastapi.testclient import TestClient

from core.agent.api import Agent, AskLimits
from core.agent.audit import AuditLog
from core.agent.model import FunctionCall, ScriptedModel
from core.agent.orchestrator import Pipeline
from core.agent.registry import ToolSpec
from core.app.main import create_app
from core.app.settings import Settings
from core.tools import config, safe_to_save
from core.tools.context import ToolContext


class _Store:
    """The evidence store's write and read-back, in memory."""

    def __init__(self):
        self.rows = {}

    def cursor(self):
        store = self

        class Cur:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def executemany(self, sql, params):
                for ref, _customer, spec in params:
                    store.rows.setdefault(ref, spec.obj)

        return Cur()

    def execute(self, sql, params):
        rows = [(r, self.rows[r]) for r in params[0] if r in self.rows]

        class Res:
            def fetchall(self):
                return rows

        return Res()


def _row(monthly: str) -> dict:
    base = {"free_month_eur": "783.79", "everyday_month_eur": "599.18", "safe_to_save_monthly_eur": monthly,
            "essentials_shortfall_month_eur": "0.00", "free_until_payday_eur": "12567.56",
            "everyday_until_payday_eur": "295.28", "safe_to_save_eur": "12272.28", "save_reason": None,
            "save_reason_category": None, "save_reason_month_eur": None,
            "next_payday": date(2026, 10, 15), "salary_status": "received_this_month"}
    return {k: Decimal(v) if isinstance(v, str) and re.fullmatch(r"-?[0-9.]+", v) else v for k, v in base.items()}


def fake_save(ctx, args: FakeArgs):
    """The real safe-to-save card for Sanna, built without a database."""
    own = ToolContext(customer_id=ctx.customer_id, as_of=ctx.as_of, conn=_Store(), language=ctx.language)
    return safe_to_save.build(own, {"cushion_eur": config.SAFE_TO_SPEND_CUSHION_EUR}, _row("184.61"))


PLAN = [FunctionCall("fake_save", {}), FunctionCall("finish")]


@pytest.fixture
def client(tmp_path, monkeypatch):
    for name in ("DATABASE_URL", "AUDIT_API", "ASK_RATE_LIMIT_PER_MIN", "TRUSTED_PROXIES"):
        monkeypatch.delenv(name, raising=False)
    app = create_app(Settings(_env_file=None))

    def install(language: str):
        draft = {"language": language, "cited": [], "lesson_key": None,
                 "text": ("Here is what a typical month leaves after your commitments." if language == "en"
                          else "Tässä on, mitä tavallisesta kuukaudesta jää sitoumusten jälkeen.")}
        audit = AuditLog(tmp_path / "audit")
        data = FakeData()
        spec = ToolSpec("fake_save", "Safe to save.", FakeArgs, fake_save, ("Working out", "Lasken"))
        pipeline = Pipeline(registry(spec), ScriptedModel(plans=[PLAN], drafts=[draft]), data, as_of=AS_OF, audit=audit)
        app.state.agent = Agent(pipeline=pipeline, data=data, audit=audit, limits=AskLimits(0, 0, 0))

    with TestClient(app) as c:
        c.install = install
        yield c


@pytest.mark.parametrize("language, label", [("en", "See monthly saving in S-mobiili"),
                                             ("fi", "Katso kuukausisäästäminen S-mobiilissa")])
def test_the_answer_about_saving_carries_the_host_screen_action(client, language, label):
    client.install(language)
    message = "How could I save more?" if language == "en" else "Miten voisin säästää enemmän?"
    r = client.post("/api/ask", json={"customer_id": "CUST00860", "conversation_id": None, "message": message,
                                      "language": language}, headers={"Accept": "application/json"})
    assert r.status_code == 200, r.text
    body = r.json()
    cards = [c for c in body["cards"] if c["type"] == "safe_to_save"]
    assert cards, body
    host = [a for a in cards[0]["actions"] if a["type"] == "open_host_screen"]
    assert len(host) == 1 and (host[0]["label"], host[0]["target"]) == (label, "monthly_saving")
    # the action carries the destination only: no amount, no evidence, no prompt, no customer data
    assert not host[0].get("evidence_ref") and not host[0].get("prompt")
    assert not re.search(r"[0-9]", host[0]["label"]) and "CUST" not in str(host[0])
