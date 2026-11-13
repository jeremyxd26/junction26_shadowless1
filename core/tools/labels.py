"""Customer labels that move a transaction to another basket (metrics.md section 1: a customer's
label on a transaction overrides the rule).

The label table arrives with the spike-review change. Until then this is the single place every
tool and evidence resolution reads labels from, and it returns no labels, runs no query and
creates no table. When labels exist, the same function feeds both the tool and `resolve`, so
evidence keeps reconciling.
"""

from __future__ import annotations

from datetime import date
from typing import Any


def basket_labels(conn: Any, customer_id: str, as_of: date) -> dict[int, str]:
    """Transaction id -> basket key chosen by the customer, for transactions up to as_of."""
    return {}
