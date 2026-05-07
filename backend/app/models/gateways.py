"""Gateway model storing organization-level gateway integration metadata."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, Text
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

RUNTIME_ANNOTATION_TYPES = (datetime,)


class Gateway(QueryModel, table=True):
    """Configured external gateway endpoint and authentication settings."""

    __tablename__ = "gateways"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(foreign_key="organizations.id", index=True)
    name: str
    url: str
    # Legacy plaintext column. New writes go to ``encrypted_token`` via
    # ``app.services.gateway_tokens.set_token``; this column is read only
    # when ``encrypted_token`` is empty (legacy rows pre-Sprint-3).
    token: str | None = Field(default=None)
    # Sprint 3 (hardening): Fernet ciphertext token. Use the
    # ``app.services.gateway_tokens`` helpers, never read this column
    # directly.
    encrypted_token: str | None = Field(
        default=None,
        sa_column=Column("encrypted_token", Text, nullable=True),
    )
    disable_device_pairing: bool = Field(default=False)
    workspace_root: str
    allow_insecure_tls: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
