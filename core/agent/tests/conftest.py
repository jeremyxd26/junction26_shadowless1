"""Fixtures for the answer pipeline tests; the fakes themselves are in agent_fakes.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from agent_fakes import AS_OF, FakeData, Pipeline, registry  # noqa: E402

from core.agent.audit import AuditLog  # noqa: E402


@pytest.fixture
def make_pipeline(tmp_path):
    def make(model, reg=None, data=None):
        return Pipeline(reg or registry(), model, data or FakeData(), as_of=AS_OF, audit=AuditLog(tmp_path / "audit"))
    return make




@pytest.fixture(autouse=True)
def tool_cache_off(monkeypatch):
    """The service's global tool cache (#86) is off in these tests, so a fake tool always runs; a test
    that checks the cache turns it on in memory. Never the disk layer."""
    from core.tools.cache import TOOL_CACHE, Stats

    monkeypatch.setattr(TOOL_CACHE, "mode", "off")
    monkeypatch.setattr(TOOL_CACHE, "stats", Stats())   # counters per test
    TOOL_CACHE._memory.clear()
    yield TOOL_CACHE
    TOOL_CACHE._memory.clear()
