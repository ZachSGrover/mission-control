"""Encrypted creator-scoped credential vault row.

Each row holds **one** encrypted credential for **one** creator under
**one** provider. The plaintext is never stored; ``encrypted_value``
holds Fernet ciphertext encrypted under the same key store as
``app.core.secrets_store`` (with the additional Sprint 2 guardrail in
:func:`app.core.secrets_store.is_dedicated_encryption_key_configured`
that refuses *new* writes if the encryption key is the auth-credential
fallback).

Lifecycle:
- Insert with ``status="active"``.
- Rotation creates a new row and marks the old one ``status="rotated"``
  (the old ciphertext stays available for in-flight tokens until the
  rotation window closes; the service decides when to purge).
- Revocation marks ``status="revoked"`` and sets ``revoked_at``;
  ``last_used_at`` is updated by the service that consumes the
  credential.

By design:
- API responses must never include ``encrypted_value``.
- Logs and audit metadata must never include the plaintext.
- Producers must go through ``app.services.creator_credentials`` which
  redacts and audits each operation.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

CREDENTIAL_PROVIDERS: frozenset[str] = frozenset(
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

CREDENTIAL_TYPES: frozenset[str] = frozenset(
    {
        "api_key",
        "session_token",
        "refresh_token",
        "access_token",
        "webhook_secret",
        "oauth_token",
        "other",
    }
)

CREDENTIAL_STATUSES: frozenset[str] = frozenset(
    {"active", "rotated", "revoked"},
)


class CreatorCredential(QueryModel, table=True):
    """Encrypted creator-scoped credential."""

    __tablename__ = "creator_credentials"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    organization_id: UUID | None = Field(default=None, index=True)
    # Soft ref — see audit_events / connector_approvals for the rationale.
    creator_id: str = Field(index=True)

    provider: str = Field(index=True)
    credential_type: str = Field(index=True)

    # Fernet ciphertext. Never plaintext. Never returned by any API.
    encrypted_value: str = Field(sa_column=Column(Text, nullable=False))

    status: str = Field(default="active", index=True)

    created_by_user_id: UUID | None = Field(default=None)
    created_by_email: str | None = Field(default=None)
    revoked_by_user_id: UUID | None = Field(default=None)
    revoked_by_email: str | None = Field(default=None)

    created_at: datetime = Field(default_factory=utcnow)
    rotated_at: datetime | None = Field(default=None)
    revoked_at: datetime | None = Field(default=None)
    last_used_at: datetime | None = Field(default=None)

    metadata_json: dict[str, object] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
