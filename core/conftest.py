"""Shared test setup for everything under core/ (#594): no test reaches the bill reader's provider.

Before every test the reader's variables (VERDA_*, NEMOTRON_*, BILL_READER) leave the environment, the reader's
settings stop reading the repository's .env (the sync hook copies the real one into every worktree), and the
transport's default opener refuses and records any attempt. Tests that need a transport pass their own opener."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

READER_PREFIXES = ("VERDA_", "NEMOTRON_")
REFUSED: list[str] = []     # every attempt a test made to open the provider's connection


def isolate_bill_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith(READER_PREFIXES) or name == "BILL_READER":
            monkeypatch.delenv(name, raising=False)
    from core.bills import nemotron

    monkeypatch.setitem(nemotron.NemotronSettings.model_config, "env_file", None)

    def refusing_opener():
        def opener(request, timeout=None):  # noqa: ANN001 - urllib's signature
            REFUSED.append(getattr(request, "full_url", str(request)))
            raise ConnectionError("tests never reach the bill reader's provider")
        return opener

    monkeypatch.setattr(nemotron, "_default_opener", refusing_opener)


@pytest.fixture(autouse=True)
def no_bill_reader_provider(monkeypatch):
    isolate_bill_reader(monkeypatch)
    yield
