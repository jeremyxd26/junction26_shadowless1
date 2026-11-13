"""Merchant aliases: what the model and the app see instead of merchant ids (R3).

Per customer and as_of, merchants are ranked by the customer's total spend with them up to as_of
(ties by merchant id).
- The key is opaque and unique: rank 1 overall is `store_a`, rank 27 is `store_aa`.
- The label is "<kind> <LETTERS>" with letters by rank within the kind, so a customer's two taxi
  companies are "Taxi A" and "Taxi B" and the top grocery store is "Grocery store A".
Keys and labels contain no digits. The map back to merchant ids stays on the server.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core.tools import config
from core.tools.db import Tx


def letters(rank: int) -> str:
    """1 -> a, 26 -> z, 27 -> aa (bijective base 26)."""
    out = ""
    while rank > 0:
        rank, rem = divmod(rank - 1, 26)
        out = chr(ord("a") + rem) + out
    return out


def merchant_kind(category: str, mcc: str | None) -> tuple[str, str]:
    """(English, Finnish) kind of a merchant, from its MCC first, then its category."""
    return config.MERCHANT_KIND_BY_MCC.get(mcc or "") or config.MERCHANT_KIND_BY_CATEGORY.get(
        category, config.MERCHANT_KIND_DEFAULT
    )


@dataclass(frozen=True)
class Alias:
    key: str           # opaque, unique per customer: store_a, store_b, ...
    merchant_id: str
    kind: tuple[str, str]
    kind_letters: str  # rank within the kind: a, b, ...

    def label(self, language: str = "en") -> str:
        return f"{config.label(self.kind, language)} {self.kind_letters.upper()}"


class AliasMap:
    def __init__(self, aliases: list[Alias]) -> None:
        self._by_key = {a.key: a for a in aliases}
        self._by_merchant = {a.merchant_id: a for a in aliases}

    def merchant_id(self, key: str) -> str:
        """The merchant id behind an alias; KeyError for an alias this customer does not have."""
        return self._by_key[key].merchant_id

    def for_merchant(self, merchant_id: str) -> Alias:
        return self._by_merchant[merchant_id]

    def keys(self) -> list[str]:
        return list(self._by_key)


def build(history: list[Tx], as_of: date) -> AliasMap:
    spend: dict[str, Decimal] = defaultdict(Decimal)
    first_seen: dict[str, Tx] = {}
    for t in history:
        if t.merchant_id is None or t.tx_date > as_of:
            continue
        spend[t.merchant_id] += -t.amount_eur
        first_seen.setdefault(t.merchant_id, t)
    ranked = sorted(spend, key=lambda m: (-spend[m], m))
    per_kind: dict[tuple[str, str], int] = defaultdict(int)
    out = []
    for i, m in enumerate(ranked, start=1):
        kind = merchant_kind(first_seen[m].category, first_seen[m].mcc)
        per_kind[kind] += 1
        out.append(Alias(key=f"store_{letters(i)}", merchant_id=m, kind=kind, kind_letters=letters(per_kind[kind])))
    return AliasMap(out)
