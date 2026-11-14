"""#417 on the database: the safe-to-save card's `weekly` and `daily` for the four personas resolve through the
evidence endpoint's resolver, reconcile, and open the card's `monthly` as their only part; their values are the
month x 7 / 30.4375 and / 30.4375 to the cent. Labels injected (no review answered), no review table touched."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest

from core.tools import config, evidence
from core.tools.context import ToolContext
from core.tools.safe_to_save import get_safe_to_save

AS_OF = date(2026, 9, 30)
PERSONAS = ["CUST00860", "CUST00493", "CUST00349", "CUST00849"]


def cents(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@pytest.mark.parametrize("customer_id", PERSONAS)
def test_week_and_day_open_the_month_and_reconcile(conn, customer_id):
    ctx = ToolContext(customer_id=customer_id, as_of=AS_OF, conn=conn)
    ctx._labels = {}
    data = get_safe_to_save(ctx, {}).data
    month = Decimal(str(data.monthly.value))
    assert month > 0, customer_id                                       # a figure worth scaling
    for number, method, factor in ((data.weekly, config.SAFE_TO_SAVE_WEEK_METHOD, 7),
                                   (data.daily, config.SAFE_TO_SAVE_DAY_METHOD, 1)):
        assert number.method == method
        assert Decimal(str(number.value)) == cents(month * factor / Decimal("30.4375")), (customer_id, method)
        resolved = evidence.resolve(conn, number.evidence_ref, customer_id, limit=1)
        assert resolved.kind == "composite" and resolved.reconciles is True, (customer_id, method)
        assert [p["ref"] for p in resolved.parts] == [data.monthly.evidence_ref], (customer_id, method)
        assert resolved.value == Decimal(str(number.value))
    assert evidence.resolve(conn, data.monthly.evidence_ref, customer_id, limit=1).reconciles is True
