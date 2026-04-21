"""
task_queue — DEPRECATED SHIM.

The Phase-3 in-memory implementation has been replaced by a Redis-backed
store in `app.core.control_tasks_store`.  This module now re-exports that
API so any existing importer (`app.api.control_tasks`, tests, future
callers) keeps working without change.

Redis gives us:
  • persistence across restarts
  • multi-replica / multi-CLAW-node shared queue
  • visibility-timeout auto-requeue if a node dies mid-task
  • exponential-backoff retry on failed tasks
  • observable depth / inflight counts

If Redis is unreachable the store transparently falls back to an in-memory
deque so local dev still works.
"""

from __future__ import annotations

from app.core.control_tasks_store import (  # noqa: F401
    Task,
    TaskStatus,
    claim_next,
    enqueue,
    get_task,
    inflight_count,
    list_tasks,
    queue_depth,
    record_result,
    sweep_inflight,
)

__all__ = [
    "Task",
    "TaskStatus",
    "claim_next",
    "enqueue",
    "get_task",
    "inflight_count",
    "list_tasks",
    "queue_depth",
    "record_result",
    "sweep_inflight",
]
