"""The tool cache with per-viewer answers (#86 with #144).

The database tests use only the transaction's private copies of the spike-review tables
(reviews.private_tables), rolled back at the end, so they never lock or change the rows the dev service
serves from. They are skipped without DATABASE_URL. The first tests need no database.
"""

from __future__ import annotations

import logging
from datetime import date

import pytest

from core.tools import label_answer, reviews, warmup
from core.tools.cache import ToolCache, labels_key_of
from core.tools.context import ToolContext
from core.tools.db import load_transactions
from core.tools.safe_to_spend import GetSafeToSpendArgs, get_safe_to_spend

LEAD = "CUST00860"
AS_OF = date(2026, 9, 30)
A, B, C, D = "a" * 64, "b" * 64, "c" * 64, "d" * 64   # viewer keys, as the API hashes the cookie


# ---- without a database ---------------------------------------------------------------------------------

def test_the_viewer_is_not_part_of_the_key():
    """Viewers with the same label set share one key: only the set is hashed, never the viewer."""
    keys = set()
    for viewer in (None, A, B):
        ctx = ToolContext(customer_id=LEAD, as_of=AS_OF, conn=None, viewer=viewer)
        ctx._labels = {606016: "unclassified"}
        ToolCache(mode="memory").ensure_labels_key(ctx)
        keys.add(ToolCache.key(ctx, "get_safe_to_spend", "{}"))
    assert len(keys) == 1


def test_lookup_without_a_label_set_finds_nothing_and_reads_nothing():
    """A key needs the label set on the context; a preset key alone is never looked up (review of #213)."""
    ctx = ToolContext(customer_id=LEAD, as_of=AS_OF, conn=None)   # no connection: a read would fail
    ctx.labels_key = labels_key_of({})
    assert ToolCache(mode="memory").lookup("get_safe_to_spend", GetSafeToSpendArgs, ctx, {}) is None
    assert ctx._labels is None


def test_the_key_always_follows_the_label_set_on_the_context():
    ctx = ToolContext(customer_id=LEAD, as_of=AS_OF, conn=None)
    ctx._labels, ctx.labels_key = {606016: "unexpected_necessities"}, labels_key_of({})   # a stale preset key
    assert ToolCache(mode="memory").ensure_labels_key(ctx) == labels_key_of({606016: "unexpected_necessities"})


# ---- with the database, on private spike-review tables ----------------------------------------------------

@pytest.fixture
def tx(conn, monkeypatch):
    monkeypatch.setenv("SPIKE_REVIEWS", "on")
    with conn.transaction(force_rollback=True):
        reviews.private_tables(conn)   # temporary copies: no lock on the shared tables
        yield conn


def safe_to_spend(cache: ToolCache, conn, viewer: str | None):
    ctx = ToolContext(customer_id=LEAD, as_of=AS_OF, conn=conn, viewer=viewer)
    result = cache.run("get_safe_to_spend", GetSafeToSpendArgs, get_safe_to_spend, ctx, {})
    return ctx.labels_key, result


def test_two_viewers_with_different_answers_get_their_own_entries(tx, tmp_path, caplog):
    """A answered the spike review "Needed", B has not: different label sets, keys and numbers. C is in
    B's state and shares B's entry. The viewer is in no key, no stored entry and no log line."""
    pending = reviews.ensure_pending(tx, LEAD, AS_OF, load_transactions(tx, LEAD, AS_OF))
    label_answer.answer(tx, LEAD, AS_OF, pending.tx_ref, "unexpected_necessities", viewer=A)
    caplog.clear()
    caplog.set_level(logging.DEBUG)

    cache = ToolCache(mode="disk", directory=tmp_path)
    key_a, a = safe_to_spend(cache, tx, A)
    key_b, b = safe_to_spend(cache, tx, B)
    key_c, c = safe_to_spend(cache, tx, C)

    assert (a.data.safe_to_spend.value, b.data.safe_to_spend.value) == (180.26, 221.58)
    assert key_a != key_b and key_c == key_b
    assert cache.stats.misses == 2 and cache.stats.hits == 1
    assert c.model_dump_json() == b.model_dump_json()
    stored = b"".join(path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
    assert stored   # the disk layer holds the two entries
    for viewer in (A, B, C):
        assert viewer.encode() not in stored
        assert not [r for r in caplog.records if viewer in r.getMessage()]


def test_the_warm_up_warms_the_label_set_a_new_viewer_starts_with(tx):
    """The warm-up runs without a viewer; a new viewer (no answers) sees the same shared state, so its
    first call is a hit. The pending review exists first, as after the first overview (#240 moves its
    creation into the warm-up)."""
    reviews.ensure_pending(tx, LEAD, AS_OF, load_transactions(tx, LEAD, AS_OF))
    cache = ToolCache(mode="memory")
    calls = [call for call in warmup.CALLS if call.function == "get_safe_to_spend"]
    warmup.warm(cache, tx, [LEAD], ["en"], AS_OF, out=lambda _: None, calls=calls)
    assert cache.stats.misses == 1

    _, first = safe_to_spend(cache, tx, D)
    assert cache.stats.hits == 1 and cache.stats.misses == 1
    assert first.data.safe_to_spend.value == 221.58   # the pending state, as B above
