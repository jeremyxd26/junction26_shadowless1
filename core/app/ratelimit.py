"""Per-process sliding-window rate limits for write and model endpoints (#144).

One limiter holds several named limits, each counted per key over the same window, for example
{"address": 10, "customer": 30} per minute. A request is admitted only if every limit allows it, and
only an admitted request counts. When a limit is full, `allow` says how many seconds until the
oldest counted request leaves the window: that is the `Retry-After` of the 429.

It lives under core/app so every endpoint can use it: POST /api/baskets/label now, and POST /api/ask
(#59, whose limiter has the same shape) can move to it later. Memory stays bounded: empty keys are
dropped, and a key never holds more entries than its limit.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Request


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
        """(admitted, retry_after_seconds). `keys` names the key of each limit, e.g. the address."""
        now = self._clock()
        with self._lock:
            self._calls += 1
            if self._calls % 1000 == 0:
                self._prune(now)
            retry = 0.0
            for name, limit in self.limits.items():
                hits = self._window(name, keys[name], now)
                if len(hits) >= limit:
                    retry = max(retry, self.window_s - (now - hits[0]))
            if retry > 0:
                return False, max(1, math.ceil(retry))
            for name in self.limits:
                self._hits.setdefault((name, keys[name]), deque()).append(now)
            return True, 0

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


def client_address(request: Request) -> str:
    """The client's address. Behind Caddy the service runs uvicorn with --proxy-headers, so this is the
    address the proxy saw, not the proxy's own."""
    return request.client.host if request.client else "unknown"
