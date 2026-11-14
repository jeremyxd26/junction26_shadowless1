"""The peer card offers a cut only above the median (#418). No database."""

from __future__ import annotations

from datetime import date

import pytest

from core.tools import peer
from core.tools.models import Number, Period, Unit

SPAN = Period(start=date(2026, 4, 1), end=date(2026, 9, 30), label="1 Apr – 30 Sep 2026")


def n(value, unit=Unit.PERCENT, method="peer_benchmark.vs_median_pct@1"):
    return Number(value=value, unit=unit, period=SPAN, method=method, evidence_ref="ev_000000000001", label="x",
                  display="x")


def data(vs: float, metric: str = "spend_total") -> peer.PeerBenchmarkData:
    eur = n(2975.65, Unit.EUR_PER_MONTH, "peer_benchmark.peer_median_month_eur@1")
    return peer.PeerBenchmarkData(
        metric=metric, metric_label="Total", period=SPAN, shown=True, reason=None, you=eur, peer_median=eur,
        peer_p25=eur, peer_p75=eur, percentile=n(51, Unit.PERCENTILE, "peer_benchmark.percentile@1"), vs_median=n(vs),
        peer_group=peer.PeerGroup(level="age_band", label="Age 35-44", size=None, comparable=True), peer_source="marts")


@pytest.mark.parametrize("vs,metric,offered", [
    (14.6, "spend_total", True), (1.2, "spend_total", True), (1.04, "spend_total", False), (1.0, "spend_total", False),
    (0.0, "spend_total", False), (-0.04, "spend_total", False), (-40.5, "spend_total", False),
    (14.6, "Restaurants", True), (14.6, "Groceries", False), (14.6, "Housing", False)])
def test_a_cut_is_offered_only_above_the_median_for_spending_that_can_be_cut(vs, metric, offered):
    card = peer._card(data(vs, metric), {"label": "Estimate", "text": "x"}, "en")
    assert bool(card.actions) is offered


def test_a_categorys_offer_is_the_what_if_itself():
    card = peer._card(data(14.6, "Restaurants"), {"label": "Estimate", "text": "x"}, "en")
    assert card.actions[0].prompt == "What if I cut total?"   # the label given here is "Total"


# ---- review of #379 part B: a card never offers a what-if that answers "no monthly habit to cut" ---------

def _rows(spec):
    """Classified rows: (day, category, basket, one_off) each, all purchases of 10 euros."""
    from datetime import datetime
    from decimal import Decimal

    from core.tools.classify import CTx
    from core.tools.db import Tx
    out = []
    for i, (d, category, basket, one_off) in enumerate(spec, start=1):
        t = Tx(i, d, datetime.combine(d, datetime.min.time()), category, "purchase", None, None, Decimal("-10.00"))
        out.append(CTx(tx=t, flow="spend", is_one_off=one_off, is_subscription=False, basket=basket, mcc_group=None))
    return out


def _ctx():
    from core.tools.context import ToolContext
    return ToolContext(customer_id="CUST00849", as_of=date(2026, 9, 30), conn=None)


IN = date(2026, 6, 14)        # inside the window of the last 6 complete months (1 Apr - 30 Sep 2026)
OUT = date(2026, 2, 14)       # before it


@pytest.mark.parametrize("spec,offered", [
    ([(IN, "Travel", "everyday_spending", False)], False),                                   # one trip: no habit
    ([(IN, "Travel", "everyday_spending", False)] * 2, False),
    ([(IN, "Travel", "everyday_spending", False)] * 3, True),                                # three: a cut
    ([(IN, "Travel", "everyday_spending", False)] * 2 + [(IN, "Travel", "everyday_spending", True)], False),  # one-off
    ([(IN, "Travel", "everyday_spending", False)] * 2 + [(IN, "Travel", "regular_essentials", False)], False),
    ([(IN, "Travel", "everyday_spending", False)] * 2 + [(OUT, "Travel", "everyday_spending", False)], False),
])
def test_the_offer_needs_three_cuttable_purchases_in_the_window(spec, offered):
    # #527: the what-if metric's own rule (04_what_if.sql n_tx >= 3), from the rows the peer tool has already
    assert peer.what_if_offered(_ctx(), "Travel", _rows(spec)) is offered


def test_a_basket_counts_its_purchases_and_the_total_needs_none():
    rows = _rows([(IN, "Restaurants", "everyday_spending", False), (IN, "Lifestyle", "everyday_spending", False),
                  (IN, "Travel", "everyday_spending", False)])
    assert peer.what_if_offered(_ctx(), "everyday_spending", rows) is True
    assert peer.what_if_offered(_ctx(), "spend_total", []) is True


def test_any_failure_drops_only_the_offer_with_a_warning(monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(peer, "cuttable_purchases", boom)
    with caplog.at_level("WARNING"):
        assert peer.what_if_offered(_ctx(), "Travel", []) is False
    assert "peer offer check failed (RuntimeError)" in caplog.text and "unexpected" not in caplog.text


def test_the_card_and_the_view_follow_the_tools_decision():
    estimate = {"label": "Estimate", "text": "x"}
    assert peer._card(data(14.6, "Restaurants"), estimate, "en", cut_offered=False).actions == []
    assert peer._card(data(14.6, "Restaurants"), estimate, "en", cut_offered=True).actions
    assert peer._model_view(data(14.6, "Travel"), estimate, [], offers_cut=False)["offers_cut"] is False


@pytest.mark.parametrize("offers_cut,what_if", [(False, False), (True, True)])
def test_the_sentence_says_the_offer_only_when_the_card_makes_it(offers_cut, what_if):
    from core.agent import answer_sentences
    view = {"metric": "Travel", "metric_label": "Travel", "shown": True, "offers_cut": offers_cut,
            "vs_median": {"id": "n3", "value": 14.6, "unit": "percent"}}
    sentences, _ = answer_sentences.peer(view, "en", lambda text: True)
    assert ("what-if" in sentences[0]) is what_if



def test_a_health_metric_is_never_offered_even_with_purchases():
    # review of #534: a health what-if is never offered anywhere, also by the helper alone (R9)
    rows = _rows([(IN, "Health", "unexpected_necessities", False)] * 4)
    assert peer.what_if_offered(_ctx(), "Health", rows) is False
