"""Per-transaction classification for one customer: flow, one-off, subscription, basket, MCC group.

This is the Python twin of the shared classification block in core/metrics/02_baskets.sql
(params .. cls), applied to one customer's history up to as_of. Keep the two in step; the
database-backed tests compare its basket totals with the worked numbers in metrics.md section 1.
User overrides are empty here, as in the SQL prototypes.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from core.tools import config
from core.tools.db import Tx
from core.tools.periods import add_months


@dataclass(frozen=True)
class CTx:
    """A classified transaction."""

    tx: Tx
    flow: str              # income | own_savings_back | saving | transfer | spend
    is_one_off: bool
    is_subscription: bool
    basket: str | None     # None outside the spend flow
    mcc_group: str | None
    overridden: bool = False  # the basket comes from a customer label, not from the rules

    @property
    def out_eur(self) -> Decimal:
        return -self.tx.amount_eur

    @property
    def in_eur(self) -> Decimal:
        return self.tx.amount_eur


def flow_of(category: str) -> str:
    if category in config.INCOME_CATEGORIES:
        return "income"
    if category in config.OWN_SAVINGS_BACK_CATEGORIES:
        return "own_savings_back"
    if category in config.SAVING_CATEGORIES:
        return "saving"
    if category in config.TRANSFER_CATEGORIES:
        return "transfer"
    return "spend"


def window(as_of: date) -> tuple[date, date]:
    """The last 6 complete calendar months (metrics.md section 0)."""
    next_month_start = (as_of + timedelta(days=1)).replace(day=1)
    return add_months(next_month_start, -config.WINDOW_MONTHS), next_month_start - timedelta(days=1)


def _spike_base(history: list[Tx], as_of: date) -> dict[str, tuple[int, float]]:
    """Per category: purchases in the 365 days up to as_of and their median out amount."""
    amounts: dict[str, list[Decimal]] = defaultdict(list)
    since = as_of - timedelta(days=365)
    for t in history:
        if t.tx_type == "purchase" and since < t.tx_date <= as_of:
            amounts[t.category].append(-t.amount_eur)
    return {c: (len(v), statistics.median(v)) for c, v in amounts.items()}


def _subscriptions(history: list[Tx], as_of: date) -> set[str]:
    """Card merchants charged once a month at a stable amount in the window (02_baskets.sql)."""
    win_start, win_end = window(as_of)
    by_merchant: dict[str, list[Tx]] = defaultdict(list)
    for t in history:
        if t.merchant_id is not None and win_start <= t.tx_date <= win_end:
            by_merchant[t.merchant_id].append(t)
    found = set()
    for merchant_id, txs in by_merchant.items():
        months = {(t.tx_date.year, t.tx_date.month) for t in txs}
        if len(months) < config.SUBSCRIPTION_MIN_MONTHS or len(txs) != len(months):
            continue
        amounts = [t.amount_eur for t in txs]  # Decimal throughout, like stddev_samp on numeric
        mean = statistics.mean(amounts)
        if mean != 0 and statistics.stdev(amounts) / abs(mean) <= Decimal(str(config.SUBSCRIPTION_MAX_CV)):
            found.add(merchant_id)
    return found


def basket_of(t: Tx, flow: str, is_one_off: bool, is_subscription: bool) -> str | None:
    """metrics.md section 1, rules 1-8; first match wins."""
    if flow != "spend":
        return None
    if t.tx_type in ("housing_payment", "utilities_payment"):
        return "regular_essentials"
    if is_subscription:
        return "regular_essentials"
    if t.category in ("Health", "Home & Tech"):
        return "unexpected_necessities"
    if t.category == "Transportation" and t.mcc in config.MCC_GROUPS["taxi"]:
        return "everyday_spending"
    if t.category in ("Groceries", "Transportation") and is_one_off:
        return "unexpected_necessities"
    if t.category in ("Groceries", "Transportation"):
        return "regular_essentials"
    if t.category in ("Restaurants", "Entertainment", "Lifestyle", "Travel"):
        return "everyday_spending"
    return "unclassified"


def classify(history: list[Tx], as_of: date, overrides: dict[int, str] | None = None) -> list[CTx]:
    """Classify every transaction up to as_of. Rows after as_of are dropped (R5).

    `overrides` maps a transaction id to the basket a customer chose (core.tools.labels; empty today).
    It applies to spending transactions only and wins over the rules. This differs from the overrides
    CTE in 02_baskets.sql, which matches a rule override by merchant, then MCC, then category (empty in
    the prototypes): customer labels are per transaction, and a label may also be `unclassified`.
    """
    overrides = overrides or {}
    spikes = _spike_base(history, as_of)
    subscriptions = _subscriptions(history, as_of)
    out = []
    for t in history:
        if t.tx_date > as_of:
            continue
        flow = flow_of(t.category)
        n_12m, median_12m = spikes.get(t.category, (0, 0))
        is_one_off = (
            t.tx_type == "purchase"
            and n_12m >= config.ONE_OFF_MIN_PURCHASES
            and -t.amount_eur > config.ONE_OFF_FACTOR * Decimal(str(median_12m))
        )
        is_sub = t.merchant_id is not None and t.merchant_id in subscriptions
        rule_basket = basket_of(t, flow, is_one_off, is_sub)
        overridden = flow == "spend" and t.id in overrides
        out.append(CTx(
            tx=t,
            flow=flow,
            is_one_off=is_one_off,
            is_subscription=is_sub,
            basket=overrides[t.id] if overridden else rule_basket,
            mcc_group=config.MCC_TO_GROUP.get(t.mcc) if t.mcc else None,
            overridden=overridden,
        ))
    return out
