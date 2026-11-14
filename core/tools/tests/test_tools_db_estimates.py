"""#380 on the database: for each persona, one customer at a time, every estimate card of every tool says what
it assumed, and every Number it lists as observed, and every assumption's value that has an evidence ref,
resolves through the evidence endpoint's resolver and reconciles. Labels injected (no review answered, and
Sanna's review pending), no review table touched.

With ESTIMATE_CARDS set to a file path, the lead persona's estimate cards (English) are written there for the PR."""

from __future__ import annotations

import json
import os
from datetime import date

import pytest

from core.tools import evidence, reviews
from core.tools.bills import get_recurring_bills
from core.tools.bonus import get_bonus_estimate
from core.tools.classify import classify
from core.tools.context import ToolContext
from core.tools.forecast import get_balance_forecast
from core.tools.peer import get_peer_benchmark
from core.tools.safe_to_save import get_safe_to_save
from core.tools.safe_to_spend import get_safe_to_spend
from core.tools.what_if import run_what_if

AS_OF = date(2026, 9, 30)
PERSONAS = ["CUST00860", "CUST00493", "CUST00349", "CUST00849"]
TOOLS = {
    "safe_to_spend": lambda ctx: get_safe_to_spend(ctx, {}),
    "safe_to_save": lambda ctx: get_safe_to_save(ctx, {}),
    "what_if": lambda ctx: run_what_if(ctx, {"selection": {"kind": "category", "value": "Restaurants"}, "cut_pct": 20}),
    "bonus": lambda ctx: get_bonus_estimate(ctx, {}),
    "bills": lambda ctx: get_recurring_bills(ctx, {}),
    "peer": lambda ctx: get_peer_benchmark(ctx, {"metric": "spend_total"}),
    "forecast": lambda ctx: get_balance_forecast(ctx, {}),
}
WRITTEN: dict[str, dict] = {}


@pytest.mark.parametrize("customer_id", PERSONAS)
def test_every_estimate_resolves_what_it_observed_and_says_what_it_assumed(conn, customer_id):
    probe = ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn)
    found = reviews.candidates(classify(probe.history(), AS_OF), AS_OF, set())
    states = {"none": {}} | ({"pending": {found[0].tx.id: "unclassified"}} if found else {})
    checked = 0
    for state, labels in states.items():
        for language in ("en", "fi"):
            for name, tool in TOOLS.items():
                ctx = ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn, language=language)
                ctx._labels = dict(labels)
                card = tool(ctx).card
                if card is None or card.estimate is None:
                    continue                                 # the bills card without pro rata bills, no peer card
                where = (customer_id, state, language, name)
                est = card.estimate
                assert est.assumptions and est.observed, where
                # decision 4: each listed Number is one of the answer's, with its id
                assert all(n.id for n in est.observed), where
                assert all(a.value.id for a in est.assumptions if a.value is not None), where
                refs = [n.evidence_ref for n in est.observed]
                refs += [a.value.evidence_ref for a in est.assumptions if a.value is not None and a.value.evidence_ref]
                for ref in refs:
                    assert evidence.resolve(conn, ref, customer_id, limit=1).reconciles is True, (where, ref)
                checked += 1
                if customer_id == "CUST00860" and language == "en" and state == "none":
                    WRITTEN[name] = card.model_dump(mode="json")["estimate"]
    assert checked >= 5, (customer_id, checked)                   # most tools give an estimate card
    if customer_id == "CUST00860":
        assert set(WRITTEN) == set(TOOLS), set(TOOLS) - set(WRITTEN)   # the lead persona: every tool's estimate
    if customer_id == "CUST00860" and os.environ.get("ESTIMATE_CARDS"):
        with open(os.environ["ESTIMATE_CARDS"], "w", encoding="utf-8") as f:
            json.dump(WRITTEN, f, indent=2, ensure_ascii=False)


def test_a_what_if_not_offered_lists_what_it_left_out(conn):
    """Review of #520, on a persona: the Groceries what-if is not offered (regular essentials are not cut), so its
    estimate observes the regular essentials it left out, which reconcile, and never a baseline of 0."""
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=conn)
    ctx._labels = {}
    result = run_what_if(ctx, {"selection": {"kind": "category", "value": "Groceries"}, "cut_pct": 20})
    assert result.data.status == "not_offered" and result.data.baseline_per_month.value == 0
    observed = result.card.estimate.observed
    assert observed and all(n.value > 0 for n in observed)
    assert [n.evidence_ref for n in observed] == [result.data.regular_excluded.evidence_ref]
    for n in observed:
        assert evidence.resolve(conn, n.evidence_ref, "CUST00860", limit=1).reconciles is True
