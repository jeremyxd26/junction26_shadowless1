"""Tests for the tool-result cache (core/tools/cache.py). No database: the tool here is a fake that
builds a real result type (SpendingData) with registered numbers, a card with Number extras and a
model view, and counts its calls."""

import json
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.tools import cache as cache_mod
from core.tools.cache import Entry, ToolCache, apply, labels_key_of
from core.tools.context import ToolContext
from core.tools.formatting import display
from core.tools.models import Args, Card, Number, Period, ToolResult, Unit
from core.tools.numbers import model_number
from core.tools.spending import SpendingData

AS_OF = date(2026, 9, 30)
PERIOD = Period(start=date(2026, 9, 1), end=date(2026, 9, 30), label="September 2026")


class FakeArgs(Args):
    amount: int = 100
    note: str = "x"


class FakeTool:
    """A tool(ctx, args) -> ToolResult that registers two numbers and one user input (no ref)."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, ctx: ToolContext, args: FakeArgs) -> ToolResult:
        self.calls += 1
        value = Decimal(args.amount) + Decimal("0.25")

        def number(v: Decimal, unit: Unit, ref: str | None, label: str) -> Number:
            return ctx.numbers.register(Number(value=float(v), unit=unit, period=PERIOD, method="spending.total@1",
                                               evidence_ref=ref, label=label, display=display(v, unit, ctx.language)))

        total = number(value, Unit.EUR, f"ev_{ctx.customer_id[-3:]}{args.amount:09d}", "Total")
        count = number(Decimal(3), Unit.COUNT, "ev_000000000003", "Transactions")
        typed = number(Decimal(20), Unit.PERCENT, None, "Cut you chose")   # user input: a new id each time
        data = SpendingData(period=PERIOD, total=total, tx_count=count, comparison=None, groups=[])
        card = Card(card_id="card_x", type="metric", title="Spending", primary=total,
                    secondary=[count.model_dump()], components=[], comparison=None, status=None)
        view = {"tool": "fake", "total": model_number(total), "tx_count": model_number(count),
                "cut": model_number(typed), "language": ctx.language}
        return ToolResult(tool="fake", data=data, card=card, notes=[], evidence=[total.evidence_ref], model_view=view)


def ctx_for(customer_id="CUST00860", language="en", preload=0):
    ctx = ToolContext(customer_id=customer_id, as_of=AS_OF, conn=None, language=language)
    ctx.labels_key = labels_key_of({})          # read once per request; here: no labels
    for i in range(preload):                    # numbers other tools of the same answer registered first
        ctx.numbers.register(Number(value=i, unit=Unit.COUNT, period=PERIOD, method="spending.n_tx@1",
                                    evidence_ref=f"ev_pre{i:08d}", label="pre", display=str(i)))
    return ctx


def dump(result: ToolResult) -> str:
    return result.model_dump_json()


@pytest.fixture
def tool():
    return FakeTool()


@pytest.fixture
def mem():
    return ToolCache(mode="memory", max_entries=8)


@pytest.mark.parametrize("preload", [0, 3])
def test_hit_is_byte_identical_to_a_fresh_call(mem, tool, preload):
    fresh_ctx = ctx_for(preload=preload)
    fresh = tool(fresh_ctx, FakeArgs())
    miss_ctx, hit_ctx = ctx_for(preload=preload), ctx_for(preload=preload)
    miss = mem.run("fake", FakeArgs, tool, miss_ctx, {})
    hit = mem.run("fake", FakeArgs, tool, hit_ctx, {})
    assert tool.calls == 2 and mem.stats.hits == 1 and mem.stats.misses == 1
    assert dump(miss) == dump(fresh) == dump(hit)                           # ids, refs, card, view
    assert miss_ctx.numbers.all() == fresh_ctx.numbers.all() == hit_ctx.numbers.all()   # same registry state
    assert hit.model_view["total"]["id"] == f"n{preload + 1}"


def test_a_number_already_in_the_answer_keeps_its_id(mem, tool):
    ctx = ctx_for()
    first = mem.run("fake", FakeArgs, tool, ctx, {})
    again = mem.run("fake", FakeArgs, tool, ctx, {})          # same answer asks twice: same refs, same ids
    assert again.data.total.id == first.data.total.id == "n1"
    assert again.model_view["cut"]["id"] != first.model_view["cut"]["id"]   # no ref: a new id, as fresh


def test_hit_returns_a_copy(mem, tool):
    a = mem.run("fake", FakeArgs, tool, ctx_for(), {})
    a.data.total.label = "changed"
    a.model_view["total"]["label"] = "changed"
    b = mem.run("fake", FakeArgs, tool, ctx_for(), {})
    assert b.data.total.label == "Total" and b.model_view["total"]["label"] == "Total"


def test_arguments_are_validated_and_normalised(mem, tool):
    mem.run("fake", FakeArgs, tool, ctx_for(), {})
    mem.run("fake", FakeArgs, tool, ctx_for(), {"amount": 100, "note": "x"})   # the defaults: same key
    mem.run("fake", FakeArgs, tool, ctx_for(), FakeArgs())
    assert tool.calls == 1
    mem.run("fake", FakeArgs, tool, ctx_for(), {"amount": 5})
    assert tool.calls == 2
    with pytest.raises(ValidationError):
        mem.run("fake", FakeArgs, tool, ctx_for(), {"customer_id": "CUST00002"})
    assert tool.calls == 2


@pytest.mark.parametrize("change", ["customer", "language", "as_of", "labels", "tool"])
def test_every_part_of_the_key_counts(mem, tool, change):
    mem.run("fake", FakeArgs, tool, ctx_for(), {})
    ctx = ctx_for(customer_id="CUST00493" if change == "customer" else "CUST00860",
                  language="fi" if change == "language" else "en")
    if change == "as_of":
        ctx.as_of = date(2026, 9, 14)
    if change == "labels":
        ctx.labels_key = labels_key_of({4711: "everyday_spending"})
    result = mem.run("other" if change == "tool" else "fake", FakeArgs, tool, ctx, {})
    assert tool.calls == 2
    assert result.model_view["language"] == ctx.language


def test_a_changed_label_set_changes_the_key():
    none, pending = labels_key_of({}), labels_key_of({4711: "unclassified"})
    answered = labels_key_of({4711: "everyday_spending"})
    assert len({none, pending, answered}) == 3
    assert labels_key_of({2: "unclassified", 1: "everyday_spending"}) == \
        labels_key_of({1: "everyday_spending", 2: "unclassified"})          # order does not matter
    assert labels_key_of({4711: "unclassified"}) == pending                  # undo back to pending: same key


def test_label_write_invalidates_that_customer_only(mem, tool):
    mem.run("fake", FakeArgs, tool, ctx_for("CUST00860"), {})
    mem.run("fake", FakeArgs, tool, ctx_for("CUST00493"), {})
    assert mem.invalidate_customer("CUST00860") == 1
    mem.run("fake", FakeArgs, tool, ctx_for("CUST00860"), {})
    mem.run("fake", FakeArgs, tool, ctx_for("CUST00493"), {})
    assert tool.calls == 3                                   # 860 recomputed, 493 still cached


def test_off_bypasses_the_cache(tool):
    off = ToolCache(mode="off")
    for _ in range(3):
        result = off.run("fake", FakeArgs, tool, ctx_for(), {})
    assert tool.calls == 3 and len(off) == 0 and off.stats.hits == 0
    assert dump(result) == dump(tool(ctx_for(), FakeArgs()))
    assert ToolCache.from_env({"TOOL_CACHE": "off"}).enabled is False
    assert ToolCache.from_env({"TOOL_CACHE": "OFF "}).mode == "off"


def test_no_entry_of_another_customer_is_returned(mem, tool):
    mem.run("fake", FakeArgs, tool, ctx_for("CUST00860"), {})
    key_860 = next(iter(mem._memory))
    # Even if another customer's request produced the same key, the read checks the customer.
    assert mem.get(key_860, "CUST00493") is None
    assert len(mem) == 0                                    # the suspicious entry is dropped
    entry = Entry("CUST00860", "fake", tool(ctx_for("CUST00860"), FakeArgs()), ())
    with pytest.raises(PermissionError):
        apply(entry, ctx_for("CUST00493"))


def test_memory_is_bounded(tool):
    small = ToolCache(mode="memory", max_entries=2)
    for amount in (1, 2, 3):
        small.run("fake", FakeArgs, tool, ctx_for(), {"amount": amount})
    assert len(small) == 2
    small.run("fake", FakeArgs, tool, ctx_for(), {"amount": 1})    # evicted first, so computed again
    assert tool.calls == 4


def test_a_failing_tool_is_not_cached(mem):
    def broken(ctx, args):
        raise RuntimeError("database went away")
    with pytest.raises(RuntimeError):
        mem.run("broken", FakeArgs, broken, ctx_for(), {})
    assert len(mem) == 0 and mem.stats.misses == 0


def test_disk_layer_survives_a_new_process_and_is_byte_identical(tmp_path, tool):
    writer = ToolCache(mode="disk", directory=tmp_path)
    fresh = writer.run("fake", FakeArgs, tool, ctx_for(preload=2), {})
    reader = ToolCache(mode="disk", directory=tmp_path)               # e.g. the service after the warm-up
    hit = reader.run("fake", FakeArgs, tool, ctx_for(preload=2), {})
    assert tool.calls == 1 and reader.stats.disk_hits == 1
    assert dump(hit) == dump(fresh)
    assert isinstance(hit.data, SpendingData) and hit.data.total.evidence_ref == fresh.data.total.evidence_ref
    reader.run("fake", FakeArgs, tool, ctx_for(), {})                 # now from memory
    assert reader.stats.disk_hits == 1 and reader.stats.hits == 2
    assert reader.invalidate_customer("CUST00860") == 1               # memory only (hygiene)
    again = ToolCache(mode="disk", directory=tmp_path)                # the warmed disk row stays
    assert again.get(next(iter(writer._memory)), "CUST00860") is not None


def test_disk_read_checks_the_customer(tmp_path, tool):
    writer = ToolCache(mode="disk", directory=tmp_path)
    writer.run("fake", FakeArgs, tool, ctx_for("CUST00860"), {})
    key = next(iter(writer._memory))
    assert ToolCache(mode="disk", directory=tmp_path).get(key, "CUST00493") is None


def test_a_broken_disk_file_falls_back_to_the_tool(tmp_path, tool):
    writer = ToolCache(mode="disk", directory=tmp_path)
    writer.run("fake", FakeArgs, tool, ctx_for(), {})
    with writer._db() as db:
        db.execute("UPDATE tool_cache SET payload = '{not json'")
    reader = ToolCache(mode="disk", directory=tmp_path)
    reader.run("fake", FakeArgs, tool, ctx_for(), {})
    assert tool.calls == 2


def test_only_core_tools_results_go_to_disk(tmp_path):
    class Foreign(Args):
        x: int = 1

    def foreign_tool(ctx, args):
        return ToolResult(tool="foreign", data=Foreign(), model_view={})

    disk = ToolCache(mode="disk", directory=tmp_path)
    disk.run("foreign", FakeArgs, foreign_tool, ctx_for(), {})
    assert len(disk) == 1
    with disk._db() as db:
        assert db.execute("SELECT count(*) FROM tool_cache").fetchone()[0] == 0


def test_code_version_is_part_of_the_key(mem, tool, monkeypatch):
    mem.run("fake", FakeArgs, tool, ctx_for(), {})
    monkeypatch.setattr(cache_mod, "code_version", lambda: "another-deploy")
    mem.run("fake", FakeArgs, tool, ctx_for(), {})
    assert tool.calls == 2


def test_labels_key_is_read_once_per_request(mem, tool, monkeypatch):
    reads = []
    monkeypatch.setattr(cache_mod.labels, "basket_labels", lambda conn, cid, as_of: reads.append(cid) or {})
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=None)
    for amount in (1, 2, 3):
        mem.run("fake", FakeArgs, tool, ctx, {"amount": amount})
    assert len(reads) == 1 + 3 and ctx.labels_key == labels_key_of({})   # the key once, one check per miss
    reads.clear()
    warm = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=None)     # the next request: all hits
    for amount in (1, 2, 3):
        mem.run("fake", FakeArgs, tool, warm, {"amount": amount})
    assert reads == ["CUST00860"]                                          # exactly one label read


def test_parallel_prepare_then_apply_in_order_gives_fresh_ids(mem, tool):
    from concurrent.futures import ThreadPoolExecutor

    ctx = ctx_for()
    with ThreadPoolExecutor(max_workers=2) as pool:
        prepared = list(pool.map(lambda a: mem.prepare("fake", FakeArgs, tool, ctx, {"amount": a}), (1, 2)))
    results = [apply(p.entry, ctx) for p in prepared]
    sequential_ctx = ctx_for()
    expected = [tool(sequential_ctx, FakeArgs(amount=a)) for a in (1, 2)]
    assert [dump(r) for r in results] == [dump(e) for e in expected]


def test_settings_from_the_environment(tmp_path):
    c = ToolCache.from_env({"TOOL_CACHE": "memory", "TOOL_CACHE_MAX_ENTRIES": "7", "TOOL_CACHE_DIR": str(tmp_path)})
    assert (c.mode, c.max_entries, c.directory) == ("memory", 7, tmp_path)
    assert ToolCache.from_env({}).mode == "disk"
    with pytest.raises(ValueError):
        ToolCache(mode="sometimes")


def test_a_cached_view_never_holds_another_answers_ids(mem, tool):
    mem.run("fake", FakeArgs, tool, ctx_for(preload=5), {})
    hit = mem.run("fake", FakeArgs, tool, ctx_for(preload=0), {})
    ids = {v["id"] for v in hit.model_view.values() if isinstance(v, dict)}
    assert ids == {"n1", "n2", "n3"}
    assert json.loads(hit.card.model_dump_json())["primary"]["id"] == "n1"


# ---- several calls of one request (the overview) ------------------------------------------------------

class SlowTool(FakeTool):
    def __init__(self, seconds: float) -> None:
        super().__init__()
        self.seconds = seconds
        self.conns: list = []

    def __call__(self, ctx, args):
        import time

        time.sleep(self.seconds)
        self.conns.append(ctx.conn)
        return super().__call__(ctx, args)


def many(tool, amounts=(1, 2, 3)):
    return [("slow", FakeArgs, tool, {"amount": a}) for a in amounts]


def request_ctx():
    ctx = ctx_for()
    ctx.conn = "request-connection"
    ctx._history = []                     # already read for this request
    return ctx


def test_prepare_many_runs_misses_on_two_connections_and_keeps_the_order(mem):
    import time
    from contextlib import contextmanager

    taken = []

    @contextmanager
    def second():
        taken.append(1)
        yield "second-connection"

    tool = SlowTool(0.3)
    ctx = request_ctx()
    t0 = time.perf_counter()
    prepared = mem.prepare_many(many(tool), ctx, extra_connection=second)
    elapsed = time.perf_counter() - t0
    results = [apply(p.entry, ctx) for p in prepared]
    assert elapsed < 0.85 and taken == [1]                              # 3 x 0.3 s took about 2 x 0.3 s
    assert set(tool.conns) == {"request-connection", "second-connection"}
    fresh_ctx = request_ctx()
    expected = [tool(fresh_ctx, FakeArgs(amount=a)) for a in (1, 2, 3)]
    assert [dump(r) for r in results] == [dump(e) for e in expected]    # same ids as one after another


def test_prepare_many_serves_hits_without_a_second_connection(mem):
    from contextlib import contextmanager

    tool = SlowTool(0.0)
    mem.prepare_many(many(tool), request_ctx())
    taken = []

    @contextmanager
    def second():
        taken.append(1)
        yield "second-connection"

    prepared = mem.prepare_many(many(tool), request_ctx(), extra_connection=second)
    assert [p.source for p in prepared] == ["memory"] * 3 and taken == [] and tool.calls == 3


def test_prepare_many_without_a_free_connection_runs_one_after_another(mem):
    from contextlib import contextmanager

    @contextmanager
    def busy():
        raise TimeoutError("pool busy")
        yield

    tool = SlowTool(0.0)
    prepared = mem.prepare_many(many(tool), request_ctx(), extra_connection=busy)
    assert [p.source for p in prepared] == ["tool"] * 3 and set(tool.conns) == {"request-connection"}


def test_prepare_many_with_the_cache_off_still_runs_everything():
    off = ToolCache(mode="off")
    tool = SlowTool(0.0)
    ctx = request_ctx()
    results = [apply(p.entry, ctx) for p in off.prepare_many(many(tool), ctx)]
    fresh_ctx = request_ctx()
    expected = [tool(fresh_ctx, FakeArgs(amount=a)) for a in (1, 2, 3)]
    assert tool.calls == 6 and [dump(r) for r in results] == [dump(e) for e in expected]
    assert [r.data.total.id for r in results] == ["n1", "n4", "n6"]   # the shared count ref keeps n2


def test_an_unwritable_cache_directory_keeps_the_memory_layer(tmp_path, tool):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("a file where the cache directory should be")   # like a read-only file system
    disk = ToolCache(mode="disk", directory=blocker / "cache")
    first = disk.run("fake", FakeArgs, tool, ctx_for(), {})
    second = disk.run("fake", FakeArgs, tool, ctx_for(), {})
    assert tool.calls == 1 and dump(first) == dump(second) and disk.stats.hits == 1
    assert disk.invalidate_customer("CUST00860") == 1



# ---- review fixes (#116) ---------------------------------------------------------------------------------

def _corrupt(directory):
    from core.tools.cache import DB_FILE

    (directory / DB_FILE).write_bytes(b"this is not a sqlite database" * 100)


def test_a_corrupted_disk_file_never_fails_clear_drop_or_invalidate(tmp_path, tool):
    disk = ToolCache(mode="disk", directory=tmp_path)
    disk.run("fake", FakeArgs, tool, ctx_for(), {})
    key = next(iter(disk._memory))
    _corrupt(tmp_path)
    fresh = ToolCache(mode="disk", directory=tmp_path)
    assert fresh.invalidate_customer("CUST00860") == 0
    fresh.drop(key)
    fresh.clear()
    result = fresh.run("fake", FakeArgs, tool, ctx_for(), {})            # falls back to the tool
    assert tool.calls == 2 and result.data.total.value == 100.25


@pytest.mark.parametrize("mode", ["memory", "off"])
def test_a_borrowed_connection_never_stays_on_the_callers_context(mode, tool):
    from contextlib import contextmanager

    seen = []

    @contextmanager
    def pool_connection():
        seen.append("taken")
        yield "pooled-connection"
        seen.append("released")

    def uses_conn(ctx, args):
        assert ctx.conn == "pooled-connection"
        return tool(ctx, args)

    c = ToolCache(mode=mode)
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn="request-connection")   # labels key unset
    c.run("fake", FakeArgs, uses_conn, ctx, {}, connection=pool_connection)
    assert ctx.conn == "request-connection" and seen and seen[-1] == "released"
    ctx.conn = None                                                      # the pipeline's contexts start empty
    c.run("fake", FakeArgs, uses_conn, ctx, {"amount": 7}, connection=pool_connection)
    assert ctx.conn is None


def test_the_database_identity_is_in_the_key_and_never_the_url(mem, tool, monkeypatch):
    from core.tools.cache import database_identity

    # Built from parts at run time, so no URL with a password stands in the source (secret scan).
    scheme, user, secret, host = "postgresql", "coach", "s3cret-pw", "db-host.example"
    url = "".join([scheme, "://", user, ":", secret, "@", host, ":5432/coachdb"])
    monkeypatch.setenv("DATABASE_URL", url)
    database_identity.cache_clear()
    try:
        first = database_identity()
        assert len(first) == 16 and all(ch in "0123456789abcdef" for ch in first)
        assert "s3cret" not in first and "db-host" not in first
        mem.run("fake", FakeArgs, tool, ctx_for(), {})
        monkeypatch.setenv("DATABASE_URL", url.replace("coachdb", "otherdb"))
        database_identity.cache_clear()
        assert database_identity() != first
        mem.run("fake", FakeArgs, tool, ctx_for(), {})                     # another database: computed again
        assert tool.calls == 2
        monkeypatch.setenv("DATABASE_URL", url.replace("s3cret-pw", "rotated-pw"))
        database_identity.cache_clear()
        assert database_identity() == first                              # a new password is the same database
    finally:
        database_identity.cache_clear()


@pytest.mark.parametrize("raw, expected", [("7", 7), ("0", 1), ("-3", 1), ("lots", 512), ("", 512)])
def test_max_entries_is_parsed_defensively(raw, expected):
    assert ToolCache.from_env({"TOOL_CACHE_MAX_ENTRIES": raw}).max_entries == expected


# ---- PR B: label race and per-call errors ----------------------------------------------------------------

def test_a_result_computed_under_changed_labels_is_returned_but_not_stored(mem, tool, monkeypatch):
    reads = iter(["labels-before", "labels-after"])          # a label write lands while the tool runs
    monkeypatch.setattr(mem, "labels_key", staticmethod(lambda conn, cid, as_of: next(reads)))
    ctx = ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=None)
    result = mem.run("fake", FakeArgs, tool, ctx, {})
    assert result.data.total.value == 100.25 and len(mem) == 0      # served, never cached under the old key
    monkeypatch.setattr(mem, "labels_key", staticmethod(lambda conn, cid, as_of: "labels-after"))
    mem.run("fake", FakeArgs, tool, ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=None), {})
    mem.run("fake", FakeArgs, tool, ToolContext(customer_id="CUST00860", as_of=AS_OF, conn=None), {})
    assert tool.calls == 2 and len(mem) == 1                         # stable labels: stored, then a hit


def test_one_failing_call_of_many_fails_alone(mem):
    tool = SlowTool(0.0)

    def broken(ctx, args):
        raise RuntimeError("this card's data is not there")

    calls = [("slow", FakeArgs, tool, {"amount": 1}), ("broken", FakeArgs, broken, {}),
             ("slow", FakeArgs, tool, {"amount": 2})]
    prepared = mem.prepare_many(calls, request_ctx())
    assert isinstance(prepared[1], RuntimeError)
    assert [p.source for i, p in enumerate(prepared) if i != 1] == ["tool", "tool"]
