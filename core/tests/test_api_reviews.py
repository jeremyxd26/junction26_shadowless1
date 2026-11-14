"""The spike review through the API (#68): GET /api/overview serves it, POST /api/baskets/label answers it.

The database tests are skipped without DATABASE_URL. They never commit anything: the app's pool is
replaced by a stub that hands out one connection inside a transaction that is rolled back
(force_rollback), and Sanna's review rows are deleted inside it first, so the dev demo state neither
affects the test nor is changed by it. SPIKE_REVIEWS is switched on for these tests only.
"""

from __future__ import annotations

from contextlib import contextmanager

import psycopg
import pytest
from fastapi.testclient import TestClient

from core.app.api.schemas import ErrorResponse, LabelResponse, OverviewResponse
from core.app.main import create_app
from core.app.settings import Settings
from core.tools import reviews

LEAD = "CUST00860"
SPIKE = 606016


def no_db_client() -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, database_url=None)), raise_server_exceptions=False)


def body(tx_ref="txr_0000000000000000", basket="unexpected_necessities", **kw):
    return {"customer_id": LEAD, "tx_ref": tx_ref, "basket": basket, "language": "en", **kw}


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    assert ErrorResponse.model_validate(response.json()).error.code == code


# ---- without a database: validation ------------------------------------------------------------------

@pytest.mark.parametrize("payload", [
    body(basket="groceries"),                                   # not a basket key
    body(basket="unclassified"),                                # a state, never an answer option
    {k: v for k, v in body().items() if k != "basket"},          # basket is required (null undoes)
    body(customer_id="customer-1"),
    body(language="sv"),
    body(tx_ref="x" * 65),
    body(state="answered"),                                     # an unknown field
])
def test_malformed_label_requests_are_400(payload):
    with no_db_client() as client:
        assert_error(client.post("/api/baskets/label", json=payload), 400, "invalid_request")


def test_label_without_a_database_is_503():
    with no_db_client() as client:
        assert_error(client.post("/api/baskets/label", json=body()), 503, "data_unavailable")


# ---- with the database, rolled back --------------------------------------------------------------------

class StubPool:
    """Hands out the test's connection, which is inside a rolled-back transaction."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    @contextmanager
    def connection(self, timeout: float | None = None):
        yield self.conn

    def close(self) -> None:
        pass


@pytest.fixture(scope="module")
def db_conn():
    url = Settings().database_url
    if url is None:
        pytest.skip("DATABASE_URL is not set")
    conn = psycopg.connect(url.get_secret_value(), autocommit=True, application_name="core-tests-reviews")
    conn.execute("SET statement_timeout = '60s'")
    yield conn
    conn.close()


@pytest.fixture
def client(db_conn, monkeypatch):
    monkeypatch.setenv("SPIKE_REVIEWS", "on")
    with db_conn.transaction(force_rollback=True):
        reviews.private_tables(db_conn)  # no lock on the shared tables
        app = create_app(Settings(_env_file=None, database_url=None))
        # https, so the client sends the Secure viewer cookie back (#144)
        with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as c:
            app.state.pool = StubPool(db_conn)
            yield c


def overview(client) -> dict:
    response = client.get(f"/api/overview/{LEAD}")
    assert response.status_code == 200, response.text
    OverviewResponse.model_validate(response.json())
    return response.json()


def items(o: dict) -> dict[str, float]:
    return {i["key"]: i["amount"]["value"] for i in o["cards"][0]["items"]}


def label(client, tx_ref, basket, language="en"):
    response = client.post("/api/baskets/label", json=body(tx_ref, basket, language=language))
    assert response.status_code == 200, response.text
    return LabelResponse.model_validate(response.json()).model_dump(mode="json")


def moved_refs(body: dict) -> dict[str, str]:
    return {c["key"]: c["after"]["evidence_ref"] for c in body["changes"]}


def test_demo_path_overview_needed_overview_undo(client):
    first = overview(client)
    assert len(first["reviews"]) == 1
    card = first["reviews"][0]
    assert (card["type"], card["amount"]["value"], card["current_basket"]["key"]) == ("review", 1080.42,
                                                                                      "unclassified")
    assert str(SPIKE) not in str(card)                                       # no transaction id, no merchant id
    assert items(first) == {"regular_essentials": 1889.04, "unexpected_necessities": 341.08,
                            "everyday_spending": 600.41, "unclassified": 180.07}
    assert first["hero"]["primary"]["value"] == 221.58                      # the hero sees the pending state
    assert overview(client)["reviews"][0]["tx_ref"] == card["tx_ref"]       # served again, never created twice

    needed = label(client, card["tx_ref"], "unexpected_necessities")
    assert (needed["review_state"], needed["changed"]) == ("answered", True)
    moved = {c["key"]: (c["before"]["value"], c["after"]["value"]) for c in needed["changes"]}
    assert moved["safe_to_spend"] == (221.58, 180.26)
    assert moved["irregular_reserve"] == (167.74, 256.3)
    assert needed["refetch"] == [f"/api/overview/{LEAD}"]

    after = overview(client)
    assert after["reviews"] == []                                            # Sanna has no other spike
    assert items(after) == {"regular_essentials": 1889.04, "unexpected_necessities": 521.15,
                            "everyday_spending": 600.41}                     # the published numbers
    assert after["hero"]["primary"]["value"] == 180.26
    assert after["hero"]["primary"]["evidence_ref"] == moved_refs(needed)["safe_to_spend"]  # the same Number

    undone = label(client, card["tx_ref"], None)
    assert (undone["review_state"], undone["label"]) == ("pending", None)
    again = overview(client)
    assert again["reviews"][0]["tx_ref"] == card["tx_ref"]                   # pending again
    assert again["hero"]["primary"]["value"] == 221.58


def evidence_of(client, ref: str) -> dict:
    response = client.get(f"/api/evidence/{ref}", params={"customer_id": LEAD})
    assert response.status_code == 200, response.text
    return response.json()


def test_row_count_of_the_unclassified_item_reconciles_before_and_after_needed(client):
    """R2: the row count is a Number with its own spec, under the same label set as what it counts."""
    first = overview(client)
    item = next(i for i in first["cards"][0]["items"] if i["key"] == "unclassified")
    opened = evidence_of(client, item["amount"]["evidence_ref"])
    rc_ref = opened["row_count"]["evidence_ref"]
    assert (opened["reconciles"], opened["row_count"]["value"]) == (True, 1)       # the one spike
    assert evidence_of(client, rc_ref)["reconciles"] is True                       # while pending

    label(client, first["reviews"][0]["tx_ref"], "unexpected_necessities")
    assert evidence_of(client, item["amount"]["evidence_ref"])["reconciles"] is True   # the number as it was
    assert evidence_of(client, rc_ref)["reconciles"] is True                           # and its row count


def save_values(card: dict) -> dict:
    return {"monthly": card["monthly"]["value"],
            "monthly_components": [(c["key"], c["amount"]["value"]) for c in card["monthly_components"]],
            "stock": card["stock"]["value"],
            "stock_components": [(c["key"], c["amount"]["value"]) for c in card["stock_components"]],
            "reason": card["reason"]}


def test_safe_to_save_follows_the_pending_review(client):
    """#165: while Sanna's review is pending the card shows contracts/api.md `overview.response_pending`
    (364.31 a month: the purchase is in no basket and not in the reserve); after "Needed" it is
    `card.safe_to_save` again (184.61). The hero and the card read one row, so they move together."""
    first = overview(client)
    assert save_values(first["safe_to_save"]) == {
        "monthly": 364.31, "monthly_components": [("free_month", 963.49), ("everyday_month", 599.18)],
        "stock": 12360.83, "stock_components": [("free_until_payday", 12656.12), ("everyday_until_payday", 295.28)],
        "reason": None,
    }
    hero_free = first["hero"]["secondary"][0]
    card_free = first["safe_to_save"]["stock_components"][0]["amount"]
    assert (hero_free["evidence_ref"], hero_free["value"]) == (card_free["evidence_ref"], card_free["value"])
    label(client, first["reviews"][0]["tx_ref"], "unexpected_necessities")
    after = overview(client)["safe_to_save"]
    assert (after["monthly"]["value"], after["stock"]["value"]) == (184.61, 12272.28)


def test_label_errors(client):
    tx_ref = overview(client)["reviews"][0]["tx_ref"]
    unknown = client.post("/api/baskets/label", json=body("txr_0000000000000000", language="fi"))
    assert_error(unknown, 404, "tx_ref_not_found")
    assert unknown.json()["error"]["message"] == "Tämä kysymys ei ole avoinna."   # the body's language
    foreign = client.post("/api/baskets/label", json=body(tx_ref, customer_id="CUST00493"))  # another persona
    assert_error(foreign, 404, "tx_ref_not_found")                           # the same answer (R4)
    assert foreign.json() == client.post("/api/baskets/label", json=body("txr_0000000000000000")).json()
    # a customer the demo does not serve: 404 customer_not_found, as on the overview (#101)
    assert_error(client.post("/api/baskets/label", json=body(tx_ref, customer_id="CUST00001")), 404,
                 "customer_not_found")
    assert_error(client.post("/api/baskets/label", json=body(tx_ref, "regular_essentials")), 422,
                 "basket_not_allowed")
    assert_error(client.post("/api/baskets/label", json=body(tx_ref, customer_id="CUST99999")), 404,
                 "customer_not_found")
    again = label(client, tx_ref, "everyday_spending", language="fi")
    assert again["message"]["numbers"]["n1"]["value"] == 1080.42


def test_switched_off_serves_no_review_and_labels_nothing(client, monkeypatch):
    monkeypatch.setenv("SPIKE_REVIEWS", "off")
    o = overview(client)
    assert o["reviews"] == [] and "unclassified" not in items(o)
    assert_error(client.post("/api/baskets/label", json=body()), 404, "tx_ref_not_found")
