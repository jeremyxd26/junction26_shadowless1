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

class _Result:
    def __init__(self, status):
        self.data = type("D", (), {"status": status})()


@pytest.mark.parametrize("outcome,offered", [("estimate", True), ("estimate_with_caveat", True),
                                             ("not_offered", False), ("missing", False), ("refused", False)])
def test_the_offer_needs_the_what_if_to_offer_a_cut(monkeypatch, outcome, offered):
    from core.tools.missing import MissingData
    from core.tools.what_if import WhatIfRefused
    seen = []

    def fake(ctx, args, too_few="raise"):
        seen.append((args["selection"], too_few))
        if outcome == "missing":
            raise MissingData("too_few_transactions", what="travel", period="x", n=1)
        if outcome == "refused":
            raise WhatIfRefused("invalid_scenario")
        return _Result(outcome)

    monkeypatch.setattr(peer, "run_what_if", fake)
    from core.tools.context import ToolContext
    ctx = ToolContext(customer_id="CUST00849", as_of=date(2026, 9, 30), conn=None)
    assert peer.what_if_offered(ctx, "Travel") is offered
    assert seen == [({"kind": "category", "value": "Travel"}, "not_offered")]   # the structured mode
    assert ctx.numbers.all() == {}                                               # a private registry


def test_a_basket_offer_asks_the_basket_what_if_and_the_total_asks_none(monkeypatch):
    seen = []
    monkeypatch.setattr(peer, "run_what_if", lambda ctx, args, too_few="raise": seen.append(args) or _Result("estimate"))
    from core.tools.context import ToolContext
    ctx = ToolContext(customer_id="CUST00849", as_of=date(2026, 9, 30), conn=None)
    assert peer.what_if_offered(ctx, "everyday_spending") and peer.what_if_offered(ctx, "spend_total")
    assert [a["selection"] for a in seen] == [{"kind": "basket", "value": "everyday_spending"}]


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

