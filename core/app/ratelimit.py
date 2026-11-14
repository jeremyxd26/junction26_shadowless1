"""Per-process sliding-window rate limits for write and model endpoints (#144).

One limiter holds several named limits over the same window, each counted per key, for example
{"address": 10, "viewer": 10} per minute. A call names the keys of the limits that apply to it; a limit
whose name it does not give is not checked. A request is admitted only if every named limit allows it,
and only an admitted request counts. When a limit is full, the result says how many seconds until the
oldest counted request leaves the window: that is the `Retry-After` of the 429.

`reserve` and `release` are for a limit that should count only an event that happened (a new viewer
session counts once its first answer is stored, not for every refused attempt): `reserve` checks and
counts in one step, so two concurrent requests cannot both take the last slot, and `release` takes the
reserved count back when the event did not happen after all.

It lives under core/app so every endpoint can use it: POST /api/baskets/label now, and POST /api/ask
(#59, whose limiter has the same shape) can move to it later. Memory stays bounded: empty keys are
dropped, and a key never holds more entries than its limit. No key is ever stored beyond the window.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    def __init__(self, limits: dict[str, int], window_s: float = 60.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.limits = {name: limit for name, limit in limits.items() if limit > 0}  # 0 = off
        self.window_s = window_s
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def allow(self, keys: dict[str, str]) -> tuple[bool, int]:
        """(admitted, retry_after_seconds); an admitted request is counted for every named limit."""
        ok, retry, _ = self.reserve(keys)
        return ok, retry

    def reserve(self, keys: dict[str, str]) -> tuple[bool, int, float | None]:
        """Like allow, and also returns the token that `release` takes (None when refused)."""
        with self._lock:
            now = self._clock()
            ok, retry = self._check(keys, now)
            if not ok:
                return False, retry, None
            self._record(keys, now)
            return True, 0, now

    def release(self, keys: dict[str, str], token: float) -> None:
        """Take back the count of a reserved request that did not happen (the same keys as `reserve`)."""
        with self._lock:
            for name in self.limits:
                if name not in keys:
                    continue
                hits = self._hits.get((name, keys[name]))
                if hits is not None and token in hits:
                    hits.remove(token)
                    if not hits:
                        del self._hits[(name, keys[name])]

    def _check(self, keys: dict[str, str], now: float) -> tuple[bool, int]:
        self._calls += 1
        if self._calls % 1000 == 0:
            self._prune(now)
        retry = 0.0
        for name, limit in self.limits.items():
            if name not in keys:
                continue
            hits = self._window(name, keys[name], now)
            if len(hits) >= limit:
                retry = max(retry, self.window_s - (now - hits[0]))
        if retry > 0:
            return False, max(1, math.ceil(retry))
        return True, 0

    def _record(self, keys: dict[str, str], now: float) -> None:
        for name in self.limits:
            if name in keys:
                self._hits.setdefault((name, keys[name]), deque()).append(now)

    def _window(self, name: str, key: str, now: float) -> deque[float]:
        hits = self._hits.get((name, key), deque())
        while hits and now - hits[0] >= self.window_s:
            hits.popleft()
        return hits

    def _prune(self, now: float) -> None:
        for k in list(self._hits):
            if not self._window(k[0], k[1], now):
                del self._hits[k]

    def size(self) -> int:
        """Keys currently held (for tests)."""
        return len(self._hits)
