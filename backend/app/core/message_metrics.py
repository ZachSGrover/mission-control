"""
message_metrics — in-memory ring buffer of recent messaging response times.

Kept deliberately tiny & process-local (no Redis, no DB).  Survives until the
uvicorn worker restarts — good enough for the SystemStatusBar dashboard pill.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Literal

__all__ = ["record", "snapshot", "MetricPoint", "MetricsSnapshot"]

Source = Literal["telegram", "discord", "other"]

_MAX_POINTS = 50
_RECENT_FOR_AVG = 10


@dataclass(frozen=True)
class MetricPoint:
    source: Source
    response_ms: float
    used_ai: bool
    reason: str
    timestamp: float  # UNIX epoch seconds


@dataclass(frozen=True)
class MetricsSnapshot:
    total_count: int
    avg_ms_last_10: float | None
    telegram_avg_ms: float | None
    telegram_last_at: float | None
    telegram_count: int
    discord_avg_ms: float | None
    discord_last_at: float | None
    discord_count: int
    ai_call_ratio_pct: float


_buffer: deque[MetricPoint] = deque(maxlen=_MAX_POINTS)
_lock = Lock()


def record(source: Source, response_ms: float, used_ai: bool, reason: str) -> None:
    """Append a single response-time observation."""
    point = MetricPoint(
        source=source,
        response_ms=float(response_ms),
        used_ai=bool(used_ai),
        reason=reason,
        timestamp=time.time(),
    )
    with _lock:
        _buffer.append(point)


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def snapshot() -> MetricsSnapshot:
    """Aggregate the current ring buffer."""
    with _lock:
        points = list(_buffer)

    if not points:
        return MetricsSnapshot(
            total_count=0,
            avg_ms_last_10=None,
            telegram_avg_ms=None,
            telegram_last_at=None,
            telegram_count=0,
            discord_avg_ms=None,
            discord_last_at=None,
            discord_count=0,
            ai_call_ratio_pct=0.0,
        )

    last_10 = points[-_RECENT_FOR_AVG:]
    tg_points = [p for p in points if p.source == "telegram"]
    dc_points = [p for p in points if p.source == "discord"]
    ai_points = [p for p in points if p.used_ai]

    return MetricsSnapshot(
        total_count=len(points),
        avg_ms_last_10=_avg([p.response_ms for p in last_10]),
        telegram_avg_ms=_avg([p.response_ms for p in tg_points]),
        telegram_last_at=tg_points[-1].timestamp if tg_points else None,
        telegram_count=len(tg_points),
        discord_avg_ms=_avg([p.response_ms for p in dc_points]),
        discord_last_at=dc_points[-1].timestamp if dc_points else None,
        discord_count=len(dc_points),
        ai_call_ratio_pct=(len(ai_points) / len(points)) * 100.0,
    )
