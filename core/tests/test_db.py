from __future__ import annotations

from core.app.db import MAX_CONNECTIONS, check_ready, create_pool


def test_pool_limits(unreachable_db):
    pool = create_pool(unreachable_db)  # created closed: no connection is attempted
    assert MAX_CONNECTIONS == 2
    assert pool.max_size == 2
    assert pool.min_size == 1


def test_check_ready_without_pool():
    assert check_ready(None) == "DATABASE_URL is not set"


def test_sessions_use_statement_timeout(real_database_url):
    pool = create_pool(real_database_url)
    pool.open(wait=True, timeout=15)
    try:
        assert check_ready(pool) is None
        with pool.connection() as conn:
            assert conn.execute("SHOW statement_timeout").fetchone()[0] == "1min"
    finally:
        pool.close()
