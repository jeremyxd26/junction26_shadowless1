"""The review card's option texts promise nothing the answer may not do (#416).

Before the answer, an option's `effect` says only which basket the purchase goes to and that the numbers are
recalculated: no claim about safe to spend, safe to save or the reserve, and no digits. The answer's own
`effect` (#382) then states what really moved, and it names the same basket in the same words.

The database test: for EVERY persona with an open review, both options in English and Finnish, each answered
in its own throwaway viewer session. Like test_label_effect_db.py: one connection, statement_timeout 60 s, a
rolled-back transaction, private copies of the review tables (reviews.private_tables), SPIKE_REVIEWS on for
these tests only. Skipped without DATABASE_URL. The text test needs no database.
"""

from __future__ import annotations

import os
import re

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient

from core.app.api import viewer
from core.app.main import create_app
from core.app.settings import ROOT, Settings
from core.tests.test_api_reviews import StubPool
from core.tools import config, reviews

PERSONAS = [p["customer_id"] for p in yaml.safe_load((ROOT / "core" / "config" / "personas.yaml")
                                                     .read_text(encoding="utf-8"))["personas"]]
# A claim about the numbers before the answer, or a number: none may stand in an option's text.
CLAIM = re.compile(r"safe to spend|safe to save|put aside|reserve|budget|turvallisesti|säästö|varau|budjet|\d", re.I)
# The basket in the words the answer's effect uses (config.LABEL_EFFECT_TEXT, "now counts as ...").
BASKET_WORDS = {"unexpected_necessities": {"en": "unexpected necessity", "fi": "odottamattomaksi välttämättömäksi menoksi"},
                "everyday_spending": {"en": "everyday spending", "fi": "arjen kulutukseksi"}}
# The answer's reply names the choice in its own words (Renat, via r-talk: "counted as a must-have / your own choice").
REPLY_WORDS = {"unexpected_necessities": {"en": "must-have", "fi": "välttämättömäksi"},
               "everyday_spending": {"en": "your own choice", "fi": "omaksi valinnaksesi"}}
TEXTS: list[tuple[str, str, str, str, str]] = []   # (customer, basket, language, option text, effect text), for the PR


@pytest.mark.parametrize("basket", sorted(BASKET_WORDS))
@pytest.mark.parametrize("language", ["en", "fi"])
def test_an_options_text_names_its_basket_and_makes_no_claim(basket, language):
    text = config.label(config.REVIEW_TEXT[f"effect_{basket}"], language).format(product=config.PRODUCT_NAME)
    assert not CLAIM.search(text), text
    assert BASKET_WORDS[basket][language] in text, text
    assert len(re.findall(r"[.?](?=\s|$)", text)) <= 2 and len(text.split()) <= 35, text


@pytest.fixture(scope="module")
def db_conn():
    url = Settings().database_url
    if url is None:
        pytest.skip("DATABASE_URL is not set")
    conn = psycopg.connect(url.get_secret_value(), autocommit=True, application_name="core-tests-review-options")
    conn.execute("SET statement_timeout = '60s'")
    yield conn
    conn.close()


@pytest.fixture
def client(db_conn, monkeypatch):
    monkeypatch.setenv("SPIKE_REVIEWS", "on")
    with db_conn.transaction(force_rollback=True):
        reviews.private_tables(db_conn)  # no lock on the shared tables, and nothing written to them
        app = create_app(Settings(_env_file=None, database_url=None))
        with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as c:
            app.state.pool = StubPool(db_conn)
            yield c


def as_viewer(c, value):
    c.cookies.clear()
    c.cookies.set(viewer.COOKIE, value, domain="testserver.local")


@pytest.mark.parametrize("customer", PERSONAS)
def test_an_options_text_never_contradicts_the_effect_its_answer_returns(client, customer):
    as_viewer(client, viewer.new_value())
    overview = client.get(f"/api/overview/{customer}").json()
    if not overview.get("reviews"):
        pytest.skip(f"{customer} has no open review")
    card = overview["reviews"][0]
    for language in ("en", "fi"):
        for option in card["options"]:
            basket, text = option["basket"], option["effect"][language]
            assert not CLAIM.search(text) and BASKET_WORDS[basket][language] in text, (customer, text)
            as_viewer(client, viewer.new_value())                          # a fresh viewer: pending first
            r = client.post("/api/baskets/label", json={"customer_id": customer, "tx_ref": card["tx_ref"],
                                                        "basket": basket, "language": language})
            assert r.status_code == 200, r.text
            effect = r.json()["effect"]["text_rendered"]
            assert REPLY_WORDS[basket][language] in effect, (customer, basket, language, effect)
            TEXTS.append((customer, basket, language, text, effect))


def test_write_texts_for_the_pr():
    """Runs last in this module: with REVIEW_OPTION_TEXTS set to a file path, every option text and the
    effect its answer returned are written there (UTF-8), for the PR."""
    path = os.environ.get("REVIEW_OPTION_TEXTS")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(f"{c} | {b} | {lang} | {o} | {e}\n" for c, b, lang, o, e in TEXTS)
