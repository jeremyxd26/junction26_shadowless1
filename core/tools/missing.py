"""Why a data tool has nothing to show (#379): a closed list of reasons the answer turns into words.

- category_absent: the customer has no spending in that category or merchant category in the whole data;
- too_few_transactions: fewer purchases than config.TOO_FEW_TRANSACTIONS behind a monthly figure.
Periods outside the data raise periods.PeriodOutOfRange (period_before_data, period_in_future).
The details are what the answer may say: labels without digits. Numbers the answer may cite travel on the
exception unregistered; the pipeline registers them in the answer's registry (MissingData.register), because the
tool cache keeps no numbers of a call that raises.
"""

from __future__ import annotations

from typing import Any

REASONS = ("category_absent", "too_few_transactions")


class MissingData(Exception):
    def __init__(self, reason: str, numbers: dict[str, Any] | None = None, **details: Any) -> None:
        assert reason in REASONS, reason
        super().__init__(reason)
        self.reason = reason
        self.details = details
        self.numbers = dict(numbers or {})   # key -> Number, not registered yet

    def register(self, registry: Any) -> dict[str, Any]:
        """The details with each Number registered in `registry` and its id under its key."""
        return {**self.details, **{key: registry.register(n).id for key, n in self.numbers.items()}}
