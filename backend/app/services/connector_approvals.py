"""Connector-approval service.

Wraps :class:`app.models.connector_approvals.ConnectorApproval` with the
state-machine helpers callers actually need:

- :func:`request_approval` — create a pending row.
- :func:`approve` / :func:`reject` / :func:`revoke` — terminal-ish
  transitions (revoked overrides approved).
- :func:`is_approved` — fail-closed predicate used by
  :func:`app.core.connector_gate.is_connector_action_allowed`. **All**
  must be true: an approval row exists, status is ``"approved"``, it
  is not revoked, the matching expiry has not passed, the
  connector_type matches, and (when supplied) the requested action and
  scope match.

Every state transition records an audit event. Producers do not have
to remember to audit — the service does it for them.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.connector_approvals import (
    APPROVAL_STATUSES,
    CONNECTOR_TYPES,
    RISK_LEVELS,
    ConnectorApproval,
)
from app.services.audit_log import record_audit


def _validate_connector_type(connector_type: str) -> None:
    if connector_type not in CONNECTOR_TYPES:
        raise ValueError(f"unknown connector_type: {connector_type!r}")


def _validate_risk(risk_level: str) -> None:
    if risk_level not in RISK_LEVELS:
        raise ValueError(f"unknown risk_level: {risk_level!r}")


async def request_approval(
    session: AsyncSession,
    *,
    connector_type: str,
    requested_action: str,
    organization_id: UUID | None = None,
    creator_id: str | None = None,
    requested_by_user_id: UUID | None = None,
    requested_by_email: str | None = None,
    risk_level: str = "medium",
    expires_at: datetime | None = None,
    reason: str | None = None,
    metadata: object | None = None,
) -> ConnectorApproval:
    """Create a pending approval row and audit the request."""
    _validate_connector_type(connector_type)
    _validate_risk(risk_level)

    row = ConnectorApproval(
        organization_id=organization_id,
        creator_id=creator_id,
        connector_type=connector_type,
        requested_action=requested_action,
        requested_by_user_id=requested_by_user_id,
        requested_by_email=requested_by_email,
        status="pending",
        reason=reason,
        risk_level=risk_level,
        expires_at=expires_at,
    )
    session.add(row)
    await session.flush()

    await record_audit(
        session,
        event_type="connector.approval.request",
        category="connector",
        action="request",
        result="success",
        severity="info",
        actor_user_id=requested_by_user_id,
        actor_email=requested_by_email,
        organization_id=organization_id,
        creator_id=creator_id,
        resource_type="connector_approval",
        resource_id=str(row.id),
        metadata={
            "connector_type": connector_type,
            "requested_action": requested_action,
            "risk_level": risk_level,
            "extra": metadata,
        },
    )
    return row


async def _set_status(
    session: AsyncSession,
    approval_id: UUID,
    *,
    status: str,
    reason: str | None,
    actor_user_id: UUID | None,
    actor_email: str | None,
    audit_event_type: str,
    audit_action: str,
    audit_severity: str,
) -> ConnectorApproval | None:
    if status not in APPROVAL_STATUSES:
        raise ValueError(f"unknown status: {status!r}")

    row = await session.get(ConnectorApproval, approval_id)
    if row is None:
        return None

    now = utcnow()
    row.status = status
    if status == "approved":
        row.approved_by_user_id = actor_user_id
        row.approved_by_email = actor_email
        row.approved_at = now
    elif status == "rejected":
        row.approved_by_user_id = None
        row.rejected_at = now
        row.reason = reason or row.reason
    elif status == "revoked":
        row.revoked_at = now
        row.reason = reason or row.reason
    elif status == "expired":
        row.reason = reason or row.reason

    session.add(row)

    # Cast to typed Literals at the call site for record_audit.
    from typing import Literal as _Literal
    from typing import cast

    sev = cast(_Literal["info", "warning", "high", "critical"], audit_severity)
    await record_audit(
        session,
        event_type=audit_event_type,
        category="connector",
        action=audit_action,
        result="success",
        severity=sev,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        organization_id=row.organization_id,
        creator_id=row.creator_id,
        resource_type="connector_approval",
        resource_id=str(row.id),
        metadata={
            "connector_type": row.connector_type,
            "requested_action": row.requested_action,
            "previous_status": "pending",  # informational only
            "new_status": status,
            "reason": reason,
        },
    )
    return row


async def approve(
    session: AsyncSession,
    approval_id: UUID,
    *,
    approver_user_id: UUID | None = None,
    approver_email: str | None = None,
    reason: str | None = None,
) -> ConnectorApproval | None:
    return await _set_status(
        session,
        approval_id,
        status="approved",
        reason=reason,
        actor_user_id=approver_user_id,
        actor_email=approver_email,
        audit_event_type="connector.approval.approve",
        audit_action="approve",
        audit_severity="warning",
    )


async def reject(
    session: AsyncSession,
    approval_id: UUID,
    *,
    rejecter_user_id: UUID | None = None,
    rejecter_email: str | None = None,
    reason: str | None = None,
) -> ConnectorApproval | None:
    return await _set_status(
        session,
        approval_id,
        status="rejected",
        reason=reason,
        actor_user_id=rejecter_user_id,
        actor_email=rejecter_email,
        audit_event_type="connector.approval.reject",
        audit_action="reject",
        audit_severity="warning",
    )


async def revoke(
    session: AsyncSession,
    approval_id: UUID,
    *,
    revoker_user_id: UUID | None = None,
    revoker_email: str | None = None,
    reason: str | None = None,
) -> ConnectorApproval | None:
    return await _set_status(
        session,
        approval_id,
        status="revoked",
        reason=reason,
        actor_user_id=revoker_user_id,
        actor_email=revoker_email,
        audit_event_type="connector.approval.revoke",
        audit_action="revoke",
        audit_severity="high",
    )


async def is_approved(
    session: AsyncSession,
    *,
    connector_type: str,
    requested_action: str,
    organization_id: UUID | None = None,
    creator_id: str | None = None,
    now: datetime | None = None,
) -> ConnectorApproval | None:
    """Return the live approval row, or ``None`` if no approval is in force.

    Fail-closed: any of the following yields ``None``:
    - no row matches the (connector_type, requested_action, scope) tuple
    - the row's ``status`` is not ``"approved"``
    - the row has been revoked / rejected
    - the row's ``expires_at`` is in the past
    """
    if connector_type not in CONNECTOR_TYPES:
        return None
    moment = now or utcnow()

    stmt = (
        select(ConnectorApproval)
        .where(ConnectorApproval.connector_type == connector_type)
        .where(ConnectorApproval.requested_action == requested_action)
        .where(ConnectorApproval.status == "approved")
    )
    if organization_id is not None:
        stmt = stmt.where(ConnectorApproval.organization_id == organization_id)
    else:
        stmt = stmt.where(ConnectorApproval.organization_id.is_(None))  # type: ignore[union-attr]
    if creator_id is not None:
        stmt = stmt.where(ConnectorApproval.creator_id == creator_id)
    else:
        stmt = stmt.where(ConnectorApproval.creator_id.is_(None))  # type: ignore[union-attr]

    result = await session.exec(stmt)
    rows = list(result.all())

    for row in rows:
        if row.revoked_at is not None:
            continue
        if row.expires_at is not None and row.expires_at <= moment:
            continue
        return row
    return None
