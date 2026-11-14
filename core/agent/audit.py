"""The audit record of every answer, appended as JSON lines (agent-core.md section 9.1, R15).

Directory: AUDIT_LOG_DIR, default var/audit/ in the repository (git-ignored), one file per day.
The record holds the question, the planner turns with their calls and arguments, the tool outputs as
model views, the numbers, the composer attempts, the validated text, the outcome and the timings.
It never holds transaction rows (tools contribute their model view only) or secrets.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def default_dir() -> Path:
    return Path(os.environ.get("AUDIT_LOG_DIR") or ROOT / "var" / "audit")


class AuditLog:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else default_dir()
        self._lock = threading.Lock()

    def _file(self, when: datetime) -> Path:
        return self.directory / f"{when:%Y-%m-%d}.jsonl"

    def write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, default=str, separators=(",", ":"))
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            with self._file(datetime.now(timezone.utc)).open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def find(self, answer_id: str) -> dict[str, Any] | None:
        """The record of one answer, newest files first (internal lookup for the team and the eval)."""
        if not self.directory.exists():
            return None
        for path in sorted(self.directory.glob("*.jsonl"), reverse=True):
            with path.open(encoding="utf-8") as f:
                for line in f:
                    if f'"answer_id":"{answer_id}"' in line:
                        return json.loads(line)
        return None
