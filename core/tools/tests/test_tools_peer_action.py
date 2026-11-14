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
