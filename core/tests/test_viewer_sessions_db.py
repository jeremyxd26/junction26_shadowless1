"""Viewer sessions on the shared database (#144). Skipped without DATABASE_URL.

Like test_api_reviews.py: the app's pool is a stub that hands out one connection inside a transaction
that is rolled back, and Sanna's review rows (with every viewer's answers, ON DELETE CASCADE) are
deleted inside it first. Nothing is committed; the dev demo state neither affects the test nor is
changed by it. SPIKE_REVIEWS is on for these tests only.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from core.app.api import viewer
from core.app.main import create_app
from core.app.settings import Settings
from core.tests.test_api_reviews import LEAD, StubPool, items
from core.tools import labels, reviews
from core.tools.db import load_transactions

A, B, C = (viewer.new_value() for _ in range(3))
AS_OF = date(2026, 9, 30)


@pytest.fixture(scope="module")
def db_conn():
    url = Settings().database_url
    if url is None:
        pytest.skip("DATABASE_URL is not set")
    conn = psycopg.connect(url.get_secret_value(), autocommit=True, application_name="core-tests-viewers")
    conn.execute("SET statement_timeout = '60s'")
    yield conn
    conn.close()


@pytest.fixture
def client(db_conn, monkeypatch):
    monkeypatch.setenv("SPIKE_REVIEWS", "on")
    with db_conn.transaction(force_rollback=True):
        reviews.private_tables(db_conn)  # no lock on the shared tables
        app = create_app(Settings(_env_file=None, database_url=None))
        with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as c:
            app.state.pool = StubPool(db_conn)
            yield c


def as_viewer(client, value: str | None) -> None:
    client.cookies.clear()
    if value is not None:  # http.cookiejar matches a dotless host as "<host>.local"
        client.cookies.set(viewer.COOKIE, value, domain="testserver.local")


def overview(client, value: str | None):
    as_viewer(client, value)
    r = client.get(f"/api/overview/{LEAD}")
    assert r.status_code == 200, r.text
    return r


def answer(client, value: str | None, tx_ref: str, basket):
    as_viewer(client, value)
    r = client.post("/api/baskets/label", json={"customer_id": LEAD, "tx_ref": tx_ref, "basket": basket,
                                                "language": "en"})
    assert r.status_code == 200, r.text
    return r.json()


def answer_rows(conn) -> int:
    return reviews.count_answers(conn, [LEAD])


def test_two_viewers_answer_independently(client, db_conn):
    tx_ref = overview(client, A).json()["reviews"][0]["tx_ref"]
    needed = answer(client, A, tx_ref, "unexpected_necessities")
    assert {c["key"]: c["after"]["value"] for c in needed["changes"]}["safe_to_spend"] == 180.26

    a, b = overview(client, A).json(), overview(client, B).json()
    assert a["reviews"] == [] and items(a)["unexpected_necessities"] == 521.15        # A answered
    assert b["reviews"][0]["tx_ref"] == tx_ref and items(b)["unclassified"] == 180.07  # B still pending
    assert "Set-Cookie" not in overview(client, B).headers                            # B keeps its cookie

    wanted = answer(client, B, tx_ref, "everyday_spending")  # from B's own pending state, not A's answer
    assert {c["key"]: (c["before"]["value"], c["after"]["value"]) for c in wanted["changes"]} == {
        "unclassified": (180.07, 0.0), "everyday_spending": (600.41, 780.48)}
    undone = answer(client, A, tx_ref, None)
    assert undone["review_state"] == "pending"
    assert overview(client, A).json()["reviews"][0]["tx_ref"] == tx_ref                # A pending again
    assert overview(client, B).json()["reviews"] == []                                # B untouched
    assert items(overview(client, B).json())["everyday_spending"] == 780.48
    # The shared row was never written: a viewer without answers sees the pending state.
    assert overview(client, C).json()["reviews"][0]["tx_ref"] == tx_ref
    shared = reviews.load_reviews(db_conn, LEAD)
    assert [r.basket for r in shared] == [None]


WHATIF_NUMBERS = ("baseline_per_month", "saving_per_month", "one_off_excluded", "regular_excluded")


def whatif(client, value: str | None, basket: str) -> dict:
    as_viewer(client, value)
    r = client.post("/api/whatif", json={"customer_id": LEAD, "language": "en", "scenario": {
        "selection": {"kind": "basket", "value": basket}, "cut_pct": 20}})
    assert r.status_code == 200, r.text
    return r.json()


def numbers_of(w: dict) -> dict:
    return {k: w[k]["value"] for k in WHATIF_NUMBERS}


def test_the_what_if_starts_from_the_viewers_own_state(client):
    """Review of #199: after A taps "Needed", A's what-if uses A's labels, as A's hero does; B and a
    viewer without a cookie still see the pending state."""
    review = overview(client, A).json()["reviews"][0]
    basket = "unexpected_necessities"
    before = whatif(client, A, basket)
    assert numbers_of(before)["one_off_excluded"] == 0                    # pending: the purchase is in no basket
    answer(client, A, review["tx_ref"], basket)                          # A: "Needed"

    a, b, fresh = whatif(client, A, basket), whatif(client, B, basket), whatif(client, None, basket)
    assert numbers_of(a) == {**numbers_of(before), "one_off_excluded": review["amount"]["value"]}   # 1080.42
    assert a["evidence_ref"] != before["evidence_ref"]                  # computed with A's labels
    assert numbers_of(b) == numbers_of(fresh) == numbers_of(before)      # B and a new viewer: still pending
    assert b["evidence_ref"] == fresh["evidence_ref"] == before["evidence_ref"]


def test_no_cookie_gets_one_and_the_shared_pending_state(client, db_conn):
    r = overview(client, None)
    assert r.json()["reviews"][0]["current_basket"]["key"] == "unclassified"
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(viewer.COOKIE + "=") and "HttpOnly" in cookie and "Secure" in cookie
    assert "SameSite=lax" in cookie and "Max-Age=7200" in cookie and "Path=/" in cookie
    assert answer_rows(db_conn) == 0                                  # a GET writes no answer row


def test_label_without_a_cookie_is_stored_for_a_new_viewer_only(client, db_conn):
    tx_ref = overview(client, A).json()["reviews"][0]["tx_ref"]
    as_viewer(client, None)
    r = client.post("/api/baskets/label", json={"customer_id": LEAD, "tx_ref": tx_ref,
                                                "basket": "unexpected_necessities", "language": "en"})
    assert r.status_code == 200 and viewer.COOKIE in r.headers["set-cookie"]
    assert overview(client, A).json()["reviews"][0]["tx_ref"] == tx_ref    # nobody else changed


def test_the_session_id_is_never_logged(client, caplog):
    caplog.set_level(logging.DEBUG)
    tx_ref = overview(client, A).json()["reviews"][0]["tx_ref"]
    answer(client, A, tx_ref, "unexpected_necessities")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "audit label" in text and A not in text and viewer.session_key(A) not in text


def test_cap_drops_the_oldest_viewer_who_sees_the_pending_card_again(client, db_conn, monkeypatch):
    monkeypatch.setattr(reviews, "MAX_SESSIONS", 2)
    tx_ref = overview(client, A).json()["reviews"][0]["tx_ref"]
    for v in (A, B, C):                                               # C's first answer evicts A
        answer(client, v, tx_ref, "unexpected_necessities")
    assert overview(client, A).json()["reviews"][0]["tx_ref"] == tx_ref
    assert overview(client, B).json()["reviews"] == [] and overview(client, C).json()["reviews"] == []
    assert answer_rows(db_conn) == 2


def test_eviction_takes_the_least_recently_active_not_the_first_to_answer(client, db_conn, monkeypatch):
    """A answered first but taps again later (last_active refreshed), so the new viewer C drops B."""
    monkeypatch.setattr(reviews, "MAX_SESSIONS", 2)
    tx_ref = overview(client, A).json()["reviews"][0]["tx_ref"]
    answer(client, A, tx_ref, "unexpected_necessities")
    answer(client, B, tx_ref, "unexpected_necessities")
    answer(client, A, tx_ref, None)                                   # A is active again (undo)
    answer(client, C, tx_ref, "everyday_spending")
    assert overview(client, B).json()["reviews"][0]["tx_ref"] == tx_ref    # B dropped: pending card again
    a = overview(client, A).json()
    assert a["reviews"][0]["tx_ref"] == tx_ref and viewer.session_key(A) in {
        r[0] for r in db_conn.execute("SELECT session_key FROM spike_review_answers").fetchall()}  # A kept


def test_every_label_write_refreshes_the_cookie(client):
    tx_ref = overview(client, A).json()["reviews"][0]["tx_ref"]
    as_viewer(client, A)
    r = client.post("/api/baskets/label", json={"customer_id": LEAD, "tx_ref": tx_ref,
                                                "basket": "unexpected_necessities", "language": "en"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{viewer.COOKIE}={A};") and "Max-Age=7200" in cookie    # same value, new age


@pytest.fixture
def one_new_session_an_hour(db_conn, monkeypatch):
    monkeypatch.setenv("SPIKE_REVIEWS", "on")
    with db_conn.transaction(force_rollback=True):
        reviews.private_tables(db_conn)  # no lock on the shared tables
        app = create_app(Settings(_env_file=None, database_url=None, label_new_sessions_per_hour=1))
        with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as c:
            app.state.pool = StubPool(db_conn)
            yield c


def test_a_first_answer_that_admits_nobody_gives_its_slot_back(one_new_session_an_hour):
    """The slot is reserved before the write and released when no session was admitted (an undo with no
    answer to undo), so it is still free for the next viewer's real first answer."""
    client = one_new_session_an_hour
    tx_ref = overview(client, A).json()["reviews"][0]["tx_ref"]
    assert answer(client, C, tx_ref, None)["review_state"] == "pending"   # changed nothing: released
    answer(client, A, tx_ref, "unexpected_necessities")                  # the hour's one session
    as_viewer(client, B)
    third = client.post("/api/baskets/label", json={"customer_id": LEAD, "tx_ref": tx_ref,
                                                    "basket": "unexpected_necessities"})
    assert third.status_code == 429


def test_new_sessions_per_address_count_only_admitted_ones(one_new_session_an_hour):
    client = one_new_session_an_hour
    tx_ref = overview(client, A).json()["reviews"][0]["tx_ref"]
    as_viewer(client, C)                                              # a refused attempt does not count
    junk = client.post("/api/baskets/label", json={"customer_id": LEAD, "tx_ref": "txr_0000000000000000",
                                                   "basket": "unexpected_necessities"})
    assert junk.status_code == 404
    answer(client, A, tx_ref, "unexpected_necessities")               # admitted: the hour's one session
    as_viewer(client, B)
    second = client.post("/api/baskets/label", json={"customer_id": LEAD, "tx_ref": tx_ref,
                                                     "basket": "unexpected_necessities"})
    assert second.status_code == 429 and second.json()["error"]["code"] == "rate_limited"
    assert answer(client, A, tx_ref, None)["review_state"] == "pending"   # an established viewer goes on


def test_answers_expire_after_the_session_ttl(db_conn, monkeypatch):
    monkeypatch.setenv("SPIKE_REVIEWS", "on")
    with db_conn.transaction(force_rollback=True):
        reviews.private_tables(db_conn)  # no lock on the shared tables
        now = reviews.utcnow()
        pending = reviews.ensure_pending(db_conn, LEAD, AS_OF, load_transactions(db_conn, LEAD, AS_OF), now)
        key = viewer.session_key(A)
        then = now - reviews.SESSION_TTL - timedelta(minutes=1)
        answered = reviews.decide(pending, "unexpected_necessities", then).review
        reviews.save_answer(db_conn, key, answered, then)
        assert labels.basket_labels(db_conn, LEAD, AS_OF, then, viewer=key) == {
            pending.tx_id: "unexpected_necessities"}
        # Two hours later the answer no longer counts, and the next write by anyone cleans it up.
        assert labels.basket_labels(db_conn, LEAD, AS_OF, now, viewer=key) == {pending.tx_id: "unclassified"}
        reviews.save_answer(db_conn, viewer.session_key(B), answered, now)
        assert reviews.count_answers(db_conn, [LEAD]) == 1


def test_a_full_session_cannot_answer_another_review(db_conn, monkeypatch):
    monkeypatch.setenv("SPIKE_REVIEWS", "on")
    monkeypatch.setattr(reviews, "MAX_ANSWERS_PER_SESSION", 1)
    with db_conn.transaction(force_rollback=True):
        reviews.private_tables(db_conn)  # no lock on the shared tables
        now = reviews.utcnow()
        first = reviews.ensure_pending(db_conn, LEAD, AS_OF, load_transactions(db_conn, LEAD, AS_OF), now)
        other_tx = db_conn.execute("SELECT id FROM transactions WHERE customer_id = %s AND id <> %s "
                                   "ORDER BY id LIMIT 1", (LEAD, first.tx_id)).fetchone()[0]
        db_conn.execute("INSERT INTO spike_reviews (customer_id, tx_id, tx_ref, created_at, expires_at) "
                        "VALUES (%s, %s, %s, %s, %s)", (LEAD, other_tx, reviews.new_tx_ref(), now,
                                                        now + timedelta(days=7)))
        second = next(r for r in reviews.load_reviews(db_conn, LEAD) if r.tx_id == other_tx)
        key = viewer.session_key(A)
        reviews.save_answer(db_conn, key, reviews.decide(first, "everyday_spending", now).review, now)
        reviews.save_answer(db_conn, key, reviews.decide(first, "unexpected_necessities", now).review, now)
        with pytest.raises(reviews.TooManyAnswers):
            reviews.save_answer(db_conn, key, reviews.decide(second, "everyday_spending", now).review, now)


# due before payday (15 Oct), so 03 runs again with the viewer's labels and the bill
BILL_FIELDS = {"payee": "Esimerkki Remontti Oy", "iban": "FI71 1234 5600 0098 76", "reference": "12344",
               "amount": "145.00", "due_date": "2026-10-10"}


def bill(client, value: str | None) -> dict:
    as_viewer(client, value)
    r = client.post("/api/bill/explain", json={"customer_id": LEAD, "language": "en", "fields": BILL_FIELDS})
    assert r.status_code == 200, r.text
    return r.json()["safe_to_spend"]


def test_the_bill_explanation_starts_from_the_viewers_own_state(client, db_conn):
    """#242, after the review of #199: after A taps "Needed", A's bill starts from A's hero, and its "after"
    is 03 run again with A's labels and the bill; B and a viewer without a cookie still see the hero of the
    pending state."""
    from core.tools import evidence

    review = overview(client, A).json()["reviews"][0]
    pending = bill(client, A)
    answer(client, A, review["tx_ref"], "unexpected_necessities")    # A: "Needed"
    a, b, fresh = bill(client, A), bill(client, B), bill(client, None)
    assert a["before"]["value"] == overview(client, A).json()["hero"]["primary"]["value"] == 180.26
    assert b["before"] == fresh["before"] == pending["before"]
    assert b["before"]["value"] == overview(client, B).json()["hero"]["primary"]["value"] == 221.58
    assert a["before"]["evidence_ref"] != b["before"]["evidence_ref"]        # computed with A's labels
    for s in (a, b):   # each from its own state, the bill added in full
        assert s["effect"] == "full"
        assert round(s["free_until_payday_before"]["value"] - s["free_until_payday_after"]["value"], 2) == 145.0
    after = evidence.resolve(db_conn, a["after"]["evidence_ref"], LEAD)
    balance = evidence.resolve(db_conn, after.parts[0]["ref"], LEAD)
    assert after.reconciles is True and balance.reconciles is True
    settings = balance.spec["source"]["settings"]
    assert settings["extra_bill_due_eur"] == "145.00" and "tx_labels" in settings   # A's labels and the bill
