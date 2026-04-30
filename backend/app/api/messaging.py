"""
Messaging routing endpoints — shared speed layer for Discord / Telegram / other.

Endpoints:
  POST /api/v1/messaging/route   → classify+reply (used by Discord via OpenClaw)
  GET  /api/v1/messaging/metrics → response-time snapshot for SystemStatusBar
"""

from __future__ import annotations

import logging
import time
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import message_metrics
from app.core.ai_backend import ask_ai
from app.core.auth import AuthContext, get_auth_context
from app.core.speed_layer import classify
from app.db.session import get_session

router = APIRouter(prefix="/messaging", tags=["messaging"])
logger = logging.getLogger(__name__)

AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)


class RouteMessageRequest(BaseModel):
    source: Literal["telegram", "discord", "other"] = "other"
    text: str = Field(..., description="The raw inbound user message.")


class RouteMessageResponse(BaseModel):
    reply: str
    used_ai: bool
    reason: str
    response_ms: float
    provider: str = "none"


@router.post("/route", response_model=RouteMessageResponse)
async def route_message(
    body: RouteMessageRequest,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> RouteMessageResponse:
    """Classify a message and return either a fast reply or an AI-generated reply."""
    start = time.perf_counter()
    route = classify(body.text)
    provider = "none"

    if route.use_ai:
        reply, provider = await ask_ai(body.text, session, trigger_source=body.source)
    else:
        # "command" means the caller should route to its own command handler —
        # surface a hint so misrouted commands don't silently no-op.
        reply = route.fast_reply or "(command — handle via slash dispatcher)"

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    message_metrics.record(
        source=body.source,
        response_ms=elapsed_ms,
        used_ai=route.use_ai,
        reason=route.reason,
    )
    logger.info(
        "messaging.routed source=%s reason=%s used_ai=%s ms=%.1f provider=%s",
        body.source,
        route.reason,
        route.use_ai,
        elapsed_ms,
        provider,
    )

    return RouteMessageResponse(
        reply=reply,
        used_ai=route.use_ai,
        reason=route.reason,
        response_ms=round(elapsed_ms, 2),
        provider=provider,
    )


class MetricsResponse(BaseModel):
    total_count: int
    avg_ms_last_10: float | None
    telegram_avg_ms: float | None
    telegram_last_at: float | None
    telegram_count: int
    discord_avg_ms: float | None
    discord_last_at: float | None
    discord_count: int
    ai_call_ratio_pct: float


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(_: AuthContext = AUTH_DEP) -> MetricsResponse:
    """Return current response-time aggregates from the in-memory ring buffer."""
    snap = message_metrics.snapshot()
    return MetricsResponse(
        total_count=snap.total_count,
        avg_ms_last_10=round(snap.avg_ms_last_10, 2) if snap.avg_ms_last_10 is not None else None,
        telegram_avg_ms=(
            round(snap.telegram_avg_ms, 2) if snap.telegram_avg_ms is not None else None
        ),
        telegram_last_at=snap.telegram_last_at,
        telegram_count=snap.telegram_count,
        discord_avg_ms=round(snap.discord_avg_ms, 2) if snap.discord_avg_ms is not None else None,
        discord_last_at=snap.discord_last_at,
        discord_count=snap.discord_count,
        ai_call_ratio_pct=round(snap.ai_call_ratio_pct, 1),
    )
