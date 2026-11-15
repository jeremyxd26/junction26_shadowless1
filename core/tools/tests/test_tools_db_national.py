"""#569 on the shared database, the four personas only: the peer tool carries the national context for the kept
categories (Groceries, Transportation) and nothing else, its evidence cites the table and resolves without any
transaction, and the comparison's own numbers, ids and refs are the same as without it."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest

from core.app.api import evidence as evidence_api
from core.tools import evidence, national
from core.tools.context import ToolContext
from core.tools.peer import get_peer_benchmark

AS_OF = date(2026, 9, 30)
PERSONAS = {"CUST00860": "35-44", "CUST00493": "45-54", "CUST00387": "18-24", "CUST00849": "25-34"}
TABLE_GROUP = {"18-24": "17-24"}   # 18-24 lies inside the table's own 17-24 (national_context.yaml); the rest are the same


def run(conn, customer, metric, language="en"):
    return get_peer_benchmark(ToolContext(customer_id=customer, as_of=AS_OF, conn=conn, language=language),
                              {"metric": metric})


@pytest.mark.parametrize("customer", sorted(PERSONAS))
@pytest.mark.parametrize("metric", ["Groceries", "Transportation"])
def test_a_kept_category_carries_the_table_value_of_the_age_group_with_its_cited_evidence(conn, customer, metric):
    result = run(conn, customer, metric)
    nat = result.data.national
    fig = national.figure(metric, PERSONAS[customer])
    group = TABLE_GROUP.get(PERSONAS[customer], PERSONAS[customer])
    assert nat is not None and nat.age_group == group and nat.survey_year == 2022
    assert Decimal(str(nat.amount.value)) == fig.monthly and nat.amount.method == "national_context.monthly_eur@1"
    assert nat.amount.period.start == date(2022, 1, 1) and nat.amount.period.end == date(2022, 12, 31)
    assert not re.search(r"\d", nat.amount.label)            # no age digits in a label (the digit rule)
    res = evidence.resolve(conn, nat.amount.evidence_ref, customer)
    assert res.kind == "composite" and res.parts == [] and res.method == "national_context.monthly_eur@1"
    spec = evidence.load(conn, nat.amount.evidence_ref)[1]
    assert spec["formula"] == "rule_value" and spec["params"]["table"] == "StatFin/ktutk/14q4.px"
    assert spec["params"]["age_group"] == group and spec["params"]["survey_year"] == 2022
    assert "selection" not in spec                            # cites the table, never transactions
    body = evidence_api.build(conn, res, customer, "en")       # the evidence view the app opens
    assert body.title.endswith("1 Jan – 31 Dec 2022") and body.parts == [] and body.rows == []
    assert "Statistics Finland" in body.method.summary and "14q4" in body.method.summary
    # the opened view names the table's age band, and for transport that buying a vehicle is left out (#585 review)
    assert group.replace("-", "\u2013") in body.title
    assert ("without buying a vehicle" in body.title) is (metric == "Transportation")
    assert "buying a vehicle is left out" in body.method.summary
    view = result.model_view["national"]
    assert view["amount"]["id"] == nat.amount.id and view["context_only"] is True and "age" not in view


@pytest.mark.parametrize("customer", sorted(PERSONAS))
@pytest.mark.parametrize("metric", ["Restaurants", "spend_total", "everyday_spending", "Housing"])
def test_no_line_for_a_dropped_category_the_total_a_basket_or_housing(conn, customer, metric):
    result = run(conn, customer, metric)
    assert result.data.national is None and "national" not in result.model_view


@pytest.mark.parametrize("customer", sorted(PERSONAS))
def test_the_comparison_is_the_same_with_and_without_the_line(conn, customer, monkeypatch):
    with_line = run(conn, customer, "Groceries")
    monkeypatch.setattr(national, "figure", lambda *a, **k: None)
    without = run(conn, customer, "Groceries")
    view = {k: v for k, v in with_line.model_view.items() if k != "national"}
    assert view == without.model_view and with_line.card == without.card
    # the line's Number is registered after every Number of the comparison
    ids = [n["id"] for n in (view["you"], view["peer_median"], view["vs_median"]) if n]
    assert all(int(i[1:]) < int(with_line.data.national.amount.id[1:]) for i in ids)
