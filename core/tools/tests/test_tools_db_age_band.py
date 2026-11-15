"""#883 on the shared database, the four personas only: 09_age_band_peer.sql gives the band of the customer's age with
its size and medians over the whole synthetic dataset; the peer tool carries it for total spending only, registered
after every Number of the comparison; each Number's evidence re-runs the file, reconciles and opens with the method,
the band, its size and the period. Every test runs inside a transaction that is rolled back: nothing is written."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest

from core.app.api import evidence as evidence_api
from core.tools import config, evidence, metric_sql
from core.tools.context import ToolContext
from core.tools.peer import age_band_for, get_peer_benchmark

AS_OF = date(2026, 9, 30)
PERSONAS = ("CUST00387", "CUST00493", "CUST00849", "CUST00860")   # Eetu is CUST00387 since #882 (band 18-24)
SETTINGS = {"band_min_n": config.AGE_BAND_MIN_N}


@pytest.fixture
def tx(conn):
    with conn.transaction(force_rollback=True):
        yield conn


def run(conn, customer, metric="spend_total", language="en"):
    return get_peer_benchmark(ToolContext(customer_id=customer, as_of=AS_OF, conn=conn, language=language),
                              {"metric": metric})


@pytest.mark.parametrize("customer", PERSONAS)
def test_the_sql_gives_the_band_of_the_customers_age_over_the_whole_dataset(tx, customer):
    age = tx.execute("SELECT age FROM customers WHERE customer_id = %s", (customer,)).fetchone()[0]
    rows = metric_sql.run(tx, config.AGE_BAND_FILE, customer, AS_OF, SETTINGS)
    assert [r["age_band"] for r in rows] == [b for b, _, _ in config.AGE_BANDS]   # one row per band
    own = [r for r in rows if r["customer_id"] == customer]
    assert len(own) == 1 and own[0]["age_band"] == age_band_for(age)
    row = own[0]
    total = tx.execute("SELECT count(*) FROM customers").fetchone()[0]
    assert sum(r["cohort_size"] for r in rows) == total      # every customer of the dataset is in one band
    assert row["shown"] and row["cohort_size"] >= int(config.AGE_BAND_MIN_N)
    for measure in config.AGE_BAND_MEASURES:
        assert row[f"median_{measure}_month_eur"] > 0
    assert (row["period_start"], row["period_end"]) == (date(2026, 4, 1), date(2026, 9, 30))
    assert metric_sql.run_one(tx, config.AGE_BAND_FILE, customer, AS_OF, SETTINGS) == row


def test_a_band_under_the_minimum_has_no_medians(tx):
    rows = metric_sql.run(tx, config.AGE_BAND_FILE, "CUST00860", AS_OF, {"band_min_n": "100000"})
    assert rows and all(not r["shown"] and r["median_ordinary_spending_month_eur"] is None for r in rows)


@pytest.mark.parametrize("customer", PERSONAS)
def test_the_peer_tool_carries_the_band_for_total_spending(tx, customer):
    result = run(tx, customer)
    data = result.data
    row = metric_sql.run_one(tx, config.AGE_BAND_FILE, customer, AS_OF, SETTINGS)
    band = data.age_band
    assert band is not None and band.band == row["age_band"] and band.dataset == "synthetic"
    assert band.cohort_size.value == row["cohort_size"] and band.cohort_size.method == "peer.age_band_cohort_size@1"
    assert (band.period.start, band.period.end) == (data.period.start, data.period.end)
    for measure in config.AGE_BAND_MEASURES:
        n = getattr(band.medians, measure)
        assert Decimal(str(n.value)) == row[f"median_{measure}_month_eur"] and n.method == "peer.age_band_median@1"
        assert not re.search(r"\d", n.label)                # no age digits in a label (the digit rule)
    # registered after every Number of the comparison: their ids do not move
    before = [n for n in (data.you, data.peer_median, data.peer_p25, data.peer_p75, data.percentile, data.vs_median,
                          data.peer_group.size) if n is not None]
    assert max(int(n.id[1:]) for n in before) < int(band.cohort_size.id[1:])
    view = result.model_view["age_band"]
    assert view["cohort_size"]["id"] == band.cohort_size.id and view["median"]["id"] == band.medians.ordinary_spending.id
    assert view["measure"] == "ordinary_spending" and view["dataset"] == "synthetic" and view["context_only"] is True
    assert not re.search(r"\d", str({k: v for k, v in view.items() if k not in ("cohort_size", "median", "period")}))


@pytest.mark.parametrize("customer", PERSONAS)
def test_the_band_numbers_reconcile_and_open_with_method_band_size_and_period(tx, customer):
    band = run(tx, customer).data.age_band
    median = band.medians.ordinary_spending
    res = evidence.resolve(tx, median.evidence_ref, customer)
    assert res.kind == "metric" and res.method == "peer.age_band_median@1" and res.reconciles is True
    size = evidence.resolve(tx, band.cohort_size.evidence_ref, customer)
    assert size.reconciles is True
    for language, aged in (("en", "People aged "), ("fi", "-vuotiaat")):
        body = evidence_api.build(tx, res, customer, language)
        dash_band = band.band.replace("-", "–")
        assert dash_band in body.title and aged in body.title and body.title.endswith(body.number.period.label)
        assert body.method.id == "peer.age_band_median@1" and body.method.summary
        assert body.number.period.start == band.period.start and body.number.period.end == band.period.end
        assert [p.role for p in body.parts] == ["cohort_size"] and body.parts[0].number.value == band.cohort_size.value
        assert body.rows == [] and body.reconciles is True


@pytest.mark.parametrize("customer", PERSONAS)
@pytest.mark.parametrize("metric", ["Groceries", "everyday_spending", "Restaurants"])
def test_no_band_for_any_other_metric(tx, customer, metric):
    result = run(tx, customer, metric)
    assert result.data.age_band is None and "age_band" not in result.model_view


@pytest.mark.parametrize("customer", PERSONAS)
def test_the_comparison_is_the_same_with_and_without_the_band(tx, customer, monkeypatch):
    with_band = run(tx, customer)
    monkeypatch.setattr(config, "AGE_BAND_MEASURE_OF", {})
    without = run(tx, customer)
    view = {k: v for k, v in with_band.model_view.items() if k != "age_band"}
    assert view == without.model_view and with_band.card == without.card
