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



def test_two_viewers_with_different_answers_get_different_safe_to_spend(conn, tmp_path):
    """#86 with per-viewer answers (#144): the label set is in the key, so one viewer's answer to the
    spike review never shows in another viewer's numbers. The two label sets stand in for two viewers
    (the context's labels are what labels.for_context returns for each); the lead persona's spike is
    pending for one (`unclassified`) and has no review for the other."""
    spike = 606016   # CUST00860's Home & Tech purchase of 1,080.42 on 2026-09-28

    def viewer(labels_by_tx):
        ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=conn)
        ctx._labels = labels_by_tx
        return ctx

    cache = ToolCache(mode="memory")
    plain = cache.run("get_safe_to_spend", GetSafeToSpendArgs, get_safe_to_spend, viewer({}), {})
    pending = cache.run("get_safe_to_spend", GetSafeToSpendArgs, get_safe_to_spend, viewer({spike: "unclassified"}), {})
    again = cache.run("get_safe_to_spend", GetSafeToSpendArgs, get_safe_to_spend, viewer({}), {})
    assert cache.stats.misses == 2 and cache.stats.hits == 1
    assert plain.data.safe_to_spend.value != pending.data.safe_to_spend.value
    assert again.model_dump_json() == plain.model_dump_json()       # the first viewer's own numbers
