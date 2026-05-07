"""Client consent record.

A consent is the *recorded fact* that a creator (or org) has given
informed permission for a specific class of data action. No connector
that touches creator data may run without a matching live consent.

By design these are insert-and-update only:
- ``status`` may move from ``"pending"`` → ``"granted"`` → ``"revoked"``.
- ``revoked_at`` is set on revocation; the row itself is kept.
- A revoked or expired consent is **not** deleted; it stays as evidence
  that consent was once given and when it was withdrawn.

Foreign references to ``organizations`` and ``users`` are soft (no FK)
to keep consent history independent of those tables' lifecycles.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

CONSENT_TYPES: frozenset[str] = frozenset(
    {
        "data_storage",
        "ai_analysis",
        "onlymonster_sync",
        "onlyfans_direct_read",
        "onlyfans_direct_write",
        "chat_log_review",
        "fan_data_processing",
        "revenue_analysis",
    }
)

CONSENT_STATUSES: frozenset[str] = frozenset(
    {"pending", "granted", "revoked", "expired"},
)


class ClientConsent(QueryModel, table=True):
    """Consent record for a creator-scoped data action."""

    __tablename__ = "client_consents"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    organization_id: UUID | None = Field(default=None, index=True)
    creator_id: str | None = Field(default=None, index=True)

    consent_type: str = Field(index=True)
    status: str = Field(default="pending", index=True)

    granted_by_user_id: UUID | None = Field(default=None)
    granted_by_email: str | None = Field(default=None)
    granted_at: datetime | None = Field(default=None)

    revoked_by_user_id: UUID | None = Field(default=None)
    revoked_by_email: str | None = Field(default=None)
    revoked_at: datetime | None = Field(default=None)

    expires_at: datetime | None = Field(default=None, index=True)

    # Free-form labels for where the consent came from — e.g. "docusign",
    # "signed_pdf", "in_app", "email_thread".
    source: str | None = Field(default=None)
    document_reference: str | None = Field(default=None)
    notes: str | None = Field(default=None)

    metadata_json: dict[str, object] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
