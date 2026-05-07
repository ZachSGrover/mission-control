"""App-level key-value settings stored encrypted in the database."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class AppSetting(SQLModel, table=True):
    """Encrypted application settings persisted in the database."""

    __tablename__ = "app_settings"  # pyright: ignore[reportAssignmentType]

    key: str = Field(primary_key=True, max_length=255)
    value: str = Field(default="")  # Fernet-encrypted ciphertext
    updated_at: datetime = Field(default_factory=utcnow)
    # Sprint 3 (hardening): nullable org scope. NULL = "global / legacy".
    # See ``app.services.app_settings_scoped`` for the read-with-fallback
    # helper. Note: the PK remains ``key`` for backwards compatibility;
    # org-scoped values use a derived key (``org:{uuid}.{key}``) so legacy
    # global rows don't collide with new org rows.
    organization_id: UUID | None = Field(default=None, index=True)
