"""Rate-limit guard for the OnlyMonster API.

Per https://omapi.onlymonster.ai/docs/json the limits are:
  • Token-wide: 25 requests / second across all endpoints
  • Per-endpoint: 15 requests / second per endpoint by default
  • 429 = rate-limit exceeded

Implementation: two layers of sliding-window counters protected by an
asyncio.Lock.  Before every outbound request we acquire both — global
first, then per-endpoint.  If either window is full we sleep until the
oldest entry ages out.  The orchestrator additionally honours `Retry-After`
on 429 responses (handled in client.py) so persistent throttling backs off
exponentially without overlapping with this proactive limiter.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

logger = logging.getLogger(__name__)


class _SlidingWindow:
    """Tiny sliding-window limiter — at most `rate` events per `period`."""

    def __init__(self, rate: int, period: float = 1.0) -> None:
        self._rate = max(int(rate), 1)
        self._period = period
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            cutoff = now - self._period
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            if len(self._timestamps) >= self._rate:
                wait_for = self._period - (now - self._timestamps[0])
                if wait_for > 0:
                    await asyncio.sleep(wait_for)
                # Re-prune after sleep before recording our slot.
                now = time.monotonic()
                cutoff = now - self._period
                while self._timestamps and self._timestamps[0] < cutoff:
                    self._timestamps.popleft()
            self._timestamps.append(now)


class OnlyMonsterRateLimiter:
    """Combined global + per-endpoint sliding-window limiter.

    Some OnlyMonster endpoints are stricter than the per-endpoint default
    (`/api/v0/accounts/{id}/fans` is 1/sec, vault endpoints are 3–5/sec,
    etc.).  Use `set_endpoint_rate(path, n)` or pass `endpoint_rate_overrides`
    at construction to register a tighter limit for a specific path.
    Bucket creation is lazy — call `set_endpoint_rate` before the first
    `acquire(...)` for an endpoint (catalog wiring time).
    """

    def __init__(
        self,
        *,
        global_rate: int = 25,
        per_endpoint_rate: int = 15,
        endpoint_rate_overrides: dict[str, int] | None = None,
    ) -> None:
        self._global = _SlidingWindow(global_rate)
        self._per_endpoint: dict[str, _SlidingWindow] = {}
        self._per_endpoint_rate = per_endpoint_rate
        self._overrides: dict[str, int] = dict(endpoint_rate_overrides or {})
        self._dict_lock = asyncio.Lock()

    def set_endpoint_rate(self, endpoint_key: str, rate: int) -> None:
        """Register a stricter (or looser) rate for a specific endpoint key."""
        self._overrides[endpoint_key] = max(int(rate), 1)

    async def acquire(self, endpoint_key: str) -> None:
        await self._global.acquire()
        bucket = await self._endpoint_bucket(endpoint_key)
        await bucket.acquire()

    async def _endpoint_bucket(self, key: str) -> _SlidingWindow:
        # Cheap path — read without lock when bucket already exists.
        bucket = self._per_endpoint.get(key)
        if bucket is not None:
            return bucket
        async with self._dict_lock:
            bucket = self._per_endpoint.get(key)
            if bucket is None:
                rate = self._overrides.get(key, self._per_endpoint_rate)
                bucket = _SlidingWindow(rate)
                self._per_endpoint[key] = bucket
            return bucket
