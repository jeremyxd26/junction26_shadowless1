"""The test harness imports core.tools from the repository root."""

from core.tools import db


def test_package_imports():
    assert db.STATEMENT_TIMEOUT == "60s"
