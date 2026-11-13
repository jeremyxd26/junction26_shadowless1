"""Customer labels that move a transaction to another basket (metrics.md section 1.1: a customer's
label on a transaction overrides the rule).

The labels come from spike reviews (core.tools.reviews, table `spike_reviews`): an answered review
puts its purchase in the chosen basket, a pending one puts it in `unclassified`, a closed one adds
nothing. This is the single place every tool and evidence resolution reads labels from:
- Python classification (`classify(..., overrides)`) takes the dict as it is;
- the metric SQL files take the same labels as the session setting `app.tx_labels`
  (`metric_settings`), so both paths classify a purchase the same way.

With SPIKE_REVIEWS=off, or before the table exists, there are no labels and no query is made
against a missing table.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from core.tools import reviews


def basket_labels(conn: Any, customer_id: str, as_of: date, now: datetime | None = None,
                  viewer: str | None = None) -> dict[int, str]:
    """Transaction id -> basket key chosen by the customer (or `unclassified` while a review is
    pending), for transactions up to as_of, as `viewer` answered (#144; None = the shared state)."""
    if not reviews.enabled():
        return {}
    now = now or reviews.utcnow()
    return reviews.label_overrides(reviews.load_reviews(conn, customer_id, as_of, viewer, now), now)


def for_context(ctx: Any) -> dict[int, str]:
    """The labels for one ToolContext (one request or answer, one viewer), read once and then shared
    by every tool of that context. A new context reads them again, so the numbers after a label write
    see it. Two viewers with different answers get different label sets (and cache keys)."""
    if ctx._labels is None:
        ctx._labels = basket_labels(ctx.conn, ctx.customer_id, ctx.as_of, viewer=ctx.viewer)
    return ctx._labels


def metric_settings_for(ctx: Any) -> dict[str, str]:
    """The settings a tool passes to core/metrics files for the labels of its context (one call)."""
    return metric_settings(for_context(ctx))


def metric_settings(labels: dict[int, str]) -> dict[str, str]:
    """The `tx_labels` setting for core/metrics files: canonical JSON, and only when there are labels,
    so the evidence specs of customers without labels do not change."""
    if not labels:
        return {}
    return {"tx_labels": json.dumps({str(k): labels[k] for k in sorted(labels)}, separators=(",", ":"))}


def label_set(labels: dict[int, str]) -> list[list[Any]]:
    """The label set as stored in an evidence spec: sorted [transaction id, basket] pairs."""
    return [[k, labels[k]] for k in sorted(labels)]
