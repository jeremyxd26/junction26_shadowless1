"""SQL ground truth for numbers an answer cites beyond a case's list (issue #112).

An answer may cite a number that a tool call of the same answer returned, beyond the numbers the case
lists. The runner then still checks its value against SQL wherever the case can derive it from the
number's method id (`<metric>.<column>@1`, agent-core.md section 6.2) and period:
- safe_to_spend, spender_profile: the metric file's column for the customer (one row);
- what_if: the column, with the selection and cut of the case's own what-if source;
- baskets: month_avg_eur of the basket named by the label; share_pct must be one of the baskets' shares;
- recurring, peer_benchmark: the value must be one of the column's values for the customer;
- spending.total / spending.n_tx: a spending source of the case with the same method and period.
Anything else (a category amount inside a basket, a bill's amount due) cannot be derived here and is
accepted only because the audit shows that a tool of this answer returned it.

One connection, opened only when a number needs it; every query is for the case's persona alone.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import expected
from core import answer_text

METHOD = re.compile(r"^([a-z_]+)\.([a-z0-9_]+)@\d+$")
SPENDING_COLUMN = {"total": "total_eur", "n_tx": "n_tx"}


def _basket_by_label() -> dict[str, str]:
    from core.tools.config import BASKET_LABELS

    return {label.lower(): key for key, pair in BASKET_LABELS.items() for label in pair}


class Deriver:
    def __init__(self, as_of: str) -> None:
        self.as_of = as_of
        self._db: expected.Db | None = None

    def db(self) -> expected.Db:
        if self._db is None:
            self._db = expected.connect(self.as_of)
        return self._db

    def candidates(self, case: dict, number: dict) -> list[Any] | None:
        """The SQL values this number may have, or None when the case cannot derive it."""
        m = METHOD.match(str(number.get("method") or ""))
        if not m:
            return None
        metric, column = m.groups()
        cid = case["persona"]
        items = [item for _, item in expected.items(case)]
        if metric in ("safe_to_spend", "spender_profile"):
            rows = self.db().metric(metric, cid)
            return [rows[0][column]] if rows and column in rows[0] else None
        if metric == "what_if":
            settings = next((i["source"].get("settings") for i in items if i["source"].get("metric") == "what_if"), None)
            if settings is None:
                return None
            return [r[column] for r in self.db().metric("what_if", cid, settings) if column in r] or None
        if metric == "baskets":
            rows = self.db().metric("baskets", cid)
            if column == "share_pct":
                return [r["share_pct"] for r in rows]
            key = _basket_by_label().get(str(number.get("label") or "").lower())
            return [r[column] for r in rows if r["basket"] == key and column in r] if key else None
        if metric in ("recurring", "peer_benchmark"):
            values = [r.get(column) for r in self.db().metric(metric, cid)]
            return [v for v in values if v is not None] or None
        if metric == "spending" and column in SPENDING_COLUMN:
            period = number.get("period") or {}
            out = []
            for i in items:
                src = i["source"]
                if src.get("query") != "spending" or src.get("column") != SPENDING_COLUMN[column]:
                    continue
                end = min(date.fromisoformat(src["end"]), date.fromisoformat(self.as_of))
                if (src["start"], end.isoformat()) == (period.get("start"), period.get("end")):
                    out.append(expected.evaluate(self.db(), cid, src))
            return out or None
        return None

    def problem(self, case: dict, number: dict) -> str | None:
        """None when the number matches SQL or cannot be derived; else what is wrong."""
        values = self.candidates(case, number)
        if values is None:
            return None
        if any(answer_text.same_value(number["value"], v, number["unit"]) for v in values if v is not None):
            return None
        return (f"Number object {number.get('value')} {number.get('unit')} ({number.get('method')}) "
                f"does not match the SQL value")
