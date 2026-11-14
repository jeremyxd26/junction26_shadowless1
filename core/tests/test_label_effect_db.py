"""The effect of an answer to a review card (#382), on the shared database. Skipped without DATABASE_URL.

For EVERY persona with an open review: "Needed", undo, "My choice", undo, each in its own viewer
session. The response's `effect` pairs equal the overview's own numbers before and after (value and
evidence ref), the undo swaps the sides, and the text states the real difference (or why safe to
spend stays). Like test_viewer_sessions_db.py: one connection, a rolled-back transaction, private
copies of the review tables (reviews.private_tables), SPIKE_REVIEWS on for these tests only.
"""

from __future__ import annotations

import os
import re

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient

from core.app.api import viewer
from core.app.api.schemas import LabelResponse
from core.app.main import create_app
from core.app.settings import ROOT, Settings
from core.tests.test_api_reviews import StubPool
from core.tools import reviews

PERSONAS = [p["customer_id"] for p in yaml.safe_load((ROOT / "core" / "config" / "personas.yaml")
                                                     .read_text(encoding="utf-8"))["personas"]]
TEXTS: list[tuple[str, str, str, str]] = []      # (customer, step, language, rendered text), for the PR


@pytest.fixture(scope="module")
def db_conn():
    url = Settings().database_url
    if url is None:
        pytest.skip("DATABASE_URL is not set")
    conn = psycopg.connect(url.get_secret_value(), autocommit=True, application_name="core-tests-label-effect")
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


def as_viewer(c, value):
    c.cookies.clear()
    c.cookies.set(viewer.COOKIE, value, domain="testserver.local")


def headline(overview: dict) -> dict:
    """The overview's numbers an effect item can name: {key: (value, evidence_ref)}."""
    out = {i["key"]: i["amount"] for i in overview["cards"][0]["items"]}          # the basket card
    hero = overview.get("hero")
    if hero:
        out["safe_to_spend"] = hero["primary"]
        out["irregular_reserve"] = next(c["amount"] for c in hero["components"] if c["key"] == "irregular_reserve")
    if overview.get("safe_to_save"):
        out["safe_to_save"] = overview["safe_to_save"]["monthly"]
    return {k: (n["value"], n["evidence_ref"]) for k, n in out.items()}


def step(c, customer, language, tx_ref, basket, name):
    before = c.get(f"/api/overview/{customer}?lang={language}").json()
    r = c.post("/api/baskets/label", json={"customer_id": customer, "tx_ref": tx_ref, "basket": basket,
                                            "language": language})
    assert r.status_code == 200, r.text
    body = LabelResponse.model_validate(r.json()).model_dump(mode="json")
    after = c.get(f"/api/overview/{customer}?lang={language}").json()
    effect = body["effect"]
    assert effect is not None and body["message"]["text"] == effect["text"]
    b, a = headline(before), headline(after)
    for item in effect["items"]:
        key = item["key"]
        if key == "unclassified" and key not in a:                        # the card hides an empty state
            assert item["after"]["value"] == 0 and (item["before"]["value"], item["before"]["evidence_ref"]) == b[key]
            continue
        if key == "unclassified" and key not in b:
            assert item["before"]["value"] == 0 and (item["after"]["value"], item["after"]["evidence_ref"]) == a[key]
            continue
        assert (item["before"]["value"], item["before"]["evidence_ref"]) == b[key], (customer, name, key)
        assert (item["after"]["value"], item["after"]["evidence_ref"]) == a[key], (customer, name, key)
    text = effect["text_rendered"]
    tokens = set(re.findall(r"\{\{(n\d+)\}\}", effect["text"]))
    assert tokens == set(effect["numbers"]) and len(tokens) <= 3
    assert len(re.findall(r"[.?](?=\s|$)", text)) <= 2 and len(text.split()) <= 40
    assert "Thanks" not in text and "Kiitos" not in text                     # no fixed promise text
    TEXTS.append((customer, name, language, text))
    return {i["key"]: i for i in effect["items"]}, effect


@pytest.mark.parametrize("customer", PERSONAS)
def test_every_answer_and_undo_states_the_real_effect(client, customer):
    as_viewer(client, viewer.new_value())
    overview = client.get(f"/api/overview/{customer}").json()
    if not overview.get("reviews"):
        pytest.skip(f"{customer} has no open review")
    tx_ref = overview["reviews"][0]["tx_ref"]
    for language in ("en", "fi"):
        for basket in ("unexpected_necessities", "everyday_spending"):
            as_viewer(client, viewer.new_value())                          # a fresh viewer: pending first
            answered, effect = step(client, customer, language, tx_ref, basket, f"answer {basket}")
            undone, effect_undo = step(client, customer, language, tx_ref, None, f"undo {basket}")
            for key in ("safe_to_spend", "safe_to_save", "irregular_reserve"):
                if key in answered and key in undone:                      # the undo swaps the sides
                    assert undone[key]["before"]["value"] == answered[key]["after"]["value"]
                    assert undone[key]["after"]["value"] == answered[key]["before"]["value"]
            sts = answered.get("safe_to_spend")
            if sts and sts["before"]["value"] != sts["after"]["value"]:
                assert sts["before"]["display"] in effect["text_rendered"] and sts["after"]["display"] in \
                    effect["text_rendered"]
            elif sts:
                assert re.search(r"does not change|stays the same|ei muuta|pysyy samana", effect["text_rendered"])


def test_the_lead_persona_text_names_what_really_moved(client):
    """No persona literal: the expected text follows the overview's own numbers (the safe-to-spend formula
    may change, #391). Another viewer's numbers do not move."""
    as_viewer(client, viewer.new_value())
    pending = client.get("/api/overview/CUST00860").json()
    tx_ref = pending["reviews"][0]["tx_ref"]
    items, effect = step(client, "CUST00860", "en", tx_ref, "unexpected_necessities", "lead Needed")
    sts, save = items["safe_to_spend"], items["safe_to_save"]
    amount = next(n for n in effect["numbers"].values() if n["method"] == "spending.total@1")["display"]
    reserve = "so the reserve grows" if items["irregular_reserve"]["after"]["value"] > \
        items["irregular_reserve"]["before"]["value"] else ""
    if sts["before"]["value"] != sts["after"]["value"]:
        assert effect["text_rendered"].startswith(f"Your safe to spend this week goes from {sts['before']['display']} "
                                                  f"to {sts['after']['display']}: {amount} now counts as an unexpected "
                                                  f"necessity")
    elif save["before"]["value"] != save["after"]["value"]:
        assert effect["text_rendered"].endswith(f"what you can typically put aside goes from {save['before']['display']} "
                                                f"to {save['after']['display']}.")
    else:
        assert "does not change this week's safe to spend" in effect["text_rendered"]
    assert reserve in effect["text_rendered"] or sts["before"]["value"] == sts["after"]["value"]
    as_viewer(client, viewer.new_value())                                   # another viewer did not move
    assert client.get("/api/overview/CUST00860").json()["hero"]["primary"] == pending["hero"]["primary"]


def test_write_texts_for_the_pr():
    """Runs last in this module: with LABEL_EFFECT_TEXTS set to a file path, the texts of every case
    are written there (UTF-8), for the PR."""
    path = os.environ.get("LABEL_EFFECT_TEXTS")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(f"{customer} | {name} | {language} | {text}\n" for customer, name, language, text in TEXTS)
