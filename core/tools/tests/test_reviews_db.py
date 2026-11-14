"""Spike review of CUST00860 (persona Sanna) on the shared database (#68). Skipped without DATABASE_URL.

Everything runs inside one transaction that is rolled back (force_rollback): the spike_reviews table,
Sanna's review rows and the evidence specs are never committed. Her rows that the dev demo may have
created are deleted inside that transaction first, so the test does not depend on the demo state,
and the demo state is untouched afterwards. SPIKE_REVIEWS is switched on for these tests only.

The numbers are the worked example of metrics.md section 1.1 and contract section 10.2:
transaction 606016, Home & Tech, 1,080.42 on 2026-09-28, a one-off.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from core.tools import evidence, label_answer, labels, review_card, reviews
from core.tools.context import ToolContext
from core.tools.db import load_transactions

LEAD = "CUST00860"
SPIKE = 606016
AS_OF = date(2026, 9, 30)


@pytest.fixture
def tx(conn, monkeypatch):
    """A rolled-back transaction with SPIKE_REVIEWS on and no review rows for Sanna."""
    monkeypatch.setenv("SPIKE_REVIEWS", "on")
    with conn.transaction(force_rollback=True):
        reviews.private_tables(conn)  # no lock on the shared tables
        yield conn


def numbers(conn) -> dict[str, float]:
    return {k: n.value for k, (_, n) in label_answer.overview_numbers(ToolContext(LEAD, AS_OF, conn)).items()}


def assert_reconciles(conn, refs):
    for ref in refs:
        res = evidence.resolve(conn, ref, LEAD)
        assert res.reconciles, f"{ref} ({res.kind} {res.method}) does not reconcile"


def test_pending_needed_wanted_undo(tx):
    conn = tx
    now = reviews.utcnow()
    rule = numbers(conn)  # no review: the published numbers (the same as after "needed")
    assert (rule["safe_to_spend"], rule["unexpected_necessities"], rule["unclassified"]) == (97.46, 521.15, 0.0)

    history = load_transactions(conn, LEAD, AS_OF)
    pending = reviews.ensure_pending(conn, LEAD, AS_OF, history, now)
    assert pending.tx_id == SPIKE and reviews.TX_REF.fullmatch(pending.tx_ref)
    assert reviews.ensure_pending(conn, LEAD, AS_OF, history, now) == pending          # idempotent
    assert len(reviews.load_reviews(conn, LEAD)) == 1
    assert labels.basket_labels(conn, LEAD, AS_OF) == {SPIKE: "unclassified"}

    # Pending: the purchase waits for the answer, in no basket and not in the reserve.
    ctx = ToolContext(LEAD, AS_OF, conn)
    before = label_answer.overview_numbers(ctx)
    got = {k: n.value for k, (_, n) in before.items()}
    assert got["safe_to_spend"] == 138.79
    assert got["unclassified"] == 180.07                       # 1,080.42 / 6 months
    assert got["unexpected_necessities"] == 341.08
    assert got["everyday_spending"] == 600.41
    assert got["irregular_reserve"] == 167.74
    card = review_card.build(ctx, pending)
    assert card["tx_ref"] == pending.tx_ref and card["amount"]["value"] == 1080.42
    assert card["current_basket"] == {"key": "unclassified", "label": "Waiting for your answer"}
    assert card["merchant"]["alias"].startswith("store_") and str(SPIKE) not in str(card)
    assert card["question"]["en"] == "€1,080.42 at Home & Tech on 28 September 2026 — needed, or your choice?"
    assert [o["label"]["en"] for o in card["options"]] == ["Needed", "My choice"]
    pending_refs = [n.evidence_ref for _, n in before.values()] + [card["amount"]["evidence_ref"]]

    # "Needed": the reserve grows by 88.56 and safe to spend goes down to 97.46 (#391: the goal stays 360).
    needed = label_answer.answer(conn, LEAD, AS_OF, pending.tx_ref, "unexpected_necessities", "en", now)
    assert (needed["review_state"], needed["changed"], needed["label"]["basket"]) == (
        "answered", True, "unexpected_necessities")
    moved = {c["key"]: (c["before"]["value"], c["after"]["value"]) for c in needed["changes"]}
    assert moved == {"unclassified": (180.07, 0.0), "unexpected_necessities": (341.08, 521.15),
                     "irregular_reserve": (167.74, 256.3), "safe_to_spend": (138.79, 97.46)}
    assert all(c["before"]["evidence_ref"] != c["after"]["evidence_ref"] for c in needed["changes"])
    assert numbers(conn) == rule

    # The same answer again changes nothing.
    again = label_answer.answer(conn, LEAD, AS_OF, pending.tx_ref, "unexpected_necessities", "en", now)
    assert (again["changed"], again["changes"]) == (False, [])

    # "My choice": everyday spending gains the purchase, safe to spend stays at its pending value.
    wanted = label_answer.answer(conn, LEAD, AS_OF, pending.tx_ref, "everyday_spending", "en", now)
    moved = {c["key"]: (c["before"]["value"], c["after"]["value"]) for c in wanted["changes"]}
    assert moved == {"unexpected_necessities": (521.15, 341.08), "everyday_spending": (600.41, 780.48),
                     "irregular_reserve": (256.3, 167.74), "safe_to_spend": (97.46, 138.79)}
    # #382: the confirmation is the real effect, built from the numbers that moved.
    amount = next((i, n) for i, n in wanted["message"]["numbers"].items() if n["method"] == "spending.total@1")
    assert (amount[1]["value"], "{{" + amount[0] + "}}" in wanted["message"]["text"]) == (1080.42, True)
    sts = next(c for c in wanted["changes"] if c["key"] == "safe_to_spend")
    assert wanted["message"]["text_rendered"] == (f"Your safe to spend this week goes from {sts['before']['display']} "
                                                  f"to {sts['after']['display']}: {amount[1]['display']} now counts "
                                                  f"as everyday spending.")
    assert wanted["effect"]["text"] == wanted["message"]["text"]

    # Undo within 7 days: pending again, with exactly the pending numbers.
    undone = label_answer.answer(conn, LEAD, AS_OF, pending.tx_ref, None, "en", now)
    assert (undone["review_state"], undone["label"]) == ("pending", None)
    assert numbers(conn) == got

    # No answer ever raised safe to spend above its pending value.
    for body in (needed, wanted, undone):
        for c in body["changes"]:
            if c["key"] == "safe_to_spend":
                assert c["after"]["value"] <= 138.79

    # Refs issued while pending still reconcile after the label changed (labels are in the spec).
    label_answer.answer(conn, LEAD, AS_OF, pending.tx_ref, "unexpected_necessities", "en", now)
    transaction_refs = [r for r in pending_refs if evidence.load(conn, r)[1]["kind"] == "transactions"]
    assert_reconciles(conn, transaction_refs)
    assert_reconciles(conn, [before["safe_to_spend"][1].evidence_ref])  # composite of two metric refs


def test_expired_review_is_closed_and_its_ref_gets_404(tx):
    conn = tx
    now = reviews.utcnow()
    history = load_transactions(conn, LEAD, AS_OF)
    old = reviews.ensure_pending(conn, LEAD, AS_OF, history, now - timedelta(days=8))
    assert old.tx_id == SPIKE
    assert labels.basket_labels(conn, LEAD, AS_OF, now) == {}                  # closed: the rules apply
    assert reviews.ensure_pending(conn, LEAD, AS_OF, history, now) is None    # never asked twice
    with pytest.raises(reviews.ReviewNotFound):                                # no late answers
        label_answer.answer(conn, LEAD, AS_OF, old.tx_ref, "unexpected_necessities", "en", now)


def test_unknown_foreign_and_malformed_refs_are_not_found(tx):
    conn = tx
    now = reviews.utcnow()
    pending = reviews.ensure_pending(conn, LEAD, AS_OF, load_transactions(conn, LEAD, AS_OF), now)
    for customer, ref in ((LEAD, "txr_0000000000000000"), ("CUST00493", pending.tx_ref), (LEAD, "606016"),
                          (LEAD, "")):
        with pytest.raises(reviews.ReviewNotFound):
            label_answer.answer(conn, customer, AS_OF, ref, "unexpected_necessities", "en", now)
    with pytest.raises(reviews.BasketNotAllowed):
        label_answer.answer(conn, LEAD, AS_OF, pending.tx_ref, "regular_essentials", "en", now)
    assert reviews.get_pending(conn, LEAD, AS_OF, now) == pending              # nothing was written


class Counting:
    """A connection wrapper that counts the statements sent through execute()."""

    def __init__(self, conn) -> None:
        self.conn, self.statements = conn, 0

    def execute(self, *args, **kwargs):
        self.statements += 1
        return self.conn.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.conn, name)


def test_warm_overview_reads_the_reviews_once(tx):
    """With a pending review, the overview's review step and every label read of the request together
    cost two statements (the table check and one read), take no lock and read no history."""
    conn = tx
    reviews.ensure_pending(conn, LEAD, AS_OF, load_transactions(conn, LEAD, AS_OF))
    counting = Counting(conn)
    ctx = ToolContext(LEAD, AS_OF, counting)
    assert reviews.ensure_pending_for(ctx).tx_id == SPIKE
    for _ in range(4):  # baskets, bills, the review card, safe to spend
        assert labels.for_context(ctx) == {SPIKE: "unclassified"}
    assert labels.metric_settings_for(ctx) == {"tx_labels": '{"606016":"unclassified"}'}
    assert counting.statements == 2 and ctx._history is None


def test_the_tests_use_private_tables_and_lock_nothing_shared(tx):
    """The fixture's tables are temporary copies, so a test never locks the live rows the dev service uses."""
    conn = tx
    for table in ("spike_reviews", "spike_review_answers"):
        schema = conn.execute("SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                              "WHERE c.oid = to_regclass(%s)", (table,)).fetchone()[0]
        assert schema.startswith("pg_temp"), (table, schema)


def test_get_pending_never_creates(tx):
    conn = tx
    assert reviews.get_pending(conn, LEAD, AS_OF) is None
    assert reviews.load_reviews(conn, LEAD) == []


def test_metric_sql_reads_the_labels_like_classify(tx):
    """03 with the pending label equals the tools' numbers; an invalid setting means no labels."""
    from core.tools import metric_sql

    conn = tx
    pending_row = metric_sql.run_one(conn, "03_safe_to_spend.sql", LEAD, AS_OF,
                                     labels.metric_settings({SPIKE: "unclassified"}))
    assert pending_row["safe_to_spend_7d_eur"] == Decimal("138.79")
    for junk in ("not json", "[1,2]", '{"606016": "groceries"}', '{"abc": "unclassified"}'):
        row = metric_sql.run_one(conn, "03_safe_to_spend.sql", LEAD, AS_OF, {"tx_labels": junk})
        assert row["safe_to_spend_7d_eur"] == Decimal("97.46"), junk
