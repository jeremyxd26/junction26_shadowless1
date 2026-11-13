from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from core.app.db import DEFAULT_POOL_MAX, check_ready, create_pool
from core.app.main import create_app
from core.app.settings import Settings


def test_pool_limits(unreachable_db):
    pool = create_pool(unreachable_db)  # created closed: no connection is attempted
    assert DEFAULT_POOL_MAX == 10
    assert pool.max_size == 10
    assert pool.min_size == 1
    assert create_pool(unreachable_db, max_size=3).max_size == 3


def test_pool_size_is_a_setting(clean_env):
    assert Settings(_env_file=None).db_pool_max == DEFAULT_POOL_MAX
    clean_env.setenv("DB_POOL_MAX", "4")
    assert Settings(_env_file=None).db_pool_max == 4
    for bad in ("0", "51", "many"):
        clean_env.setenv("DB_POOL_MAX", bad)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)


def test_the_service_opens_its_pool_with_the_setting(clean_env, unreachable_db):
    settings = Settings(_env_file=None, database_url=unreachable_db, db_pool_max=3)
    with TestClient(create_app(settings)) as client:
        assert client.app.state.pool.max_size == 3


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
