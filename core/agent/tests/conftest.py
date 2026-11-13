"""Shared fakes for the answer pipeline tests: a fake data tool, fake data access and a pipeline
factory. No network and no database (the one database test is in test_agent_db.py)."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.agent.audit import AuditLog  # noqa: E402
from core.agent.orchestrator import AskRequest, DataUnavailable, Pipeline  # noqa: E402
from core.agent.registry import Registry, ToolSpec  # noqa: E402
from core.tools.formatting import display  # noqa: E402
from core.tools.models import Args, Card, Number, Period, ToolResult, Unit  # noqa: E402

AS_OF = date(2026, 9, 30)
AUG = Period(start=date(2026, 8, 1), end=date(2026, 8, 31), label="August 2026")
CANARY = "MRC-CANARY-0001"  # a merchant id in the tool's data and card, never in its model view (R3)


class FakeArgs(Args):
    category: str = "Restaurants"


def fake_spending(ctx, args: FakeArgs) -> ToolResult:
    """Restaurants in August 2026: a total and a count, a card, and a model view without the canary."""
    total = ctx.numbers.register(Number(value=147.64, unit=Unit.EUR, period=AUG, method="spending.total@1",
                                        evidence_ref="ev_aaaaaaaaaaa1", label="Restaurants",
                                        display=display(Decimal("147.64"), Unit.EUR, ctx.language)))
    count = ctx.numbers.register(Number(value=10, unit=Unit.COUNT, period=AUG, method="spending.n_tx@1",
                                        evidence_ref="ev_aaaaaaaaaaa2", label="Transactions",
                                        display=display(Decimal(10), Unit.COUNT, ctx.language)))
    card = Card(card_id="card_test0001", type="metric", title="Restaurants", subtitle=AUG.label,
                evidence_ref=total.evidence_ref, primary=total, secondary=[count], merchant=CANARY)
    view = {"tool": "fake_spending", "period": AUG.label,
            "total": {"id": total.id, "value": total.value, "unit": "eur", "label": total.label},
            "tx_count": {"id": count.id, "value": count.value, "unit": "count", "label": count.label}, "notes": []}
    return ToolResult(tool="fake_spending", data={"merchant_id": CANARY, "rows": [{"merchant": CANARY}]}, card=card,
                      evidence=[total.evidence_ref, count.evidence_ref], model_view=view)


def failing_tool(ctx, args: FakeArgs) -> ToolResult:
    raise RuntimeError(f"boom {CANARY} postgresql://user:secret@host/db")


def db_down_tool(ctx, args: FakeArgs) -> ToolResult:
    raise DataUnavailable()


class FakeData:
    def __init__(self, customers=("CUST00860", "CUST00493"), down: bool = False) -> None:
        self.customers = set(customers)
        self.down = down
        self.connections = 0

    def customer_exists(self, customer_id: str) -> bool:
        if self.down:
            raise DataUnavailable()
        return customer_id in self.customers

    @contextmanager
    def connection(self):
        if self.down:
            raise DataUnavailable()
        self.connections += 1
        yield None


def registry(*extra: ToolSpec) -> Registry:
    reg = Registry()
    reg.register(ToolSpec("fake_spending", "Restaurants spending.", FakeArgs, fake_spending, ("Looking", "Katson")))
    for spec in extra:
        reg.register(spec)
    return reg


@pytest.fixture
def make_pipeline(tmp_path):
    def make(model, reg=None, data=None):
        return Pipeline(reg or registry(), model, data or FakeData(), as_of=AS_OF, audit=AuditLog(tmp_path / "audit"))
    return make


def run(pipeline: Pipeline, message: str = "How much did I spend on restaurants in August 2026?",
        customer_id: str = "CUST00860", language: str = "auto", conversation_id: str | None = None):
    events: list[tuple[str, dict]] = []
    pipeline.run(AskRequest(customer_id=customer_id, message=message, language=language,
                            conversation_id=conversation_id), lambda e, p: events.append((e, p)))
    return events


def audit_records(pipeline: Pipeline) -> list[dict]:
    import json
    out = []
    for path in sorted(pipeline.audit.directory.glob("*.jsonl")):
        out += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return out
