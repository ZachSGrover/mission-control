"""Mission Control allowlist model — controls who may sign in."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class MCAllowedUser(SQLModel, table=True):
    """Allowlist entry — only users with a row here may access Mission Control."""

    __tablename__ = "mc_allowed_users"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    clerk_user_id: str = Field(index=True, unique=True, max_length=255)
    added_by_clerk_user_id: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=utcnow)
