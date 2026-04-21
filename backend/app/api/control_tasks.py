"""
control_tasks — shared task queue HTTP API.

Endpoints (prefix /api/v1/control/tasks):
  POST /              → enqueue {kind, payload, agent_id?, tags?}
  GET  /              → list (optional ?status=queued|running|done|…)
  GET  /{task_id}     → fetch one
  POST /claim         → CLAW node claims next queued task {device_id, kinds?}
  POST /{task_id}/result → CLAW posts result {status, result?, error?}
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core import task_queue
from app.core.auth import AuthContext, get_auth_context

router = APIRouter(prefix="/control/tasks", tags=["control-tasks"])
logger = logging.getLogger(__name__)
AUTH_DEP = Depends(get_auth_context)


class TaskOut(BaseModel):
    id:          str
    kind:        str
    payload:     dict[str, Any]
    status:      str
    agent_id:    str | None
    device_id:   str | None
    result:      Any
    error:       str | None
    created_at:  float
    started_at:  float | None
    finished_at: float | None
    tags:        list[str]
    attempts:    int = 0


def _to_out(task: task_queue.Task) -> TaskOut:
    return TaskOut(**task.to_dict())


class EnqueueRequest(BaseModel):
    kind:     str = Field(..., min_length=1, max_length=80)
    payload:  dict[str, Any] = {}
    agent_id: str | None = None
    tags:     list[str] = []


class ClaimRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=80)
    kinds:     list[str] | None = None


class ResultRequest(BaseModel):
    status: str = Field(..., pattern="^(done|failed|cancelled)$")
    result: Any = None
    error:  str | None = None


@router.post("", response_model=TaskOut)
async def enqueue(body: EnqueueRequest, _: AuthContext = AUTH_DEP) -> TaskOut:
    task = task_queue.enqueue(body.kind, body.payload, body.agent_id, body.tags)
    logger.info("control.task.enqueued id=%s kind=%s", task.id, task.kind)
    return _to_out(task)


@router.get("", response_model=list[TaskOut])
async def list_all(
    status: str | None = None,
    limit: int = 100,
    _: AuthContext = AUTH_DEP,
) -> list[TaskOut]:
    return [_to_out(t) for t in task_queue.list_tasks(status=status, limit=limit)]  # type: ignore[arg-type]


@router.get("/{task_id}", response_model=TaskOut)
async def get_one(task_id: str, _: AuthContext = AUTH_DEP) -> TaskOut:
    task = task_queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _to_out(task)


@router.post("/claim")
async def claim(body: ClaimRequest, _: AuthContext = AUTH_DEP) -> dict[str, Any]:
    task = task_queue.claim_next(body.device_id, body.kinds)
    if task is None:
        return {"claimed": False}
    logger.info(
        "control.task.claimed id=%s kind=%s device=%s",
        task.id, task.kind, body.device_id,
    )
    return {"claimed": True, "task": _to_out(task).model_dump()}


@router.post("/{task_id}/result", response_model=TaskOut)
async def post_result(
    task_id: str,
    body: ResultRequest,
    _: AuthContext = AUTH_DEP,
) -> TaskOut:
    task = task_queue.record_result(
        task_id, status=body.status, result=body.result, error=body.error  # type: ignore[arg-type]
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    logger.info("control.task.result id=%s status=%s attempt=%d", task.id, task.status, task.attempts)
    return _to_out(task)


# ── Observability ────────────────────────────────────────────────────────────

class QueueStats(BaseModel):
    queue_depth:    int
    inflight_count: int
    backend:        str                # "redis" | "memory"
    node_id:        str


@router.get("/_/stats", response_model=QueueStats)
async def queue_stats(_: AuthContext = AUTH_DEP) -> QueueStats:
    """
    Snapshot of the underlying queue for the SystemStatusBar / ops dashboards.
    `backend` reflects whether the Redis store is reachable right now.
    """
    # Peek by querying a lightweight operation; if it succeeds, redis is live.
    try:
        import redis
        from app.core.config import settings
        redis.Redis.from_url(settings.rq_redis_url).ping()
        backend = "redis"
    except Exception:
        backend = "memory"
    from app.core import node_identity
    return QueueStats(
        queue_depth=task_queue.queue_depth(),
        inflight_count=task_queue.inflight_count(),
        backend=backend,
        node_id=node_identity.node_id(),
    )
