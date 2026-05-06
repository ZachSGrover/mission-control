"""OnlyFans Intelligence QC Discord — Settings → Integrations card backend.

Owner-only endpoints that back a single Discord-webhook integration card in
the Mission Control Settings UI.  The webhook URL is stored encrypted via
``secrets_store`` (key ``discord.qc.webhook_url``); the operator toggle and
last-test outcome live in the singleton ``of_qc_discord_status`` row.

Hard rules enforced here:
  • Webhook URL is never echoed to clients.  Responses carry only the
    fixed masked preview ``https://discord.com/api/webhooks/****``.
  • PUT validates the host allowlist before storing.  Anything outside
    ``discord.com / discordapp.com / canary.discord.com / ptb.discord.com``
    is rejected with 400.
  • The /test endpoint sends ONE canned alert with hard-coded fake values.
    No real OF data is read or referenced.  ``bypass_kill_switch=True`` is
    used so the operator can verify the webhook before flipping the
    enable toggle on; the webhook URL is still required.

Endpoints:
  GET    /api/v1/of-qc-discord/status     → card state
  PUT    /api/v1/of-qc-discord/webhook    → save webhook (validated, encrypted)
  DELETE /api/v1/of-qc-discord/webhook    → clear webhook + test history
  PUT    /api/v1/of-qc-discord/enabled    → operator toggle
  POST   /api/v1/of-qc-discord/test       → send one canned test alert
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.mc_roles import require_owner
from app.core.auth import AuthContext, get_auth_context
from app.core.logging import get_logger
from app.core.secrets_store import (
    QC_DISCORD_WEBHOOK_DB_KEY,
    delete_secret,
    get_secret_with_source,
    set_secret,
)
from app.core.time import utcnow
from app.db.session import get_session
from app.models.of_qc_discord_status import OfQcDiscordStatus
from app.services.of_intelligence.qc import (
    AlertPayload,
    PublishResult,
    Severity,
    format_alert,
    publish,
)

router = APIRouter(prefix="/of-qc-discord", tags=["of-qc-discord"])
AUTH_DEP = Depends(get_auth_context)
OWNER_DEP = Depends(require_owner)
SESSION_DEP = Depends(get_session)
logger = get_logger(__name__)

# Single, fixed masked preview — never includes any portion of the real URL.
_MASKED_PREVIEW = "https://discord.com/api/webhooks/****"

# Discord webhook host + path allowlist.  We accept the four documented
# Discord hosts.  Unknown hosts are rejected before encryption.
_WEBHOOK_URL_PATTERN = re.compile(
    r"^https://(discord\.com|discordapp\.com|canary\.discord\.com|ptb\.discord\.com)"
    r"/api/(?:v\d+/)?webhooks/\d+/[\w-]+$",
)

# Singleton row id.
_STATUS_ROW_ID = 1

CardState = Literal["not_configured", "configured", "last_test_failed", "connected"]


# ── Schemas ──────────────────────────────────────────────────────────────────


class StatusResponse(BaseModel):
    configured: bool
    preview: str | None = None
    source: str = "none"  # "db" | "env" | "none"
    enabled: bool = False
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_failure_reason: str | None = None
    last_failure_status: int | None = None
    card_state: CardState = "not_configured"
    # Privacy mode (Safe Summary today; Internal Detail is scaffolded but
    # always falls back to Safe Summary at render time until the rest of
    # its preconditions are implemented).
    privacy_mode: str = "safe_summary"
    privacy_mode_effective: str = "safe_summary"


class SetWebhookRequest(BaseModel):
    key: str = Field(min_length=1, max_length=512)


class SetEnabledRequest(BaseModel):
    enabled: bool


class TestResponse(BaseModel):
    ok: bool
    status: int | None
    attempts: int
    reason: str
    elapsed_ms: int
    card_state: CardState


# ── Helpers ──────────────────────────────────────────────────────────────────


def _validate_webhook_url(value: str) -> str:
    """Reject anything that isn't a Discord webhook URL.

    The error message intentionally never includes the submitted value —
    that's how a malicious paste would otherwise reach error logs.
    """
    candidate = (value or "").strip()
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook URL must not be empty.",
        )
    if not _WEBHOOK_URL_PATTERN.match(candidate):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Must be a Discord webhook URL " "(https://discord.com/api/webhooks/<id>/<token>)."
            ),
        )
    return candidate


async def _get_or_create_row(session: AsyncSession) -> OfQcDiscordStatus:
    row = await session.get(OfQcDiscordStatus, _STATUS_ROW_ID)
    if row is None:
        row = OfQcDiscordStatus(id=_STATUS_ROW_ID, enabled=False)
        session.add(row)
        await session.flush()
    return row


async def _build_status(session: AsyncSession) -> StatusResponse:
    from app.services.of_intelligence.qc.privacy_modes import (
        PrivacyMode,
        effective_mode,
    )

    value, source = await get_secret_with_source(session, QC_DISCORD_WEBHOOK_DB_KEY)
    configured = bool(value and value.strip())

    row = await session.get(OfQcDiscordStatus, _STATUS_ROW_ID)
    enabled = bool(row.enabled) if row is not None else False
    last_success = row.last_success_at if row is not None else None
    last_failure = row.last_failure_at if row is not None else None
    last_reason = row.last_failure_reason if row is not None else None
    last_status = row.last_failure_status if row is not None else None
    privacy_mode = (
        PrivacyMode.coerce(row.privacy_mode).value
        if row is not None
        else PrivacyMode.SAFE_SUMMARY.value
    )
    privacy_mode_effective = effective_mode(requested=privacy_mode).value

    return StatusResponse(
        configured=configured,
        preview=_MASKED_PREVIEW if configured else None,
        source=source if configured else "none",
        enabled=enabled,
        last_success_at=last_success,
        last_failure_at=last_failure,
        last_failure_reason=last_reason,
        last_failure_status=last_status,
        card_state=_compute_card_state(
            configured=configured,
            last_success=last_success,
            last_failure=last_failure,
        ),
        privacy_mode=privacy_mode,
        privacy_mode_effective=privacy_mode_effective,
    )


def _compute_card_state(
    *,
    configured: bool,
    last_success: datetime | None,
    last_failure: datetime | None,
) -> CardState:
    if not configured:
        return "not_configured"
    if last_failure is not None and (last_success is None or last_failure > last_success):
        return "last_test_failed"
    if last_success is not None:
        return "connected"
    return "configured"


def _build_test_payload() -> AlertPayload:
    """Hard-coded canned test alert.  Never reads OF data."""
    return AlertPayload(
        severity=Severity.INFO,
        code="qc_discord_settings_test",
        title="Mission Control test alert",
        facts=(
            ("Source", "Settings → OF QC Discord card"),
            ("Note", "no real OF data"),
        ),
        action="If you can read this, the QC Discord webhook is working.",
        ref=f"qc/test/{uuid4()}",
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/status", response_model=StatusResponse)
async def get_card_status(
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> StatusResponse:
    """Return the full state of the Discord QC integration card."""
    return await _build_status(session)


@router.put("/webhook", response_model=StatusResponse)
async def save_webhook(
    body: SetWebhookRequest,
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> StatusResponse:
    """Save (or rotate) the encrypted webhook URL.

    The submitted value is validated against the Discord host allowlist
    before being passed to ``set_secret``.  The response never echoes the
    submitted URL — only the fixed masked preview.
    """
    validated = _validate_webhook_url(body.key)
    await set_secret(session, QC_DISCORD_WEBHOOK_DB_KEY, validated)
    # Ensure the singleton row exists so the toggle has a home.
    await _get_or_create_row(session)
    await session.commit()
    return await _build_status(session)


@router.delete("/webhook", response_model=StatusResponse)
async def remove_webhook(
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> StatusResponse:
    """Remove the stored webhook and reset test history.

    Removing the webhook clears the last-success / last-failure fields so
    the card returns to a clean ``Not configured`` state.  The toggle is
    forced off as well — there is nothing to enable any more.
    """
    await delete_secret(session, QC_DISCORD_WEBHOOK_DB_KEY)
    row = await _get_or_create_row(session)
    row.enabled = False
    row.last_success_at = None
    row.last_failure_at = None
    row.last_failure_reason = None
    row.last_failure_status = None
    row.updated_at = utcnow()
    session.add(row)
    await session.commit()
    return await _build_status(session)


@router.put("/enabled", response_model=StatusResponse)
async def set_enabled(
    body: SetEnabledRequest,
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> StatusResponse:
    """Operator toggle.  When false, real alerts short-circuit to ``disabled``."""
    row = await _get_or_create_row(session)
    row.enabled = bool(body.enabled)
    row.updated_at = utcnow()
    session.add(row)
    await session.commit()
    return await _build_status(session)


@router.post("/test", response_model=TestResponse)
async def send_test_alert(
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> TestResponse:
    """Send one canned test alert.

    Always uses hard-coded fake values — never touches real OF data.
    Bypasses the operator toggle (so the user can verify the webhook before
    flipping it on) but still requires a saved webhook URL and still runs
    the privacy guard.
    """
    payload = _build_test_payload()
    rendered = format_alert(payload)
    result: PublishResult = await publish(
        rendered,
        code=payload.code,
        severity=payload.severity.value,
        log_extra={"settings_test": True},
        bypass_kill_switch=True,
    )

    # Update the singleton row with the outcome — drives the card state.
    row = await _get_or_create_row(session)
    now = utcnow()
    if result.ok:
        row.last_success_at = now
        row.last_failure_at = None
        row.last_failure_reason = None
        row.last_failure_status = None
    else:
        row.last_failure_at = now
        row.last_failure_reason = result.reason[:64]
        row.last_failure_status = result.status
    row.updated_at = now
    session.add(row)
    await session.commit()

    refreshed = await _build_status(session)
    return TestResponse(
        ok=result.ok,
        status=result.status,
        attempts=result.attempts,
        reason=result.reason,
        elapsed_ms=result.elapsed_ms,
        card_state=refreshed.card_state,
    )
