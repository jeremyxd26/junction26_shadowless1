"""A cache of tool results, so a repeated question or overview does not wait for the database.

Tool results are deterministic for (customer, tool, validated arguments, as_of, language, label state)
and the code that computes them (agent-core.md section 6.1). The key holds all of these:
- the label state is `labels_key`: a hash of the customer's basket labels as the request's viewer sees
  them (core/tools/labels.py, #144), never of the viewer itself. It is read once per request and kept
  on the ToolContext, so every tool call of the request shares it and a label write changes the key at
  once;
- the code version is a hash of core/tools/*.py and core/metrics/*.sql, so a deploy never serves a
  result of older code.
- the database identity is a hash of the database's host, port and name (never the URL), so a changed
  DATABASE_URL never serves numbers whose evidence lives in another database. A reset of the same
  database is caught by the warm-up, which checks that the evidence refs of every cached result exist.

Correctness comes from the key alone: a changed label set, as_of or code version is a different key, so
a stale entry is never served, whichever process wrote it. `invalidate_customer` only frees memory.

Layers: an LRU in memory (bounded by entries) and, in mode `disk`, a small sqlite file under var/cache
that the warm-up command (core/tools/warmup.py) fills and the service reads. Setting `TOOL_CACHE` is
`off`, `memory` or `disk` (default); `TOOL_CACHE_MAX_ENTRIES` and `TOOL_CACHE_DIR` tune it. Settings
come from the environment, else from the repository's .env. `TOOL_CACHE_WAIT_S` (default 5) limits how
long a caller waits for another caller's computation of the same key (single-flight) before it computes
itself. In the service container the repository
root is /srv and /srv/var is the persistent bind mount (#78), so the default directory is the right
one there; the warm-up runs inside that container, so both processes share one sqlite file. If the
directory cannot be written, the disk layer logs a warning and the memory layer still works.

Number ids (n1, n2, ...) belong to one answer's registry, so a cached result is never handed out with
the ids of the call that computed it. A miss runs the tool against a private registry and records the
numbers it registered, in order. Every use, hit or miss, registers those numbers in the answer's
registry in the same order and rewrites the ids in a copy of the result. The result is therefore
byte-identical to a fresh call in the same registry state, evidence refs included. The evidence specs
behind those refs were written by the miss into coach_evidence, the same table a fresh call writes to.

Safety: the customer is part of the key and is checked again on every read, so an entry of another
customer is never returned. Only result classes of core.tools are restored from disk (JSON, no pickle).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import AbstractContextManager, ExitStack, contextmanager, nullcontext
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from core.tools import labels
from core.tools.context import NumberRegistry, ToolContext
from core.tools.models import Card, Number, ToolResult

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MODES = ("off", "memory", "disk")
DEFAULT_MODE = "disk"
DEFAULT_MAX_ENTRIES = 512
DEFAULT_MAX_DISK_ENTRIES = 5000
DEFAULT_WAIT_S = 5.0   # a waiter's limit: a little above the slowest tool (03 is about 0.5 s on a busy db)
DEFAULT_DIR = ROOT / "var" / "cache"
DB_FILE = "tools.sqlite3"
SOURCES = (("core/tools", "*.py"), ("core/metrics", "*.sql"))   # not recursive: tests are not code
RESULT_MODULE_PREFIX = "core.tools."

Connector = Callable[[], AbstractContextManager[Any]]


# ---- settings and keys ------------------------------------------------------------------------------

def setting(name: str, environ: dict[str, str] | None = None) -> str | None:
    """A setting from the environment, else from the repository's .env (like core/tools/db.py)."""
    env = os.environ if environ is None else environ
    value = env.get(name)
    if not value and environ is None:
        env_file = ROOT / ".env"
        if env_file.exists():
            match = re.search(rf"^{re.escape(name)}=(.*)$", env_file.read_text(encoding="utf-8"), re.M)
            value = match.group(1).strip().strip("\"'") if match else None
    return value or None


@lru_cache(maxsize=1)
def code_version() -> str:
    """Hash of the code that computes tool results; line endings normalised, so a checkout's
    autocrlf does not matter."""
    h = hashlib.sha256()
    for folder, pattern in SOURCES:
        for path in sorted((ROOT / folder).glob(pattern)):
            h.update(path.relative_to(ROOT).as_posix().encode())
            h.update(b"\0")
            h.update(path.read_bytes().replace(b"\r\n", b"\n"))
            h.update(b"\0")
    return h.hexdigest()[:16]


@lru_cache(maxsize=1)
def database_identity() -> str:
    """A hash of the database's host, port and name, part of every key: after a change of DATABASE_URL
    no entry points at evidence rows of another database. Never the URL itself, never logged."""
    from core.tools import db

    url = db.database_url(required=False)
    if not url:
        return "no-database"
    try:
        from psycopg.conninfo import conninfo_to_dict

        parts = conninfo_to_dict(url)
    except Exception:  # noqa: BLE001 - the driver's text can repeat the URL; only a fixed marker is kept
        return "unparsed"
    text = "|".join(str(parts.get(k) or "") for k in ("host", "port", "dbname"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def label_set(labels_by_tx: dict[int, str]) -> list[list[Any]]:
    """Sorted [tx_id, basket] pairs, the canonical form the evidence specs store (labels.label_set)."""
    return labels.label_set(labels_by_tx)


def labels_key_of(labels_by_tx: dict[int, str]) -> str:
    text = json.dumps(label_set(labels_by_tx), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def args_json(args_model: type[BaseModel], args: Any) -> tuple[BaseModel, str]:
    """Validate the arguments (invalid ones raise before anything runs) and give their canonical JSON."""
    parsed = args if isinstance(args, args_model) else args_model.model_validate({} if args is None else args)
    return parsed, json.dumps(parsed.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


# Results that must not be stored, by tool: they depend on a state outside the key that is about to
# change. The peer benchmark reads the marts only when their build for as_of is complete and otherwise
# falls back to the customer's range (no group, "not shown"); such a result is served but never cached,
# so a warm-up during a mart build cannot pin "not shown" until the next deploy. A rebuild of complete
# marts with other data for the same as_of is a data reload, which the cache-reset runbook covers.
DO_NOT_STORE: dict[str, Callable[[ToolResult], bool]] = {
    "get_peer_benchmark": lambda result: getattr(result.data, "peer_source", "marts") != "marts",
}


# ---- entries --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Entry:
    """A result computed against a private number registry, and the numbers it registered, in order."""

    customer_id: str
    tool: str
    result: ToolResult
    registered: tuple[tuple[str, Number], ...]


class _OwnerFailed:
    """What a failed owner hands the callers waiting for its key, in place of a result. Never the owner's
    own exception: a cancelled request's BaseException (or a KeyboardInterrupt) belongs to that request
    alone. A waiter that receives this computes itself."""


OWNER_FAILED = _OwnerFailed()


@dataclass(frozen=True)
class Prepared:
    entry: Entry
    hit: bool          # served from memory or disk
    source: str        # "memory", "disk", "inflight" (another caller's computation), "tool" or "off"
    seconds: float
    key: str | None = None


def _remap(obj: Any, ids: dict[str, str], seen: set[int] | None = None) -> None:
    """Rewrite number ids in place: Number objects, and number dicts (id + unit) in cards and views.

    A copied result can hold the same object in several places (data.total is also card.primary), so
    each object is rewritten once: an old id and a new id can look alike (n6 -> n9, n9 -> n12).
    """
    seen = set() if seen is None else seen
    if isinstance(obj, (BaseModel, dict, list)):
        if id(obj) in seen:
            return
        seen.add(id(obj))
    if isinstance(obj, Number):
        if obj.id is not None:
            # An id the tool registered is remapped; one it set by hand (never registered) stays as a
            # fresh call would return it.
            obj.id = ids.get(obj.id, obj.id)
        return
    if isinstance(obj, BaseModel):
        for name in type(obj).model_fields:
            _remap(getattr(obj, name), ids, seen)
        for value in (obj.__pydantic_extra__ or {}).values():
            _remap(value, ids, seen)
    elif isinstance(obj, dict):
        if isinstance(obj.get("id"), str) and "unit" in obj and obj["id"] in ids:
            obj["id"] = ids[obj["id"]]
        for value in obj.values():
            _remap(value, ids, seen)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _remap(value, ids, seen)


def apply(entry: Entry, ctx: ToolContext) -> ToolResult:
    """The entry's result for this answer: its numbers registered in ctx.numbers, ids rewritten."""
    if entry.customer_id != ctx.customer_id:
        raise PermissionError("a cached result of another customer")
    ids = {old: ctx.numbers.register(n.model_copy(update={"id": None})).id for old, n in entry.registered}
    result = entry.result.model_copy(deep=True)
    _remap(result, ids)
    return result


def _dump(entry: Entry) -> str | None:
    """JSON for the disk layer, or None when the result class is not a core.tools model."""
    data = entry.result.data
    cls = type(data)
    if not isinstance(data, BaseModel) or not cls.__module__.startswith(RESULT_MODULE_PREFIX) or "." in cls.__qualname__:
        return None
    return json.dumps({
        "customer_id": entry.customer_id,
        "tool": entry.tool,
        "data_type": f"{cls.__module__}:{cls.__qualname__}",
        "result": entry.result.model_dump(mode="json"),
        "registered": [[old, n.model_dump(mode="json")] for old, n in entry.registered],
    }, ensure_ascii=False, separators=(",", ":"))


def _load(text: str) -> Entry:
    p = json.loads(text)
    module, _, name = p["data_type"].partition(":")
    if not module.startswith(RESULT_MODULE_PREFIX):
        raise ValueError("cached result class outside core.tools")
    data_cls = getattr(importlib.import_module(module), name)
    r = p["result"]
    result = ToolResult(tool=r["tool"], data=data_cls.model_validate(r["data"]),
                        card=Card.model_validate(r["card"]) if r["card"] is not None else None,
                        notes=r["notes"], evidence=r["evidence"], model_view=r["model_view"])
    registered = tuple((old, Number.model_validate(n)) for old, n in p["registered"])
    return Entry(customer_id=p["customer_id"], tool=p["tool"], result=result, registered=registered)


# ---- the cache ------------------------------------------------------------------------------------------

@dataclass
class Stats:
    hits: int = 0
    misses: int = 0
    disk_hits: int = 0
    waits: int = 0        # served by another caller's computation of the same key (single-flight)


@dataclass
class ToolCache:
    mode: str = DEFAULT_MODE
    max_entries: int = DEFAULT_MAX_ENTRIES
    directory: Path = DEFAULT_DIR
    max_disk_entries: int = DEFAULT_MAX_DISK_ENTRIES
    wait_s: float = DEFAULT_WAIT_S
    stats: Stats = field(default_factory=Stats)
    _memory: OrderedDict[str, Entry] = field(default_factory=OrderedDict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _inflight: dict[str, Future] = field(default_factory=dict, repr=False)
    _disk_ready: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"TOOL_CACHE must be one of {MODES}")
        if self.max_entries < 1:
            raise ValueError("TOOL_CACHE_MAX_ENTRIES must be at least 1")

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> ToolCache:
        mode = (setting("TOOL_CACHE", environ) or DEFAULT_MODE).strip().lower()
        if mode not in MODES:   # never fail an import over a typo; serve fresh results instead
            log.error("TOOL_CACHE must be one of %s; the tool cache is off", "/".join(MODES))
            mode = "off"
        raw = setting("TOOL_CACHE_MAX_ENTRIES", environ)
        try:
            max_entries = max(1, int(raw)) if raw else DEFAULT_MAX_ENTRIES
        except ValueError:      # never fail the service's import over a typo
            log.error("TOOL_CACHE_MAX_ENTRIES must be a whole number; using %d", DEFAULT_MAX_ENTRIES)
            max_entries = DEFAULT_MAX_ENTRIES
        directory = setting("TOOL_CACHE_DIR", environ)
        path = Path(directory) if directory else DEFAULT_DIR
        if not path.is_absolute():
            path = ROOT / path
        raw_wait = setting("TOOL_CACHE_WAIT_S", environ)
        try:
            wait_s = max(0.0, float(raw_wait)) if raw_wait else DEFAULT_WAIT_S
        except ValueError:      # never fail the service's import over a typo
            log.error("TOOL_CACHE_WAIT_S must be a number of seconds; using %.1f", DEFAULT_WAIT_S)
            wait_s = DEFAULT_WAIT_S
        return cls(mode=mode, max_entries=max_entries, directory=path, wait_s=wait_s)

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    # ---- keys ----

    def ensure_labels_key(self, ctx: ToolContext, connection: Connector | None = None) -> str:
        """ctx.labels_key: the hash of `labels.for_context(ctx)`, the very label set the tools use, read
        once per request (with ctx.conn, or a connection from `connection`; the overview fills it from
        its one reviews read). With per-viewer answers (#144) the set is the viewer's, so two viewers
        with different answers get different keys and viewers in the same state share entries. The
        viewer itself is never part of a key, an entry or a log.

        The key is always made from the label set on the context (ctx._labels), the set the tools will
        use, and never taken from a preset value: a key without its set would let the tools read the
        labels again, and a label write in between would store a value under the key of other labels.
        Without a set on the context, it is read here once (for the context's viewer, #144).
        """
        if ctx._labels is None:
            with _connected(ctx, connection):
                ctx._labels = labels.for_context(ctx)        # reads the set once and keeps it on ctx
        ctx.labels_key = labels_key_of(ctx._labels)          # hashing the set needs no read
        return ctx.labels_key

    @staticmethod
    def key(ctx: ToolContext, tool: str, canonical_args: str) -> str:
        parts = [code_version(), database_identity(), ctx.customer_id, tool, canonical_args, ctx.as_of.isoformat(),
                 ctx.language, ctx.labels_key]
        return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode("utf-8")).hexdigest()

    # ---- calls ----

    def run(self, tool: str, args_model: type[BaseModel], fn: Callable[[ToolContext, Any], ToolResult],
            ctx: ToolContext, args: Any = None, connection: Connector | None = None) -> ToolResult:
        """Call a tool through the cache. With the cache off this is exactly `fn(ctx, args)`."""
        if not self.enabled:
            parsed, _ = args_json(args_model, args)
            with _connected(ctx, connection):
                return fn(ctx, parsed)
        return apply(self.prepare(tool, args_model, fn, ctx, args, connection).entry, ctx)

    def prepare(self, tool: str, args_model: type[BaseModel], fn: Callable[[ToolContext, Any], ToolResult],
                ctx: ToolContext, args: Any = None, connection: Connector | None = None) -> Prepared:
        """Find or compute the entry; thread-safe, so independent calls can be prepared in parallel and
        then applied in a fixed order. A hit needs no connection once ctx.labels_key is known."""
        t0 = time.perf_counter()
        parsed, canonical = args_json(args_model, args)
        if not self.enabled:
            private = replace(ctx, numbers=NumberRegistry())
            with _connected(private, connection):
                result = fn(private, parsed)
            entry = Entry(ctx.customer_id, tool, result, tuple(private.numbers.all().items()))
            return Prepared(entry, False, "off", time.perf_counter() - t0)

        # The labels first: the private context below is a copy of ctx (its _labels included), so the
        # tool sees the very label set the key was made from.
        self.ensure_labels_key(ctx, connection)
        private = replace(ctx, numbers=NumberRegistry())
        key = self.key(ctx, tool, canonical)
        found = self.get(key, ctx.customer_id)
        if found is not None:
            entry, source = found
            return Prepared(entry, True, source, time.perf_counter() - t0, key)

        # Single-flight: of the callers that miss the same key at once, the first computes and the others
        # wait for its result (ten cold overviews run the metric SQL once). A waiter whose owner fails or
        # takes longer than wait_s computes itself. No deadlock: a caller waits only here, before it owns
        # anything, and an owner computes without waiting on another key; every wait is also bounded.
        # The owner stores its result before it leaves _inflight, so a caller that missed above while an
        # owner was finishing finds the result in memory here and does not compute it again.
        with self._lock:
            stored = self._memory.get(key)
            if stored is not None and stored.customer_id == ctx.customer_id:
                self._memory.move_to_end(key)
                self.stats.hits += 1
                return Prepared(stored, True, "memory", time.perf_counter() - t0, key)
            flight = self._inflight.get(key)
            owner = flight is None
            if owner:
                flight = self._inflight[key] = Future()
        if not owner:
            try:
                entry = flight.result(timeout=self.wait_s)
            except (FutureTimeout, CancelledError):   # the owner is slow: compute here instead
                entry = None
            # Only these two: the owner never sets an exception, and the waiter's own interrupt must
            # reach it. OWNER_FAILED (the owner raised) also makes the waiter compute.
            if isinstance(entry, Entry) and entry.customer_id == ctx.customer_id:   # checked anyway
                with self._lock:
                    self.stats.hits += 1
                    self.stats.waits += 1
                return Prepared(entry, True, "inflight", time.perf_counter() - t0, key)

        try:
            # The tool reads its labels through labels.for_context(private): the set copied from ctx, from
            # which the key was made. A label write during the call cannot slip a result of other labels
            # under this key; the next request reads the new labels and gets a new key.
            with _connected(private, connection):
                result = fn(private, parsed)
            if ctx._history is None and private._history is not None:
                ctx._history = private._history   # the transactions read by this call serve the next one
            entry = Entry(ctx.customer_id, tool, result, tuple(private.numbers.all().items()))
            skip = DO_NOT_STORE.get(tool)
            if skip is None or not skip(result):
                self.put(key, entry)
            with self._lock:
                self.stats.misses += 1
        except BaseException:
            if owner:
                flight.set_result(OWNER_FAILED)   # never the exception itself: it is this caller's alone
            raise
        finally:
            if owner:
                with self._lock:
                    self._inflight.pop(key, None)
        if owner:
            flight.set_result(entry)
        return Prepared(entry, False, "tool", time.perf_counter() - t0, key)

    def prepare_many(self, calls: list[tuple[str, type[BaseModel], Callable, Any]], ctx: ToolContext,
                     extra_connection: Connector | None = None) -> list[Prepared | Exception]:
        """Prepare several independent calls of one request; apply the results in list order.

        Hits are served at once. Misses run on ctx.conn, and when there are two or more and
        `extra_connection` gives a second connection, half of them run on that one in parallel
        (the pool's limit is two connections). If the second connection is not available at once,
        everything runs on ctx.conn. The customer's transactions are read once and shared.
        A call that fails gives its exception in its place, so one card can fail alone; the caller
        decides what to show.
        """
        out: list[Prepared | Exception | None] = [None] * len(calls)
        if self.enabled:
            self.ensure_labels_key(ctx)
            for i, (name, args_model, _, args) in enumerate(calls):
                out[i] = self.lookup(name, args_model, ctx, args)
        misses = [i for i, p in enumerate(out) if p is None]

        def run(lane: list[int], connection: Connector | None) -> None:
            for i in lane:
                name, args_model, fn, args = calls[i]
                try:
                    out[i] = self.prepare(name, args_model, fn, ctx, args, connection)
                except Exception as exc:  # noqa: BLE001 - this call fails alone
                    out[i] = exc

        if len(misses) < 2 or extra_connection is None:
            run(misses, None)
            return out  # type: ignore[return-value]
        if ctx._history is None:
            ctx.history()   # one transactions read on ctx.conn, copied into every call's context
        own, other = misses[0::2], misses[1::2]
        with ExitStack() as stack:
            try:
                conn = stack.enter_context(extra_connection())
            except Exception as exc:  # noqa: BLE001 - no second connection now: stay on the first one
                log.info("tool cache: no second connection (%s); calls run one after another", type(exc).__name__)
                run(misses, None)
                return out  # type: ignore[return-value]
            if conn is ctx.conn:   # the same connection twice (a one-connection pool): never use it from two threads
                stack.close()
                run(misses, None)
                return out  # type: ignore[return-value]
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(run, own, None), pool.submit(run, other, lambda: nullcontext(conn))]
                for future in futures:
                    future.result()
        return out  # type: ignore[return-value]

    def lookup(self, tool: str, args_model: type[BaseModel], ctx: ToolContext, args: Any = None) -> Prepared | None:
        """The cached entry for this call, or None; never runs and never reads anything. Without the
        context's label set (ctx._labels) there is no key to look under, so it is None."""
        if not self.enabled or ctx._labels is None:
            return None
        self.ensure_labels_key(ctx)                          # from the set on the context: no read
        t0 = time.perf_counter()
        _, canonical = args_json(args_model, args)
        key = self.key(ctx, tool, canonical)
        found = self.get(key, ctx.customer_id)
        if found is None:
            return None
        return Prepared(found[0], True, found[1], time.perf_counter() - t0, key)

    # ---- storage ----

    def get(self, key: str, customer_id: str) -> tuple[Entry, str] | None:
        with self._lock:
            entry = self._memory.get(key)
            if entry is not None:
                if entry.customer_id != customer_id:   # never another customer's entry
                    log.error("tool cache: key of one customer held an entry of another; dropped")
                    del self._memory[key]
                    return None
                self._memory.move_to_end(key)
                self.stats.hits += 1
                return entry, "memory"
        if self.mode != "disk":
            return None
        entry = self._disk_get(key, customer_id)
        if entry is None:
            return None
        with self._lock:
            self._remember(key, entry)
            self.stats.hits += 1
            self.stats.disk_hits += 1
        return entry, "disk"

    def put(self, key: str, entry: Entry) -> None:
        with self._lock:
            self._remember(key, entry)
        if self.mode == "disk":
            self._disk_put(key, entry)

    def _remember(self, key: str, entry: Entry) -> None:
        self._memory[key] = entry
        self._memory.move_to_end(key)
        while len(self._memory) > self.max_entries:
            self._memory.popitem(last=False)

    def invalidate_customer(self, customer_id: str) -> int:
        """Drop the customer's entries from memory, after a label write. Memory hygiene only: the label
        set is in the key, so the old entries can never be served again. The disk rows stay: they are
        unreachable under the new labels, and an undo back to the earlier labels finds them warm again.
        Returns the number dropped."""
        with self._lock:
            keys = [k for k, e in self._memory.items() if e.customer_id == customer_id]
            for k in keys:
                del self._memory[k]
        return len(keys)

    def drop(self, key: str) -> None:
        """Forget one entry in memory and on disk (the warm-up's evidence check)."""
        with self._lock:
            self._memory.pop(key, None)
        if self.mode == "disk" and self._db_path().exists():
            try:
                with self._db() as db:
                    db.execute("DELETE FROM tool_cache WHERE key = ?", (key,))
            except Exception as exc:  # noqa: BLE001 - a broken cache file must never fail a request
                log.warning("tool cache: disk delete failed (%s)", type(exc).__name__)

    def clear(self) -> None:
        with self._lock:
            self._memory.clear()
        if self.mode == "disk" and self._db_path().exists():
            try:
                with self._db() as db:
                    db.execute("DELETE FROM tool_cache")
            except Exception as exc:  # noqa: BLE001 - corrupted, read-only or locked: memory is cleared
                log.warning("tool cache: disk clear failed (%s)", type(exc).__name__)

    def __len__(self) -> int:
        return len(self._memory)

    # ---- disk layer (sqlite, JSON payloads) ----

    def _db_path(self) -> Path:
        return self.directory / DB_FILE

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        if not self._disk_ready:
            self.directory.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self._db_path(), timeout=5)
        try:
            if not self._disk_ready:
                db.execute("PRAGMA journal_mode=WAL")   # the service reads while the warm-up writes
                db.execute("CREATE TABLE IF NOT EXISTS tool_cache (key TEXT PRIMARY KEY, customer_id TEXT NOT NULL, "
                           "tool TEXT NOT NULL, created_at REAL NOT NULL, payload TEXT NOT NULL)")
                db.execute("CREATE INDEX IF NOT EXISTS tool_cache_customer ON tool_cache (customer_id)")
                self._disk_ready = True
            with db:
                yield db
        finally:
            db.close()

    def _disk_get(self, key: str, customer_id: str) -> Entry | None:
        if not self._db_path().exists():
            return None
        try:
            with self._db() as db:
                row = db.execute("SELECT customer_id, payload FROM tool_cache WHERE key = ?", (key,)).fetchone()
            if row is None or row[0] != customer_id:
                return None
            entry = _load(row[1])
        except Exception as exc:  # noqa: BLE001 - a broken cache file must never break an answer
            log.warning("tool cache: disk read failed (%s); computing instead", type(exc).__name__)
            return None
        return entry if entry.customer_id == customer_id else None

    def _disk_put(self, key: str, entry: Entry) -> None:
        payload = _dump(entry)
        if payload is None:
            return
        try:
            with self._db() as db:
                db.execute("INSERT OR REPLACE INTO tool_cache VALUES (?, ?, ?, ?, ?)",
                           (key, entry.customer_id, entry.tool, time.time(), payload))
                db.execute("DELETE FROM tool_cache WHERE key IN (SELECT key FROM tool_cache "
                           "ORDER BY created_at DESC LIMIT -1 OFFSET ?)", (self.max_disk_entries,))
        except Exception as exc:  # noqa: BLE001 - the memory layer still holds the entry
            log.warning("tool cache: disk write failed (%s)", type(exc).__name__)


@contextmanager
def _connected(ctx: ToolContext, connection: Connector | None) -> Iterator[ToolContext]:
    """Give ctx a connection for a tool run: its own, or one from `connection` for the run only."""
    if connection is None:
        yield ctx
        return
    saved = ctx.conn
    try:
        with connection() as conn:
            ctx.conn = conn
            yield ctx
    finally:
        ctx.conn = saved   # never leave a released pool connection on the caller's context


TOOL_CACHE = ToolCache.from_env()
