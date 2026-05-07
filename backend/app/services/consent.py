"""Client-consent service.

Wraps :class:`app.models.client_consents.ClientConsent`. Two operations
plus a fail-closed predicate:

- :func:`grant` — record a consent (creating a new row, or transitioning
  the latest matching row out of ``"pending"``/``"revoked"`` into
  ``"granted"``).
- :func:`revoke` — mark the latest live consent as revoked.
- :func:`is_granted` — single source of truth for "is this action
  consented to *right now* for this scope?". Fail-closed.

Every grant and revoke records an audit event at severity ``warning``.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.client_consents import CONSENT_TYPES, ClientConsent
from app.services.audit_log import record_audit_event


def _validate_consent_type(consent_type: str) -> None:
    if consent_type not in CONSENT_TYPES:
        raise ValueError(f"unknown consent_type: {consent_type!r}")


async def grant(
    session: AsyncSession,
    *,
    consent_type: str,
    organization_id: UUID | None = None,
    creator_id: str | None = None,
    granted_by_user_id: UUID | None = None,
    granted_by_email: str | None = None,
    source: str | None = None,
    document_reference: str | None = None,
    expires_at: datetime | None = None,
    notes: str | None = None,
    metadata: object | None = None,
) -> ClientConsent:
    _validate_consent_type(consent_type)
    now = utcnow()

    row = ClientConsent(
        organization_id=organization_id,
        creator_id=creator_id,
        consent_type=consent_type,
        status="granted",
        granted_by_user_id=granted_by_user_id,
        granted_by_email=granted_by_email,
        granted_at=now,
        source=source,
        document_reference=document_reference,
        expires_at=expires_at,
        notes=notes,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()

    await record_audit_event(
        session,
        event_type="consent.grant",
        category="permission",
        action="grant",
        result="success",
        severity="warning",
        actor_user_id=granted_by_user_id,
        actor_email=granted_by_email,
        organization_id=organization_id,
        creator_id=creator_id,
        resource_type="client_consent",
        resource_id=str(row.id),
        metadata={
            "consent_type": consent_type,
            "source": source,
            "document_reference": document_reference,
            "extra": metadata,
        },
    )
    return row


async def revoke(
    session: AsyncSession,
    *,
    consent_id: UUID,
    revoked_by_user_id: UUID | None = None,
    revoked_by_email: str | None = None,
    reason: str | None = None,
) -> ClientConsent | None:
    row = await session.get(ClientConsent, consent_id)
    if row is None:
        return None

    now = utcnow()
    row.status = "revoked"
    row.revoked_by_user_id = revoked_by_user_id
    row.revoked_by_email = revoked_by_email
    row.revoked_at = now
    row.updated_at = now
    if reason is not None:
        row.notes = (row.notes + "; " if row.notes else "") + f"revoke_reason: {reason}"
    session.add(row)

    await record_audit_event(
        session,
        event_type="consent.revoke",
        category="permission",
        action="revoke",
        result="success",
        severity="high",
        actor_user_id=revoked_by_user_id,
        actor_email=revoked_by_email,
        organization_id=row.organization_id,
        creator_id=row.creator_id,
        resource_type="client_consent",
        resource_id=str(row.id),
        metadata={"consent_type": row.consent_type, "reason": reason},
    )
    return row


async def is_granted(
    session: AsyncSession,
    *,
    consent_type: str,
    organization_id: UUID | None = None,
    creator_id: str | None = None,
    now: datetime | None = None,
) -> ClientConsent | None:
    """Return the live granted consent row, or ``None`` if not consented.

    Fail-closed: missing rows, revoked rows, expired rows, or unknown
    consent types all yield ``None``.
    """
    if consent_type not in CONSENT_TYPES:
        return None
    moment = now or utcnow()

    stmt = (
        select(ClientConsent)
        .where(ClientConsent.consent_type == consent_type)
        .where(ClientConsent.status == "granted")
    )
    if organization_id is not None:
        stmt = stmt.where(ClientConsent.organization_id == organization_id)
    else:
        stmt = stmt.where(ClientConsent.organization_id.is_(None))  # type: ignore[union-attr]
    if creator_id is not None:
        stmt = stmt.where(ClientConsent.creator_id == creator_id)
    else:
        stmt = stmt.where(ClientConsent.creator_id.is_(None))  # type: ignore[union-attr]

    result = await session.exec(stmt)
    rows = list(result.all())
    for row in rows:
        if row.revoked_at is not None:
            continue
        if row.expires_at is not None and row.expires_at <= moment:
            continue
        return row
    return None
