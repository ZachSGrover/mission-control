"""App-level key-value settings stored encrypted in the database."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class AppSetting(SQLModel, table=True):
    """Encrypted application settings persisted in the database."""

    __tablename__ = "app_settings"  # pyright: ignore[reportAssignmentType]

    key: str = Field(primary_key=True, max_length=255)
    value: str = Field(default="")  # Fernet-encrypted ciphertext
    updated_at: datetime = Field(default_factory=utcnow)
