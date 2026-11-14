"""Why a data tool has nothing to show (#379): a closed list of reasons the answer turns into words.

- category_absent: the customer has no spending in that category or merchant category in the whole data;
- too_few_transactions: fewer purchases than config.TOO_FEW_TRANSACTIONS behind a monthly figure.
Periods outside the data raise periods.PeriodOutOfRange (period_before_data, period_in_future).
The details are what the answer may say: labels without digits, and the ids of Numbers the tool registered.
"""

from __future__ import annotations

from typing import Any

REASONS = ("category_absent", "too_few_transactions")


class MissingData(Exception):
    def __init__(self, reason: str, **details: Any) -> None:
        assert reason in REASONS, reason
        super().__init__(reason)
        self.reason = reason
        self.details = details
