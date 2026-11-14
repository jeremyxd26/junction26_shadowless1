"""Shared test setup for core/bills: the repository root goes on sys.path so tests import
`core.bills.*` (core/ has no __init__.py). The bill parser needs no database."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
