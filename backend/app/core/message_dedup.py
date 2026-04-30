"""
message_dedup — idempotency guard for inbound messages.

Used to prevent duplicate processing when:
  • Telegram replays a webhook update after switching webhook<->polling modes
  • Discord re-dispatches a message after a gateway reconnect
  • OpenClaw or any upstream retries on transient error

Storage:
  • Redis SET `mc:dedup:<namespace>` with per-member TTL via a companion ZSET
    (keys expire after _TTL_S).
  • In-memory LRU fallback (size _MAX_MEMORY) if Redis is unreachable.

API is boolean: `seen(key, namespace)` atomically records + tests.  True →
"already seen, skip processing".  False → "first time, proceed".
"""

from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict
from threading import RLock
from typing import Any

__all__ = ["seen", "namespace_size"]

logger = logging.getLogger(__name__)

_TTL_S = 24 * 3600  # 24-hour replay window — generous but bounded
_MAX_MEMORY = 10_000  # fallback LRU size per namespace
_MEM: dict[str, "OrderedDict[str, float]"] = {}
_mem_lock = RLock()
_redis_warned = False


def _redis() -> Any | None:
    global _redis_warned
    try:
        import redis

        from app.core.config import settings

        client = redis.Redis.from_url(os.getenv("MC_DEDUP_REDIS_URL") or settings.rq_redis_url)
        client.ping()
        return client
    except Exception as exc:
        if not _redis_warned:
            logger.warning("message_dedup: Redis unavailable (%s) — in-memory fallback", exc)
            _redis_warned = True
        return None


def _zset_key(namespace: str) -> str:
    return f"mc:dedup:{namespace}"


def seen(key: str, namespace: str) -> bool:
    """Return True if (namespace, key) was seen within the TTL window."""
    key = str(key)
    client = _redis()
    if client is not None:
        try:
            zkey = _zset_key(namespace)
            now = time.time()
            # Lazy-evict anything beyond the TTL window
            client.zremrangebyscore(zkey, "-inf", now - _TTL_S)
            # Atomic "add-if-absent": ZADD NX returns 1 if added, 0 if already present
            added = client.zadd(zkey, {key: now}, nx=True)
            if added == 0:
                return True
            # Cap size at something sane to prevent runaway growth
            client.zremrangebyrank(zkey, 0, -50_001)
            return False
        except Exception as exc:
            logger.warning("message_dedup.redis_failed ns=%s key=%s error=%s", namespace, key, exc)

    with _mem_lock:
        store = _MEM.setdefault(namespace, OrderedDict())
        now = time.time()
        # evict by TTL
        expired = [k for k, ts in store.items() if ts < now - _TTL_S]
        for k in expired:
            store.pop(k, None)
        if key in store:
            store.move_to_end(key)
            return True
        store[key] = now
        if len(store) > _MAX_MEMORY:
            store.popitem(last=False)
        return False


def namespace_size(namespace: str) -> int:
    """Debug helper — how many fingerprints are currently tracked."""
    client = _redis()
    if client is not None:
        try:
            return int(client.zcard(_zset_key(namespace)))
        except Exception:
            pass
    with _mem_lock:
        return len(_MEM.get(namespace, {}))
