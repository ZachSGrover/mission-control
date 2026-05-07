"""Direct OnlyFans sandbox owner sign-off.

Sprint 8C: a typed audit event and helper for the
``connector.golive.sandbox`` row. The sandbox gate refuses to run
unless an owner has explicitly recorded a sign-off for the
specific creator id.

Contract:

- One audit row per ``(connector_type='onlyfans_direct',
  creator_id, owner)`` — duplicates are allowed and treated as
  re-confirmations; the sandbox gate looks for the most recent
  non-revoked row.
- The row never contains a credential value, a credential
  preview, or any creator-specific data beyond the ``creator_id``.
- The row's ``severity`` is ``"high"`` because go-live is a
  high-stakes event; a forensic reviewer should easily filter by
  severity to see the ladder of approvals.
- Production code MUST NOT auto-record an owner sign-off. Sign-off
  is operator-driven (admin endpoint or psql); the helper here
  exists for that path. Tests use it through fixtures only.

This module performs no I/O beyond the audit insert and a single
SELECT. There is no decryption, no client construction, no
notifier call.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.audit_event import AuditEvent
from app.services.audit_log import record_audit_event

CONNECTOR_TYPE: Final[str] = "onlyfans_direct"
EVENT_TYPE: Final[str] = "connector.golive.sandbox"


async def record_owner_signoff(
    session: AsyncSession,
    *,
    creator_id: str,
    owner_user_id: UUID,
    owner_email: str,
    organization_id: UUID | None = None,
    notes: str | None = None,
) -> str | None:
    """Record one ``connector.golive.sandbox`` audit row.

    Used by the owner-only admin path that records sandbox sign-off
    for a specific test creator. The sandbox gate later queries
    audit_events for this row before allowing a sandbox attempt.

    The metadata is intentionally minimal — the row's identity is
    in the ``(event_type, creator_id, actor_user_id)`` tuple, not
    in any free-form field that could leak details.
    """
    metadata: dict[str, object] = {
        "connector_type": CONNECTOR_TYPE,
        "scope": "sandbox",
    }
    if notes:
        # Bounded length to keep the audit metadata small and
        # auditable; notes are free-form operator commentary so we
        # cap at 500 chars to stop a future caller from pasting a
        # transcript into this field.
        metadata["notes"] = notes[:500]

    row = await record_audit_event(
        session,
        event_type=EVENT_TYPE,
        category="connector",
        action="golive_signoff",
        result="success",
        severity="high",
        actor_user_id=owner_user_id,
        actor_email=owner_email,
        organization_id=organization_id,
        creator_id=creator_id,
        resource_type="connector_run",
        resource_id=f"{CONNECTOR_TYPE}:sandbox:{creator_id}",
        metadata=metadata,
    )
    await session.commit()
    return str(row.id) if row is not None else None


async def has_owner_signoff(
    session: AsyncSession,
    *,
    creator_id: str,
    organization_id: UUID | None = None,
) -> bool:
    """Return True iff a ``connector.golive.sandbox`` row exists for
    the creator.

    Sprint 8C uses the cheapest possible signal: a single row's
    presence. A future sprint may add expiry / revocation
    semantics on top, but for now the operator's discipline (don't
    record a sign-off you don't mean) is the only check. The
    helper is used by the sandbox gate; the audit row is the
    source of truth.
    """
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.event_type == EVENT_TYPE)
        .where(AuditEvent.creator_id == creator_id)
    )
    if organization_id is not None:
        stmt = stmt.where(AuditEvent.organization_id == organization_id)
    result = await session.exec(stmt)
    return result.first() is not None
