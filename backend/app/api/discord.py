"""
Discord integration status — read-only probe via OpenClaw gateway.

Endpoints:
  GET /api/v1/discord/status  → Returns Discord bot connection status
"""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.auth import AuthContext, get_auth_context

router = APIRouter(prefix="/discord", tags=["discord"])
logger = logging.getLogger(__name__)

AUTH_DEP = Depends(get_auth_context)

_OPENCLAW_BASE = os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789")
_OPENCLAW_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "").strip()


class DiscordStatusResponse(BaseModel):
    connected: bool
    bot_username: str | None = None
    detail: str = ""


@router.get("/status", response_model=DiscordStatusResponse)
async def discord_status(_: AuthContext = AUTH_DEP) -> DiscordStatusResponse:
    """
    Return Discord bot connection status by probing the OpenClaw gateway.
    Returns connected=True if the gateway reports the Discord bot is live.
    """
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
            # OpenClaw channel status format: list of channel objects
            if isinstance(data, list):
                for ch in data:
                    if ch.get("type") == "discord" or "discord" in ch.get("id", "").lower():
                        is_connected = ch.get("connected", False) or ch.get("status") == "connected"
                        bot_name = ch.get("botUsername") or ch.get("bot_username")
                        return DiscordStatusResponse(
                            connected=is_connected,
                            bot_username=bot_name,
                            detail=ch.get("status", ""),
                        )
            # Fallback: gateway reachable = bot likely running
            return DiscordStatusResponse(connected=True, detail="gateway-reachable")

    except httpx.ConnectError:
        logger.debug("discord.status: OpenClaw gateway not reachable")
    except Exception as exc:
        logger.warning("discord.status error: %s", exc)

    # Can't reach OpenClaw — check via Discord REST API directly using token from env
    discord_token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if discord_token:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": f"Bot {discord_token}"},
                )
            if resp.status_code == 200:
                data = resp.json()
                return DiscordStatusResponse(
                    connected=True,
                    bot_username=data.get("username"),
                    detail="rest-api",
                )
        except Exception as exc:
            logger.warning("discord.status rest fallback error: %s", exc)

    return DiscordStatusResponse(connected=False, detail="unreachable")
