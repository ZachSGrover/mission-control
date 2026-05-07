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


# ── Sprint 4: management endpoints ────────────────────────────────────────────
#
# Owner-gated, narrow-scope endpoints that let the future admin UI drive
# the prevention controls Sprint 2 / 3 added. Every state-changing call
# threads through the same audited service helpers used by tests, so a
# UI cannot escape the audit trail.

from uuid import UUID  # noqa: E402

from fastapi import HTTPException
from fastapi import status as _http_status  # noqa: E402

from app.core.connector_gate import (  # noqa: E402
    GateVerdict,
    is_connector_action_allowed,
)
from app.services import connector_approvals as _approvals_svc  # noqa: E402
from app.services import consent as _consent_svc  # noqa: E402
from app.services import kill_switch as _kill_switch_svc  # noqa: E402
from app.services.audit_log import record_audit  # noqa: E402
from app.services.gateway_tokens import migrate_legacy_tokens  # noqa: E402

# ── Kill switches ────────────────────────────────────────────────────────────


class KillSwitchToggleRequest(BaseModel):
    scope: str  # "global" | "connector" | "organization" | "creator"
    scope_id: str | None = None  # required for non-global
    reason: str | None = None


@router.post("/kill-switches/enable", response_model=KillSwitchSummary)
async def enable_kill_switch(
    body: KillSwitchToggleRequest,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> KillSwitchSummary:
    """Enable a kill switch at the requested scope. Owner only."""
    del role
    try:
        row = await _kill_switch_svc.enable(
            session,
            scope=body.scope,  # type: ignore[arg-type]
            scope_id=body.scope_id,
            actor_user_id=auth.user.id if auth.user else None,
            actor_email=auth.user.email if auth.user else None,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=_http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return KillSwitchSummary(scope=row.scope, scope_id=row.scope_id, enabled=row.enabled)


@router.post("/kill-switches/disable", response_model=KillSwitchSummary)
async def disable_kill_switch(
    body: KillSwitchToggleRequest,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> KillSwitchSummary:
    """Disable a kill switch. Owner only."""
    del role
    try:
        row = await _kill_switch_svc.disable(
            session,
            scope=body.scope,  # type: ignore[arg-type]
            scope_id=body.scope_id,
            actor_user_id=auth.user.id if auth.user else None,
            actor_email=auth.user.email if auth.user else None,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=_http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return KillSwitchSummary(scope=row.scope, scope_id=row.scope_id, enabled=row.enabled)


# ── Connector approvals ──────────────────────────────────────────────────────


class ApprovalSummary(BaseModel):
    id: str
    connector_type: str
    requested_action: str
    status: str
    risk_level: str
    organization_id: str | None
    creator_id: str | None
    requested_by_email: str | None
    approved_by_email: str | None
    expires_at: str | None
    created_at: str
    approved_at: str | None
    rejected_at: str | None
    revoked_at: str | None


def _approval_to_summary(row: ConnectorApproval) -> ApprovalSummary:
    return ApprovalSummary(
        id=str(row.id),
        connector_type=row.connector_type,
        requested_action=row.requested_action,
        status=row.status,
        risk_level=row.risk_level,
        organization_id=str(row.organization_id) if row.organization_id else None,
        creator_id=row.creator_id,
        requested_by_email=row.requested_by_email,
        approved_by_email=row.approved_by_email,
        expires_at=row.expires_at.isoformat() if row.expires_at else None,
        created_at=row.created_at.isoformat(),
        approved_at=row.approved_at.isoformat() if row.approved_at else None,
        rejected_at=row.rejected_at.isoformat() if row.rejected_at else None,
        revoked_at=row.revoked_at.isoformat() if row.revoked_at else None,
    )


@router.get("/approvals", response_model=list[ApprovalSummary])
async def list_approvals(
    _: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
    only_pending: bool = False,
    limit: int = 100,
) -> list[ApprovalSummary]:
    """List recent connector approvals. Owner only."""
    del role
    stmt = select(ConnectorApproval).order_by(
        ConnectorApproval.created_at.desc()  # type: ignore[attr-defined]
    )
    if only_pending:
        stmt = stmt.where(ConnectorApproval.status == "pending")
    stmt = stmt.limit(limit)
    rows = (await session.exec(stmt)).all()
    return [_approval_to_summary(r) for r in rows]


class ApprovalDecisionRequest(BaseModel):
    reason: str | None = None


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalSummary)
async def approve_approval(
    approval_id: UUID,
    body: ApprovalDecisionRequest,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ApprovalSummary:
    del role
    row = await _approvals_svc.approve(
        session,
        approval_id,
        approver_user_id=auth.user.id if auth.user else None,
        approver_email=auth.user.email if auth.user else None,
        reason=body.reason,
    )
    if row is None:
        raise HTTPException(
            status_code=_http_status.HTTP_404_NOT_FOUND, detail="approval not found"
        )
    await session.commit()
    return _approval_to_summary(row)


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalSummary)
async def reject_approval(
    approval_id: UUID,
    body: ApprovalDecisionRequest,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ApprovalSummary:
    del role
    row = await _approvals_svc.reject(
        session,
        approval_id,
        rejecter_user_id=auth.user.id if auth.user else None,
        rejecter_email=auth.user.email if auth.user else None,
        reason=body.reason,
    )
    if row is None:
        raise HTTPException(
            status_code=_http_status.HTTP_404_NOT_FOUND, detail="approval not found"
        )
    await session.commit()
    return _approval_to_summary(row)


@router.post("/approvals/{approval_id}/revoke", response_model=ApprovalSummary)
async def revoke_approval(
    approval_id: UUID,
    body: ApprovalDecisionRequest,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ApprovalSummary:
    del role
    row = await _approvals_svc.revoke(
        session,
        approval_id,
        revoker_user_id=auth.user.id if auth.user else None,
        revoker_email=auth.user.email if auth.user else None,
        reason=body.reason,
    )
    if row is None:
        raise HTTPException(
            status_code=_http_status.HTTP_404_NOT_FOUND, detail="approval not found"
        )
    await session.commit()
    return _approval_to_summary(row)


# ── Consents ─────────────────────────────────────────────────────────────────


class ConsentSummary(BaseModel):
    id: str
    consent_type: str
    status: str
    organization_id: str | None
    creator_id: str | None
    granted_by_email: str | None
    granted_at: str | None
    revoked_at: str | None
    expires_at: str | None
    source: str | None


def _consent_to_summary(row: ClientConsent) -> ConsentSummary:
    return ConsentSummary(
        id=str(row.id),
        consent_type=row.consent_type,
        status=row.status,
        organization_id=str(row.organization_id) if row.organization_id else None,
        creator_id=row.creator_id,
        granted_by_email=row.granted_by_email,
        granted_at=row.granted_at.isoformat() if row.granted_at else None,
        revoked_at=row.revoked_at.isoformat() if row.revoked_at else None,
        expires_at=row.expires_at.isoformat() if row.expires_at else None,
        source=row.source,
    )


@router.get("/consents", response_model=list[ConsentSummary])
async def list_consents(
    _: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
    only_live: bool = False,
    limit: int = 100,
) -> list[ConsentSummary]:
    """List recent consent records. Owner only."""
    del role
    stmt = select(ClientConsent).order_by(
        ClientConsent.created_at.desc()  # type: ignore[attr-defined]
    )
    if only_live:
        stmt = stmt.where(ClientConsent.status == "granted")
        stmt = stmt.where(ClientConsent.revoked_at.is_(None))  # type: ignore[union-attr]
    stmt = stmt.limit(limit)
    rows = (await session.exec(stmt)).all()
    return [_consent_to_summary(r) for r in rows]


class ConsentRevokeRequest(BaseModel):
    reason: str | None = None


@router.post("/consents/{consent_id}/revoke", response_model=ConsentSummary)
async def revoke_consent(
    consent_id: UUID,
    body: ConsentRevokeRequest,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ConsentSummary:
    del role
    row = await _consent_svc.revoke(
        session,
        consent_id=consent_id,
        revoked_by_user_id=auth.user.id if auth.user else None,
        revoked_by_email=auth.user.email if auth.user else None,
        reason=body.reason,
    )
    if row is None:
        raise HTTPException(status_code=_http_status.HTTP_404_NOT_FOUND, detail="consent not found")
    await session.commit()
    return _consent_to_summary(row)


# ── Gateway token migration ──────────────────────────────────────────────────


class GatewayTokenMigrationResponse(BaseModel):
    scanned: int
    migrated: int
    dry_run: bool


@router.post("/gateway-tokens/migrate", response_model=GatewayTokenMigrationResponse)
async def migrate_gateway_tokens(
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
    dry_run: bool = True,
) -> GatewayTokenMigrationResponse:
    """Migrate legacy plaintext gateway tokens into encrypted_token. Defaults to dry-run.

    Owner-only. Refused unless ``SETTINGS_ENCRYPTION_KEY`` is set so the
    migrator can never write rows under the rotation-prone fallback seed.
    """
    del role
    try:
        scanned, migrated = await migrate_legacy_tokens(
            session,
            actor_email=auth.user.email if auth.user else None,
            dry_run=dry_run,
        )
    except RuntimeError as exc:
        # Refusal because dedicated key isn't set — surface to UI cleanly.
        raise HTTPException(status_code=_http_status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # The migrator only audits *successful* migrations per row. Audit the
    # invocation itself so an operator dry-run is also visible in the trail.
    await record_audit(
        session,
        event_type="gateway.token.migrate.invoke",
        category="credential",
        action="migrate",
        result="success",
        severity="info" if dry_run else "high",
        actor_user_id=auth.user.id if auth.user else None,
        actor_email=auth.user.email if auth.user else None,
        resource_type="gateway",
        metadata={"dry_run": dry_run, "scanned": scanned, "would_migrate_or_migrated": migrated},
    )
    await session.commit()
    return GatewayTokenMigrationResponse(scanned=scanned, migrated=migrated, dry_run=dry_run)


# ── Connector gate preview ───────────────────────────────────────────────────
#
# Sprint 4's "first wiring" of the connector gate. Lets the operator
# (and a future connector) ask the gate whether a given action would be
# allowed, without actually running it. Demonstrates the gate end-to-end
# via a real route, without touching any production hot path.


class GatePreviewRequest(BaseModel):
    connector_type: str
    requested_action: str
    organization_id: UUID | None = None
    creator_id: str | None = None


class GatePreviewResponse(BaseModel):
    allowed: bool
    reason: str
    detail: str | None


@router.post("/connector-gate/preview", response_model=GatePreviewResponse)
async def preview_connector_gate(
    body: GatePreviewRequest,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> GatePreviewResponse:
    """Run the connector gate without executing anything. Useful for ops drills."""
    del role
    verdict: GateVerdict = await is_connector_action_allowed(
        session,
        connector_type=body.connector_type,
        requested_action=body.requested_action,
        organization_id=body.organization_id,
        creator_id=body.creator_id,
    )
    # Audit the preview attempt so we have a record of who asked.
    await record_audit(
        session,
        event_type="connector.gate.preview",
        category="connector",
        action="preview",
        result="success" if verdict.allowed else "blocked",
        severity="info",
        actor_user_id=auth.user.id if auth.user else None,
        actor_email=auth.user.email if auth.user else None,
        organization_id=body.organization_id,
        creator_id=body.creator_id,
        resource_type="connector_gate",
        resource_id=f"{body.connector_type}:{body.requested_action}",
        metadata={
            "connector_type": body.connector_type,
            "requested_action": body.requested_action,
            "verdict_reason": verdict.reason,
            "verdict_detail": verdict.detail,
        },
    )
    await session.commit()
    return GatePreviewResponse(
        allowed=verdict.allowed, reason=verdict.reason, detail=verdict.detail
    )


# ── Sprint 5: approval and consent creation ──────────────────────────────────
#
# Sprint 4 added read + state-transition endpoints. Sprint 5 adds the
# missing creation endpoints so an owner can drive the full lifecycle
# from the security admin UI without touching the database directly.


class ApprovalCreateRequest(BaseModel):
    connector_type: str
    requested_action: str
    organization_id: UUID | None = None
    creator_id: str | None = None
    risk_level: str = "medium"
    expires_at_iso: str | None = None
    reason: str | None = None


@router.post("/approvals", response_model=ApprovalSummary, status_code=201)
async def create_approval(
    body: ApprovalCreateRequest,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ApprovalSummary:
    """Create a pending connector approval. Owner only.

    The approval starts in ``status="pending"``. Use ``POST
    /approvals/{id}/approve`` to move it to approved, ``/reject`` to
    decline, or ``/revoke`` to invalidate after approval.
    """
    del role
    from datetime import datetime as _dt

    expires_at: _dt | None = None
    if body.expires_at_iso:
        try:
            expires_at = _dt.fromisoformat(body.expires_at_iso)
        except ValueError as exc:
            raise HTTPException(
                status_code=_http_status.HTTP_400_BAD_REQUEST,
                detail=f"invalid expires_at_iso: {exc}",
            ) from exc

    try:
        row = await _approvals_svc.request_approval(
            session,
            connector_type=body.connector_type,
            requested_action=body.requested_action,
            organization_id=body.organization_id,
            creator_id=body.creator_id,
            requested_by_user_id=auth.user.id if auth.user else None,
            requested_by_email=auth.user.email if auth.user else None,
            risk_level=body.risk_level,
            expires_at=expires_at,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=_http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return _approval_to_summary(row)


class ConsentGrantRequest(BaseModel):
    consent_type: str
    organization_id: UUID | None = None
    creator_id: str | None = None
    source: str | None = None
    document_reference: str | None = None
    expires_at_iso: str | None = None
    notes: str | None = None


@router.post("/consents", response_model=ConsentSummary, status_code=201)
async def create_consent(
    body: ConsentGrantRequest,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ConsentSummary:
    """Grant a client consent. Owner only.

    Consent capture is **out-of-band** in v1 — the operator records the
    fact of consent here after the creator has signed (DocuSign,
    PDF, email thread). Sprint 5 only adds the recording surface; a
    self-serve creator portal is post-MVP.
    """
    del role
    from datetime import datetime as _dt

    expires_at: _dt | None = None
    if body.expires_at_iso:
        try:
            expires_at = _dt.fromisoformat(body.expires_at_iso)
        except ValueError as exc:
            raise HTTPException(
                status_code=_http_status.HTTP_400_BAD_REQUEST,
                detail=f"invalid expires_at_iso: {exc}",
            ) from exc

    try:
        row = await _consent_svc.grant(
            session,
            consent_type=body.consent_type,
            organization_id=body.organization_id,
            creator_id=body.creator_id,
            granted_by_user_id=auth.user.id if auth.user else None,
            granted_by_email=auth.user.email if auth.user else None,
            source=body.source,
            document_reference=body.document_reference,
            expires_at=expires_at,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=_http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return _consent_to_summary(row)


# ── Sprint 7: direct OnlyFans connector status (read-only) ───────────────────
#
# Surfaces the disabled-shell status to the security admin UI. Returns
# safe enums and booleans only — no token, no preview, no fixture
# data. The disabled state is the *whole point* of this surface in
# Sprint 7; the UI uses it to make the disabled status unambiguous.


class OnlyFansDirectStatusResponse(BaseModel):
    """Sprint 7 read-only status for the direct OnlyFans connector.

    Every field is a boolean, an enum, or a small int. There is no
    place in this shape for a credential preview, a token, or any
    fixture payload.
    """

    connector_type: str
    mode: str  # "disabled" | "dry_run"
    enabled: bool
    real_client_wired: bool
    rate_max_per_minute: int
    rate_max_per_hour: int
    backoff_initial_seconds: float
    backoff_max_seconds: float
    session_health: str
    notes: str
    read_actions_count: int
    write_actions_count: int
    # Sprint 8B additions
    dry_run_available: bool
    fake_allowed_in_production: bool
    is_production: bool
    notify_channel_status: str  # "not_configured" | "skipped"
    production_mode_blocked: bool  # always True
    real_account_connection_blocked: bool  # always True
    # Sprint 8C additions
    sandbox_env_flag_set: bool  # MC_OF_DIRECT_SANDBOX_ALLOWED
    sandbox_available: bool  # env flag set AND not production
    real_client_skeleton_present: bool  # always True post-Sprint-8C
    sandbox_missing_prerequisites: list[str]  # human-readable list
    # Sprint 8D additions
    sandbox_read_methods_implemented: list[str]  # has a body via fake transport
    sandbox_read_methods_blocked: list[str]  # still raises RealClientNotEnabledError
    # Sprint 8E additions
    real_client_env_flag_set: bool  # MC_OF_DIRECT_REAL_CLIENT_ALLOWED
    sandbox_transport_configured: bool  # both env flags AND non-production
    sandbox_signoff_endpoint_path: str  # the admin path that records connector.golive.sandbox


# ── Sprint 8A: OnlyMonster gated proof status + preview ─────────────────────


class OnlyMonsterGateStatusResponse(BaseModel):
    """Sprint 8A read-only status for the OnlyMonster gated read path.

    Surfaces only the booleans, enums, and small ints the security
    admin UI needs to render readiness. Never includes the
    OnlyMonster credential, a token preview, or any fan/creator
    payload data.
    """

    connector_type: str
    requested_action: str
    creator_id: str | None
    organization_id: str | None
    env_flag_enabled: bool  # MC_ONLYMONSTER_GATED_SYNC_ENABLED
    fake_allowed_in_production: bool  # MC_ONLYMONSTER_ALLOW_FAKE_CLIENT
    is_production: bool
    approval_present: bool
    consent_present: bool
    kill_switch_blocking: str | None  # None | "global" | "connector" | "organization" | "creator"
    encryption_key_dedicated: bool
    real_client_wired: bool
    direct_onlyfans_blocked: bool  # always True in Sprint 8A
    notes: str


@router.get("/onlymonster-gate/status", response_model=OnlyMonsterGateStatusResponse)
async def onlymonster_gate_status(
    _: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
    creator_id: str | None = None,
) -> OnlyMonsterGateStatusResponse:
    """Owner-only readiness snapshot for the OnlyMonster gated path.

    Sprint 8A surface. Pass ``creator_id`` to check the per-creator
    approval / consent / kill-switch state; omit it for global
    (unscoped) readiness.
    """
    del role
    import os as _os

    from app.core.startup_guard import is_production
    from app.services import connector_approvals as _approvals_svc
    from app.services import consent as _consent_svc
    from app.services import kill_switch as _kill_switch_svc
    from app.services.gated_onlymonster_sync import ENV_ENABLED as _OM_ENV_ENABLED
    from app.services.onlymonster_fake_client import ENV_ALLOW_FAKE_IN_PROD as _OM_ENV_FAKE

    env_flag = _os.environ.get(_OM_ENV_ENABLED, "0").strip() == "1"
    fake_allowed = _os.environ.get(_OM_ENV_FAKE, "0").strip() == "1"

    approval = await _approvals_svc.is_approved(
        session,
        connector_type="onlymonster",
        requested_action="creator_sync",
        creator_id=creator_id,
    )
    consent = await _consent_svc.is_granted(
        session,
        consent_type="onlymonster_sync",
        creator_id=creator_id,
    )
    blocking = await _kill_switch_svc.check_action_allowed(
        session,
        connector_type="onlymonster",
        creator_id=creator_id,
    )

    return OnlyMonsterGateStatusResponse(
        connector_type="onlymonster",
        requested_action="creator_sync",
        creator_id=creator_id,
        organization_id=None,
        env_flag_enabled=env_flag,
        fake_allowed_in_production=fake_allowed,
        is_production=is_production(),
        approval_present=approval is not None,
        consent_present=consent is not None,
        kill_switch_blocking=blocking[0] if blocking else None,
        encryption_key_dedicated=is_dedicated_encryption_key_configured(),
        real_client_wired=False,  # Sprint 8A: real client lives on feat/of-intelligence
        direct_onlyfans_blocked=True,
        notes=(
            "OnlyMonster gated proof: env flag and gate must both pass. "
            "Real OnlyMonster client is not on this branch; preview runs "
            "use the fake client only."
        ),
    )


class OnlyMonsterGatePreviewRequest(BaseModel):
    creator_id: str
    organization_id: UUID | None = None


class OnlyMonsterGatePreviewResponse(BaseModel):
    """Result of an owner-initiated gated proof preview.

    Always uses the fake client in Sprint 8A. The shape mirrors
    :class:`app.services.onlymonster_gate_proof.GatedProofResult`
    minus internal-only fields.
    """

    allowed: bool
    connector_type: str
    requested_action: str
    creator_id: str | None
    rows_read: int
    rows_written: int
    last_event_at_iso: str | None
    audit_event_id: str | None
    error_category: str | None
    used_fake_client: bool
    notes: str


@router.post("/onlymonster-gate/preview", response_model=OnlyMonsterGatePreviewResponse)
async def onlymonster_gate_preview(
    body: OnlyMonsterGatePreviewRequest,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> OnlyMonsterGatePreviewResponse:
    """Owner-only: run one gated proof against the fake OnlyMonster
    client.

    The fake client is the only client wired in this branch. The
    seam, the gated wrapper, and the gate are all real — only the
    last hop (the OnlyMonster client) is the fake. This proves the
    chain end-to-end on a real integration-style path before any
    direct OnlyFans connector exists.
    """
    del role
    from app.services.onlymonster_fake_client import FakeOnlyMonsterClient
    from app.services.onlymonster_gate_proof import run_onlymonster_gated_proof

    fake = FakeOnlyMonsterClient()
    result = await run_onlymonster_gated_proof(
        session,
        creator_id=body.creator_id,
        organization_id=body.organization_id,
        actor_user_id=auth.user.id if auth.user else None,
        actor_email=auth.user.email if auth.user else None,
        fake_client=fake,
    )
    return OnlyMonsterGatePreviewResponse(
        allowed=result.allowed,
        connector_type=result.connector_type,
        requested_action=result.requested_action,
        creator_id=result.creator_id,
        rows_read=result.rows_read,
        rows_written=result.rows_written,
        last_event_at_iso=result.last_event_at_iso,
        audit_event_id=result.audit_event_id,
        error_category=result.error_category,
        used_fake_client=result.used_fake_client,
        notes=result.notes,
    )


# ── Sprint 8E: owner sign-off endpoint ───────────────────────────────────────


class SandboxSignoffRequest(BaseModel):
    """Body for ``POST /security/onlyfans-direct/sandbox-signoff``.

    Carries only the creator id and an optional operator note.
    The endpoint records a ``connector.golive.sandbox`` audit row
    at severity ``high``. It does NOT auto-approve the connector,
    grant consent, or run a read.
    """

    creator_id: str
    notes: str | None = None


class SandboxSignoffResponse(BaseModel):
    creator_id: str
    audit_event_id: str | None
    notes_recorded: bool


@router.post(
    "/onlyfans-direct/sandbox-signoff",
    response_model=SandboxSignoffResponse,
    status_code=201,
)
async def onlyfans_direct_sandbox_signoff(
    body: SandboxSignoffRequest,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> SandboxSignoffResponse:
    """Owner-only: record a sandbox owner sign-off for a creator.

    Sprint 8C / 8D / 8E sandbox path refuses to run unless an
    audit row with ``event_type='connector.golive.sandbox'``
    exists for the creator. This endpoint is the only operator
    surface that records one — production code MUST NOT auto-call
    it.
    """
    del role
    if not body.creator_id.strip():
        raise HTTPException(
            status_code=_http_status.HTTP_400_BAD_REQUEST,
            detail="creator_id must not be empty",
        )
    if auth.user is None or auth.user.id is None:
        # The endpoint is owner-gated; auth.user should always be
        # set. Defensive guard.
        raise HTTPException(
            status_code=_http_status.HTTP_400_BAD_REQUEST,
            detail="owner identity could not be resolved",
        )
    from app.services.onlyfans_direct_owner_signoff import record_owner_signoff

    audit_id = await record_owner_signoff(
        session,
        creator_id=body.creator_id.strip(),
        owner_user_id=auth.user.id,
        owner_email=auth.user.email or "unknown@example.test",
        notes=body.notes,
    )
    return SandboxSignoffResponse(
        creator_id=body.creator_id.strip(),
        audit_event_id=audit_id,
        notes_recorded=bool(body.notes),
    )


@router.get("/onlyfans-direct/status", response_model=OnlyFansDirectStatusResponse)
async def onlyfans_direct_status(
    _: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
) -> OnlyFansDirectStatusResponse:
    """Read-only status for the disabled direct OnlyFans connector.

    Sprint 7 surface. Always reports ``mode="disabled"`` and
    ``enabled=False`` until a future sprint flips the shell. Used by
    the security admin UI to render the "Direct OnlyFans connector:
    disabled" card.
    """
    del role
    import os as _os

    from app.core.onlyfans_direct_policy import READ_ACTIONS, WRITE_ACTIONS
    from app.core.startup_guard import is_production as _is_production
    from app.services.onlyfans_direct_connector import OnlyFansDirectConnector
    from app.services.onlyfans_direct_fake_client import ENV_ALLOW_FAKE_IN_PROD as _OF_ENV_FAKE
    from app.services.onlyfans_direct_session_health import notify_channel_status

    snapshot = OnlyFansDirectConnector().status()
    fake_allowed = _os.environ.get(_OF_ENV_FAKE, "0").strip() == "1"
    in_prod = _is_production()
    # Dry-run is "available" iff we can construct the fake client at
    # all — i.e. either we're not in production or the explicit drill
    # flag is set. We never actually construct one here; the UI uses
    # the boolean to render the readiness state.
    dry_run_available = (not in_prod) or fake_allowed
    # Sprint 8C: sandbox availability + missing-prereq breakdown.
    from app.services.onlyfans_direct_connector import ENV_SANDBOX_ALLOWED as _OF_ENV_SANDBOX

    sandbox_env_flag_set = _os.environ.get(_OF_ENV_SANDBOX, "0").strip() == "1"
    sandbox_available = sandbox_env_flag_set and (not in_prod)
    missing_sandbox: list[str] = []
    if not sandbox_env_flag_set:
        missing_sandbox.append(f"{_OF_ENV_SANDBOX}=1 not set")
    if in_prod:
        missing_sandbox.append("running in production environment")
    if not is_dedicated_encryption_key_configured():
        missing_sandbox.append("SETTINGS_ENCRYPTION_KEY not configured (vault unavailable)")
    if notify_channel_status() == "not_configured":
        # Notify is not strictly required to *attempt* a sandbox run,
        # but the operator should know it isn't wired.
        missing_sandbox.append("challenge notify channel not configured (informational)")
    # Sprint 8D: which sandbox read methods have real bodies vs.
    # still raise RealClientNotEnabledError. The lists are static
    # per-sprint; UI renders them so the operator can see exactly
    # which reads are wired.
    sandbox_implemented = sorted(
        ["account_profile_read", "account_stats_read", "revenue_summary_read"]
    )
    sandbox_blocked_methods = sorted(set(READ_ACTIONS) - set(sandbox_implemented))

    # Sprint 8E: real-client env flag + transport-configurable status.
    from app.services.onlyfans_direct_transport import ENV_REAL_CLIENT_ALLOWED as _OF_ENV_REAL

    real_client_env_flag_set = _os.environ.get(_OF_ENV_REAL, "0").strip() == "1"
    sandbox_transport_configured = sandbox_env_flag_set and real_client_env_flag_set and not in_prod

    return OnlyFansDirectStatusResponse(
        connector_type=snapshot.connector_type,
        mode=snapshot.mode,
        enabled=snapshot.enabled,
        real_client_wired=snapshot.real_client_wired,
        rate_max_per_minute=snapshot.rate_max_per_minute,
        rate_max_per_hour=snapshot.rate_max_per_hour,
        backoff_initial_seconds=snapshot.backoff_initial_seconds,
        backoff_max_seconds=snapshot.backoff_max_seconds,
        session_health=snapshot.session_health,
        notes=snapshot.notes,
        read_actions_count=len(READ_ACTIONS),
        write_actions_count=len(WRITE_ACTIONS),
        dry_run_available=dry_run_available,
        fake_allowed_in_production=fake_allowed,
        is_production=in_prod,
        notify_channel_status=notify_channel_status(),
        production_mode_blocked=True,
        real_account_connection_blocked=True,
        sandbox_env_flag_set=sandbox_env_flag_set,
        sandbox_available=sandbox_available,
        real_client_skeleton_present=True,
        sandbox_missing_prerequisites=missing_sandbox,
        sandbox_read_methods_implemented=sandbox_implemented,
        sandbox_read_methods_blocked=sandbox_blocked_methods,
        real_client_env_flag_set=real_client_env_flag_set,
        sandbox_transport_configured=sandbox_transport_configured,
        sandbox_signoff_endpoint_path="/api/v1/security/onlyfans-direct/sandbox-signoff",
    )
