"""Which transactions a number is computed from, and the value it has.

A `Selection` is the data part of an evidence spec. Every tool and evidence resolution use
`select` and `value_of`, so re-running a stored spec reproduces exactly the original number.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any

from core.tools import config
from core.tools.classify import CTx
from core.tools.formatting import money
from core.tools.periods import month_key, week_start

NONE_KEY = "_none"  # group key for rows without a merchant or without an MCC group


@dataclass(frozen=True)
class Selection:
    direction: str                      # "out" | "in"
    start: date
    end: date
    categories: tuple[str, ...] = ()    # sorted, unique; empty = the default flow of the direction
    baskets: tuple[str, ...] = ()
    mcc_groups: tuple[str, ...] = ()
    merchant_id: str | None = None
    group_by: str | None = None         # category | basket | merchant | mcc_group | month | week
    group_key: str | None = None        # rows whose group key equals this
    group_not_in: tuple[str, ...] = ()  # or rows whose group key is none of these ("other")
    series_key: str | None = None       # a recurring series: a tx_type, or a merchant id for card
                                        # purchases (metrics.md section 2); replaces the flow filter
    series_keys: tuple[str, ...] | None = None  # several series (the bills due total); () = none
    tx_ids: tuple[int, ...] | None = None       # exactly these transactions (a reviewed purchase, #68)

    def to_spec(self) -> dict[str, Any]:
        spec: dict[str, Any] = {
            "direction": self.direction,
            "period": {"start": self.start.isoformat(), "end": self.end.isoformat()},
            "categories": list(self.categories),
            "baskets": list(self.baskets),
            "mcc_groups": list(self.mcc_groups),
            "merchant_id": self.merchant_id,
            "group": None,
        }
        if self.group_by:
            spec["group"] = {"by": self.group_by, "key": self.group_key, "not_in": list(self.group_not_in)}
        if self.series_key is not None:  # only when set, so refs of other numbers do not change
            spec["series_key"] = self.series_key
        if self.series_keys is not None:
            spec["series_keys"] = list(self.series_keys)
        if self.tx_ids is not None:
            spec["tx_ids"] = list(self.tx_ids)
        return spec

    @classmethod
    def from_spec(cls, spec: dict[str, Any]) -> Selection:
        group = spec.get("group") or {}
        return cls(
            direction=spec["direction"],
            start=date.fromisoformat(spec["period"]["start"]),
            end=date.fromisoformat(spec["period"]["end"]),
            categories=tuple(spec["categories"]),
            baskets=tuple(spec["baskets"]),
            mcc_groups=tuple(spec["mcc_groups"]),
            merchant_id=spec["merchant_id"],
            group_by=group.get("by"),
            group_key=group.get("key"),
            group_not_in=tuple(group.get("not_in") or ()),
            series_key=spec.get("series_key"),
            series_keys=tuple(spec["series_keys"]) if "series_keys" in spec else None,
            tx_ids=tuple(int(i) for i in spec["tx_ids"]) if "tx_ids" in spec else None,
        )

    def with_group(self, by: str, key: str | None = None, not_in: tuple[str, ...] = ()) -> Selection:
        return replace(self, group_by=by, group_key=key, group_not_in=tuple(sorted(not_in)))

    def with_period(self, start: date, end: date) -> Selection:
        return replace(self, start=start, end=end)


def series_key_of(c: CTx) -> str | None:
    """The recurring-series key of a transaction (01_recurring.sql `keyed`), or None for a card
    purchase without a merchant."""
    if c.tx.tx_type == "purchase":
        return c.tx.merchant_id
    return c.tx.tx_type


def group_key(c: CTx, by: str) -> str:
    if by == "category":
        return c.tx.category
    if by == "basket":
        return c.basket or NONE_KEY
    if by == "merchant":
        return c.tx.merchant_id or NONE_KEY
    if by == "mcc_group":
        return c.mcc_group or NONE_KEY
    if by == "month":
        return month_key(c.tx.tx_date)
    if by == "week":
        return week_start(c.tx.tx_date).isoformat()
    raise ValueError(f"unknown group_by {by!r}")


def _in_direction(c: CTx, sel: Selection) -> bool:
    if sel.series_keys is not None:
        return series_key_of(c) in sel.series_keys
    if sel.series_key is not None:
        return series_key_of(c) == sel.series_key
    if sel.categories:
        return c.tx.category in sel.categories
    if sel.direction == "out":
        return c.flow == "spend"
    return c.flow == "income"


def select(rows: list[CTx], sel: Selection) -> list[CTx]:
    out = []
    for c in rows:
        if not (sel.start <= c.tx.tx_date <= sel.end) or not _in_direction(c, sel):
            continue
        if sel.tx_ids is not None and c.tx.id not in sel.tx_ids:
            continue
        if sel.baskets and c.basket not in sel.baskets:
            continue
        if sel.mcc_groups and c.mcc_group not in sel.mcc_groups:
            continue
        if sel.merchant_id is not None and c.tx.merchant_id != sel.merchant_id:
            continue
        if sel.group_by:
            key = group_key(c, sel.group_by)
            if sel.group_key is not None and key != sel.group_key:
                continue
            if sel.group_not_in and key in sel.group_not_in:
                continue
        out.append(c)
    return out


def amount(c: CTx, direction: str) -> Decimal:
    """Positive euros: money out for "out", money in for "in"."""
    return c.out_eur if direction == "out" else c.in_eur


def _monthly_totals(rows: list[CTx]) -> list[Decimal]:
    by_month: dict[str, Decimal] = defaultdict(Decimal)
    for c in rows:
        by_month[month_key(c.tx.tx_date)] += abs(c.tx.amount_eur)
    return list(by_month.values())


SUM_METHODS = {config.METHODS["total"], config.METHODS["basket_total"]}
COUNT_METHODS = {config.METHODS["n_tx"], config.METHODS["row_count"]}
MONTH_AVG_METHODS = {config.METHODS["basket_month_avg"], config.METHODS["spend_month"],
                     config.METHODS["peer_you"]}
MEDIAN_MONTH_METHODS = {config.METHODS["typical_month"]}
SCALED_MEDIAN_METHODS = {config.METHODS["bill_due"]}
SUM_OF_SCALED_MEDIANS_METHODS = {config.METHODS["bills_due"]}


def value_of(rows: list[CTx], sel: Selection, method: str, params: dict[str, Any] | None = None) -> Decimal:
    """The final value of a transactions-kind number: euros rounded to cents, counts as integers.

    - spending.total, baskets.total_eur: sum of the selected amounts.
    - spending.n_tx, evidence.row_count: number of rows.
    - baskets.month_avg_eur, spender_profile.spend_month_eur, peer_benchmark.you_month_eur:
      sum / params["n_months"] (metrics.md sections 1, 5 and 6).
    - recurring.typical_month_eur: median of the monthly totals of the series (metrics.md section 2).
    - safe_to_spend.bill_due_eur: that unrounded median * factor_num / factor_den, rounded once, as
      in the `bills` step of 03_safe_to_spend.sql (occurrences before payday, or N / 30.4375).
    - safe_to_spend.bills_due_eur: the same unrounded term for every series in params["factors"]
      ({series key: [factor_num, factor_den]}), summed and rounded once, exactly as 03 computes
      bills_due_eur (metrics wins: the per-bill items, each rounded, may differ from it by 0.01 each).
    """
    if method in SUM_METHODS:
        return money(sum((amount(c, sel.direction) for c in rows), Decimal("0")))
    if method in COUNT_METHODS:
        return Decimal(len(rows))
    if method in MONTH_AVG_METHODS:
        n_months = int((params or {})["n_months"])
        return money(sum((amount(c, sel.direction) for c in rows), Decimal("0")) / n_months)
    if method in MEDIAN_MONTH_METHODS:
        totals = _monthly_totals(rows)
        return money(statistics.median(totals)) if totals else Decimal("0.00")
    if method in SCALED_MEDIAN_METHODS:
        totals = _monthly_totals(rows)
        p = params or {}
        median = statistics.median(totals) if totals else Decimal("0")
        return money(median * Decimal(str(p["factor_num"])) / Decimal(str(p["factor_den"])))
    if method in SUM_OF_SCALED_MEDIANS_METHODS:
        by_key: dict[str, list[CTx]] = defaultdict(list)
        for c in rows:
            by_key[series_key_of(c)].append(c)
        total = Decimal("0")
        for key, (num, den) in (params or {})["factors"].items():
            totals = _monthly_totals(by_key.get(key, []))
            if totals:
                total += statistics.median(totals) * Decimal(str(num)) / Decimal(str(den))
        return money(total)
    raise ValueError(f"method {method!r} is not a transactions method")
