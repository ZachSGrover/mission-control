"""
Discord integration status — read-only probe via OpenClaw gateway.

Endpoints:
  GET /api/v1/discord/status  → Returns Discord bot connection status
"""

from __future__ import annotations

import os
import time

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import message_dedup, message_metrics
from app.core.ai_backend import ask_ai
from app.core.auth import AuthContext, get_auth_context
from app.core.logging import get_logger
from app.core.speed_layer import classify
from app.db.session import get_session

router = APIRouter(prefix="/discord", tags=["discord"])
logger = get_logger(__name__)

AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)

# Last-known Discord gateway state — compared on every /status probe so we can
# log offline→online transitions (reconnect events) without needing to touch
# OpenClaw.  Purely observational.
_last_connected: bool | None = None
_last_transition_at: float | None = None


def _note_transition(now_connected: bool) -> None:
    global _last_connected, _last_transition_at
    if _last_connected is None:
        _last_connected = now_connected
        return
    if now_connected != _last_connected:
        import time as _time

        _last_transition_at = _time.time()
        if now_connected:
            logger.warning("discord.reconnected at=%s", _last_transition_at)
        else:
            logger.warning("discord.disconnected at=%s", _last_transition_at)
        _last_connected = now_connected


_OPENCLAW_BASE = os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789")
_OPENCLAW_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "").strip()
# Cloud-first mode: skip the localhost OpenClaw probe entirely.  On Render
# and other cloud hosts loopback can't reach a laptop anyway, so the probe
# just wastes 5 s and logs noise.  Set MC_ENABLE_OPENCLAW_PROBE=1 on your
# local laptop if you still want the local-gateway check.
_OPENCLAW_PROBE_ENABLED = os.getenv("MC_ENABLE_OPENCLAW_PROBE", "").strip() in ("1", "true", "yes")


class DiscordStatusResponse(BaseModel):
    connected: bool
    bot_username: str | None = None
    detail: str = ""


@router.get("/status", response_model=DiscordStatusResponse)
async def discord_status(_: AuthContext = AUTH_DEP) -> DiscordStatusResponse:
    """
    Return Discord bot connection status.

    Cloud-first: hits Discord's REST API directly using DISCORD_BOT_TOKEN.
    Optional: if MC_ENABLE_OPENCLAW_PROBE=1, also tries the local OpenClaw
    gateway at 127.0.0.1:18789 (only useful on a laptop running OpenClaw).
    """
    # ── Primary: cloud REST probe against discord.com ────────────────────────
    discord_token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if discord_token:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://discord.com/api/v10/users/@me",
                    headers={
                        "Authorization": f"Bot {discord_token}",
                        "User-Agent": "DiscordBot (mission-control, 1.0)",
                    },
                )
            if resp.status_code == 200:
                data = resp.json()
                _note_transition(True)
                return DiscordStatusResponse(
                    connected=True,
                    bot_username=data.get("username"),
                    detail="cloud",
                )
            logger.warning("discord.status cloud probe http=%s", resp.status_code)
        except Exception as exc:
            logger.warning("discord.status cloud probe error: %s", exc)

    # ── Optional: local-laptop OpenClaw probe (opt-in) ───────────────────────
    if _OPENCLAW_PROBE_ENABLED:
        try:
            headers: dict[str, str] = {}
            if _OPENCLAW_TOKEN:
                headers["Authorization"] = f"Bearer {_OPENCLAW_TOKEN}"
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{_OPENCLAW_BASE}/api/channels/status",
                    headers=headers,
                )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    for ch in data:
                        if ch.get("type") == "discord" or "discord" in ch.get("id", "").lower():
                            is_connected = (
                                ch.get("connected", False) or ch.get("status") == "connected"
                            )
                            bot_name = ch.get("botUsername") or ch.get("bot_username")
                            _note_transition(is_connected)
                            return DiscordStatusResponse(
                                connected=is_connected,
                                bot_username=bot_name,
                                detail=f"openclaw:{ch.get('status', '')}",
                            )
                _note_transition(True)
                return DiscordStatusResponse(connected=True, detail="openclaw:gateway-reachable")
        except httpx.ConnectError:
            logger.debug("discord.status: OpenClaw gateway not reachable (local probe)")
        except Exception as exc:
            logger.warning("discord.status openclaw probe error: %s", exc)

    _note_transition(False)
    return DiscordStatusResponse(
        connected=False,
        detail="no DISCORD_BOT_TOKEN configured" if not discord_token else "cloud-unreachable",
    )


# ── Speed-layer message routing (OpenClaw → backend → reply) ─────────────────


class DiscordMessageRequest(BaseModel):
    text: str
    channel_id: str | None = None
    user: str | None = None
    message_id: str | None = None  # optional; enables replay-protection after reconnect


class DiscordMessageResponse(BaseModel):
    reply: str
    used_ai: bool
    reason: str
    response_ms: float
    provider: str = "none"


@router.post("/message", response_model=DiscordMessageResponse)
async def handle_discord_message(
    body: DiscordMessageRequest,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> DiscordMessageResponse:
    """
    Entry point for the OpenClaw Discord bot.  Applies the speed layer BEFORE
    any AI call.  Short/greeting messages return instantly with predefined
    text.  Long messages or questions are routed to Claude/OpenAI.
    """
    # ── Replay protection after Discord gateway reconnects ───────────────────
    if body.message_id:
        fp = f"{body.channel_id or ''}:{body.message_id}"
        if message_dedup.seen(fp, "discord.message_id"):
            logger.info("discord.dup message_id=%s channel=%s", body.message_id, body.channel_id)
            return DiscordMessageResponse(
                reply="",
                used_ai=False,
                reason="duplicate",
                response_ms=0.0,
                provider="none",
            )

    start = time.perf_counter()
    route = classify(body.text)
    provider = "none"

    if route.use_ai:
        reply, provider = await ask_ai(body.text, session, trigger_source="discord")
    else:
        reply = route.fast_reply or "👍"

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    message_metrics.record(
        source="discord",
        response_ms=elapsed_ms,
        used_ai=route.use_ai,
        reason=route.reason,
    )
    logger.info(
        "discord.response source=discord ms=%.1f used_ai=%s reason=%s provider=%s",
        elapsed_ms,
        route.use_ai,
        route.reason,
        provider,
    )
    from app.core import node_identity

    print(
        f"[messaging] node={node_identity.node_id()} source=discord "
        f"ms={elapsed_ms:.1f} used_ai={route.use_ai} reason={route.reason}",
        flush=True,
    )

    return DiscordMessageResponse(
        reply=reply,
        used_ai=route.use_ai,
        reason=route.reason,
        response_ms=round(elapsed_ms, 2),
        provider=provider,
    )
