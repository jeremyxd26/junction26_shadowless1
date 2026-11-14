from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# `pytest core` does not put the repository root on sys.path; the service is imported as `core.app`.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SETTINGS_ENV = ("DATABASE_URL", "DEMO_TODAY", "GEMINI_API_KEY", "GEMINI_MODEL", "CORS_ORIGINS",
                "DEMO_CUSTOMERS")

@pytest.fixture(scope="session", autouse=True)
def spike_reviews_off():
    """Tests see the published numbers whatever the demo answered on the shared database: no label is
    read and no review is created. Session-scoped, so it is set before any module or session fixture
    calls the API. Spike-review tests switch it on inside a rolled-back transaction (#68)."""
    previous = os.environ.get("SPIKE_REVIEWS")
    os.environ["SPIKE_REVIEWS"] = "off"
    yield
    if previous is None:
        os.environ.pop("SPIKE_REVIEWS", None)
    else:
        os.environ["SPIKE_REVIEWS"] = previous


@pytest.fixture
def unreachable_db() -> str:
    """A database URL nobody listens on (port 1), so connecting fails at once."""
    return "postgresql://coach:not-a-real-password@127.0.0.1:1/coach"


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove the service's variables from the environment; tests pass `_env_file=None` to skip `.env`."""
    for name in SETTINGS_ENV:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def real_database_url() -> str:
    """The configured DATABASE_URL (environment or `.env`); skips the test when there is none."""
    from core.app.settings import Settings

    url = Settings().database_url
    if url is None:
        pytest.skip("DATABASE_URL is not set")
    return url.get_secret_value()
