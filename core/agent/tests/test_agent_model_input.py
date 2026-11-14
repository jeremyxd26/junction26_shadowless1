"""What the language model is given (#487, the review of #484). No database.

The peer tool's model view holds no group label (the age band and the postal area stay on the card), the bills
model view holds no bill id (a hash of the customer id and the merchant), and a peer question's planner and
composer inputs hold neither. The database test over every tool and persona is
core/tools/tests/test_tools_db_model_views.py.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from agent_fakes import AUG, FakeArgs, registry, run

from core.agent.model import FunctionCall, ScriptedModel
from core.agent.registry import ToolSpec
from core.tools import bills, peer
from core.tools.formatting import display
from core.tools.models import Card, Number, ToolResult, Unit

GROUP = "Age 35-44, postal area 005"


def number(value, unit=Unit.EUR, label="x", ref="ev_000000000001"):
    return Number(value=value, unit=unit, period=AUG, method="peer.median@1", evidence_ref=ref, label=label,
                  display=display(Decimal(str(value)), unit, "en"))


def peer_data(numbers=None) -> peer.PeerBenchmarkData:
    n = numbers or (lambda value, unit=Unit.EUR, label="x": number(value, unit, label))
    return peer.PeerBenchmarkData(
        metric="spend_total", metric_label="Spending", period=AUG, shown=True, reason=None,
        you=n(3010.59, label="You"), peer_median=n(2974.9, label="Median"), peer_p25=n(2400.0, label="25th"),
        peer_p75=n(3600.0, label="75th"), percentile=n(52, Unit.PERCENT, "Percentile"),
        vs_median=n(1.2, Unit.PERCENT, "Compared with the median"),
        peer_group=peer.PeerGroup(level="age_band+area3", label=GROUP, size=n(118, Unit.COUNT, "People in the group"),
                                  comparable=True),
        peer_source="marts")


def assert_no_group(text: str) -> None:
    assert "35-44" not in text and "005" not in text and "postal" not in text.lower() and GROUP not in text, text


def test_the_peer_model_view_holds_no_group_label():
    view = peer._model_view(peer_data(), None, [])
    assert set(view["peer_group"]) == {"level", "size", "comparable"}
    assert_no_group(json.dumps(view))


def test_the_bills_model_view_holds_no_bill_id():
    item = SimpleNamespace(bill_id="bill_0123456789", label="Housing", status="regular", typical_day=3,
                           typical_month=number(836.65), due_until_payday=number(836.65), next_expected=date(2026, 10, 3))
    data = SimpleNamespace(window=SimpleNamespace(label="Apr–Sep 2026"), due_period=SimpleNamespace(label="1–15 Oct"),
                           next_payday=date(2026, 10, 15), salary_status="regular", upcoming_total=number(928.5),
                           bills=[item], income=[])
    view = bills._model_view(data, [])
    assert "bill_id" not in view["bills"][0] and "bill_0123456789" not in json.dumps(view, default=str)


def fake_peer(ctx, args):
    """The real peer model view of numbers registered in this answer, and a card that keeps the group label."""
    def n(value, unit=Unit.EUR, label="x"):
        return ctx.numbers.register(number(value, unit, label, ref=f"ev_{int(value * 100) % 10**12:012d}"))
    data = peer_data(n)
    card = Card(card_id="card_peer01", type="peer", title="Spending", evidence_ref=data.you.evidence_ref,
                peer_group={"label": GROUP})
    return ToolResult(tool="get_peer_benchmark", data={}, card=card, evidence=[data.you.evidence_ref],
                      model_view=peer._model_view(data, None, []))


def test_a_peer_questions_planner_and_composer_inputs_hold_no_age_band_or_postal_area(make_pipeline):
    reg = registry(ToolSpec("get_peer_benchmark", "Peers.", FakeArgs, fake_peer, ("x", "x")))
    draft = {"language": "en", "text": "You spend {{n6}} more than the median of people like you.", "cited": ["n6"],
             "lesson_key": None}
    model = ScriptedModel(plans=[[FunctionCall("get_peer_benchmark", {})], [FunctionCall("finish")]], drafts=[draft])
    events = run(make_pipeline(model, reg=reg), "How do I compare with people like me?")
    cards = [p["card"] for e, p in events if e == "card"]
    assert cards and cards[0]["peer_group"]["label"] == GROUP                 # the card keeps it
    sent = json.dumps([dataclasses.asdict(i) for i in model.plan_inputs + model.compose_inputs], default=str)
    assert "Spending" in sent or "spend_total" in sent                         # the view reached the model
    assert_no_group(sent)
