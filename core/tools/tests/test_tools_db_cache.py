"""Database-backed check of the tool cache with real tools. Skipped without DATABASE_URL.

Few calls on purpose (the shared database is small): per tool, one fresh call, one miss through the
cache and then hits from memory and from disk, all for the lead persona.
"""

from datetime import date

import pytest

from core.tools.baskets import GetBasketBreakdownArgs, get_basket_breakdown
from core.tools.cache import ToolCache
from core.tools.context import ToolContext
from core.tools.safe_to_spend import GetSafeToSpendArgs, get_safe_to_spend

AS_OF = date(2026, 9, 30)
CALLS = [
    ("get_basket_breakdown", GetBasketBreakdownArgs, get_basket_breakdown, {"period": {"preset": "last_6_months"}}),
    ("get_safe_to_spend", GetSafeToSpendArgs, get_safe_to_spend, {}),   # card extras hold Number objects
]


@pytest.mark.parametrize("name, args_model, fn, args", CALLS, ids=[c[0] for c in CALLS])
def test_real_tool_hit_equals_a_fresh_call(conn, tmp_path, name, args_model, fn, args):
    def ctx():
        return ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=conn)

    fresh = fn(ctx(), args).model_dump_json()
    writer = ToolCache(mode="disk", directory=tmp_path)
    miss = writer.run(name, args_model, fn, ctx(), args).model_dump_json()
    memory_hit = writer.run(name, args_model, fn, ctx(), args).model_dump_json()
    reader = ToolCache(mode="disk", directory=tmp_path)            # a new process: the service after warm-up
    disk_hit = reader.run(name, args_model, fn, ctx(), args).model_dump_json()
    assert writer.stats.misses == 1 and writer.stats.hits == 1 and reader.stats.disk_hits == 1
    assert fresh == miss == memory_hit == disk_hit
