"""Spike reviews without a database (#68): state machine, limits, expiry, selection and the label plumbing.

The rules are design doc section 7.8 and contract 0.2.0 sections 6 and 10.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from core.tools import evidence, labels, reviews
from core.tools.classify import classify
from core.tools.db import Tx
from core.tools.reviews import ANSWERED, CLOSED, PENDING, Review
from core.tools.selection import Selection, select

UTC = timezone.utc
NOW = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)          # a Saturday
AS_OF = date(2026, 9, 30)
METRICS = Path(__file__).resolve().parents[2] / "metrics"


def review(tx_id=1, created=NOW, basket=None, answered=None, ref=None) -> Review:
    return Review("CUST00860", tx_id, ref or f"txr_{tx_id:016d}", created, created + timedelta(days=7), basket,
                  answered)


def tx(i, d, category, amount, mcc=None, merchant="m1", tx_type="purchase") -> Tx:
    return Tx(i, d, datetime.combine(d, datetime.min.time()), category, tx_type, merchant, mcc, Decimal(amount))


# ---- states and transitions ---------------------------------------------------------------------

def test_state_is_derived_from_basket_and_expiry():
    r = review()
    assert r.state(NOW) == PENDING
    assert r.state(NOW + timedelta(days=7) - timedelta(seconds=1)) == PENDING
    assert r.state(NOW + timedelta(days=7)) == CLOSED                       # expires 7 days after creation
    answered = review(basket="unexpected_necessities", answered=NOW)
    assert answered.state(NOW + timedelta(days=30)) == ANSWERED            # an answer does not expire


def test_answer_change_and_same_answer_again():
    r = review()
    needed = reviews.decide(r, "unexpected_necessities", NOW)
    assert (needed.state, needed.changed, needed.review.basket, needed.review.answered_at) == (
        ANSWERED, True, "unexpected_necessities", NOW)
    again = reviews.decide(needed.review, "unexpected_necessities", NOW + timedelta(hours=1))
    assert (again.state, again.changed, again.review) == (ANSWERED, False, needed.review)   # idempotent
    wanted = reviews.decide(needed.review, "everyday_spending", NOW + timedelta(hours=2))
    assert (wanted.state, wanted.changed, wanted.review.basket) == (ANSWERED, True, "everyday_spending")


def test_undo_within_seven_days_is_pending_again_and_after_them_closes():
    answered = reviews.decide(review(), "unexpected_necessities", NOW).review
    undone = reviews.decide(answered, None, NOW + timedelta(days=6))
    assert (undone.state, undone.changed, undone.review.basket, undone.review.answered_at) == (
        PENDING, True, None, None)
    late_undo = reviews.decide(answered, None, NOW + timedelta(days=8))
    assert (late_undo.state, late_undo.changed) == (CLOSED, True)
    with pytest.raises(reviews.ReviewNotFound):                            # closed: never re-opened
        reviews.decide(late_undo.review, "unexpected_necessities", NOW + timedelta(days=8))


def test_undo_of_a_pending_review_changes_nothing():
    out = reviews.decide(review(), None, NOW)
    assert (out.state, out.changed) == (PENDING, False)


def test_no_late_answers_after_expiry():
    with pytest.raises(reviews.ReviewNotFound):
        reviews.decide(review(), "everyday_spending", NOW + timedelta(days=7))


@pytest.mark.parametrize("basket", ["regular_essentials", "unclassified", "anything"])
def test_only_the_two_options_are_allowed(basket):
    with pytest.raises(reviews.BasketNotAllowed):
        reviews.decide(review(), basket, NOW)


def test_closed_ref_is_not_found_before_the_basket_is_checked():
    with pytest.raises(reviews.ReviewNotFound):                            # 404 before 422 (R4)
        reviews.decide(review(), "regular_essentials", NOW + timedelta(days=9))


def test_label_overrides_pending_unclassified_answered_basket_closed_nothing():
    rs = [review(1), review(2, basket="everyday_spending", answered=NOW),
          review(3, created=NOW - timedelta(days=10))]
    assert reviews.label_overrides(rs, NOW) == {1: "unclassified", 2: "everyday_spending"}


# ---- one at a time, weekly limit (Helsinki calendar week, wall clock) -----------------------------

def test_one_pending_review_at_a_time():
    assert reviews.may_create([], NOW)
    assert not reviews.may_create([review()], NOW)
    assert reviews.may_create([review(basket="everyday_spending", answered=NOW)], NOW)


def test_week_starts_monday_midnight_in_helsinki():
    start = reviews.week_start(NOW)
    assert start == datetime(2026, 11, 9, 0, 0, tzinfo=reviews.HELSINKI)
    assert start.astimezone(UTC) == datetime(2026, 11, 8, 22, 0, tzinfo=UTC)   # UTC+2 in November
    # Sunday 23:30 Helsinki is still the old week; Monday 00:30 Helsinki is the new one.
    sunday_late = datetime(2026, 11, 15, 21, 30, tzinfo=UTC)
    monday_early = datetime(2026, 11, 15, 22, 30, tzinfo=UTC)
    assert reviews.week_start(sunday_late) == start
    assert reviews.week_start(monday_early) == datetime(2026, 11, 16, 0, 0, tzinfo=reviews.HELSINKI)
    # summer time: UTC+3
    assert reviews.week_start(datetime(2026, 7, 1, 12, tzinfo=UTC)).astimezone(UTC) == datetime(
        2026, 6, 28, 21, 0, tzinfo=UTC)


def test_at_most_three_reviews_created_per_calendar_week():
    monday = reviews.week_start(NOW).astimezone(UTC)
    done = [review(i, created=monday + timedelta(hours=i), basket="everyday_spending", answered=NOW)
            for i in (1, 2, 3)]
    assert not reviews.may_create(done, NOW)
    assert reviews.may_create(done[:2], NOW)
    last_week = [review(i, created=monday - timedelta(hours=i), basket="everyday_spending", answered=NOW)
                 for i in (1, 2, 3)]
    assert reviews.may_create(last_week, NOW)                              # a new week, a new limit


# ---- selection ------------------------------------------------------------------------------------

def history_with_spikes() -> list[Tx]:
    """Ten small purchases per category over the year, then spikes (> 5 x median) in the window."""
    out, i = [], 100
    for cat, mcc in (("Home & Tech", "5200"), ("Entertainment", "7922"), ("Health", "8011"),
                     ("Groceries", "5411"), ("Lifestyle", "5912")):
        for k in range(10):
            out.append(tx(i, date(2025, 11, 1) + timedelta(days=30 * k), cat, "-20.00", mcc))
            i += 1
    out += [
        tx(1, date(2026, 9, 28), "Home & Tech", "-1080.42", "5200"),      # most recent
        tx(2, date(2026, 9, 28), "Entertainment", "-300.00", "7922"),     # same day, smaller
        tx(3, date(2026, 9, 20), "Entertainment", "-900.00", "7922"),     # older
        tx(4, date(2026, 9, 29), "Health", "-2000.00", "8011"),           # Health: never asked (R9)
        tx(5, date(2026, 9, 29), "Lifestyle", "-500.00", "5912"),         # a health MCC: never asked
        tx(6, date(2026, 9, 29), "Groceries", "-400.00", "5411"),         # a one-off grocery: needed by rule
        tx(7, date(2026, 3, 15), "Home & Tech", "-999.00", "5200"),       # outside the 6-month window
        tx(8, date(2026, 9, 27), "Entertainment", "-30.00", "7922"),      # not a spike
    ]
    return out


def test_candidates_order_and_exclusions():
    rows = classify(history_with_spikes(), AS_OF)
    got = [c.tx.id for c in reviews.candidates(rows, AS_OF, asked=set())]
    # 6 is a one-off grocery purchase, which the rules put in unexpected_necessities: it qualifies.
    assert got == [6, 1, 2, 3]
    assert [c.tx.id for c in reviews.candidates(rows, AS_OF, asked={6, 1})] == [2, 3]


def test_same_day_ties_break_on_amount_then_id():
    h = history_with_spikes() + [tx(9, date(2026, 9, 28), "Home & Tech", "-1080.42", "5200")]
    rows = classify(h, AS_OF)
    got = [c.tx.id for c in reviews.candidates(rows, AS_OF, set()) if c.tx.tx_date == date(2026, 9, 28)]
    assert got == [1, 9, 2]


def test_next_candidate_respects_limits_and_never_asks_twice():
    h = history_with_spikes()
    assert reviews.next_candidate(h, AS_OF, [], NOW).id == 6
    assert reviews.next_candidate(h, AS_OF, [review(6)], NOW) is None                  # one pending
    closed = review(6, created=NOW - timedelta(days=8))
    assert reviews.next_candidate(h, AS_OF, [closed], NOW).id == 1                    # closed: not again
    answered = [review(i, basket="everyday_spending", answered=NOW) for i in (6, 1, 2)]
    assert reviews.next_candidate(h, AS_OF, answered, NOW) is None                     # weekly limit


def test_tx_ref_is_random_and_opaque():
    refs = {reviews.new_tx_ref() for _ in range(200)}
    assert len(refs) == 200
    assert all(reviews.TX_REF.fullmatch(r) for r in refs)


@pytest.mark.parametrize("value, on", [(None, True), ("", True), ("on", True), ("off", False), ("OFF", False),
                                       ("0", False), ("false", False), ("no", False)])
def test_switch(monkeypatch, tmp_path, value, on):
    monkeypatch.setattr(reviews, "ROOT", tmp_path)                         # no .env
    if value is None:
        monkeypatch.delenv("SPIKE_REVIEWS", raising=False)
    else:
        monkeypatch.setenv("SPIKE_REVIEWS", value)
    assert reviews.enabled() is on


def test_switch_off_reads_no_labels_and_makes_no_query():
    class NoQueries:
        def execute(self, *a, **kw):
            raise AssertionError("no query when SPIKE_REVIEWS is off")

    assert labels.basket_labels(NoQueries(), "CUST00860", AS_OF) == {}                 # the suite runs off
    assert reviews.get_pending(NoQueries(), "CUST00860", AS_OF) is None
    assert reviews.ensure_pending(NoQueries(), "CUST00860", AS_OF, []) is None


# ---- labels in the metric SQL and in evidence specs -------------------------------------------------

def test_metric_settings_are_canonical_and_absent_without_labels():
    assert labels.metric_settings({}) == {}
    s = labels.metric_settings({606016: "unclassified", 12: "everyday_spending"})
    assert s == {"tx_labels": '{"12":"everyday_spending","606016":"unclassified"}'}
    assert json.loads(s["tx_labels"]) == {"12": "everyday_spending", "606016": "unclassified"}


def test_transactions_spec_carries_labels_only_when_there_are_any():
    sel = Selection(direction="out", start=date(2026, 4, 1), end=date(2026, 9, 30))
    plain = evidence.transactions_spec("CUST00860", AS_OF, "spending.total@1", sel, Decimal("1.00"))
    assert "labels" not in plain
    assert evidence.transactions_spec("CUST00860", AS_OF, "spending.total@1", sel, Decimal("1.00"), None, []) == plain
    labelled = evidence.transactions_spec("CUST00860", AS_OF, "spending.total@1", sel, Decimal("1.00"), None,
                                          labels.label_set({606016: "unclassified"}))
    assert labelled["labels"] == [[606016, "unclassified"]]
    assert evidence.make_ref(labelled) != evidence.make_ref(plain)       # a label set gives a new ref


def test_selection_tx_ids_round_trip_and_filter():
    sel = Selection(direction="out", start=date(2026, 9, 28), end=date(2026, 9, 28), categories=("Home & Tech",),
                    tx_ids=(1,))
    assert Selection.from_spec(sel.to_spec()) == sel
    plain = Selection(direction="out", start=date(2026, 9, 28), end=date(2026, 9, 28))
    assert "tx_ids" not in plain.to_spec()                               # other refs do not change
    rows = classify(history_with_spikes() + [tx(9, date(2026, 9, 28), "Home & Tech", "-5.00", "5200")], AS_OF)
    assert [c.tx.id for c in select(rows, sel)] == [1]


def test_shared_block_identical_in_02_to_06_and_reads_tx_labels():
    blocks = {}
    for f in ("02_baskets.sql", "03_safe_to_spend.sql", "04_what_if.sql", "05_spender_profile.sql",
              "06_peer_benchmark.sql"):
        text = (METRICS / f).read_text(encoding="utf-8")
        m = re.search(r"^-- -+ shared classification block: begin -*$\n(.*?)^-- -+ shared classification block: end",
                      text, re.S | re.M)
        blocks[f] = hashlib.md5(m.group(1).encode()).hexdigest()
        assert "current_setting('app.tx_labels', true)" in m.group(1)
        assert "pg_input_is_valid" in m.group(1)                         # a malformed setting = no labels
    assert len(set(blocks.values())) == 1, blocks
