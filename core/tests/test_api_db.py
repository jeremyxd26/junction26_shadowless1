"""API endpoints on the shared database. Skipped when DATABASE_URL is not set.

One module-scoped client (its pool holds at most 2 connections). Reads are one customer at a time;
the only writes are evidence specs in coach_evidence.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from core.app.main import create_app
from core.app.settings import Settings
from core.tools import db as tools_db
from core.tools.baskets import get_basket_breakdown
from core.tools.bills import get_recurring_bills
from core.tools.context import ToolContext

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
    assert (o["customer_id"], o["as_of"], o["greeting"], o["hero"]) == (LEAD, "2026-09-30", "Hi Sanna", None)
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
    finally:
        conn.close()
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
        if e["kind"] == "transactions":
            assert e["reconciles"] is True and e["row_count"]["value"] == len(e["rows"]) or e["next_cursor"], path
            assert e["parts"] == [] and e["query"] is not None
        else:
            assert (e["rows"], e["row_count"], e["reconciles"], e["query"]) == ([], None, None, None), path
            assert e["parts"]
        seen += 1
    assert seen >= 10


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


def test_finnish_overview_has_the_same_numbers(client, lead_overview):
    fi = client.get(f"/api/overview/{LEAD}", params={"lang": "fi"}).json()
    assert fi["greeting"] == "Hei Sanna" and fi["language"] == "fi"
    refs = lambda o: [(p, n["evidence_ref"], n["value"]) for p, n in numbers_in(o)]  # noqa: E731
    assert refs(fi) == refs(lead_overview)
    assert fi["cards"][0]["items"][0]["amount"]["display"] == "1 889,04 € / kk"
