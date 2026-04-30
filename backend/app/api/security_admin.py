"""Security admin status surface.

Read-only owner-gated endpoint that summarises the prevention controls
introduced in Sprint 2. Designed to be called from a future security
dashboard, but useful right now for incident drills and runbook
verification.

Returns ONLY high-level state — never secrets, never specific creator
data, never raw audit metadata. The intent is "is the system in the
shape we expect", not "show me everything".
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.mc_roles import require_owner
from app.core.auth import AuthContext, get_auth_context
from app.core.secrets_store import is_dedicated_encryption_key_configured
from app.core.time import utcnow
from app.db.session import get_session
from app.models.audit_events import AuditEvent
from app.models.client_consents import ClientConsent
from app.models.connector_approvals import ConnectorApproval
from app.models.creator_credentials import CreatorCredential
from app.models.kill_switches import KillSwitch

router = APIRouter(prefix="/security", tags=["security"])

AUTH_DEP = Depends(get_auth_context)
OWNER_DEP = Depends(require_owner)
SESSION_DEP = Depends(get_session)


class KillSwitchSummary(BaseModel):
    scope: str
    scope_id: str | None
    enabled: bool


class SecurityStatusResponse(BaseModel):
    timestamp: str
    encryption_key_dedicated: bool
    is_production: bool
    kill_switches: list[KillSwitchSummary]
    audit_events_24h: int
    audit_events_7d: int
    approvals_pending: int
    approvals_approved_live: int
    consents_granted_live: int
    creator_credentials_active: int
    legacy_gateway_token_count: int
    audit_retention_preview: dict[str, int]
    missing_prerequisites: list[str]


def _missing_prerequisites(
    *,
    encryption_key_dedicated: bool,
    creator_credentials_active: int,
    consents_granted_live: int,
    audit_events_24h: int,
    legacy_gateway_token_count: int = 0,
) -> list[str]:
    out: list[str] = []
    if not encryption_key_dedicated:
        out.append(
            "SETTINGS_ENCRYPTION_KEY is not set — creator credential vault "
            "will refuse new writes."
        )
    if creator_credentials_active == 0:
        out.append(
            "No active creator credentials in the vault. This is the "
            "expected state pre-direct-connector; flagged for visibility."
        )
    if consents_granted_live == 0:
        out.append(
            "No live client consents on file. Direct-connector actions "
            "that need consent will all fail closed."
        )
    if audit_events_24h == 0:
        out.append(
            "No audit events in the last 24h — either the system is idle "
            "or the audit pipeline is silently broken. Confirm by writing "
            "a credential and checking the row count."
        )
    if legacy_gateway_token_count > 0:
        out.append(
            f"{legacy_gateway_token_count} gateway row(s) still hold a "
            "plaintext `token` column value. Run "
            "`app.services.gateway_tokens.migrate_legacy_tokens` once "
            "with `dry_run=False` to encrypt them."
        )
    return out


@router.get("/status", response_model=SecurityStatusResponse)
async def security_status(
    _: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> SecurityStatusResponse:
    """Owner-only view of every Sprint 2 prevention control.

    Aggregates only — no per-row PII, no creator names, no payload bodies.
    """
    del role  # required dep, not used in body

    now = utcnow()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    # Kill switches — every row, including disabled, so the operator can
    # see history without us inventing a separate query.
    rows = (await session.exec(select(KillSwitch))).all()
    ks_summaries = [
        KillSwitchSummary(scope=r.scope, scope_id=r.scope_id, enabled=r.enabled) for r in rows
    ]

    # Audit counts (cheap aggregate; no PII pulled).
    audit_24h = await _scalar_count(
        session,
        select(func.count()).select_from(AuditEvent).where(AuditEvent.created_at >= cutoff_24h),
    )
    audit_7d = await _scalar_count(
        session,
        select(func.count()).select_from(AuditEvent).where(AuditEvent.created_at >= cutoff_7d),
    )

    # Approvals.
    pending = await _scalar_count(
        session,
        select(func.count())
        .select_from(ConnectorApproval)
        .where(ConnectorApproval.status == "pending"),
    )
    approved_live = await _scalar_count(
        session,
        select(func.count())
        .select_from(ConnectorApproval)
        .where(ConnectorApproval.status == "approved")
        .where(ConnectorApproval.revoked_at.is_(None)),  # type: ignore[union-attr]
    )

    # Consents (granted, not revoked, not expired).
    consents_live = await _scalar_count(
        session,
        select(func.count())
        .select_from(ClientConsent)
        .where(ClientConsent.status == "granted")
        .where(ClientConsent.revoked_at.is_(None)),  # type: ignore[union-attr]
    )

    # Active creator credentials (vault occupancy).
    creds_active = await _scalar_count(
        session,
        select(func.count())
        .select_from(CreatorCredential)
        .where(CreatorCredential.status == "active"),
    )

    encryption_key_dedicated = is_dedicated_encryption_key_configured()

    # Sprint 3: legacy plaintext gateway tokens still on disk.
    from app.models.gateways import Gateway

    legacy_gateway_count = await _scalar_count(
        session,
        select(func.count())
        .select_from(Gateway)
        .where(Gateway.token.is_not(None))  # type: ignore[union-attr]
        .where(Gateway.token != ""),
    )

    # Sprint 3: dry-run preview of audit retention purge.
    from app.core.startup_guard import is_production
    from app.services.audit_retention import preview_purge

    retention_preview = await preview_purge(session, now=now)

    return SecurityStatusResponse(
        timestamp=now.isoformat(),
        encryption_key_dedicated=encryption_key_dedicated,
        is_production=is_production(),
        kill_switches=ks_summaries,
        audit_events_24h=audit_24h,
        audit_events_7d=audit_7d,
        approvals_pending=pending,
        approvals_approved_live=approved_live,
        consents_granted_live=consents_live,
        creator_credentials_active=creds_active,
        legacy_gateway_token_count=legacy_gateway_count,
        audit_retention_preview=retention_preview,
        missing_prerequisites=_missing_prerequisites(
            encryption_key_dedicated=encryption_key_dedicated,
            creator_credentials_active=creds_active,
            consents_granted_live=consents_live,
            audit_events_24h=audit_24h,
            legacy_gateway_token_count=legacy_gateway_count,
        ),
    )


async def _scalar_count(session: AsyncSession, stmt: Any) -> int:
    """Run a ``select(func.count())`` statement and return the int."""
    result = await session.exec(stmt)
    value = result.one()
    # SQLAlchemy returns the raw scalar for func.count() under sqlmodel.
    if isinstance(value, tuple):
        value = value[0]
    return int(value)
