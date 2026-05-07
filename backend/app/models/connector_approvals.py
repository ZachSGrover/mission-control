"""Connector approval row.

A connector action (sync, write, mass-message, etc.) is only allowed
when there's a non-expired, non-revoked, ``status="approved"`` row
matching its (connector_type, requested_action, scope) tuple.

By design these are insert-and-update only — never deleted. Status
transitions go pending → approved/rejected → revoked/expired, and the
historical row is preserved for audit.

Foreign references to ``users`` and ``organizations`` are intentionally
**soft** (no FK constraint) to mirror :class:`AuditEvent` — approval
history must outlive user / org deletion.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

CONNECTOR_TYPES: frozenset[str] = frozenset(
    {
        "onlymonster",
        "onlyfans_direct",
        "discord",
        "telegram",
        "github",
        "openai",
        "anthropic",
        "internal",
    }
)

APPROVAL_STATUSES: frozenset[str] = frozenset(
    {"pending", "approved", "rejected", "revoked", "expired"},
)

RISK_LEVELS: frozenset[str] = frozenset(
    {"low", "medium", "high", "critical"},
)


class ConnectorApproval(QueryModel, table=True):
    """Approval gating row for a connector action."""

    __tablename__ = "connector_approvals"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    organization_id: UUID | None = Field(default=None, index=True)
    creator_id: str | None = Field(default=None, index=True)

    connector_type: str = Field(index=True)
    requested_action: str = Field(index=True)

    requested_by_user_id: UUID | None = Field(default=None, index=True)
    requested_by_email: str | None = Field(default=None)

    approved_by_user_id: UUID | None = Field(default=None)
    approved_by_email: str | None = Field(default=None)

    status: str = Field(default="pending", index=True)
    reason: str | None = Field(default=None)
    risk_level: str = Field(default="medium", index=True)

    expires_at: datetime | None = Field(default=None, index=True)

    created_at: datetime = Field(default_factory=utcnow, index=True)
    approved_at: datetime | None = Field(default=None)
    rejected_at: datetime | None = Field(default=None)
    revoked_at: datetime | None = Field(default=None)

    metadata_json: dict[str, object] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
