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

Viewer sessions (#144). On the public demo service anyone could answer a persona's review, so the
answers given through the API belong to one viewer:
- `spike_reviews` holds the question, shared by everyone: which purchase, its `tx_ref`, created and
  expiry time. Creation, the weekly limit and "never twice" stay shared. Its own `basket` is the shared
  answer that tools and scripts can still write without a viewer; the API never writes it.
- `spike_review_answers` holds one viewer's answer per review, keyed by a hash of the viewer cookie
  (never the cookie itself). For that viewer, an answer row wins over the shared answer, also after an
  undo (basket NULL). Without a viewer, or without an answer row, the shared state applies.
- A viewer's answers live SESSION_TTL after the first one; at most MAX_SESSIONS viewers have answers
  at a time (the oldest are dropped), and a viewer has at most MAX_ANSWERS_PER_SESSION answer rows.
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

ANSWERS_DDL = """
CREATE TABLE IF NOT EXISTS spike_review_answers (
    session_key  text        NOT NULL,
    customer_id  text        NOT NULL,
    tx_id        bigint      NOT NULL,
    basket       text CHECK (basket IN ('unexpected_necessities', 'everyday_spending')),
    answered_at  timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_active  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_key, customer_id, tx_id),
    FOREIGN KEY (customer_id, tx_id) REFERENCES spike_reviews (customer_id, tx_id) ON DELETE CASCADE
)
"""
SESSION_TTL = timedelta(hours=2)
# A storage bound, not a security boundary (review of #144): with at most 20 rows each the table stays
# small. New sessions per address are limited in the API, so filling it costs hundreds of address-hours,
# and the least recently active viewer is the one dropped (`last_active`, refreshed on every write).
MAX_SESSIONS = 10_000
MAX_ANSWERS_PER_SESSION = 20
SESSION_KEY = re.compile(r"^[0-9a-f]{64}$")


class ReviewNotFound(Exception):
    """Unknown tx_ref, another customer's, or a closed review: all answered with the same 404 (R4)."""


class BasketNotAllowed(Exception):
    """A basket key that is not one of the review's two options."""


class TooManyAnswers(Exception):
    """A viewer session already holds MAX_ANSWERS_PER_SESSION answer rows (answered with a 429)."""


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


def is_open(review: Review, now: datetime) -> bool:
    """Created less than REVIEW_DAYS ago: it can still be answered, changed or undone (any state)."""
    return now < review.expires_at


def may_create(reviews: list[Review], now: datetime) -> bool:
    """A new review only when none of the customer's reviews is still open, so a customer has at most
    one open review per 7 days and an undo can never meet a second pending review (review of #141);
    WEEKLY_LIMIT per calendar week stays as an upper bound."""
    return not any(is_open(r, now) for r in reviews) and created_this_week(reviews, now) < WEEKLY_LIMIT


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
    """CREATE TABLE IF NOT EXISTS spike_reviews and spike_review_answers: the tables this feature creates."""
    conn.execute(DDL)
    conn.execute(ANSWERS_DDL)


def tables_exist(conn: psycopg.Connection) -> tuple[bool, bool]:
    """(spike_reviews exists, spike_review_answers exists), in one round trip."""
    row = conn.execute("SELECT to_regclass('spike_reviews') IS NOT NULL, "
                       "to_regclass('spike_review_answers') IS NOT NULL").fetchone()
    return bool(row[0]), bool(row[1])


def table_exists(conn: psycopg.Connection) -> bool:
    return tables_exist(conn)[0]


def _review(row: tuple) -> Review:
    return Review(*row)


_R_COLUMNS = ", ".join("r." + c.strip() for c in COLUMNS.split(","))


def _load(conn: psycopg.Connection, customer_id: str, as_of: date | None = None, viewer: str | None = None,
          now: datetime | None = None) -> tuple[list[Review], list[Review]]:
    """(shared, the viewer's): the customer's reviews as everyone sees them, and with the viewer's live
    answer rows applied. One indexed read of a few rows; with as_of, only transactions up to it."""
    reviews_ok, answers_ok = tables_exist(conn)
    if not reviews_ok:
        return [], []
    use_answers = viewer is not None and answers_ok
    sql = f"SELECT {_R_COLUMNS}"
    if use_answers:
        sql += ", a.session_key IS NOT NULL, a.basket, a.answered_at"
    sql += " FROM spike_reviews r"
    if as_of is not None:
        sql += " JOIN transactions t ON t.id = r.tx_id AND t.customer_id = r.customer_id"
    if use_answers:
        sql += (" LEFT JOIN spike_review_answers a ON a.session_key = %(viewer)s"
                " AND a.customer_id = r.customer_id AND a.tx_id = r.tx_id AND a.created_at > %(fresh_after)s")
    sql += " WHERE r.customer_id = %(customer_id)s"
    if as_of is not None:
        sql += " AND t.tx_date <= %(as_of)s"
    params = {"customer_id": customer_id, "as_of": as_of, "viewer": viewer,
              "fresh_after": (now or utcnow()) - SESSION_TTL}
    shared: list[Review] = []
    mine: list[Review] = []
    for row in conn.execute(sql, params).fetchall():
        review = _review(row[:7])
        shared.append(review)
        mine.append(replace(review, basket=row[8], answered_at=row[9]) if use_answers and row[7] else review)
    return shared, mine


def load_reviews(conn: psycopg.Connection, customer_id: str, as_of: date | None = None,
                 viewer: str | None = None, now: datetime | None = None) -> list[Review]:
    """The customer's reviews as `viewer` sees them (as everyone does without a viewer)."""
    return _load(conn, customer_id, as_of, viewer, now)[1]


def get_pending(conn: psycopg.Connection, customer_id: str, as_of: date, now: datetime | None = None,
                viewer: str | None = None) -> Review | None:
    """The viewer's pending review, read-only. An answer (/api/ask) may attach it but never creates one."""
    if not enabled():
        return None
    now = now or utcnow()
    return pending_of(load_reviews(conn, customer_id, as_of, viewer, now), now)


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
    pending = pending_of(current, now)
    if pending is not None or not may_create(current, now):  # checked again under the lock
        return pending
    return _create_pending(conn, customer_id, as_of, history, now)


def ensure_pending_for(ctx: Any, now: datetime | None = None) -> Review | None:
    """ensure_pending for a ToolContext and its viewer (#144): the review pending for that viewer.

    Creation follows the shared state, so a viewer's answer never makes the server ask about another
    purchase. The reviews it read become the context's labels, so the tools of the same request read
    no reviews again (core.tools.labels.for_context)."""
    if not enabled():
        return None
    now = now or utcnow()
    shared, mine = _load(ctx.conn, ctx.customer_id, ctx.as_of, ctx.viewer, now)
    if pending_of(shared, now) is None and may_create(shared, now):  # checked again under the lock
        created = _create_pending(ctx.conn, ctx.customer_id, ctx.as_of, ctx.history, now)
        if created is not None and all(r.tx_id != created.tx_id for r in shared):
            mine = [*mine, created]  # new for everyone; a candidate comes from the history up to as_of
    ctx._labels = label_overrides(mine, now)
    return pending_of(mine, now)


def lock_customer(conn: psycopg.Connection, customer_id: str) -> None:
    """The per-customer lock (transaction-level) that review creation and every label write take, so
    the "one open review" rule cannot race with an answer or an undo."""
    _lock(conn, "spike_reviews", f"customer:{customer_id}")


def _lock(conn: psycopg.Connection, table: str, key: str) -> None:
    """A transaction-level advisory lock named after the table it guards, by its OID, and a key. A
    test's private copies of the tables (private_tables) have other OIDs, so a test never waits for, or
    holds up, the dev service's locks on the shared tables."""
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended("
                 "COALESCE(to_regclass(%s)::oid::text, 'none') || ':' || %s, 0))", (table, key))


def private_tables(conn: psycopg.Connection) -> None:
    """Tests only: session-private (temporary) copies of both tables, dropped at the end of the current
    transaction. PostgreSQL looks up the temporary schema first, so every query of this module in that
    transaction uses them, and a rolled-back test takes no lock on the shared tables the dev service
    serves from (a test that deleted the persona's live row held up the live service, review of #144)."""
    for ddl in (DDL, ANSWERS_DDL):
        conn.execute(ddl.replace("CREATE TABLE IF NOT EXISTS", "CREATE TEMP TABLE").strip() + " ON COMMIT DROP")


def _ensure_table_once(conn: psycopg.Connection) -> None:
    """Create the table under one global lock, so first serves for different customers on a fresh
    database cannot race on CREATE TABLE IF NOT EXISTS (which can fail with a duplicate type)."""
    if not table_exists(conn):
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('spike_reviews:ddl', 0))")
        ensure_table(conn)


def _create_pending(conn: psycopg.Connection, customer_id: str, as_of: date, history: History,
                    now: datetime) -> Review | None:
    with conn.transaction():
        lock_customer(conn, customer_id)
        _ensure_table_once(conn)
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


def find(conn: psycopg.Connection, customer_id: str, tx_ref: str, *, lock: bool = False,
         viewer: str | None = None, now: datetime | None = None) -> Review:
    """The customer's review with this tx_ref, as `viewer` sees it. ReviewNotFound for a malformed,
    unknown or foreign ref. `lock` locks the shared row (the shared answer is written to it)."""
    if not TX_REF.fullmatch(tx_ref or ""):
        raise ReviewNotFound(tx_ref)
    reviews_ok, answers_ok = tables_exist(conn)
    if not reviews_ok:
        raise ReviewNotFound(tx_ref)
    row = conn.execute(
        f"SELECT {COLUMNS} FROM spike_reviews WHERE tx_ref = %s AND customer_id = %s"
        + (" FOR UPDATE" if lock else ""), (tx_ref, customer_id)).fetchone()
    if row is None:
        raise ReviewNotFound(tx_ref)
    review = _review(row)
    if viewer is not None and answers_ok:
        answer = conn.execute(
            "SELECT basket, answered_at FROM spike_review_answers WHERE session_key = %s AND customer_id = %s "
            "AND tx_id = %s AND created_at > %s",
            (viewer, customer_id, review.tx_id, (now or utcnow()) - SESSION_TTL)).fetchone()
        if answer is not None:
            review = replace(review, basket=answer[0], answered_at=answer[1])
    return review


def save(conn: psycopg.Connection, review: Review) -> None:
    """Write the shared answer (basket and answered_at); nothing else of a row ever changes. Tools and
    scripts only: the API writes per viewer (save_answer)."""
    conn.execute("UPDATE spike_reviews SET basket = %s, answered_at = %s WHERE customer_id = %s AND tx_id = %s",
                 (review.basket, review.answered_at, review.customer_id, review.tx_id))


def lock_viewer(conn: psycopg.Connection, viewer: str, customer_id: str) -> None:
    """Serialise one viewer's label writes for one customer (transaction-level advisory lock)."""
    _lock(conn, "spike_review_answers", f"viewer:{viewer}:{customer_id}")


def save_answer(conn: psycopg.Connection, viewer: str, review: Review, now: datetime) -> None:
    """Write one viewer's answer to a review (an upsert), within the session limits.

    Expired rows of this viewer are dropped first. A viewer's first answer admits a new session:
    expired answers of every viewer are deleted and, at MAX_SESSIONS, the least recently active
    viewers lose theirs. A viewer with MAX_ANSWERS_PER_SESSION rows cannot add another review.
    """
    if not SESSION_KEY.fullmatch(viewer or ""):
        raise ValueError("not a session key")
    if not tables_exist(conn)[1]:  # a database where spike_reviews predates #144
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('spike_reviews:ddl', 0))")
        conn.execute(ANSWERS_DDL)
    conn.execute("DELETE FROM spike_review_answers WHERE session_key = %s AND created_at <= %s",
                 (viewer, now - SESSION_TTL))
    n_rows, has_row = conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE customer_id = %s AND tx_id = %s) "
        "FROM spike_review_answers WHERE session_key = %s", (review.customer_id, review.tx_id, viewer)).fetchone()
    if n_rows == 0:
        _admit_session(conn, now)
    elif not has_row and n_rows >= MAX_ANSWERS_PER_SESSION:
        raise TooManyAnswers()
    conn.execute(
        "INSERT INTO spike_review_answers (session_key, customer_id, tx_id, basket, answered_at, created_at, "
        "last_active) VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (session_key, customer_id, tx_id) "
        "DO UPDATE SET basket = EXCLUDED.basket, answered_at = EXCLUDED.answered_at, "
        "last_active = EXCLUDED.last_active",
        (viewer, review.customer_id, review.tx_id, review.basket, review.answered_at, now, now))
    # every write is activity of the whole session, so none of its rows looks idle
    conn.execute("UPDATE spike_review_answers SET last_active = %s WHERE session_key = %s", (now, viewer))


def _admit_session(conn: psycopg.Connection, now: datetime) -> None:
    """Room for one more viewer: expired answers go, then, at MAX_SESSIONS, the least recently active."""
    _lock(conn, "spike_review_answers", "admit")
    conn.execute("DELETE FROM spike_review_answers WHERE created_at <= %s", (now - SESSION_TTL,))
    n = conn.execute("SELECT count(DISTINCT session_key) FROM spike_review_answers").fetchone()[0]
    if n >= MAX_SESSIONS:
        conn.execute(
            "DELETE FROM spike_review_answers WHERE session_key IN ("
            " SELECT session_key FROM spike_review_answers GROUP BY session_key"
            " ORDER BY max(last_active), session_key LIMIT %s)", (n - MAX_SESSIONS + 1,))


def viewer_established(conn: psycopg.Connection, viewer: str, now: datetime | None = None) -> bool:
    """Whether this viewer already has a live answer row (so its next answer admits no new session)."""
    if not tables_exist(conn)[1]:
        return False
    row = conn.execute("SELECT 1 FROM spike_review_answers WHERE session_key = %s AND created_at > %s LIMIT 1",
                       (viewer, (now or utcnow()) - SESSION_TTL)).fetchone()
    return row is not None


def count_answers(conn: psycopg.Connection, customer_ids: list[str]) -> int:
    """Viewer answer rows of these customers (for the reset script)."""
    if not tables_exist(conn)[1]:
        return 0
    return conn.execute("SELECT count(*) FROM spike_review_answers WHERE customer_id = ANY(%s)",
                        (list(customer_ids),)).fetchone()[0]


def reset(conn: psycopg.Connection, customer_ids: list[str]) -> int:
    """Delete these customers' reviews (the demo reset); every viewer's answers to them go with them
    (ON DELETE CASCADE). Labels live only in these two tables."""
    if not customer_ids:
        raise ValueError("reset needs explicit customer ids")
    if not table_exists(conn):
        return 0
    return conn.execute("DELETE FROM spike_reviews WHERE customer_id = ANY(%s)", (list(customer_ids),)).rowcount


def label_state(conn: psycopg.Connection, customer_id: str, as_of: date, now: datetime | None = None,
                viewer: str | None = None) -> dict[str, Any]:
    """For the audit record of an answer: how many labels and pending reviews its numbers include (for
    that viewer). The viewer itself is never part of the record."""
    if not enabled():
        return {"spike_reviews": "off", "labels": 0, "pending": 0}
    now = now or utcnow()
    overrides = label_overrides(load_reviews(conn, customer_id, as_of, viewer, now), now)
    pending = sum(1 for b in overrides.values() if b == UNCLASSIFIED)
    return {"spike_reviews": "on", "labels": len(overrides) - pending, "pending": pending}
