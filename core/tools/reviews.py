"""Spike reviews: the coach asks about one spending spike (design doc section 7.8, contract 0.2.0).

One table, `spike_reviews`, holds every review a customer was asked. The state is derived, never stored:
- ANSWERED: `basket` is set ("needed" = unexpected_necessities, "I chose it" = everyday_spending).
  An answered review does not expire.
- PENDING: `basket` is NULL and now < `expires_at` (created_at + 7 days). The purchase is
  `unclassified`: in no basket total and not in the reserve.
- CLOSED: otherwise (expired unanswered, or undone after the 7 days). The purchase is back in the basket
  the rules give it, its `tx_ref` gets 404, and the transaction is never asked about again.

The pure functions below decide everything (selection, limits, transitions) from a list of reviews and
a wall-clock `now`; the database functions only read and write rows. Creation, expiry and the weekly
limit run on the wall clock, never on DEMO_TODAY.

SPIKE_REVIEWS=off (environment, or .env) switches the feature off: no label is read and no review is
created. The test suites run with it off, so they see the published numbers whatever the demo did.
"""

from __future__ import annotations

import os
import re
import secrets
import string
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from core.tools import config
from core.tools.classify import CTx, classify, window
from core.tools.db import ROOT, Tx

PENDING, ANSWERED, CLOSED = "pending", "answered", "closed"
UNCLASSIFIED = "unclassified"
ANSWER_BASKETS = ("unexpected_necessities", "everyday_spending")  # the two options of a review card
REVIEW_DAYS = 7
WEEKLY_LIMIT = 3
HELSINKI = ZoneInfo("Europe/Helsinki")
SENSITIVE_CATEGORIES = frozenset({"Health"})
SENSITIVE_MCCS = frozenset(config.MCC_GROUPS["health"])  # 5912, 8011, 8021, 8099 (R9)
TX_REF_PREFIX = "txr_"
TX_REF_ALPHABET = string.ascii_lowercase + string.digits
TX_REF = re.compile(r"^txr_[a-z0-9]{16}$")
OFF_VALUES = {"off", "0", "false", "no"}

DDL = """
CREATE TABLE IF NOT EXISTS spike_reviews (
    customer_id  text        NOT NULL,
    tx_id        bigint      NOT NULL,
    tx_ref       text        NOT NULL UNIQUE,
    created_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    basket       text CHECK (basket IN ('unexpected_necessities', 'everyday_spending')),
    answered_at  timestamptz,
    PRIMARY KEY (customer_id, tx_id)
)
"""
COLUMNS = "customer_id, tx_id, tx_ref, created_at, expires_at, basket, answered_at"


class ReviewNotFound(Exception):
    """Unknown tx_ref, another customer's, or a closed review: all answered with the same 404 (R4)."""


class BasketNotAllowed(Exception):
    """A basket key that is not one of the review's two options."""


@dataclass(frozen=True)
class Review:
    customer_id: str
    tx_id: int
    tx_ref: str
    created_at: datetime
    expires_at: datetime
    basket: str | None
    answered_at: datetime | None

    def state(self, now: datetime) -> str:
        if self.basket is not None:
            return ANSWERED
        return PENDING if now < self.expires_at else CLOSED


@dataclass(frozen=True)
class Outcome:
    """What a label call does to a review."""

    review: Review   # the review after the call
    state: str       # its state after the call
    changed: bool


# ---- switch and clock ----------------------------------------------------------------------------

def enabled() -> bool:
    """SPIKE_REVIEWS from the environment, else from the repository's .env; on unless set to off."""
    value = os.environ.get("SPIKE_REVIEWS")
    env_file = ROOT / ".env"
    if value is None and env_file.exists():
        match = re.search(r"^SPIKE_REVIEWS=(.*)$", env_file.read_text(encoding="utf-8"), re.M)
        value = match.group(1) if match else None
    return (value or "").strip().strip("\"'").lower() not in OFF_VALUES


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def week_start(now: datetime) -> datetime:
    """Monday 00:00 in Helsinki of the calendar week that contains `now` (an aware datetime)."""
    local = now.astimezone(HELSINKI)
    monday = (local - timedelta(days=local.weekday())).date()
    return datetime(monday.year, monday.month, monday.day, tzinfo=HELSINKI)


def new_tx_ref() -> str:
    """An opaque random token, not derived from the transaction id."""
    return TX_REF_PREFIX + "".join(secrets.choice(TX_REF_ALPHABET) for _ in range(16))


# ---- pure rules ----------------------------------------------------------------------------------

def is_sensitive(t: Tx) -> bool:
    return t.category in SENSITIVE_CATEGORIES or (t.mcc is not None and t.mcc in SENSITIVE_MCCS)


def candidates(rule_rows: list[CTx], as_of: date, asked: set[int]) -> list[CTx]:
    """Reviewable spikes in selection order: most recent day first, then largest, then transaction id.

    `rule_rows` are classified by the rules only (no labels). A candidate is a one-off in the spend
    flow inside the 6-month window, in unexpected_necessities or everyday_spending by the rules, not
    Health or a health MCC, and never asked about before.
    """
    start, end = window(as_of)
    out = [c for c in rule_rows
           if c.flow == "spend" and c.is_one_off and start <= c.tx.tx_date <= end
           and c.basket in ANSWER_BASKETS and not is_sensitive(c.tx) and c.tx.id not in asked]
    out.sort(key=lambda c: (-c.tx.tx_date.toordinal(), -c.out_eur, c.tx.id))
    return out


def pending_of(reviews: list[Review], now: datetime) -> Review | None:
    pending = [r for r in reviews if r.state(now) == PENDING]
    return min(pending, key=lambda r: (r.created_at, r.tx_id)) if pending else None


def created_this_week(reviews: list[Review], now: datetime) -> int:
    start = week_start(now)
    return sum(1 for r in reviews if start <= r.created_at <= now)


def may_create(reviews: list[Review], now: datetime) -> bool:
    """One pending review at a time, and at most WEEKLY_LIMIT created per calendar week."""
    return pending_of(reviews, now) is None and created_this_week(reviews, now) < WEEKLY_LIMIT


def next_candidate(history: list[Tx], as_of: date, reviews: list[Review], now: datetime) -> Tx | None:
    """The transaction to ask about next, or None (nothing qualifies, or a limit applies)."""
    if not may_create(reviews, now):
        return None
    found = candidates(classify(history, as_of), as_of, {r.tx_id for r in reviews})
    return found[0].tx if found else None


def label_overrides(reviews: list[Review], now: datetime) -> dict[int, str]:
    """Transaction id -> basket for classification: the answer, or `unclassified` while pending."""
    out: dict[int, str] = {}
    for r in reviews:
        state = r.state(now)
        if state == ANSWERED:
            out[r.tx_id] = r.basket
        elif state == PENDING:
            out[r.tx_id] = UNCLASSIFIED
    return out


def decide(review: Review, basket: str | None, now: datetime) -> Outcome:
    """The label call's transition (contract section 10.1). Raises ReviewNotFound or BasketNotAllowed.

    - a closed review cannot be answered, changed or undone (no late answers);
    - the same answer again changes nothing;
    - a different answer replaces the label;
    - undo (None) within 7 days of creation makes the review pending again, after them it closes it.
    """
    state = review.state(now)
    if state == CLOSED:
        raise ReviewNotFound(review.tx_ref)
    if basket is not None and basket not in ANSWER_BASKETS:
        raise BasketNotAllowed(basket)
    if basket == review.basket:
        return Outcome(review, state, changed=False)
    if basket is None:
        after = replace(review, basket=None, answered_at=None)
    else:
        after = replace(review, basket=basket, answered_at=now)
    return Outcome(after, after.state(now), changed=True)


# ---- database ------------------------------------------------------------------------------------

def ensure_table(conn: psycopg.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS spike_reviews: the one table this feature creates."""
    conn.execute(DDL)


def table_exists(conn: psycopg.Connection) -> bool:
    return conn.execute("SELECT to_regclass('spike_reviews') IS NOT NULL").fetchone()[0]


def _review(row: tuple) -> Review:
    return Review(*row)


def load_reviews(conn: psycopg.Connection, customer_id: str, as_of: date | None = None) -> list[Review]:
    """The customer's reviews (an indexed read of a few rows); with as_of, only transactions up to it."""
    if not table_exists(conn):
        return []
    if as_of is None:
        rows = conn.execute(f"SELECT {COLUMNS} FROM spike_reviews WHERE customer_id = %s",
                            (customer_id,)).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {', '.join('r.' + c.strip() for c in COLUMNS.split(','))} "
            "FROM spike_reviews r JOIN transactions t ON t.id = r.tx_id AND t.customer_id = r.customer_id "
            "WHERE r.customer_id = %s AND t.tx_date <= %s", (customer_id, as_of)).fetchall()
    return [_review(r) for r in rows]


def get_pending(conn: psycopg.Connection, customer_id: str, as_of: date, now: datetime | None = None
                ) -> Review | None:
    """The pending review, read-only. An answer (/api/ask) may attach it but never creates one."""
    if not enabled():
        return None
    return pending_of(load_reviews(conn, customer_id, as_of), now or utcnow())


History = list[Tx] | Callable[[], list[Tx]]

# (customer, as_of, transactions already asked) for which no transaction qualifies. The dataset does not
# change, so the answer stays the same until a review is created or deleted (which changes the key).
_NO_CANDIDATE: set[tuple[str, date, frozenset[int]]] = set()


def ensure_pending(conn: psycopg.Connection, customer_id: str, as_of: date, history: History,
                   now: datetime | None = None) -> Review | None:
    """The pending review, created on first serve if a spike qualifies and no limit applies.

    The only write of GET /api/overview. Warm path: when a review is pending, one read and nothing
    else (no lock, no history). Otherwise the creation path runs, serialised per customer by a
    transaction-level advisory lock, with an upsert keyed by customer and transaction. `history` may
    be a callable, so the transactions are read only when a candidate has to be looked for.
    """
    if not enabled():
        return None
    now = now or utcnow()
    current = load_reviews(conn, customer_id, as_of)
    return pending_of(current, now) or _create_pending(conn, customer_id, as_of, history, now)


def ensure_pending_for(ctx: Any, now: datetime | None = None) -> Review | None:
    """ensure_pending for a ToolContext, which also keeps the reviews it read as the context's labels,
    so the tools of the same request read no reviews again (core.tools.labels.for_context)."""
    if not enabled():
        return None
    now = now or utcnow()
    current = load_reviews(ctx.conn, ctx.customer_id, ctx.as_of)
    pending = pending_of(current, now)
    if pending is None:
        pending = _create_pending(ctx.conn, ctx.customer_id, ctx.as_of, ctx.history, now)
        if pending is not None and all(r.tx_id != pending.tx_id for r in current):
            current = [*current, pending]  # a candidate comes from the history up to as_of
    ctx._labels = label_overrides(current, now)
    return pending


def _create_pending(conn: psycopg.Connection, customer_id: str, as_of: date, history: History,
                    now: datetime) -> Review | None:
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('spike_reviews:' || %s, 0))",
                     (customer_id,))
        if not table_exists(conn):
            ensure_table(conn)
        reviews = load_reviews(conn, customer_id)
        pending = pending_of(reviews, now)
        if pending is not None:
            return pending  # created by a concurrent request
        if not may_create(reviews, now):
            return None
        key = (customer_id, as_of, frozenset(r.tx_id for r in reviews))
        if key in _NO_CANDIDATE:
            return None
        tx = next_candidate(history() if callable(history) else history, as_of, reviews, now)
        if tx is None:
            _NO_CANDIDATE.add(key)
            return None
        conn.execute(
            "INSERT INTO spike_reviews (customer_id, tx_id, tx_ref, created_at, expires_at) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (customer_id, tx_id) DO NOTHING",
            (customer_id, tx.id, new_tx_ref(), now, now + timedelta(days=REVIEW_DAYS)))
        return pending_of(load_reviews(conn, customer_id), now)


def find(conn: psycopg.Connection, customer_id: str, tx_ref: str, *, lock: bool = False) -> Review:
    """The customer's review with this tx_ref. ReviewNotFound for a malformed, unknown or foreign ref."""
    if not TX_REF.fullmatch(tx_ref or "") or not table_exists(conn):
        raise ReviewNotFound(tx_ref)
    row = conn.execute(
        f"SELECT {COLUMNS} FROM spike_reviews WHERE tx_ref = %s AND customer_id = %s"
        + (" FOR UPDATE" if lock else ""), (tx_ref, customer_id)).fetchone()
    if row is None:
        raise ReviewNotFound(tx_ref)
    return _review(row)


def save(conn: psycopg.Connection, review: Review) -> None:
    """Write a review's answer (basket and answered_at); nothing else of a row ever changes."""
    conn.execute("UPDATE spike_reviews SET basket = %s, answered_at = %s WHERE customer_id = %s AND tx_id = %s",
                 (review.basket, review.answered_at, review.customer_id, review.tx_id))


def reset(conn: psycopg.Connection, customer_ids: list[str]) -> int:
    """Delete these customers' reviews (the demo reset). Labels live only in this table."""
    if not customer_ids:
        raise ValueError("reset needs explicit customer ids")
    if not table_exists(conn):
        return 0
    return conn.execute("DELETE FROM spike_reviews WHERE customer_id = ANY(%s)", (list(customer_ids),)).rowcount


def label_state(conn: psycopg.Connection, customer_id: str, as_of: date, now: datetime | None = None
                ) -> dict[str, Any]:
    """For the audit record of an answer: how many labels and pending reviews its numbers include."""
    if not enabled():
        return {"spike_reviews": "off", "labels": 0, "pending": 0}
    now = now or utcnow()
    overrides = label_overrides(load_reviews(conn, customer_id, as_of), now)
    pending = sum(1 for b in overrides.values() if b == UNCLASSIFIED)
    return {"spike_reviews": "on", "labels": len(overrides) - pending, "pending": pending}
