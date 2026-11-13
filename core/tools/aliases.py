"""Merchant aliases: what the model and the app see instead of merchant ids (R3).

Per customer and as_of, merchants are ranked by the customer's total spend with them up to as_of
(ties by merchant id). Rank 1 is `store_a`, 27 is `store_aa`. The label is "<kind> <LETTERS>",
for example "Grocery store A" or "Restaurant B", with the same letters as the key. Keys and labels
contain no digits. The map back to merchant ids stays on the server.
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


def merchant_kind(category: str, mcc: str | None, language: str) -> str:
    pair = config.MERCHANT_KIND_BY_MCC.get(mcc or "") or config.MERCHANT_KIND_BY_CATEGORY.get(
        category, config.MERCHANT_KIND_DEFAULT
    )
    return config.label(pair, language)


@dataclass(frozen=True)
class Alias:
    key: str
    merchant_id: str
    category: str
    mcc: str | None

    def label(self, language: str = "en") -> str:
        return f"{merchant_kind(self.category, self.mcc, language)} {self.key.removeprefix('store_').upper()}"


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
    return AliasMap([
        Alias(key=f"store_{letters(i)}", merchant_id=m, category=first_seen[m].category, mcc=first_seen[m].mcc)
        for i, m in enumerate(ranked, start=1)
    ])
