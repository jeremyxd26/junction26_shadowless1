"""#575 on the shared database: "why is my safe to spend lower?" names the purchase of a pending or "Needed" review.
The four review states, one customer per query, one connection, every write rolled back (force_rollback), on
session-private copies of the review tables (reviews.private_tables), so the live review the stand's visitors get
stays pending. Skipped without DATABASE_URL, and until reviews.private_tables exists."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date

import psycopg
import pytest
from fastapi.testclient import TestClient

from core.agent import why_review
from core.agent.api import label_steps
from core.app.main import create_app
from core.app.settings import Settings
from core.tools import reviews
from core.tools.context import ToolContext
from core.tools.safe_to_spend import get_safe_to_spend

LEAD, NO_REVIEW = "CUST00860", "CUST00493"
AS_OF = date(2026, 9, 30)
WHY = "Why is my safe to spend so low?"
PENDING_EN = "still waits for your answer: marking it needed would lower this."
NEEDED_EN = "Marking your"
OTHER_SIDE_EN = "would allow"   # #574's second sentence: "Your balance alone would allow …"


class StubPool:
    """Hands out the test's connection, which is inside a rolled-back transaction."""

    def __init__(self, conn) -> None:
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
    conn = psycopg.connect(url.get_secret_value(), autocommit=True, application_name="core-tests-why-review")
    conn.execute("SET statement_timeout = '60s'")
    yield conn
    conn.close()


@pytest.fixture
def rolled_back(db_conn, monkeypatch, tmp_path):
    if not hasattr(reviews, "private_tables"):
        pytest.skip("waits for reviews.private_tables (#199): no test may touch the live spike_reviews table")
    monkeypatch.setenv("SPIKE_REVIEWS", "on")
    monkeypatch.setenv("AUDIT_LOG_DIR", str(tmp_path / "audit"))
    with db_conn.transaction(force_rollback=True):
        reviews.private_tables(db_conn)
        yield db_conn


@pytest.fixture
def client(rolled_back):
    app = create_app(Settings(_env_file=None, database_url=None))
    # https: the viewer cookie is Secure, so the label answer and the questions after it are one viewer's (#429)
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as c:
        app.state.pool = StubPool(rolled_back)
        yield c


def ask(client, customer: str, question: str = WHY, language: str = "en") -> dict:
    r = client.post("/api/ask", json={"customer_id": customer, "message": question, "language": language},
                    headers={"Accept": "application/json"})
    assert r.status_code == 200, r.text
    return r.json()


def overview(client, customer: str = LEAD) -> dict:
    r = client.get(f"/api/overview/{customer}")
    assert r.status_code == 200, r.text
    return r.json()


def label(client, tx_ref: str, basket: str) -> None:
    r = client.post("/api/baskets/label", json={"customer_id": LEAD, "tx_ref": tx_ref, "basket": basket, "language": "en"})
    assert r.status_code == 200, r.text


def review_rows(conn) -> list[tuple]:
    rows = conn.execute("SELECT customer_id, tx_id, tx_ref FROM spike_reviews ORDER BY 1, 2").fetchall()
    return rows + conn.execute("SELECT * FROM spike_review_answers ORDER BY 1, 2").fetchall()


def amount_number(answer: dict) -> dict:
    return next(n for n in answer["numbers"].values() if abs(n["value"] - 1080.42) < 0.005)


def test_pending_names_the_purchase_and_the_review_stays_pending(client, rolled_back):
    first = overview(client)                       # the review step: the card is shown, the review is pending
    tx_ref, hero = first["reviews"][0]["tx_ref"], first["hero"]["primary"]
    before = review_rows(rolled_back)
    answer = ask(client, LEAD)
    assert PENDING_EN in answer["text_rendered"] and OTHER_SIDE_EN not in answer["text_rendered"], answer["text_rendered"]
    number = amount_number(answer)                  # the review card's own Number, with evidence that opens
    r = client.get(f"/api/evidence/{number['evidence_ref']}?customer_id={LEAD}")
    assert r.status_code == 200, r.text
    assert review_rows(rolled_back) == before       # the why-answer wrote no review row and no answer
    after = overview(client)
    assert after["reviews"][0]["tx_ref"] == tx_ref  # still pending for this viewer: the review step is still there
    assert (after["hero"]["primary"]["value"], after["hero"]["primary"]["evidence_ref"]) == \
        (hero["value"], hero["evidence_ref"])       # the hero's Number unchanged


def test_needed_says_it_lowered_safe_to_spend(client, rolled_back):
    tx_ref = overview(client)["reviews"][0]["tx_ref"]
    label(client, tx_ref, "unexpected_necessities")
    hero = overview(client)["hero"]["primary"]
    before = review_rows(rolled_back)
    answer = ask(client, LEAD)
    assert answer["text_rendered"].split(". ", 1)[1].startswith(NEEDED_EN), answer["text_rendered"]
    assert "lowered this" in answer["text_rendered"] and OTHER_SIDE_EN not in answer["text_rendered"]
    amount_number(answer)
    assert review_rows(rolled_back) == before
    after = overview(client)["hero"]["primary"]
    assert (after["value"], after["evidence_ref"]) == (hero["value"], hero["evidence_ref"])


def test_not_needed_is_the_574_answer_unchanged(client, rolled_back):
    tx_ref = overview(client)["reviews"][0]["tx_ref"]
    label(client, tx_ref, "everyday_spending")
    before = review_rows(rolled_back)
    answer = ask(client, LEAD)
    assert OTHER_SIDE_EN in answer["text_rendered"] and "purchase" not in answer["text_rendered"], answer["text_rendered"]
    assert review_rows(rolled_back) == before


def test_no_review_is_the_574_answer_unchanged(client):
    answer = ask(client, NO_REVIEW)
    assert OTHER_SIDE_EN in answer["text_rendered"] and "purchase" not in answer["text_rendered"], answer["text_rendered"]


def test_the_effect_writes_nothing(rolled_back):
    """The before/after pair and the card: no evidence row, no review row, no answer row is added."""
    steps = label_steps()
    ctx = ToolContext(customer_id=LEAD, as_of=AS_OF, conn=rolled_back, language="en")
    pending = steps.establish(ctx)                  # the pending review (private tables) and the answer's labels
    current = get_safe_to_spend(ctx, {}).data.safe_to_spend.value
    steps.card(ctx, pending)                        # the card as the review step shows it
    ctx.conn = None
    view = {"tool": "get_safe_to_spend", "safe_to_spend": {"value": current}}
    count = "SELECT (SELECT count(*) FROM coach_evidence), (SELECT count(*) FROM spike_reviews), " \
            "(SELECT count(*) FROM spike_review_answers)"
    before = rolled_back.execute(count).fetchone()
    found = why_review.effect(StubPool(rolled_back), steps, ctx, pending, view)
    assert rolled_back.execute(count).fetchone() == before
    assert found is not None and found["state"] == "pending" and found["moved"] is True and found["amount"]["id"]
