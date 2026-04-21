"""
control_tasks_store — Redis-backed store for the Mission Control task queue.

Replaces the Phase-3 in-memory implementation while keeping the exact public
API so `app/core/task_queue.py` (now a shim) and `app/api/control_tasks.py`
don't have to change.

Redis layout
------------
  mc:control:queue                    LIST     FIFO pending task IDs (LPUSH / BRPOP)
  mc:control:queue:scheduled          ZSET     id → epoch-seconds for delayed/retry
  mc:control:task:<id>                STRING   JSON blob of the Task (TTL 7 days)
  mc:control:index                    ZSET     id → created_at (listing / GC)
  mc:control:inflight                 ZSET     id → claim timestamp (visibility timeout)

Properties
----------
• Persistent across restarts (Redis owns the queue).
• Visibility timeout: claimed tasks re-appear in the queue if not completed
  within _CLAIM_TIMEOUT_S.  Sweep runs on every `claim_next()` call + on list
  reads, so there's no separate worker required.
• Retry-aware: `record_result(status="failed")` increments `attempts` and
  (below _MAX_ATTEMPTS) re-queues with exponential backoff.
• Graceful degradation: if Redis is unreachable, falls back to a process-local
  in-memory implementation so dev/test environments and offline smoke tests
  still work.  Logs a warning once per process.

Scales
------
Multiple backend replicas share one Redis instance → they all see the same
queue. CLAW nodes on any device call `claim_next()` and receive exclusive
ownership of a task via the Redis atomics (RPOPLPUSH-style with inflight ZSET).
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from threading import RLock
from typing import Any, Literal

__all__ = [
    "Task",
    "TaskStatus",
    "enqueue",
    "list_tasks",
    "get_task",
    "claim_next",
    "record_result",
    "queue_depth",
    "inflight_count",
    "sweep_inflight",
]

logger = logging.getLogger(__name__)

TaskStatus = Literal["queued", "running", "done", "failed", "cancelled"]

# ── Tunables ─────────────────────────────────────────────────────────────────
_NS = "mc:control"
_QUEUE_KEY          = f"{_NS}:queue"
_SCHEDULED_KEY      = f"{_NS}:queue:scheduled"
_INFLIGHT_KEY       = f"{_NS}:inflight"
_INDEX_KEY          = f"{_NS}:index"
_TASK_KEY_FMT       = f"{_NS}:task:{{task_id}}"
_TASK_TTL_S         = 7 * 24 * 3600          # week of history
_CLAIM_TIMEOUT_S    = 300.0                  # 5 min — reclaim if node died
_MAX_ATTEMPTS       = 3
_BASE_RETRY_DELAY_S = 2.0
_LIST_CAP           = 500


@dataclass
class Task:
    id:          str
    kind:        str
    payload:     dict[str, Any]
    status:      TaskStatus = "queued"
    agent_id:    str | None = None
    device_id:   str | None = None
    result:      Any = None
    error:       str | None = None
    created_at:  float = 0.0
    started_at:  float | None = None
    finished_at: float | None = None
    tags:        list[str] = field(default_factory=list)
    attempts:    int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ═════════════════════════════════════════════════════════════════════════════
# Redis backend (preferred)
# ═════════════════════════════════════════════════════════════════════════════

_redis_warned = False


def _redis():
    """Return a redis.Redis client or None if unavailable."""
    global _redis_warned
    try:
        import redis
        from app.core.config import settings
        client = redis.Redis.from_url(
            os.getenv("MC_CONTROL_QUEUE_REDIS_URL") or settings.rq_redis_url
        )
        client.ping()
        return client
    except Exception as exc:
        if not _redis_warned:
            logger.warning(
                "control_tasks_store: Redis unavailable (%s) — falling back to in-memory. "
                "Persistence and multi-replica scaling are disabled until Redis recovers.",
                exc,
            )
            _redis_warned = True
        return None


def _task_key(task_id: str) -> str:
    return _TASK_KEY_FMT.format(task_id=task_id)


def _save_task_redis(client, task: Task) -> None:
    client.set(_task_key(task.id), json.dumps(task.to_dict()), ex=_TASK_TTL_S)


def _load_task_redis(client, task_id: str) -> Task | None:
    raw = client.get(_task_key(task_id))
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return Task(**json.loads(raw))
    except Exception:
        return None


def _sweep_inflight_redis(client) -> int:
    """Re-queue tasks that have been inflight past the visibility timeout."""
    cutoff = time.time() - _CLAIM_TIMEOUT_S
    stuck_ids = client.zrangebyscore(_INFLIGHT_KEY, "-inf", cutoff)
    recovered = 0
    for tid_raw in stuck_ids or []:
        tid = tid_raw.decode("utf-8") if isinstance(tid_raw, bytes) else tid_raw
        client.zrem(_INFLIGHT_KEY, tid_raw)
        task = _load_task_redis(client, tid)
        if not task or task.status in ("done", "failed", "cancelled"):
            continue
        task.status = "queued"
        task.device_id = None
        task.started_at = None
        task.attempts += 1
        _save_task_redis(client, task)
        client.lpush(_QUEUE_KEY, tid)
        recovered += 1
        logger.warning(
            "control_tasks_store.visibility_timeout id=%s attempt=%d",
            tid, task.attempts,
        )
    return recovered


def _drain_scheduled_redis(client) -> None:
    now = time.time()
    ready = client.zrangebyscore(_SCHEDULED_KEY, "-inf", now)
    if not ready:
        return
    pipe = client.pipeline()
    for tid_raw in ready:
        pipe.lpush(_QUEUE_KEY, tid_raw)
        pipe.zrem(_SCHEDULED_KEY, tid_raw)
    pipe.execute()


# ═════════════════════════════════════════════════════════════════════════════
# In-memory fallback (dev/offline only)
# ═════════════════════════════════════════════════════════════════════════════

_mem_lock = RLock()
_mem_tasks: dict[str, Task] = {}
_mem_queue: deque[str] = deque()
_mem_inflight: dict[str, float] = {}     # task_id → claim_ts


def _sweep_inflight_memory() -> int:
    cutoff = time.time() - _CLAIM_TIMEOUT_S
    recovered = 0
    with _mem_lock:
        for tid, ts in list(_mem_inflight.items()):
            if ts < cutoff:
                task = _mem_tasks.get(tid)
                _mem_inflight.pop(tid, None)
                if not task or task.status in ("done", "failed", "cancelled"):
                    continue
                task.status = "queued"
                task.device_id = None
                task.started_at = None
                task.attempts += 1
                _mem_queue.append(tid)
                recovered += 1
    return recovered


# ═════════════════════════════════════════════════════════════════════════════
# Public API (signature-compatible with Phase-3 task_queue.py)
# ═════════════════════════════════════════════════════════════════════════════

def enqueue(
    kind: str,
    payload: dict[str, Any],
    agent_id: str | None = None,
    tags: list[str] | None = None,
) -> Task:
    task = Task(
        id=uuid.uuid4().hex[:16],
        kind=kind,
        payload=payload or {},
        agent_id=agent_id,
        tags=tags or [],
        created_at=time.time(),
    )
    client = _redis()
    if client is not None:
        try:
            _save_task_redis(client, task)
            client.zadd(_INDEX_KEY, {task.id: task.created_at})
            client.lpush(_QUEUE_KEY, task.id)
            # Light GC — keep index from growing unbounded
            client.zremrangebyrank(_INDEX_KEY, 0, -(_LIST_CAP * 2) - 1)
            logger.info("control_tasks_store.enqueued id=%s kind=%s backend=redis", task.id, kind)
            return task
        except Exception as exc:
            logger.warning("control_tasks_store.enqueue redis failed: %s (falling back)", exc)

    with _mem_lock:
        _mem_tasks[task.id] = task
        _mem_queue.append(task.id)
    logger.info("control_tasks_store.enqueued id=%s kind=%s backend=memory", task.id, kind)
    return task


def get_task(task_id: str) -> Task | None:
    client = _redis()
    if client is not None:
        try:
            return _load_task_redis(client, task_id)
        except Exception as exc:
            logger.warning("control_tasks_store.get_task redis failed: %s", exc)
    with _mem_lock:
        return _mem_tasks.get(task_id)


def list_tasks(status: TaskStatus | None = None, limit: int = 100) -> list[Task]:
    client = _redis()
    if client is not None:
        try:
            _drain_scheduled_redis(client)
            _sweep_inflight_redis(client)
            ids = client.zrevrange(_INDEX_KEY, 0, min(limit, _LIST_CAP) - 1)
            tasks: list[Task] = []
            for tid_raw in ids:
                tid = tid_raw.decode("utf-8") if isinstance(tid_raw, bytes) else tid_raw
                t = _load_task_redis(client, tid)
                if t:
                    tasks.append(t)
            if status:
                tasks = [t for t in tasks if t.status == status]
            return tasks[:limit]
        except Exception as exc:
            logger.warning("control_tasks_store.list_tasks redis failed: %s (falling back)", exc)

    _sweep_inflight_memory()
    with _mem_lock:
        tasks = sorted(_mem_tasks.values(), key=lambda t: t.created_at, reverse=True)
    if status:
        tasks = [t for t in tasks if t.status == status]
    return tasks[:limit]


def claim_next(device_id: str, kinds: list[str] | None = None) -> Task | None:
    client = _redis()
    if client is not None:
        try:
            _drain_scheduled_redis(client)
            _sweep_inflight_redis(client)
            skipped: list[str] = []
            claimed: Task | None = None
            # Walk the queue a bounded number of times looking for a kind match
            for _ in range(256):
                tid_raw = client.rpop(_QUEUE_KEY)
                if tid_raw is None:
                    break
                tid = tid_raw.decode("utf-8") if isinstance(tid_raw, bytes) else tid_raw
                task = _load_task_redis(client, tid)
                if task is None or task.status != "queued":
                    continue
                if kinds and task.kind not in kinds:
                    skipped.append(tid)
                    continue
                # Atomic-ish claim: flip status + record inflight.
                task.status = "running"
                task.device_id = device_id
                task.started_at = time.time()
                _save_task_redis(client, task)
                client.zadd(_INFLIGHT_KEY, {tid: task.started_at})
                claimed = task
                break
            # Restore skipped tasks to the front of the queue (FIFO preserved)
            if skipped:
                pipe = client.pipeline()
                for tid in reversed(skipped):
                    pipe.lpush(_QUEUE_KEY, tid)
                pipe.execute()
            return claimed
        except Exception as exc:
            logger.warning("control_tasks_store.claim_next redis failed: %s (falling back)", exc)

    _sweep_inflight_memory()
    with _mem_lock:
        skipped: list[str] = []
        claimed: Task | None = None
        while _mem_queue:
            tid = _mem_queue.popleft()
            task = _mem_tasks.get(tid)
            if not task or task.status != "queued":
                continue
            if kinds and task.kind not in kinds:
                skipped.append(tid)
                continue
            task.status = "running"
            task.device_id = device_id
            task.started_at = time.time()
            _mem_inflight[tid] = task.started_at
            claimed = task
            break
        for tid in reversed(skipped):
            _mem_queue.appendleft(tid)
        return claimed


def record_result(
    task_id: str,
    status: TaskStatus,
    result: Any = None,
    error: str | None = None,
) -> Task | None:
    retry_delay = 0.0

    client = _redis()
    if client is not None:
        try:
            task = _load_task_redis(client, task_id)
            if task is None:
                return None
            client.zrem(_INFLIGHT_KEY, task_id)
            if status == "failed" and task.attempts + 1 < _MAX_ATTEMPTS:
                task.attempts += 1
                task.status = "queued"
                task.error = error
                task.device_id = None
                task.started_at = None
                retry_delay = _BASE_RETRY_DELAY_S * (2 ** (task.attempts - 1))
                _save_task_redis(client, task)
                client.zadd(_SCHEDULED_KEY, {task.id: time.time() + retry_delay})
                logger.info(
                    "control_tasks_store.retry id=%s attempt=%d delay=%.1fs",
                    task.id, task.attempts, retry_delay,
                )
                return task
            task.status = status
            task.result = result
            task.error = error
            task.finished_at = time.time()
            _save_task_redis(client, task)
            return task
        except Exception as exc:
            logger.warning("control_tasks_store.record_result redis failed: %s (falling back)", exc)

    with _mem_lock:
        task = _mem_tasks.get(task_id)
        if task is None:
            return None
        _mem_inflight.pop(task_id, None)
        if status == "failed" and task.attempts + 1 < _MAX_ATTEMPTS:
            task.attempts += 1
            task.status = "queued"
            task.error = error
            task.device_id = None
            task.started_at = None
            _mem_queue.append(task.id)
            return task
        task.status = status
        task.result = result
        task.error = error
        task.finished_at = time.time()
        return task


# ── Observability helpers (wired into SystemStatusBar) ───────────────────────

def queue_depth() -> int:
    client = _redis()
    if client is not None:
        try:
            return int(client.llen(_QUEUE_KEY))
        except Exception:
            pass
    with _mem_lock:
        return len(_mem_queue)


def inflight_count() -> int:
    client = _redis()
    if client is not None:
        try:
            return int(client.zcard(_INFLIGHT_KEY))
        except Exception:
            pass
    with _mem_lock:
        return len(_mem_inflight)


def sweep_inflight() -> int:
    """Public sweep — safe to call on a timer from a supervisor."""
    client = _redis()
    if client is not None:
        try:
            return _sweep_inflight_redis(client)
        except Exception as exc:
            logger.warning("control_tasks_store.sweep redis failed: %s", exc)
    return _sweep_inflight_memory()
