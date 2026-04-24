"""Mission Control allowlist model — controls who may sign in.

A row represents a pre-authorization. Two lookup keys are supported:
- `clerk_user_id` — known once a user has signed in at least once.
- `email` — used to invite someone before they have a Clerk account.

On first sign-in of an email-only row, `clerk_user_id` is backfilled.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class MCAllowedUser(SQLModel, table=True):
    """Allowlist entry — only users with a matching row here may access Digital OS."""

    __tablename__ = "mc_allowed_users"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    clerk_user_id: str | None = Field(default=None, index=True, unique=True, max_length=255)
    email: str | None = Field(default=None, index=True, unique=True, max_length=320)
    added_by_clerk_user_id: str | None = Field(default=None, max_length=255)
    # pending_role: intended role captured at invite time. Applied to mc_user_roles on first
    # sign-in so email-only invites don't silently downgrade to viewer.
    pending_role: str | None = Field(default=None, max_length=32)
    created_at: datetime = Field(default_factory=utcnow)
