"""Shared test setup for core/tools.

The repository root goes on sys.path so tests import `core.tools.*` (core/ has no __init__.py).
Database-backed tests use one session-scoped connection and are skipped when DATABASE_URL is
not set in the environment or in the repository's .env file.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tools import db  # noqa: E402


@pytest.fixture(scope="session")
def conn():
    """One connection for the whole test session (database limit: 1 connection)."""
    if not db.database_url(required=False):
        pytest.skip("DATABASE_URL is not set; database-backed tests skipped")
    connection = db.connect()
    db.ensure_evidence_table(connection)
    yield connection
    connection.close()
