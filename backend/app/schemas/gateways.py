"""Schemas for gateway CRUD and template-sync API payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import field_validator, model_validator
from sqlmodel import Field, SQLModel

RUNTIME_ANNOTATION_TYPES = (datetime, UUID)


class GatewayBase(SQLModel):
    """Shared gateway fields used across create/read payloads."""

    name: str
    url: str
    workspace_root: str
    allow_insecure_tls: bool = False
    disable_device_pairing: bool = False


class GatewayCreate(GatewayBase):
    """Payload for creating a gateway configuration."""

    token: str | None = None

    @field_validator("token", mode="before")
    @classmethod
    def normalize_token(cls, value: object) -> str | None | object:
        """Normalize empty/whitespace tokens to `None`."""
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class GatewayUpdate(SQLModel):
    """Payload for partial gateway updates."""

    name: str | None = None
    url: str | None = None
    token: str | None = None
    workspace_root: str | None = None
    allow_insecure_tls: bool | None = None
    disable_device_pairing: bool | None = None

    @field_validator("token", mode="before")
    @classmethod
    def normalize_token(cls, value: object) -> str | None | object:
        """Normalize empty/whitespace tokens to `None`."""
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class GatewayRead(GatewayBase):
    """Gateway payload returned from read endpoints.

    Sprint 4 hardening notes:
    - ``token`` is the legacy plaintext column. Sprint 3 introduced
      :func:`app.services.gateway_tokens.set_token` which clears this
      column on every new write — so post-Sprint-3 gateways always
      return ``token=None`` here. Legacy rows still leak via this
      field until an operator runs ``migrate_legacy_tokens``; that's
      tracked operationally.
    - ``token_configured`` is the safe boolean replacement. Sprint 4
      callers should rely on this field; future sprints will
      ``token`` from the response entirely.
    """

    id: UUID
    organization_id: UUID
    token: str | None = None
    # Sprint 4: never serialised to clients. Used only by the validator
    # below to derive ``token_configured`` from a Gateway ORM row.
    encrypted_token: str | None = Field(default=None, exclude=True)
    token_configured: bool = False
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _derive_token_configured(self) -> Self:
        if not self.token_configured:
            self.token_configured = bool(self.token) or bool(self.encrypted_token)
        return self


class GatewayTemplatesSyncError(SQLModel):
    """Per-agent error entry from a gateway template sync operation."""

    agent_id: UUID | None = None
    agent_name: str | None = None
    board_id: UUID | None = None
    message: str


class GatewayTemplatesSyncResult(SQLModel):
    """Summary payload returned by gateway template sync endpoints."""

    gateway_id: UUID
    include_main: bool
    reset_sessions: bool
    agents_updated: int
    agents_skipped: int
    main_updated: bool
    errors: list[GatewayTemplatesSyncError] = Field(default_factory=list)
