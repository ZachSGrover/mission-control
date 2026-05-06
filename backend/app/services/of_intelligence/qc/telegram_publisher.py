"""Telegram daily-summary publisher (Layer 3 — Safe Summary only).

Mirrors ``daily_summary.ship_daily_summary`` but ships to Telegram instead
of Discord.  The publisher RE-DERIVES the safe summary from
``build_daily_summary`` — it never accepts a dashboard payload as input,
which means fan handles cannot leak via this path even if a caller passes
something privileged.

Configuration:
  • Bot token: read by ``app.api.telegram._get_bot_token`` (encrypted DB
    secret with env fallback).  We reuse that helper rather than reading
    the secret ourselves.
  • Chat id: encrypted DB secret ``telegram.qc.chat_id`` (preferred) with
    env fallback ``MC_OF_QC_TELEGRAM_CHAT_ID``.

Graceful skip rules (NEVER raise):
  • ``OfQcDiscordStatus.enabled`` is false (operator master toggle off)
    → ``reason="disabled"``
  • ``telegram_enabled`` flag false on the same row
    → ``reason="telegram_disabled"``
  • Token missing → ``reason="no_telegram"``
  • Chat id missing → ``reason="no_telegram_chat"``
  • Telegram HTTP 4xx/5xx → ``reason="http_NNN"`` (logged, never raised)

Privacy:
  • Renders via the existing ``daily_summary.render_daily_summary`` which
    runs inside ``format_rollup`` — same allowlist + post-render guard
    that protects the Discord path.
  • Bot token never logged.  Chat id is logged as a hash prefix only.
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import dataclass

import httpx
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.telegram import _get_bot_token
from app.core.logging import get_logger
from app.core.secrets_store import get_secret
from app.models.of_qc_discord_status import OfQcDiscordStatus
from app.services.of_intelligence.qc.daily_summary import (
    DailySummary,
    build_daily_summary,
    render_daily_summary,
)

logger = get_logger(__name__)

TELEGRAM_QC_CHAT_DB_KEY = "telegram.qc.chat_id"
_ENV_QC_CHAT_ID = "MC_OF_QC_TELEGRAM_CHAT_ID"
_TG_API = "https://api.telegram.org/bot{token}/sendMessage"
_HTTP_TIMEOUT = 10.0
_STATUS_ROW_ID = 1

# Privacy guard mirrors formatters.py — bot tokens never appear in any string
# we POST or log.
_TG_TOKEN_RX = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")


@dataclass(frozen=True)
class TelegramPublishResult:
    ok: bool
    status: int | None
    reason: str  # "ok" | "disabled" | "telegram_disabled" | "no_telegram"
    # | "no_telegram_chat" | "http_NNN" | "network_error" | "privacy_violation"
    elapsed_ms: int


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _hash_prefix(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


async def _resolve_chat_id(session: AsyncSession) -> str:
    db_value = await get_secret(session, TELEGRAM_QC_CHAT_DB_KEY)
    if db_value and db_value.strip():
        return db_value.strip()
    return (os.environ.get(_ENV_QC_CHAT_ID) or "").strip()


async def _read_status_row(session: AsyncSession) -> OfQcDiscordStatus | None:
    return await session.get(OfQcDiscordStatus, _STATUS_ROW_ID)


def _privacy_safe(text: str) -> bool:
    """No webhook URL, no Discord token shape, no Telegram token shape."""
    if "https://discord.com/api/webhooks/" in text:
        return False
    if _TG_TOKEN_RX.search(text):
        return False
    return True


async def ship_daily_summary_telegram(
    session: AsyncSession,
    *,
    bypass_kill_switch: bool = False,
) -> tuple[DailySummary, TelegramPublishResult]:
    """Build the daily summary + ship to Telegram (or skip safely)."""
    started_ns = time.perf_counter_ns()
    summary = await build_daily_summary(session)

    row = await _read_status_row(session)
    if not bypass_kill_switch and not (row and row.enabled):
        return summary, _result(False, None, "disabled", started_ns)
    if row is not None and not getattr(row, "telegram_enabled", False):
        return summary, _result(False, None, "telegram_disabled", started_ns)
    if not bypass_kill_switch and not (row and getattr(row, "live_send_enabled", False)):
        return summary, _result(False, None, "live_send_disabled", started_ns)

    try:
        token = await _get_bot_token(session)
    except Exception:
        logger.exception("of_qc.telegram.token_lookup_failed")
        token = ""
    if not token:
        return summary, _result(False, None, "no_telegram", started_ns)

    chat_id = await _resolve_chat_id(session)
    if not chat_id:
        return summary, _result(False, None, "no_telegram_chat", started_ns)

    rendered = render_daily_summary(summary)
    if not _privacy_safe(rendered):
        logger.error("of_qc.telegram.privacy_violation")
        return summary, _result(False, None, "privacy_violation", started_ns)

    payload = {"chat_id": chat_id, "text": rendered}
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(_TG_API.format(token=token), json=payload)
    except httpx.HTTPError:
        logger.warning("of_qc.telegram.network_error chat=%s", _hash_prefix(chat_id))
        return summary, _result(False, None, "network_error", started_ns)

    if 200 <= resp.status_code < 300:
        logger.info(
            "of_qc.telegram.sent status=%s chat_hash=%s elapsed_ms=%s",
            resp.status_code,
            _hash_prefix(chat_id),
            _elapsed_ms(started_ns),
        )
        return summary, _result(True, resp.status_code, "ok", started_ns)

    reason = f"http_{resp.status_code}"
    logger.warning(
        "of_qc.telegram.failed status=%s reason=%s chat_hash=%s",
        resp.status_code,
        reason,
        _hash_prefix(chat_id),
    )
    return summary, _result(False, resp.status_code, reason, started_ns)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _elapsed_ms(started_ns: int) -> int:
    return max(0, (time.perf_counter_ns() - started_ns) // 1_000_000)


def _result(
    ok: bool,
    status: int | None,
    reason: str,
    started_ns: int,
) -> TelegramPublishResult:
    return TelegramPublishResult(
        ok=ok,
        status=status,
        reason=reason,
        elapsed_ms=_elapsed_ms(started_ns),
    )
