"""Shared test setup for core/tools.

The repository root goes on sys.path so tests import `core.tools.*` (core/ has no __init__.py).
Database-backed tests use one session-scoped connection and are skipped when DATABASE_URL is
not set in the environment or in the repository's .env file.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tools import db  # noqa: E402

# Database tests read the four personas only on the shared database (#502). A test that reads a sample
# customer (CUST00001, CUST00002, CUST00006: the worked numbers of metrics.md) carries this marker and runs
# only when asked for, on a private database: DB_SAMPLE_CUSTOMERS=1.
SAMPLE_CUSTOMERS_ENV = "DB_SAMPLE_CUSTOMERS"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "sample_customer: reads a sample customer from the database; skipped unless "
                   f"{SAMPLE_CUSTOMERS_ENV}=1 (the shared database is for the four personas)")


def pytest_collection_modifyitems(config, items):
    if os.environ.get(SAMPLE_CUSTOMERS_ENV) == "1":
        return
    skip = pytest.mark.skip(reason="reads a sample customer: the shared database is for the four personas "
                                   f"({SAMPLE_CUSTOMERS_ENV}=1 runs it on a private database)")
    for item in items:
        if "sample_customer" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def spike_reviews_off():
    """Tests see the published numbers whatever the demo answered on the shared database: no label is
    read and no review is created. Session-scoped, so it is set before any module or session fixture
    calls a tool. Spike-review tests switch it on inside a rolled-back transaction (#68)."""
    previous = os.environ.get("SPIKE_REVIEWS")
    os.environ["SPIKE_REVIEWS"] = "off"
    yield
    if previous is None:
        os.environ.pop("SPIKE_REVIEWS", None)
    else:
        os.environ["SPIKE_REVIEWS"] = previous


@pytest.fixture(scope="session")
def conn():
    """One connection for the whole test session (database limit: 1 connection)."""
    if not db.database_url(required=False):
        pytest.skip("DATABASE_URL is not set; database-backed tests skipped")
    connection = db.connect()
    db.ensure_evidence_table(connection)
    yield connection
    connection.close()
