"""Discord publisher for OF Intelligence QC alerts.

Single outbound webhook.  No state.  No queue.  Callers hand a rendered
message to ``publish()`` and get a ``PublishResult`` back — never an
exception.  Failures are logged and absorbed; QC evaluation must never break
because Discord is down.

Webhook resolution order (first non-empty wins):
  1. encrypted DB secret  ``discord.qc.webhook_url``  (Settings UI)
  2. ``MC_OF_QC_DISCORD_WEBHOOK_URL`` env var (laptop / dry-run / CI)

Kill switch resolution (DB-first with env fallback):
  1. ``of_qc_discord_status.enabled`` row — operator-controlled in the
     Mission Control Settings UI.  When the row exists, its value wins.
  2. ``MC_OF_QC_DISCORD_ENABLED`` env var — used only when no DB row
     exists yet (local dev, CI).
Default everywhere is OFF — every alert short-circuits to
``suppressed:disabled`` until the operator opts in.

The ``Send test alert`` button in Settings calls ``publish()`` with
``bypass_kill_switch=True`` so the operator can verify the webhook before
flipping the toggle on.  The webhook URL is still required.

Privacy:
  • Webhook URL is never logged, even masked.
  • Rendered message is privacy-checked before send.
  • Forbidden substrings (caller-supplied) abort the send and log a
    ``privacy_violation`` event.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.of_intelligence.qc.formatters import (
    PrivacyViolation,
    assert_privacy_safe,
)

logger = get_logger(__name__)

# ── Tunables ────────────────────────────────────────────────────────────────

_HTTP_TIMEOUT_SECONDS = 5.0
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.5
_BACKOFF_MAX_SECONDS = 4.0
# Discord 429 retry_after values can be unreasonable; clamp.
_MAX_RETRY_AFTER_SECONDS = 10.0


@dataclass(frozen=True)
class PublishResult:
    ok: bool
    status: int | None
    attempts: int
    reason: str  # "ok" | "disabled" | "no_webhook" | "privacy_violation"
                 # | "http_4xx" | "http_5xx" | "rate_limited" | "network_error"
                 # | "timeout" | "exception"
    elapsed_ms: int


# ── Config ──────────────────────────────────────────────────────────────────


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


async def _read_db_enabled() -> bool | None:
    """Read the operator toggle from the singleton DB row.

    Returns ``None`` if no row exists yet (operator has never opened the
    Settings card) or the DB is unreachable.  ``None`` means "fall through
    to the env var".
    """
    try:
        from app.db.session import async_session_maker
        from app.models.of_qc_discord_status import OfQcDiscordStatus
    except Exception:
        return None
    try:
        async with async_session_maker() as session:
            row = await session.get(OfQcDiscordStatus, 1)
        return row.enabled if row is not None else None
    except Exception:
        return None


async def is_enabled() -> bool:
    """Resolve the kill switch on every send.

    DB-first: the singleton ``of_qc_discord_status`` row's ``enabled`` value
    wins when present (whether True or False).  When no row exists, fall
    through to the ``MC_OF_QC_DISCORD_ENABLED`` env var.  Default OFF.
    """
    db_value = await _read_db_enabled()
    if db_value is not None:
        return db_value
    return _truthy(os.environ.get("MC_OF_QC_DISCORD_ENABLED"))


async def _read_db_webhook() -> str:
    """Read the DB-backed encrypted secret.

    Returns ``""`` on any failure — DB unreachable, secret absent, decryption
    error.  Callers must always be prepared for an empty string and fall back
    to the env var.  This function deliberately catches every exception so
    the publisher can keep its never-raise contract even when the database
    is offline.
    """
    try:
        from app.core.secrets_store import QC_DISCORD_WEBHOOK_DB_KEY, get_secret
        from app.db.session import async_session_maker
    except Exception:
        return ""
    try:
        async with async_session_maker() as session:
            value = await get_secret(session, QC_DISCORD_WEBHOOK_DB_KEY)
        return (value or "").strip()
    except Exception:
        # Intentionally silent — DB outages must not generate noise on every
        # alert.  ``no_webhook`` will be logged once at the call site.
        return ""


async def _resolve_webhook_url() -> str:
    """Return the configured webhook URL, DB-first with env fallback.

    Order:
      1. encrypted DB secret ``discord.qc.webhook_url`` (Settings UI / set_secret)
      2. ``MC_OF_QC_DISCORD_WEBHOOK_URL`` env var (laptop, CI, dry-run)
    """
    db_value = await _read_db_webhook()
    if db_value:
        return db_value
    return (os.environ.get("MC_OF_QC_DISCORD_WEBHOOK_URL") or "").strip()


# ── Public API ──────────────────────────────────────────────────────────────


async def publish(
    rendered_message: str,
    *,
    code: str,
    severity: str,
    forbidden_substrings: Iterable[str] = (),
    log_extra: dict[str, Any] | None = None,
    bypass_kill_switch: bool = False,
) -> PublishResult:
    """Send a pre-rendered QC alert to Discord.

    Never raises — callers can ignore the return value if they only need
    fire-and-forget semantics, but the result is useful for audit logging.

    ``bypass_kill_switch`` is only used by the Settings → Send test alert
    path so the operator can verify a freshly-saved webhook before flipping
    the toggle on.  The webhook URL is still required.
    """
    started_ns = time.perf_counter_ns()
    base_extra: dict[str, Any] = {"code": code, "severity": severity}
    if log_extra:
        base_extra.update(log_extra)

    if not bypass_kill_switch and not await is_enabled():
        return _result(False, None, 0, "disabled", started_ns, base_extra, level="debug")

    webhook_url = await _resolve_webhook_url()
    if not webhook_url:
        return _result(False, None, 0, "no_webhook", started_ns, base_extra, level="warning")

    try:
        assert_privacy_safe(rendered_message, forbidden_substrings=forbidden_substrings)
    except PrivacyViolation as exc:
        # Never log the raw text — only the violation reason (which itself
        # never contains the forbidden value).
        logger.error(
            "of_qc.discord.privacy_violation reason=%s",
            str(exc),
            extra=base_extra,
        )
        return _result(False, None, 0, "privacy_violation", started_ns, base_extra, level=None)

    return await _post_with_retry(webhook_url, rendered_message, started_ns, base_extra)


# ── Internal: HTTP loop ──────────────────────────────────────────────────────


async def _post_with_retry(
    webhook_url: str,
    rendered_message: str,
    started_ns: int,
    log_extra: dict[str, Any],
) -> PublishResult:
    body = {"content": rendered_message}
    last_status: int | None = None
    last_reason = "exception"

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS) as client:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                resp = await client.post(webhook_url, json=body)
            except httpx.TimeoutException:
                last_status = None
                last_reason = "timeout"
                if attempt < _MAX_ATTEMPTS:
                    await _sleep_backoff(attempt)
                    continue
                break
            except httpx.HTTPError:
                last_status = None
                last_reason = "network_error"
                if attempt < _MAX_ATTEMPTS:
                    await _sleep_backoff(attempt)
                    continue
                break

            last_status = resp.status_code
            if 200 <= resp.status_code < 300:
                return _result(
                    True, resp.status_code, attempt, "ok", started_ns, log_extra, level="info"
                )

            if resp.status_code == 429:
                retry_after = _parse_retry_after(resp)
                last_reason = "rate_limited"
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(min(retry_after, _MAX_RETRY_AFTER_SECONDS))
                    continue
                break

            if 500 <= resp.status_code < 600:
                last_reason = "http_5xx"
                if attempt < _MAX_ATTEMPTS:
                    await _sleep_backoff(attempt)
                    continue
                break

            # 4xx other than 429 — don't retry; webhook gone or payload rejected.
            last_reason = "http_4xx"
            break

    level = "warning" if last_reason in ("rate_limited", "http_5xx") else "error"
    return _result(False, last_status, _MAX_ATTEMPTS, last_reason, started_ns, log_extra, level=level)


async def _sleep_backoff(attempt: int) -> None:
    delay = min(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)), _BACKOFF_MAX_SECONDS)
    jitter = random.uniform(0.0, delay * 0.25)
    await asyncio.sleep(delay + jitter)


def _parse_retry_after(resp: httpx.Response) -> float:
    header = resp.headers.get("retry-after") or resp.headers.get("Retry-After")
    if header:
        try:
            return max(float(header), 0.0)
        except ValueError:
            pass
    try:
        body = resp.json()
        if isinstance(body, dict) and "retry_after" in body:
            return max(float(body["retry_after"]), 0.0)
    except (ValueError, TypeError, httpx.DecodingError):
        pass
    return _BACKOFF_BASE_SECONDS


# ── Internal: result + logging ───────────────────────────────────────────────


def _result(
    ok: bool,
    status: int | None,
    attempts: int,
    reason: str,
    started_ns: int,
    log_extra: dict[str, Any],
    *,
    level: str | None,
) -> PublishResult:
    elapsed_ms = max(0, (time.perf_counter_ns() - started_ns) // 1_000_000)
    result = PublishResult(ok=ok, status=status, attempts=attempts, reason=reason, elapsed_ms=elapsed_ms)
    if level is not None:
        log_method = getattr(logger, level)
        log_method(
            "of_qc.discord.%s status=%s attempts=%s elapsed_ms=%s reason=%s",
            "sent" if ok else "failed" if reason not in ("disabled",) else "suppressed",
            status,
            attempts,
            elapsed_ms,
            reason,
            extra=log_extra,
        )
    return result
