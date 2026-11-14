"""#267: a real answer to "How could I save more?" carries the safe-to-save card with its `open_host_screen`
action when the monthly figure is above 0, and none when it is 0. The plan is the rule planner's own
(RuleModel: since #216 "save more" starts from get_safe_to_save, then the baskets); no database. The
safe-to-save card comes from the real card builder (core.tools.safe_to_save.build) on Sanna's row of
03_safe_to_spend.sql; the baskets are a fake that returns the tool's model view shape."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest
from agent_fakes import AS_OF, FakeData
from fastapi.testclient import TestClient

from core.agent.api import Agent, AskLimits
from core.agent.audit import AuditLog
from core.agent.orchestrator import Pipeline
from core.agent.registry import Registry, ToolSpec
from core.agent.rules import SAVE_MORE_CALLS, RuleModel
from core.app.main import create_app
from core.app.settings import Settings
from core.tools import config, safe_to_save
from core.tools.baskets import GetBasketBreakdownArgs
from core.tools.context import ToolContext
from core.tools.formatting import display
from core.tools.models import Number, Period, ToolResult, Unit

WINDOW = Period(start=date(2026, 4, 1), end=date(2026, 9, 30), label="1 Apr – 30 Sep 2026")


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


SANNA = {"free_month_eur": "783.79", "everyday_month_eur": "599.18", "safe_to_save_monthly_eur": "184.61",
         "essentials_shortfall_month_eur": "0.00", "free_until_payday_eur": "12567.56",
         "everyday_until_payday_eur": "295.28", "safe_to_save_eur": "12272.28", "save_reason": None,
         "save_reason_category": None, "save_reason_month_eur": None,
         "next_payday": date(2026, 10, 15), "salary_status": "received_this_month"}
# Everyday spending uses the free month up: monthly 0, with the largest everyday category as the reason.
ZERO = {**SANNA, "everyday_month_eur": "900.00", "safe_to_save_monthly_eur": "0.00",
        "save_reason": "largest_everyday_category", "save_reason_category": "Restaurants",
        "save_reason_month_eur": "186.93"}


def _row(base: dict) -> dict:
    return {k: Decimal(v) if isinstance(v, str) and re.fullmatch(r"-?[0-9.]+", v) else v for k, v in base.items()}


def save_tool(base: dict):
    def get_safe_to_save(ctx, args: safe_to_save.GetSafeToSaveArgs) -> ToolResult:
        own = ToolContext(customer_id=ctx.customer_id, as_of=ctx.as_of, conn=_Store(), language=ctx.language,
                          numbers=ctx.numbers)
        return safe_to_save.build(own, {"cushion_eur": config.SAFE_TO_SPEND_CUSHION_EUR}, _row(base))
    return get_safe_to_save


def fake_baskets(ctx, args: GetBasketBreakdownArgs) -> ToolResult:
    """The basket breakdown's model view for the window: the total and the three shares, no card."""
    def num(value: str, unit: Unit, label: str, ref: str) -> Number:
        return ctx.numbers.register(Number(value=float(value), unit=unit, period=WINDOW, method="spending.total@1",
                                           evidence_ref=ref, label=label,
                                           display=display(Decimal(value), unit, ctx.language)))

    total = num("3010.59", Unit.EUR_PER_MONTH, "Total spending", "ev_bbbbbbbbbbb0")
    shares = [(key, label, num(pct, Unit.PERCENT, "Share", f"ev_bbbbbbbbbbb{i}"))
              for i, (key, label, pct) in enumerate([("regular_essentials", "Regular essentials", "62.7"),
                                                     ("unexpected_necessities", "Unexpected necessities", "11.3"),
                                                     ("everyday_spending", "Everyday spending", "19.9")], 1)]
    view = {"tool": "get_basket_breakdown", "period": WINDOW.label, "monthly_average": True,
            "total": {"id": total.id, "value": total.value, "unit": "eur_per_month", "label": total.label},
            "baskets": [{"key": key, "label": label,
                         "share": {"id": s.id, "value": s.value, "unit": "percent", "label": s.label},
                         "categories": []} for key, label, s in shares]}
    return ToolResult(tool="get_basket_breakdown", data={}, card=None,
                      evidence=[total.evidence_ref, *(s.evidence_ref for _, _, s in shares)], model_view=view)


@pytest.fixture
def client(tmp_path, monkeypatch):
    for name in ("DATABASE_URL", "AUDIT_API", "ASK_RATE_LIMIT_PER_MIN", "TRUSTED_PROXIES"):
        monkeypatch.delenv(name, raising=False)
    app = create_app(Settings(_env_file=None))

    def install(base: dict):
        audit = AuditLog(tmp_path / "audit")
        data = FakeData()
        reg = Registry()
        reg.register(ToolSpec("get_safe_to_save", "Safe to save.", safe_to_save.GetSafeToSaveArgs, save_tool(base),
                              ("Working out", "Lasken")))
        reg.register(ToolSpec("get_basket_breakdown", "Baskets.", GetBasketBreakdownArgs, fake_baskets,
                              ("Looking", "Katson")))
        pipeline = Pipeline(reg, RuleModel(), data, as_of=AS_OF, audit=audit)
        app.state.agent = Agent(pipeline=pipeline, data=data, audit=audit, limits=AskLimits(0, 0, 0))

    with TestClient(app) as c:
        c.install = install
        yield c


def ask(client, message: str, language: str) -> dict:
    r = client.post("/api/ask", json={"customer_id": "CUST00860", "conversation_id": None, "message": message,
                                      "language": language}, headers={"Accept": "application/json"})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_rule_planner_starts_save_more_from_safe_to_save():
    # the precondition of this file: without it no rule answer to "save more" has the card (review of #308)
    assert SAVE_MORE_CALLS[0][0] == "get_safe_to_save"


@pytest.mark.parametrize("message, language, label", [
    ("How could I save more?", "en", "See monthly saving in S-mobiili"),
    ("Miten voisin säästää enemmän?", "fi", "Katso kuukausisäästäminen S-mobiilissa")])
def test_a_rule_answer_to_save_more_carries_the_host_screen_action(client, message, language, label):
    client.install(SANNA)
    body = ask(client, message, language)
    assert body["outcome"] == "answered" and body["language"] == language, body
    cards = [c for c in body["cards"] if c["type"] == "safe_to_save"]
    assert len(cards) == 1, [c["type"] for c in body["cards"]]
    assert cards[0]["monthly"]["value"] == 184.61
    host = [a for a in cards[0]["actions"] if a["type"] == "open_host_screen"]
    assert len(host) == 1 and (host[0]["label"], host[0]["target"]) == (label, "monthly_saving")
    # the action carries the destination only: no amount, no evidence, no prompt, no customer data
    assert not host[0].get("evidence_ref") and not host[0].get("prompt")
    assert not re.search(r"[0-9]", host[0]["label"]) and "CUST" not in str(host[0])


@pytest.mark.parametrize("message, language", [("How could I save more?", "en"),
                                               ("Miten voisin säästää enemmän?", "fi")])
def test_no_host_screen_action_when_the_monthly_figure_is_zero(client, message, language):
    client.install(ZERO)
    body = ask(client, message, language)
    cards = [c for c in body["cards"] if c["type"] == "safe_to_save"]
    assert len(cards) == 1 and cards[0]["monthly"]["value"] == 0
    assert [a["type"] for a in cards[0]["actions"]] == ["open_evidence"]
