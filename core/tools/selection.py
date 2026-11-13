"""Which transactions a number is computed from, and the value it has.

A `Selection` is the data part of an evidence spec. `get_spending` and evidence resolution both
use `select` and `value_of`, so re-running a stored spec reproduces exactly the original number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from core.tools import config
from core.tools.classify import CTx
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
        )

    def with_group(self, by: str, key: str | None = None, not_in: tuple[str, ...] = ()) -> Selection:
        return Selection(self.direction, self.start, self.end, self.categories, self.baskets,
                         self.mcc_groups, self.merchant_id, by, key, tuple(sorted(not_in)))

    def with_period(self, start: date, end: date) -> Selection:
        return Selection(self.direction, start, end, self.categories, self.baskets, self.mcc_groups,
                         self.merchant_id, self.group_by, self.group_key, self.group_not_in)


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


def value_of(rows: list[CTx], sel: Selection, method: str) -> Decimal:
    if method == config.METHODS["total"]:
        return sum((amount(c, sel.direction) for c in rows), Decimal("0"))
    if method in (config.METHODS["n_tx"], config.METHODS["row_count"]):
        return Decimal(len(rows))
    raise ValueError(f"method {method!r} is not a transactions method")
