"""Database-backed tests for get_spender_profile and get_peer_benchmark.

Skipped without DATABASE_URL. For the three sample customers of metrics.md and the four personas of
docs/design/personas.md, both tools are compared with an independent run of the metric SQL
(05_spender_profile.sql, 06_peer_benchmark.sql) for a one-customer range, and with the worked numbers
of those documents (persona peer values: core/eval/cases.yaml of #40). Every evidence ref must resolve
and reconcile; peer evidence shows group statistics only. One customer per query, tx_date <= as_of;
each independent 06 run is made once per customer (module cache), to keep the shared database quiet.
"""

import json
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from core.tools import config, evidence, labels
from core.tools.baskets import get_basket_breakdown, months_with_history
from core.tools.classify import classify
from core.tools.context import ToolContext
from core.tools.formatting import display
from core.tools.models import Period
from core.tools.peer import get_peer_benchmark, metric_selection, peer_status
from core.tools.profile import DECIDING, get_spender_profile, profile_key
from core.tools.selection import select, value_of

AS_OF = date(2026, 9, 30)
METRICS = Path(__file__).resolve().parents[2] / "metrics"
SAMPLE = ["CUST00001", "CUST00002", "CUST00006"]
PERSONAS = ["CUST00860", "CUST00493", "CUST00349", "CUST00849"]
EVERYONE = SAMPLE + PERSONAS
D = Decimal

# metrics.md section 5 and personas.md Q2: profile, traits, keep rate, net income / month, spend / month
PROFILE_WORKED = {
    "CUST00001": ("steady", ["regular_investor"], "12.6", "2388.42", "2087.92"),
    "CUST00002": ("stretched", ["went_below_zero", "frequent_small_purchases"], "-4.5", "1628.40", "1702.17"),
    "CUST00006": ("saver", ["salary_moved_elsewhere"], "24.8", "337.13", "253.54"),
    "CUST00860": ("big_ticket", ["frequent_small_purchases"], "15.4", "3558.38", "3010.59"),
    "CUST00493": ("steady", ["frequent_small_purchases"], "17.6", "2577.84", "2124.09"),
    "CUST00349": ("everyday_heavy", ["regular_investor", "frequent_small_purchases"], "22.6", "3161.55", "2445.52"),
    "CUST00849": ("steady", ["went_below_zero", "frequent_small_purchases"], "9.4", "2075.65", "1881.06"),
}
# metrics.md section 6 (full population) and the persona cases of core/eval/cases.yaml:
# (customer, metric) -> you / month, peer median, percentile, peer group, other peers
PEER_WORKED = {
    ("CUST00001", "spend_total"): ("2087.92", "3027.77", 10, "55-64 009", 31),
    ("CUST00001", "Restaurants"): ("56.86", "188.90", 16, "55-64 009", 31),
    ("CUST00002", "spend_total"): ("1702.17", "3138.52", 4, "45-54 005", 93),
    ("CUST00002", "everyday_spending"): ("430.29", "850.10", 26, "45-54 005", 93),
    ("CUST00860", "spend_total"): ("3010.59", "2975.65", 51, "35-44 005", 118),
    ("CUST00493", "spend_total"): ("2124.09", "3567.81", 8, "45-54 001", 121),
    ("CUST00349", "spend_total"): ("2445.52", "1894.55", 67, "25-34 021", 24),
    ("CUST00849", "spend_total"): ("1881.06", "2202.21", 31, "25-34 022", 39),
}
PEER_COLUMNS = {"you": "you_month_eur", "peer_median": "peer_median_month_eur", "peer_p25": "peer_p25_month_eur",
                "peer_p75": "peer_p75_month_eur", "percentile": "percentile", "vs_median": "vs_median_pct"}


def ctx_for(conn, customer_id, language="en"):
    return ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn, language=language)


def sql_rows(conn, file_name, customer_id, settings=None):
    """Independent run of a metric file for [customer_id, next id): plain session settings."""
    values = {"demo_today": AS_OF.isoformat(), "customer_from": customer_id,
              "customer_to": f"CUST{int(customer_id[4:]) + 1:05d}", "peer_min_n": "20", **(settings or {})}
    for name, value in values.items():
        conn.execute("SELECT set_config(%s, %s, false)", (f"app.{name}", value))
    rows = []
    with conn.cursor() as cur:
        cur.execute((METRICS / file_name).read_text(encoding="utf-8"))
        for _ in cur.results():
            if cur.description:
                names = [d.name for d in cur.description]
                rows = [dict(zip(names, r)) for r in cur.fetchall()]
    conn.execute("SET statement_timeout = '60s'")
    return [r for r in rows if r["customer_id"] == customer_id]


@pytest.fixture(scope="module")
def profile_rows(conn):
    return {cid: sql_rows(conn, config.PROFILE_FILE, cid)[0] for cid in EVERYONE}


@pytest.fixture(scope="module")
def peer_rows(conn):
    return {cid: {r["metric"]: r for r in sql_rows(conn, config.PEER_FILE, cid)} for cid in EVERYONE}


def dec(number):
    return D(str(number.value))


def assert_displays_from_formatter(numbers, language="en"):
    """Every display is exactly the formatter's output for its value and unit (the answer validator's rule)."""
    numbers = [n for n in numbers if n is not None]
    assert numbers
    for n in numbers:
        assert n.display == display(D(str(n.value)), n.unit, language), (n.method, n.display)


def assert_reconciles(conn, customer_id, refs):
    assert refs
    for ref in refs:
        res = evidence.resolve(conn, ref, customer_id, limit=1)
        assert res.reconciles, f"{ref} ({res.kind} {res.method}) does not reconcile"


def assert_model_view_clean(view, customer_id):
    text = json.dumps(view, default=str)
    assert customer_id not in text
    assert "MRC-" not in text            # no merchant ids (R3)
    assert "ev_" not in text             # no evidence refs in the model view
    assert "Health" not in text          # nothing health-related is singled out (R9)


# ---- get_spender_profile -------------------------------------------------------------------------------

@pytest.mark.parametrize("customer_id", EVERYONE)
def test_profile_equals_05_and_the_worked_numbers(conn, profile_rows, customer_id):
    result = get_spender_profile(ctx_for(conn, customer_id))
    data = result.data
    row = profile_rows[customer_id]

    features = {f.key: f for f in data.features}
    for key, column, unit in config.PROFILE_FEATURES:
        if row[column] is None:
            assert key not in features, key
            continue
        number = features[key].value
        assert dec(number) == row[column], key
        assert number.unit.value == unit and number.method == f"spender_profile.{column}@1", key
        assert (number.period.start, number.period.end) == (row["period_start"], row["period_end"])
    assert data.profile.key == row["profile"]
    assert [t.key for t in data.traits] == [t for t in config.PROFILE_TRAITS if t in row["traits"]]
    assert data.n_months == row["n_months"]
    assert (data.top_everyday_category.key if data.top_everyday_category else None) == row["top_everyday_category"]

    # the Python rule agrees with 05 on these customers, and marks the features that decided the label
    assert profile_key(row["keep_rate_pct"], row["one_off_share_pct"], row["everyday_share_pct"]) == row["profile"]
    assert [f.key for f in data.features if f.decides_label] == list(DECIDING[row["profile"]])
    # traits follow their features
    traits = {t.key for t in data.traits}
    assert ("went_below_zero" in traits) == (row["n_tx_below_zero"] > 0)
    assert ("regular_investor" in traits) == (row["saving_month_eur"] > 0)

    key, trait_keys, keep, net_income, spend = PROFILE_WORKED[customer_id]
    assert (data.profile.key, sorted(t.key for t in data.traits)) == (key, sorted(trait_keys))
    assert [dec(features["keep_rate"].value), dec(features["net_income"].value), dec(features["spend"].value)] == \
        [D(keep), D(net_income), D(spend)]


def test_profile_feature_details_of_cust00002(conn):
    features = {f.key: f.value for f in get_spender_profile(ctx_for(conn, "CUST00002")).data.features}
    assert features["n_tx_below_zero"].value == 11                       # metrics.md section 5
    assert features["everyday_tx_month"].value == 13.3                   # a rate keeps its decimal
    assert features["everyday_share_pct"].value == 25.3
    assert_displays_from_formatter(features.values())                    # "13" for 13.3: the count formatter


@pytest.mark.parametrize("customer_id", ["CUST00001", "CUST00860"])
def test_profile_spending_is_the_same_number_as_the_basket_card(conn, customer_id):
    ctx = ctx_for(conn, customer_id)
    spend = next(f.value for f in get_spender_profile(ctx).data.features if f.key == "spend")
    total = get_basket_breakdown(ctx, {"period": {"preset": "last_6_months"}}).data.total
    assert spend.evidence_ref == total.evidence_ref and spend.value == total.value


@pytest.mark.parametrize("customer_id", ["CUST00860"])   # lead persona; each metric ref re-runs 05
def test_profile_evidence_card_and_model_view(conn, customer_id):
    result = get_spender_profile(ctx_for(conn, customer_id))
    assert_reconciles(conn, customer_id, result.evidence)
    card = result.card
    assert card.type == "profile" and card.estimate is None
    assert card.profile["key"] == result.data.profile.key
    deciding = [f for f in card.features if f["decides_label"]]
    assert deciding and card.evidence_ref == deciding[0]["value"]["evidence_ref"]
    assert {f["key"] for f in card.features} >= {"keep_rate", "everyday_share_pct", "one_off_share"}
    assert_model_view_clean(result.model_view, customer_id)
    assert "Health" not in json.dumps(card.model_dump(), default=str)


def test_profile_in_finnish(conn):
    result = get_spender_profile(ctx_for(conn, "CUST00860", "fi"))
    assert result.data.profile.label == "Isot hankinnat"
    keep = next(f.value for f in result.data.features if f.key == "keep_rate")
    assert keep.display == "15,4 %"
    assert_displays_from_formatter([f.value for f in result.data.features], "fi")


# ---- get_peer_benchmark ----------------------------------------------------------------------------------

@pytest.mark.parametrize("customer_id, metric", sorted(PEER_WORKED))
def test_peer_benchmark_equals_06_and_the_worked_numbers(conn, peer_rows, customer_id, metric):
    result = get_peer_benchmark(ctx_for(conn, customer_id), {"metric": metric})
    data = result.data
    row = peer_rows[customer_id][metric]

    assert data.shown is True and row["shown"] is True and data.reason is None
    for key, column in PEER_COLUMNS.items():
        assert dec(getattr(data, key)) == row[column], key
        assert getattr(data, key).method == f"peer_benchmark.{column}@1"
    assert data.peer_group.size.value == row["peer_n"]
    assert (data.peer_group.level, data.peer_source) == (row["peer_level"], row["peer_source"]) == \
        ("age_band+area3", "marts")
    assert (data.period.start, data.period.end) == (row["period_start"], row["period_end"])

    you, median, percentile, group, n = PEER_WORKED[(customer_id, metric)]
    assert (dec(data.you), dec(data.peer_median), data.percentile.value) == (D(you), D(median), percentile)
    assert (row["peer_group"], data.peer_group.size.value) == (group, n)


@pytest.mark.parametrize("customer_id", EVERYONE)
def test_own_value_of_every_metric_equals_06(conn, peer_rows, customer_id):
    # `you` is computed from the customer's rows (its evidence lists them); it must equal 06 for all 13
    # metrics, not only the ones the tool is called with above. No extra 06 run: the module cache is reused.
    ctx = ctx_for(conn, customer_id)
    history = ctx.history()
    rows = classify(history, AS_OF, labels.basket_labels(conn, customer_id, AS_OF))
    assert set(peer_rows[customer_id]) == set(config.PEER_METRICS)
    for metric, row in peer_rows[customer_id].items():
        period = Period(start=row["period_start"], end=row["period_end"], label="")
        n_months = months_with_history(period.start, period.end, history[0].tx_date)
        sel = metric_selection(metric, period)
        value = value_of(select(rows, sel), sel, config.METHODS["peer_you"], {"n_months": n_months})
        assert value == row["you_month_eur"], metric


@pytest.mark.parametrize("customer_id", PERSONAS)
def test_persona_group_sizes_match_personas_yaml(conn, peer_rows, customer_id):
    # personas.yaml peer_group.comparable_others: the same count for every metric of the customer
    expected = {"CUST00860": 118, "CUST00493": 121, "CUST00349": 24, "CUST00849": 39}[customer_id]
    assert {r["peer_n"] for r in peer_rows[customer_id].values()} == {expected}
    assert {r["peer_level"] for r in peer_rows[customer_id].values()} == {"age_band+area3"}


def test_sweep_customer_is_not_compared(conn, peer_rows):
    result = get_peer_benchmark(ctx_for(conn, "CUST00006"), {"metric": "spend_total"})
    data = result.data
    row = peer_rows["CUST00006"]["spend_total"]
    assert (row["shown"], row["comparable"], row["peer_group"], row["peer_n"]) == (False, False, "35-44 007", 132)
    assert (data.shown, data.reason, data.peer_group.comparable) == (False, "not_comparable", False)
    assert result.card is None and data.peer_group.size is None
    assert all(getattr(data, k) is None for k in ("peer_median", "peer_p25", "peer_p75", "percentile", "vs_median"))
    assert dec(data.you) == row["you_month_eur"] == D("253.54")
    assert result.evidence == [data.you.evidence_ref]          # no group statistic is written
    assert result.notes and "another account" in result.notes[0]
    assert_model_view_clean(result.model_view, "CUST00006")


def test_group_below_the_minimum_is_not_shown(conn, monkeypatch):
    # With an unreachable minimum no level qualifies: 06 takes the coarsest level and shows nothing.
    monkeypatch.setattr(config, "PEER_MIN_N", "100000")
    result = get_peer_benchmark(ctx_for(conn, "CUST00349"), {"metric": "Restaurants"})
    row = sql_rows(conn, config.PEER_FILE, "CUST00349", {"peer_min_n": "100000"})
    row = next(r for r in row if r["metric"] == "Restaurants")
    assert row["shown"] is False and row["peer_median_month_eur"] is None and row["peer_level"] == "age_band"
    data = result.data
    assert (data.shown, data.reason, data.peer_group.level) == (False, "group_too_small", "age_band")
    assert peer_status(True, row["peer_n"], 100000) == (False, "group_too_small")
    assert result.card is None and data.peer_median is None and data.peer_group.size is None
    assert dec(data.you) == row["you_month_eur"]


@pytest.mark.parametrize("customer_id", ["CUST00860"])   # lead persona; each peer ref re-runs 06
def test_peer_evidence_is_group_statistics_only(conn, customer_id):
    result = get_peer_benchmark(ctx_for(conn, customer_id), {"metric": "spend_total"})
    assert len(result.evidence) == 7                                   # you + six group statistics
    for ref in result.evidence:                                        # each ref resolved once (06 per call)
        res = evidence.resolve(conn, ref, customer_id, limit=5)
        assert res.reconciles, f"{ref} ({res.kind} {res.method}) does not reconcile"
        if ref == result.data.you.evidence_ref:
            assert res.kind == "transactions" and res.row_count > 0    # the customer's own rows
            continue
        assert res.kind == "peer_aggregate" and res.rows == [] and res.row_count is None
        assert {p["role"] for p in res.parts} == {"peer_median", "peer_p25", "peer_p75", "peer_n", "peer_level"}
        text = json.dumps(res.parts)
        assert "CUST" not in text and "tx_" not in text                # never another customer's rows
    with pytest.raises(evidence.EvidenceForbidden):
        evidence.resolve(conn, result.data.peer_median.evidence_ref, "CUST00002")


def test_peer_card_and_model_view(conn):
    result = get_peer_benchmark(ctx_for(conn, "CUST00860"), {"metric": "spend_total"})
    card = result.card
    assert card.type == "peer" and card.estimate["label"] == "Estimate"
    assert card.estimate["text"].startswith("Compared with at least 20 other customers")
    assert card.percentile["value"] == 51 and card.percentile["display"] == "51.0%"
    assert card.peer_group["label"] == "Age 35-44, postal area 005" and card.peer_group["size"]["value"] == 118
    assert card.evidence_ref == result.data.peer_median.evidence_ref
    assert card.you["display"] == "€3,010.59 a month"
    d = result.data
    assert_displays_from_formatter([d.you, d.peer_median, d.peer_p25, d.peer_p75, d.percentile, d.vs_median,
                                    d.peer_group.size])
    assert_model_view_clean(result.model_view, "CUST00860")


def test_peer_in_finnish(conn):
    result = get_peer_benchmark(ctx_for(conn, "CUST00860", "fi"), {"metric": "spend_total"})
    assert result.data.percentile.display == "51,0 %"
    assert result.card.peer_group["label"] == "Ikä 35-44, postinumeroalue 005"
    d = result.data
    assert_displays_from_formatter([d.you, d.peer_median, d.percentile, d.vs_median], "fi")


def test_negative_difference_shows_its_minus(conn, peer_rows):
    # CUST00001 spends less than the group: the display carries the formatter's minus sign
    row = peer_rows["CUST00001"]["spend_total"]
    assert row["vs_median_pct"] < 0
    vs = get_peer_benchmark(ctx_for(conn, "CUST00001"), {"metric": "spend_total"}).data.vs_median
    assert vs.value < 0 and vs.display.startswith("-") and vs.display == display(row["vs_median_pct"], vs.unit)


# ---- timing (one call of each tool for one customer) ------------------------------------------------

def test_one_call_of_each_tool_is_fast_enough(conn):
    ctx = ctx_for(conn, "CUST00860")
    t0 = time.perf_counter()
    get_spender_profile(ctx)
    t1 = time.perf_counter()
    get_peer_benchmark(ctx, {"metric": "spend_total"})
    t2 = time.perf_counter()
    print(f"get_spender_profile {1000 * (t1 - t0):.0f} ms, get_peer_benchmark {1000 * (t2 - t1):.0f} ms")
    # Idle: about 0.4 s and 0.7 s. Under load the shared database is 10-20x slower, so the bound is the
    # statement timeout; the printed times are what the PR reports.
    assert t1 - t0 < 60 and t2 - t1 < 60
