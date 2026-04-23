"""
system_node — remote-callable health + identity endpoint for this node.

Public (no auth): anyone who can reach the backend can verify it's up, learn
the node_id, and read high-level queue counters.  No secrets, no user data.

Endpoints:
  GET /api/v1/system/node    → node_id, uptime_s, queue depth/inflight,
                               last messaging activity, backend mode
  GET /api/v1/system/ping    → cheap liveness probe  {node_id, ok}
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel

from app.core import message_metrics, network_monitor, node_identity, task_queue, telegram_polling

router = APIRouter(prefix="/system", tags=["system"])


class NodeHealth(BaseModel):
    node_id: str
    ok: bool
    uptime_s: float
    started_at: float
    now: float
    queue_depth: int
    inflight_count: int
    queue_backend: str  # "redis" | "memory"
    messages_total: int
    avg_ms_last_10: float | None
    telegram_last_at: float | None
    discord_last_at: float | None
    last_activity_at: float | None


class NodePing(BaseModel):
    node_id: str
    ok: bool
    now: float


def _queue_backend_label() -> str:
    try:
        import redis

        from app.core.config import settings

        redis.Redis.from_url(settings.rq_redis_url).ping()
        return "redis"
    except Exception:
        return "memory"


@router.get("/node", response_model=NodeHealth)
async def node_health() -> NodeHealth:
    snap = message_metrics.snapshot()
    last_activity = max(
        [t for t in (snap.telegram_last_at, snap.discord_last_at) if t is not None],
        default=None,
    )
    return NodeHealth(
        node_id=node_identity.node_id(),
        ok=True,
        uptime_s=round(node_identity.uptime_seconds(), 1),
        started_at=node_identity.start_time(),
        now=time.time(),
        queue_depth=task_queue.queue_depth(),
        inflight_count=task_queue.inflight_count(),
        queue_backend=_queue_backend_label(),
        messages_total=snap.total_count,
        avg_ms_last_10=snap.avg_ms_last_10,
        telegram_last_at=snap.telegram_last_at,
        discord_last_at=snap.discord_last_at,
        last_activity_at=last_activity,
    )


@router.get("/ping", response_model=NodePing)
async def node_ping() -> NodePing:
    return NodePing(node_id=node_identity.node_id(), ok=True, now=time.time())


class NetworkState(BaseModel):
    is_online: bool | None
    last_online_at: float | None
    last_offline_at: float | None
    consecutive_failures: int
    consecutive_successes: int
    last_checked_at: float | None
    probe_target: str


@router.get("/network", response_model=NetworkState)
async def network_state() -> NetworkState:
    snap = network_monitor.snapshot()
    return NetworkState(**snap.__dict__)


class TelegramMode(BaseModel):
    mode: str
    last_webhook_hit_at: float | None
    last_mode_change_at: float | None
    last_update_id: int | None
    polling_active: bool


@router.get("/telegram-mode", response_model=TelegramMode)
async def telegram_mode() -> TelegramMode:
    snap = telegram_polling.mode_snapshot()
    return TelegramMode(**snap.__dict__)
