"""
Telegram Bot integration — remote operation of Mission Control via Telegram.

Endpoints:
  POST /api/v1/telegram/webhook  → Receives Telegram bot updates (no auth, validates secret token)
  GET  /api/v1/telegram/config   → Returns config status (authenticated)
  POST /api/v1/telegram/config   → Save bot token (requires owner role)
  DELETE /api/v1/telegram/config → Remove bot token (requires owner role)
  POST /api/v1/telegram/test     → Send a test message (requires owner role)

Security:
  - Webhook validates X-Telegram-Bot-Api-Secret-Token header if TELEGRAM_WEBHOOK_SECRET is set.
  - If TELEGRAM_ALLOWED_CHAT_IDS is set, only messages from those chat IDs are processed.
  - Bot token is stored encrypted in DB via secrets_store, with TELEGRAM_BOT_TOKEN env as fallback.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import time

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.mc_roles import require_owner
from app.core import message_dedup, message_metrics, telegram_polling
from app.core.ai_backend import ask_ai
from app.core.auth import AuthContext, get_auth_context
from app.core.secrets_store import delete_secret, get_secret_with_source, mask_key, set_secret
from app.core.speed_layer import classify
from app.db.session import get_session

router = APIRouter(prefix="/telegram", tags=["telegram"])
logger = logging.getLogger(__name__)

AUTH_DEP = Depends(get_auth_context)
OWNER_DEP = Depends(require_owner)
SESSION_DEP = Depends(get_session)

# ── DB key for the telegram bot token ────────────────────────────────────────

_TELEGRAM_TOKEN_DB_KEY = "telegram.bot_token"

# ── Env vars read at import time ──────────────────────────────────────────────

_ENV_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
_RAW_ALLOWED_IDS = os.getenv("TELEGRAM_ALLOWED_CHAT_IDS", "").strip()
_ALLOWED_CHAT_IDS: set[int] = set()
if _RAW_ALLOWED_IDS:
    for _part in _RAW_ALLOWED_IDS.split(","):
        _part = _part.strip()
        if _part.lstrip("-").isdigit():
            _ALLOWED_CHAT_IDS.add(int(_part))

# ── Known projects (hardcoded per spec) ──────────────────────────────────────

_KNOWN_PROJECTS = [
    "General",
    "Digidle",
    "Modern Sales Agency",
    "Modern Athlete",
    "Grover Art Projects",
]

# ── Telegram Bot API base URL ─────────────────────────────────────────────────

_TG_API = "https://api.telegram.org/bot{token}/{method}"


# ── Schemas ───────────────────────────────────────────────────────────────────

class TelegramConfigStatus(BaseModel):
    has_token: bool
    bot_username: str | None = None
    source: str = "none"  # "db" | "env" | "none"


class SaveTokenRequest(BaseModel):
    token: str


class TestMessageRequest(BaseModel):
    chat_id: str
    message: str = "Mission Control test message. Bot is connected and operational."


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _get_bot_token(session: AsyncSession) -> str:
    """Return the active bot token. DB value overrides env fallback."""
    token, _source = await get_secret_with_source(
        session, _TELEGRAM_TOKEN_DB_KEY, fallback=_ENV_BOT_TOKEN
    )
    return token


async def _send_message(
    token: str,
    chat_id: int | str,
    text: str,
    message_thread_id: int | None = None,
) -> None:
    """Send a plain-text message via Telegram Bot API.

    If the incoming message came from a forum supergroup topic, pass its
    `message_thread_id` so the reply lands in the same topic instead of General.
    """
    url = _TG_API.format(token=token, method="sendMessage")
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if message_thread_id is not None:
        payload["message_thread_id"] = message_thread_id
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()


async def _get_me(token: str) -> dict[str, Any]:
    """Call getMe to validate the token and retrieve the bot's profile."""
    url = _TG_API.format(token=token, method="getMe")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


# ── Command handlers ──────────────────────────────────────────────────────────

async def _handle_command(command: str, session: AsyncSession) -> str:
    """Parse a Telegram bot command and return a plain-text response."""
    cmd = command.strip().lower().split()[0]
    # Strip bot-name suffix e.g. /status@MyBot
    if "@" in cmd:
        cmd = cmd.split("@")[0]

    if cmd == "/help":
        return (
            "Mission Control — Available Commands\n\n"
            "/status    System health summary\n"
            "/health    Detailed health check\n"
            "/projects  List known projects\n"
            "/agents    Active agents count and names\n"
            "/logs      Log access instructions\n"
            "/deploy    Trigger a Render redeploy\n"
            "/help      This help message"
        )

    if cmd in ("/status", "/health"):
        try:
            from app.api.workflows import run_health_check
            report = await run_health_check()
            detail_lines = ""
            if cmd == "/health":
                detail_lines = "\n" + "\n".join(
                    f"  {'✅' if c.status == 'pass' else '❌'} {c.name}: {c.detail}"
                    for c in report.checks
                )
            return (
                f"System Status: {report.overall.upper()}\n"
                f"Checks passed: {report.pass_count}/{report.pass_count + report.fail_count}\n"
                f"Timestamp: {report.timestamp}"
                + detail_lines
            )
        except Exception as exc:
            logger.error("telegram.command.status error: %s", exc)
            return f"Could not retrieve health status: {exc}"

    if cmd == "/projects":
        lines = "\n".join(f"  • {p}" for p in _KNOWN_PROJECTS)
        return f"Known Projects ({len(_KNOWN_PROJECTS)}):\n{lines}"

    if cmd == "/agents":
        try:
            from app.core.config import settings
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{settings.base_url}/api/v1/agents",
                    headers={"X-Internal-Request": "telegram-bot"},
                    timeout=10.0,
                )
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", data) if isinstance(data, dict) else data
                if isinstance(items, list):
                    count = len(items)
                    names = [
                        a.get("name") or a.get("id", "unnamed")
                        for a in items[:10]
                    ]
                    name_list = "\n".join(f"  • {n}" for n in names)
                    suffix = f"\n  … and {count - 10} more" if count > 10 else ""
                    return f"Agents ({count}):\n{name_list}{suffix}"
            return "Agents API is not accessible from this context."
        except Exception as exc:
            logger.error("telegram.command.agents error: %s", exc)
            return f"Could not retrieve agents: {exc}"

    if cmd == "/logs":
        return (
            "Logs are stored in your browser's localStorage and are not\n"
            "directly accessible from the backend.\n\n"
            "View full logs in the Mission Control dashboard:\n"
            "  → Memory page for action history\n"
            "  → Activity feed for recent events"
        )

    if cmd == "/deploy":
        render_key = os.getenv("RENDER_API_KEY", "").strip()
        render_svc = os.getenv("RENDER_SERVICE_ID", "srv-d7cq41q8qa3s73bbke00").strip()
        if not render_key:
            return (
                "Deployment not configured.\n"
                "Set RENDER_API_KEY in the backend environment to enable remote deploys."
            )
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"https://api.render.com/v1/services/{render_svc}/deploys",
                    headers={"Authorization": f"Bearer {render_key}"},
                    json={"clearCache": "do_not_clear"},
                )
                resp.raise_for_status()
                data = resp.json()
            deploy_id = data.get("deploy", {}).get("id", "unknown")
            logger.info("telegram.deploy triggered deploy_id=%s", deploy_id)
            return f"Deploy triggered successfully.\nDeploy ID: {deploy_id}"
        except Exception as exc:
            logger.error("telegram.command.deploy error: %s", exc)
            return f"Deploy failed: {exc}"

    return (
        f"Unknown command: {command.split()[0]}\n"
        "Send /help for a list of available commands."
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Telegram webhook receiver",
    description=(
        "Receives Telegram Bot API update payloads. "
        "No user auth required; validated via X-Telegram-Bot-Api-Secret-Token or chat allowlist."
    ),
)
async def telegram_webhook(
    request: Request,
    session: AsyncSession = SESSION_DEP,
    x_telegram_bot_api_secret_token: str | None = Header(default=None, alias="X-Telegram-Bot-Api-Secret-Token"),
) -> dict[str, str]:
    """Process incoming Telegram bot updates."""
    # ── Secret-token validation ───────────────────────────────────────────────
    if _WEBHOOK_SECRET:
        if x_telegram_bot_api_secret_token != _WEBHOOK_SECRET:
            logger.warning(
                "telegram.webhook.rejected reason=invalid_secret "
                "ip=%s",
                request.client.host if request.client else "unknown",
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook secret token.",
            )

    # ── Parse payload ─────────────────────────────────────────────────────────
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload.",
        )

    # ── Record liveness signal + dedup ────────────────────────────────────────
    telegram_polling.record_webhook_hit()
    update_id = payload.get("update_id")
    if update_id is not None and message_dedup.seen(str(update_id), "telegram.update_id"):
        logger.info("telegram.webhook.dup update_id=%s", update_id)
        return {"ok": "duplicate"}

    message: dict[str, Any] = payload.get("message") or payload.get("edited_message") or {}
    if not message:
        # Non-message update (e.g. inline query, callback) — acknowledge silently
        return {"ok": "accepted"}

    result = await _process_incoming_message(message, session)
    return {"ok": result}


async def _process_incoming_message(
    message: dict[str, Any],
    session: AsyncSession,
) -> str:
    """
    Shared processing path for webhook deliveries and polled updates.
    Returns a short status label (processed|rejected|no_token|accepted).
    """
    chat: dict[str, Any] = message.get("chat", {})
    chat_id: int = chat.get("id", 0)
    from_user: dict[str, Any] = message.get("from", {})
    username: str = from_user.get("username", "") or str(from_user.get("id", "unknown"))
    text: str = message.get("text", "").strip()
    # Forum supergroup topic threading: echo the reply into the same topic.
    raw_thread = message.get("message_thread_id")
    message_thread_id: int | None = int(raw_thread) if isinstance(raw_thread, (int, str)) and str(raw_thread).lstrip("-").isdigit() else None

    # ── Chat allowlist ────────────────────────────────────────────────────────
    if _ALLOWED_CHAT_IDS and chat_id not in _ALLOWED_CHAT_IDS:
        logger.warning(
            "telegram.rejected reason=chat_not_allowed chat_id=%s username=%s",
            chat_id, username,
        )
        return "rejected"

    if not text:
        return "accepted"

    # Defensive dedup on per-message id (covers webhook-polling overlap if bot
    # has both active for a moment, or a polling retry after a transient error)
    msg_id = message.get("message_id")
    if msg_id is not None and chat_id:
        if message_dedup.seen(f"{chat_id}:{msg_id}", "telegram.message_id"):
            logger.info("telegram.dup message_id=%s chat_id=%s", msg_id, chat_id)
            return "duplicate"

    # ── Retrieve bot token (needed for every reply path) ──────────────────────
    token = await _get_bot_token(session)
    if not token:
        logger.error("telegram.error reason=no_token_configured chat_id=%s", chat_id)
        return "no_token"

    start = time.perf_counter()
    used_ai = False
    reason = "command" if text.startswith("/") else "unclassified"

    if text.startswith("/"):
        # ── Slash command → existing dispatcher (unchanged) ───────────────────
        logger.info(
            "telegram.command.received chat_id=%s username=%s command=%r",
            chat_id, username, text.split()[0],
        )
        try:
            response_text = await _handle_command(text, session)
        except Exception as exc:
            logger.error("telegram.command.error command=%r error=%s", text, exc)
            response_text = f"An error occurred processing your command: {exc}"
    else:
        # ── Speed layer: fast reply vs AI ─────────────────────────────────────
        route = classify(text)
        reason = route.reason
        if route.use_ai:
            used_ai = True
            logger.info(
                "telegram.speed_layer source=telegram path=ai reason=%s chat_id=%s",
                route.reason, chat_id,
            )
            response_text, provider = await ask_ai(text, session)
            logger.info("telegram.ai.replied provider=%s chars=%d", provider, len(response_text))
        else:
            response_text = route.fast_reply or "👍"
            logger.info(
                "telegram.speed_layer source=telegram path=fast reason=%s chat_id=%s",
                route.reason, chat_id,
            )

    # ── Send reply ────────────────────────────────────────────────────────────
    try:
        await _send_message(token, chat_id, response_text, message_thread_id=message_thread_id)
    except Exception as exc:
        logger.error(
            "telegram.send_message.error chat_id=%s error=%s", chat_id, exc
        )

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    message_metrics.record(
        source="telegram",
        response_ms=elapsed_ms,
        used_ai=used_ai,
        reason=reason,
    )
    logger.info(
        "telegram.response source=telegram ms=%.1f used_ai=%s reason=%s chars=%d",
        elapsed_ms, used_ai, reason, len(response_text),
    )
    from app.core import node_identity
    print(
        f"[messaging] node={node_identity.node_id()} source=telegram "
        f"ms={elapsed_ms:.1f} used_ai={used_ai} reason={reason}",
        flush=True,
    )
    return "processed"


async def dispatch_message_from_polling(message: dict[str, Any]) -> None:
    """Entry point used by `telegram_polling._dispatch_update`."""
    async for session in get_session():
        await _process_incoming_message(message, session)
        return


@router.get("/config", response_model=TelegramConfigStatus)
async def get_telegram_config(
    _auth: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> TelegramConfigStatus:
    """Return current Telegram bot configuration status (never exposes the token)."""
    token, source = await get_secret_with_source(
        session, _TELEGRAM_TOKEN_DB_KEY, fallback=_ENV_BOT_TOKEN
    )

    if not token:
        return TelegramConfigStatus(has_token=False, bot_username=None, source="none")

    # Attempt to resolve bot username from Telegram
    bot_username: str | None = None
    try:
        data = await _get_me(token)
        if data.get("ok"):
            bot_username = data["result"].get("username")
    except Exception as exc:
        logger.warning("telegram.config.get_me_failed error=%s", exc)

    return TelegramConfigStatus(has_token=True, bot_username=bot_username, source=source)


@router.post("/config", response_model=TelegramConfigStatus, status_code=status.HTTP_200_OK)
async def save_telegram_config(
    body: SaveTokenRequest,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> TelegramConfigStatus:
    """Save (or replace) the Telegram bot token. Encrypted in DB. Owner only."""
    token = body.token.strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Token must not be empty.",
        )

    # Validate the token works before saving
    try:
        data = await _get_me(token)
        if not data.get("ok"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Telegram rejected the token (getMe returned ok=false).",
            )
        bot_username: str | None = data["result"].get("username")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not validate token with Telegram API: {exc}",
        ) from exc

    await set_secret(session, _TELEGRAM_TOKEN_DB_KEY, token)
    logger.info("telegram.config.saved bot_username=%s", bot_username)

    return TelegramConfigStatus(has_token=True, bot_username=bot_username, source="db")


@router.delete("/config", status_code=status.HTTP_204_NO_CONTENT)
async def delete_telegram_config(
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> None:
    """Remove the stored Telegram bot token from the DB. Owner only."""
    await delete_secret(session, _TELEGRAM_TOKEN_DB_KEY)
    logger.info("telegram.config.deleted")


@router.post("/test", response_model=dict[str, str], status_code=status.HTTP_200_OK)
async def test_telegram_bot(
    body: TestMessageRequest,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> dict[str, str]:
    """Send a test message to the given chat_id. Owner only."""
    token = await _get_bot_token(session)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No Telegram bot token configured. Save a token in config first.",
        )

    chat_id_raw = body.chat_id.strip()
    if not chat_id_raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="chat_id must not be empty.",
        )

    try:
        await _send_message(token, chat_id_raw, body.message)
        logger.info("telegram.test.sent chat_id=%s", chat_id_raw)
        return {"ok": "Message sent successfully."}
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Telegram API error: {exc.response.status_code} {exc.response.text}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to send message: {exc}",
        ) from exc
