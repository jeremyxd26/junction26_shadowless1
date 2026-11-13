"""The server-bound context every tool receives, and the per-answer number registry.

The customer id, as_of and language come only from here, never from tool arguments (R4, R5).
Number ids (n1, n2, ...) are allocated by the registry, which the orchestrator owns for one
answer; a tool only registers the numbers it puts into its model view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import psycopg

from core.tools.db import Db, Tx, load_transactions
from core.tools.models import Number


class NumberRegistry:
    """Gives each number of one answer an id. The same evidence ref always gets the same id."""

    def __init__(self) -> None:
        self._by_id: dict[str, Number] = {}
        self._by_ref: dict[str, str] = {}

    def register(self, number: Number) -> Number:
        if number.evidence_ref and number.evidence_ref in self._by_ref:
            return number.model_copy(update={"id": self._by_ref[number.evidence_ref]})
        number_id = f"n{len(self._by_id) + 1}"
        registered = number.model_copy(update={"id": number_id})
        self._by_id[number_id] = registered
        if number.evidence_ref:
            self._by_ref[number.evidence_ref] = number_id
        return registered

    def get(self, number_id: str) -> Number:
        return self._by_id[number_id]

    def all(self) -> dict[str, Number]:
        return dict(self._by_id)


@dataclass
class ToolContext:
    customer_id: str
    as_of: date
    conn: Db | psycopg.Connection  # db.connect() returns Db, whose repr hides connection details
    language: str = "en"
    numbers: NumberRegistry = field(default_factory=NumberRegistry)
    _history: list[Tx] | None = field(default=None, repr=False)

    def history(self) -> list[Tx]:
        """The customer's transactions up to as_of, read once per context."""
        if self._history is None:
            self._history = load_transactions(self.conn, self.customer_id, self.as_of)
        return self._history
