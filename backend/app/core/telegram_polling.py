"""
telegram_polling — supervisor that falls back to getUpdates polling when the
Telegram → backend webhook stops delivering.

Behavior:
  • On every inbound webhook hit, call `record_webhook_hit()` from the
    webhook handler.  The supervisor treats the webhook as healthy while
    those records are recent.
  • Periodically check:
        internet online  AND
        bot token configured  AND
        last_webhook_hit > _WEBHOOK_STALE_S ago  →  activate polling
    Otherwise ensure polling is stopped.
  • While polling is active, call getUpdates in a long-poll loop, run each
    update through the same code path as webhook delivery, and track
    `last_update_id` so we resume from the right offset after any restart.
  • Mode transitions (webhook → polling, polling → webhook) are logged and
    queryable via mode_snapshot().

No restart required if polling isn't needed — the supervisor stays idle.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

import httpx

from app.core import message_dedup, network_monitor

__all__ = [
    "record_webhook_hit",
    "mode_snapshot",
    "run_supervisor",
    "TelegramModeSnapshot",
]

logger = logging.getLogger(__name__)

_DATA_DIR = Path(os.getenv("MC_DATA_DIR", str(Path.home() / ".mission-control")))
_OFFSET_PATH = _DATA_DIR / "telegram_last_update_id"
_WEBHOOK_STALE_S = 300.0  # 5 min without a webhook hit → try polling
_CHECK_INTERVAL_S = 60.0
_POLL_TIMEOUT_S = 25  # long-poll: server holds up to 25s
_TG_API = "https://api.telegram.org/bot{token}/{method}"

_lock = RLock()
_last_webhook_hit: float | None = None
_current_mode: str = "webhook"  # "webhook" | "polling" | "idle"
_last_mode_change_at: float | None = None
_polling_task: asyncio.Task | None = None


@dataclass
class TelegramModeSnapshot:
    mode: str
    last_webhook_hit_at: float | None
    last_mode_change_at: float | None
    last_update_id: int | None
    polling_active: bool


# ── Persisted offset helpers ──────────────────────────────────────────────────


def _load_offset() -> int:
    try:
        raw = _OFFSET_PATH.read_text().strip()
        return int(raw) if raw else 0
    except Exception:
        return 0


def _save_offset(update_id: int) -> None:
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _OFFSET_PATH.with_suffix(".tmp")
        tmp.write_text(str(int(update_id)))
        tmp.replace(_OFFSET_PATH)
    except Exception as exc:
        logger.warning("telegram_polling.save_offset_failed: %s", exc)


# ── Public API ────────────────────────────────────────────────────────────────


def record_webhook_hit() -> None:
    global _last_webhook_hit, _current_mode, _last_mode_change_at
    with _lock:
        _last_webhook_hit = time.time()
        if _current_mode != "webhook":
            logger.warning("telegram_polling.mode_change from=%s to=webhook", _current_mode)
            _current_mode = "webhook"
            _last_mode_change_at = _last_webhook_hit


def mode_snapshot() -> TelegramModeSnapshot:
    with _lock:
        return TelegramModeSnapshot(
            mode=_current_mode,
            last_webhook_hit_at=_last_webhook_hit,
            last_mode_change_at=_last_mode_change_at,
            last_update_id=_load_offset() or None,
            polling_active=(_polling_task is not None and not _polling_task.done()),
        )


# ── Polling loop ──────────────────────────────────────────────────────────────


async def _get_bot_token_once() -> str:
    """Resolve the bot token from the DB / env (one lookup per call)."""
    from app.core.config import settings
    from app.core.secrets_store import get_secret_with_source
    from app.db.session import get_session

    async for session in get_session():
        token, _src = await get_secret_with_source(
            session, "telegram.bot_token", fallback=os.getenv("TELEGRAM_BOT_TOKEN", "")
        )
        return (token or settings.dict().get("telegram_bot_token", "") or "").strip()
    return ""


async def _dispatch_update(update: dict[str, Any]) -> None:
    """Run the same logic as the webhook handler (minus the HTTP plumbing)."""
    message: dict[str, Any] = update.get("message") or update.get("edited_message") or {}
    if not message:
        return
    update_id = update.get("update_id")
    # Global replay guard — covers both webhook and polling modes.
    if update_id is not None and message_dedup.seen(str(update_id), "telegram.update_id"):
        logger.info("telegram_polling.dup update_id=%s", update_id)
        return

    # Re-use the webhook handler's core path by dispatching directly in-process.
    # Late import to avoid circular at module load.
    from app.api.telegram import dispatch_message_from_polling

    try:
        await dispatch_message_from_polling(message)
    except Exception as exc:
        logger.error("telegram_polling.dispatch_error update_id=%s error=%s", update_id, exc)


async def _poll_once(token: str) -> None:
    global _current_mode, _last_mode_change_at
    offset = _load_offset()
    params = {
        "timeout": _POLL_TIMEOUT_S,
        "allowed_updates": ["message", "edited_message"],
    }
    if offset:
        params["offset"] = offset + 1

    url = _TG_API.format(token=token, method="getUpdates")
    async with httpx.AsyncClient(timeout=_POLL_TIMEOUT_S + 5) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    if not data.get("ok"):
        logger.warning("telegram_polling.getUpdates_not_ok %s", data)
        return

    results = data.get("result") or []
    if not results:
        return

    with _lock:
        if _current_mode != "polling":
            logger.warning("telegram_polling.mode_change from=%s to=polling", _current_mode)
            _current_mode = "polling"
            _last_mode_change_at = time.time()

    max_update_id = offset
    for update in results:
        await _dispatch_update(update)
        uid = int(update.get("update_id") or 0)
        if uid > max_update_id:
            max_update_id = uid

    if max_update_id > offset:
        _save_offset(max_update_id)


async def _polling_loop(token: str, stop_event: asyncio.Event) -> None:
    logger.info("telegram_polling.loop.start")
    backoff = 2.0
    while not stop_event.is_set():
        try:
            await _poll_once(token)
            backoff = 2.0  # reset on success
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("telegram_polling.loop.error: %s (backoff=%.1fs)", exc, backoff)
            await asyncio.sleep(min(backoff, 30.0))
            backoff = min(backoff * 2.0, 30.0)
    logger.info("telegram_polling.loop.stop")


def _should_poll(token: str) -> bool:
    if not token:
        return False
    net = network_monitor.snapshot()
    if net.is_online is False:
        return False
    with _lock:
        last_hit = _last_webhook_hit
    if last_hit is None:
        # Haven't ever seen a webhook — give it a cold-start grace window.
        return False
    return (time.time() - last_hit) > _WEBHOOK_STALE_S


async def run_supervisor(stop_event: asyncio.Event | None = None) -> None:
    """Supervisor loop — spawned once from the FastAPI lifespan."""
    global _polling_task, _current_mode, _last_mode_change_at
    inner_stop = asyncio.Event()
    logger.info("telegram_polling.supervisor.start")
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            try:
                token = await _get_bot_token_once()
            except Exception as exc:
                logger.warning("telegram_polling.token_lookup_failed: %s", exc)
                token = ""

            want_polling = _should_poll(token)
            task_alive = _polling_task is not None and not _polling_task.done()

            if want_polling and not task_alive:
                inner_stop = asyncio.Event()
                _polling_task = asyncio.create_task(_polling_loop(token, inner_stop))
            elif not want_polling and task_alive:
                logger.warning(
                    "telegram_polling.mode_change from=polling to=webhook (webhook healthy)"
                )
                inner_stop.set()
                with _lock:
                    _current_mode = "webhook"
                    _last_mode_change_at = time.time()

            try:
                await asyncio.sleep(_CHECK_INTERVAL_S)
            except asyncio.CancelledError:
                break
    finally:
        if _polling_task and not _polling_task.done():
            _polling_task.cancel()
        logger.info("telegram_polling.supervisor.stop")
