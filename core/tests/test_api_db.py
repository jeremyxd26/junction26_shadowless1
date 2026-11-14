"""API endpoints on the shared database. Skipped when DATABASE_URL is not set.

One module-scoped client (its pool holds at most 2 connections). Reads are one customer at a time;
the only writes are evidence specs in coach_evidence.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from core.app.main import create_app
from core.app.settings import Settings
from core.tools import config
from core.tools import db as tools_db
from core.tools.baskets import get_basket_breakdown
from core.tools.bills import get_recurring_bills
from core.tools.context import ToolContext
from core.tools.formatting import display
from core.tools.models import Unit
from core.tools.safe_to_spend import get_safe_to_spend

LEAD = "CUST00860"


@pytest.fixture(scope="module")
def client():
    url = Settings().database_url
    if url is None:
        pytest.skip("DATABASE_URL is not set")
    with TestClient(create_app(Settings(_env_file=None, database_url=url.get_secret_value()))) as c:
        yield c


@pytest.fixture(scope="module")
def lead_overview(client):
    response = client.get(f"/api/overview/{LEAD}")
    assert response.status_code == 200, response.text
    return response.json()


def numbers_in(obj, path="$"):
    """Every Number object (a dict with method and evidence_ref) in a response, with its path."""
    if isinstance(obj, dict):
        if {"method", "evidence_ref", "value", "unit"} <= set(obj):
            yield path, obj
        for k, v in obj.items():
            yield from numbers_in(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from numbers_in(v, f"{path}[{i}]")


def test_lead_overview_matches_the_reference_answers(lead_overview):
    """docs/design/personas.md section 4 (Q1 baskets, profile spend per month) and the housing series."""
    o = lead_overview
    assert (o["customer_id"], o["as_of"], o["greeting"]) == (LEAD, "2026-09-30", "Hi Sanna")
    assert o["reviews"] == []
    # Q3: safe to spend in the next 7 days, 2026-10-01 .. 2026-10-07, budget limit binding (after the goal)
    hero = o["hero"]
    assert (hero["type"], hero["status"], hero["primary"]["value"], hero["primary"]["unit"]) == (
        "metric", "below_usual", 97.46, "eur")   # #391: after the savings goal, under the usual 137.80
    assert (hero["primary"]["period"]["start"], hero["primary"]["period"]["end"]) == ("2026-10-01", "2026-10-07")
    assert [c["key"] for c in hero["components"]] == [
        "balance", "bills_due", "essentials_reserve", "irregular_reserve", "cushion"]
    assert all(c["amount"]["evidence_ref"] for c in hero["components"]) and hero["estimate"]["text"]
    baskets, bills = o["cards"]
    assert (baskets["type"], bills["type"]) == ("breakdown", "bills")
    got = {i["key"]: (i["amount"]["value"], i["share"]["value"]) for i in baskets["items"]}
    assert got == {"regular_essentials": (1889.04, 62.7), "unexpected_necessities": (521.15, 17.3),
                   "everyday_spending": (600.41, 19.9)}
    assert baskets["total"]["value"] == 3010.59 and baskets["total"]["unit"] == "eur_per_month"
    housing = next(i for i in bills["items"] if i["bill_id"] == "bill_housing_payment")
    assert (housing["typical_month"]["value"], housing["status"]) == (836.65, "done_this_month")
    # metrics wins: the total is 03's rounded sum; the items are rounded each (0.01 apart at most each)
    items = sum(i["due_until_payday"]["value"] for i in bills["items"])
    assert abs(items - bills["total"]["value"]) <= 0.01 * len(bills["items"]) + 1e-9


def test_overview_equals_the_tool_outputs(lead_overview):
    conn = tools_db.connect()
    try:
        ctx = ToolContext(customer_id=LEAD, as_of=date(2026, 9, 30), conn=conn)
        b = get_basket_breakdown(ctx, {"period": {"preset": "last_6_months"}}).card.model_dump(mode="json")
        r = get_recurring_bills(ctx, {"include_income": False}).card.model_dump(mode="json")
        s = get_safe_to_spend(ctx, {}).card.model_dump(mode="json")
    finally:
        conn.close()
    hero = lead_overview["hero"]
    assert (hero["primary"]["evidence_ref"], hero["primary"]["value"]) == (s["primary"]["evidence_ref"],
                                                                           s["primary"]["value"])
    assert [(c["key"], c["amount"]["evidence_ref"], c["amount"]["value"]) for c in hero["components"]] == [
        (c["key"], c["amount"]["evidence_ref"], c["amount"]["value"]) for c in s["components"]]
    # one value and one ref for the bills due before payday, in the hero and on the bills card
    bills_due = next(c["amount"] for c in hero["components"] if c["key"] == "bills_due")
    assert bills_due["evidence_ref"] == lead_overview["cards"][1]["total"]["evidence_ref"]
    baskets, bills = lead_overview["cards"]
    assert [(i["key"], i["amount"]["evidence_ref"], i["amount"]["value"]) for i in baskets["items"]] == [
        (i["key"], i["amount"]["evidence_ref"], i["amount"]["value"]) for i in b["items"]]
    assert baskets["total"]["evidence_ref"] == b["total"]["evidence_ref"]
    assert [(i["bill_id"], i["due_until_payday"]["evidence_ref"], i["due_until_payday"]["value"]) for i in bills["items"]] == [
        (i["bill_id"], i["due_until_payday"]["evidence_ref"], i["due_until_payday"]["value"]) for i in r["items"]]
    assert bills["total"]["evidence_ref"] == r["total"]["evidence_ref"]


def test_every_number_of_the_overview_opens_as_evidence(client, lead_overview):
    seen = 0
    for path, number in numbers_in(lead_overview):
        response = client.get(f"/api/evidence/{number['evidence_ref']}", params={"customer_id": LEAD, "limit": 200})
        assert response.status_code == 200, (path, response.text)
        e = response.json()
        n = e["number"]
        assert (n["value"], n["unit"], n["method"], n["evidence_ref"]) == (
            number["value"], number["unit"], number["method"], number["evidence_ref"]), path
        assert (n["period"]["start"], n["period"]["end"]) == (number["period"]["start"], number["period"]["end"]), path
        assert_opens_like(e, path)
        seen += 1
    assert seen >= 27  # baskets, bills, the hero with its components, and the safe_to_save card


def assert_opens_like(e, path):
    """The fields each evidence kind fills (contracts/api.md section 9)."""
    if e["kind"] == "transactions":
        assert e["reconciles"] is True and e["row_count"]["value"] == len(e["rows"]) or e["next_cursor"], path
        assert e["parts"] == [] and e["query"] is not None
    elif e["kind"] == "composite":
        assert (e["rows"], e["row_count"], e["reconciles"], e["query"]) == ([], None, None, None), path
        assert e["parts"]
    else:  # metric: re-run from its SQL file for this customer
        assert e["kind"] == "metric" and e["reconciles"] is True, path
        assert (e["row_count"], e["query"], e["parts"]) == (None, None, []), path


def opens_with_the_same_number(client, number, path):
    response = client.get(f"/api/evidence/{number['evidence_ref']}", params={"customer_id": LEAD, "limit": 200})
    assert response.status_code == 200, (path, response.text)
    e = response.json()
    n = e["number"]
    assert (n["value"], n["unit"], n["method"], n["evidence_ref"]) == (
        number["value"], number["unit"], number["method"], number["evidence_ref"]), path
    assert (n["period"]["start"], n["period"]["end"]) == (number["period"]["start"], number["period"]["end"]), path
    assert_opens_like(e, path)


def test_evidence_rows_paginate_and_the_row_count_opens(client, lead_overview):
    ref = lead_overview["cards"][0]["items"][0]["amount"]["evidence_ref"]  # regular essentials, many rows
    first = client.get(f"/api/evidence/{ref}", params={"customer_id": LEAD, "limit": 20}).json()
    rows, cursor = list(first["rows"]), first["next_cursor"]
    while cursor:
        page = client.get(f"/api/evidence/{ref}", params={"customer_id": LEAD, "limit": 20, "cursor": cursor}).json()
        rows += page["rows"]
        cursor = page["next_cursor"]
    assert len(rows) == first["row_count"]["value"] > 20
    assert len({r["tx_id"] for r in rows}) == len(rows)
    # #79: each row's amount also comes formatted, like a Number's display (bank sign kept)
    assert all(r["display"] == display(Decimal(r["amount"]), Unit.EUR, "en") for r in rows)
    assert rows[0]["amount"].startswith("-") and rows[0]["display"].startswith("-€")
    assert all(r["merchant"] is None or not any(ch.isdigit() for ch in r["merchant"]["label"]) for r in rows)
    count = client.get(f"/api/evidence/{first['row_count']['evidence_ref']}", params={"customer_id": LEAD}).json()
    assert count["number"]["value"] == first["row_count"]["value"] and count["reconciles"] is True


def test_refs_of_another_customer_and_unknown_ids_are_refused(client, lead_overview):
    ref = lead_overview["cards"][0]["total"]["evidence_ref"]
    foreign = client.get(f"/api/evidence/{ref}", params={"customer_id": "CUST00493"})
    assert foreign.status_code == 403 and foreign.json()["error"]["code"] == "evidence_forbidden"
    unknown = client.get("/api/evidence/ev_000000000000", params={"customer_id": LEAD})
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "evidence_not_found"
    for path, params in ((f"/api/evidence/{ref}", {"customer_id": "CUST99999"}), ("/api/overview/CUST99999", {})):
        response = client.get(path, params=params)
        assert response.status_code == 404 and response.json()["error"]["code"] == "customer_not_found"


def test_a_metric_kind_ref_opens_as_evidence(client):
    """#55 stores numbers re-run from metric SQL files (kind "metric"); they must open, not fail."""
    from core.tools import evidence

    spec = {"v": 1, "kind": "metric", "customer_id": LEAD, "as_of": "2026-09-30",
            "method": "safe_to_spend.safe_to_spend_7d_eur@1",
            "source": {"file": "03_safe_to_spend.sql", "column": "safe_to_spend_7d_eur", "settings": {}},
            "value": "97.46"}   # #391: after the savings goal
    ref = evidence.make_ref(spec)
    conn = tools_db.connect()
    try:
        evidence.write(conn, {ref: spec})
    finally:
        conn.close()
    response = client.get(f"/api/evidence/{ref}", params={"customer_id": LEAD})
    assert response.status_code == 200, response.text
    e = response.json()
    assert (e["kind"], e["number"]["value"], e["number"]["unit"], e["number"]["label"]) == (
        "metric", 97.46, "eur", "Safe to spend")
    assert e["method"]["doc"].endswith("metrics.md#3-safe-to-spend")
    assert (e["query"], e["row_count"], e["parts"]) == (None, None, [])
    assert e["reconciles"] is True  # the #55 resolver re-runs 03_safe_to_spend.sql for this customer


# No database test for peer_aggregate evidence here: it would have to store a synthetic spec in the
# shared coach_evidence (review of #106). The mapping is tested without a database on the resolver's
# exact shape (test_api_endpoints.py); a database test follows with #95's real peer specs.


def test_finnish_overview_has_the_same_numbers(client, lead_overview):
    fi = client.get(f"/api/overview/{LEAD}", params={"lang": "fi"}).json()
    assert fi["greeting"] == "Hei Sanna" and fi["language"] == "fi"
    refs = lambda o: [(p, n["evidence_ref"], n["value"]) for p, n in numbers_in(o)]  # noqa: E731
    assert refs(fi) == refs(lead_overview)
    assert fi["cards"][0]["items"][0]["amount"]["display"] == "1 889,04 € / kk"


# ---- the safe_to_save card (#165) -----------------------------------------------------------------

def save_values(card: dict) -> dict:
    return {
        "monthly": card["monthly"]["value"],
        "monthly_components": [(c["key"], c["operation"], c["amount"]["value"]) for c in card["monthly_components"]],
        "stock": card["stock"]["value"],
        "stock_components": [(c["key"], c["operation"], c["amount"]["value"]) for c in card["stock_components"]],
        "reason": card["reason"],
    }


def test_sannas_safe_to_save_equals_the_contract_example(lead_overview):
    """contracts/api.md `card.safe_to_save` (no review answered): 184.61 a month, 12,272.28 in stock."""
    card = lead_overview["safe_to_save"]
    assert card["type"] == "safe_to_save"
    assert save_values(card) == {
        "monthly": 184.61,
        "monthly_components": [("free_month", "add", 783.79), ("everyday_month", "subtract", 599.18)],
        "stock": 12272.28,
        "stock_components": [("free_until_payday", "add", 12567.56), ("everyday_until_payday", "subtract", 295.28)],
        "reason": None,
    }
    # the hero's "free until payday" and the card's are one number with one ref
    hero_free = lead_overview["hero"]["secondary"][0]
    card_free = card["stock_components"][0]["amount"]
    assert (hero_free["method"], hero_free["evidence_ref"], hero_free["value"]) == (
        card_free["method"], card_free["evidence_ref"], card_free["value"])


def test_aleksis_safe_to_save_equals_the_contract_example(client):   # client: skipped without a database
    """contracts/api.md `card.safe_to_save_aleksi` (persona CUST00849)."""
    from core.tools.safe_to_save import get_safe_to_save

    conn = tools_db.connect()
    try:
        card = get_safe_to_save(ToolContext(customer_id="CUST00849", as_of=date(2026, 9, 30), conn=conn), {})
    finally:
        conn.close()
    assert save_values(card.card.model_dump(mode="json")) == {
        "monthly": 199.95,
        "monthly_components": [("free_month", "add", 725.47), ("everyday_month", "subtract", 525.52)],
        "stock": 560.64,
        "stock_components": [("free_until_payday", "add", 819.62), ("everyday_until_payday", "subtract", 258.98)],
        "reason": None,
    }


def test_the_overview_runs_the_metric_file_once(client, monkeypatch):
    """The hero and the safe_to_save card read the same row of 03_safe_to_spend.sql."""
    from core.tools import metric_sql

    runs = []
    real = metric_sql.run_one

    def counting(conn, file, *args, **kwargs):
        runs.append(file)
        return real(conn, file, *args, **kwargs)

    monkeypatch.setattr(metric_sql, "run_one", counting)
    response = client.get(f"/api/overview/{LEAD}")
    assert response.status_code == 200 and response.json()["safe_to_save"] is not None
    assert response.json()["hero"] is not None
    assert runs == [config.SAFE_TO_SPEND_FILE]


# ---- POST /api/whatif ----------------------------------------------------------------------------

def post_whatif(client, kind, value, cut_pct=20, language="en"):
    return client.post("/api/whatif", json={"customer_id": LEAD, "language": language,
                                            "scenario": {"selection": {"kind": kind, "value": value},
                                                         "cut_pct": cut_pct}})


def test_dining_out_what_if_matches_the_reference_and_every_number_opens(client):
    """docs/design/personas.md Q4: Restaurants cut by 20% (04_what_if.sql)."""
    response = post_whatif(client, "category", "Restaurants")
    assert response.status_code == 200, response.text
    w = response.json()
    assert (w["customer_id"], w["as_of"], w["status"]) == (LEAD, "2026-09-30", "estimate")
    got = {k: w[k]["value"] for k in ("baseline_per_month", "saving_per_month", "saving_per_week",
                                      "saving_per_year", "one_off_excluded", "regular_excluded")}
    assert got == {"baseline_per_month": 229.56, "saving_per_month": 45.91, "saving_per_week": 10.56,
                   "saving_per_year": 550.95, "one_off_excluded": 0, "regular_excluded": 0}
    assert (w["baseline_per_month"]["period"]["start"], w["baseline_per_month"]["period"]["end"]) == (
        "2026-04-01", "2026-09-30")
    assert w["scenario"]["selection"] == {"kind": "category", "value": "Restaurants"}
    assert (w["scenario"]["cut_pct"]["value"], w["scenario"]["cut_pct"]["evidence_ref"]) == (20, None)
    assert w["evidence_ref"] == w["saving_per_month"]["evidence_ref"] and w["estimate"]["text"]
    opened = set()
    for path, number in numbers_in(w):
        if number["evidence_ref"] is None:  # the cut the user chose: user_input@1, no evidence
            continue
        opens_with_the_same_number(client, number, path)
        opened.add(number["evidence_ref"])
    # six numbers; the baseline opens a second time from `estimate.observed` (#380), with the same ref
    assert len(opened) == 6 and w["estimate"]["observed"][0]["evidence_ref"] == w["baseline_per_month"]["evidence_ref"]


def test_finnish_what_if_has_the_same_numbers(client):
    en = post_whatif(client, "category", "Restaurants").json()
    fi = post_whatif(client, "category", "Restaurants", language="fi").json()
    assert fi["language"] == "fi" and fi["saving_per_month"]["display"] == "45,91 € / kk"
    assert [(p, n["evidence_ref"], n["value"]) for p, n in numbers_in(fi)] == [
        (p, n["evidence_ref"], n["value"]) for p, n in numbers_in(en)]


def test_groceries_are_not_offered(client):
    w = post_whatif(client, "category", "Groceries").json()
    assert w["status"] == "not_offered" and w["saving_per_month"]["value"] == 0
    assert w["regular_excluded"]["value"] > 0 and len(w["caveats"]) == 2


def test_unexpected_necessities_are_an_estimate_with_a_caveat(client):
    """The basket unexpected_necessities stays allowed (coordinator decision): its baseline leaves out
    Sanna's Home & Tech one-off of 1,080.42 (docs/design/personas.md)."""
    response = post_whatif(client, "basket", "unexpected_necessities")
    assert response.status_code == 200, response.text
    w = response.json()
    assert w["status"] == "estimate_with_caveat" and len(w["caveats"]) == 2
    assert (w["baseline_per_month"]["value"], w["one_off_excluded"]["value"]) == (341.08, 1080.42)
    assert w["saving_per_month"]["value"] > 0


def test_a_merchant_id_from_a_card_is_accepted(client, lead_overview):
    everyday = next(i for i in lead_overview["cards"][0]["items"] if i["key"] == "everyday_spending")
    rows = client.get(f"/api/evidence/{everyday['amount']['evidence_ref']}",
                      params={"customer_id": LEAD, "limit": 200}).json()["rows"]
    merchant_id = next(r["merchant"]["id"] for r in rows if r["category"] == "Restaurants" and r["merchant"])
    response = post_whatif(client, "merchant", merchant_id, cut_pct=50)
    assert response.status_code == 200, response.text
    w = response.json()
    assert w["scenario"]["selection"] == {"kind": "merchant", "value": merchant_id}
    assert w["status"] == "estimate" and w["saving_per_month"]["value"] > 0
    assert merchant_id not in w["scenario"]["label"]  # the label names the alias, not the id


def test_refused_selections_are_422(client):
    conn = tools_db.connect()
    try:
        history = ToolContext(customer_id=LEAD, as_of=date(2026, 9, 30), conn=conn).history()
    finally:
        conn.close()
    spent = {t.category for t in history if date(2026, 4, 1) <= t.tx_date <= date(2026, 9, 30)}
    for kind, value in [("category", "Health"), ("merchant", "MRC-XXX-9999"),
                        *[("category", c) for c in sorted(config.WHAT_IF_CATEGORIES - spent)][:1]]:
        response = post_whatif(client, kind, value)
        assert response.status_code == 422 and response.json()["error"]["code"] == "invalid_scenario", (kind, value)
    unknown = client.post("/api/whatif", json={"customer_id": "CUST99999", "scenario": {
        "selection": {"kind": "category", "value": "Restaurants"}, "cut_pct": 20}})
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "customer_not_found"
