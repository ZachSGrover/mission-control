"""Mission Control role model — stores per-user access level."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from app.core.time import utcnow

MCRoleEnum = str  # "owner" | "operator" | "builder" | "viewer"

VALID_ROLES: frozenset[str] = frozenset({"owner", "operator", "builder", "viewer"})

# Privilege ranks (higher = more privileged).  Used by role-gate dependencies
# in ``app.api.mc_roles`` so that a single source of truth defines hierarchy.
ROLE_RANK: dict[str, int] = {
    "owner": 4,
    "operator": 3,
    "builder": 2,
    "viewer": 1,
}


class MCUserRole(SQLModel, table=True):
    """Per-user role assignment for Mission Control access control."""

    __tablename__ = "mc_user_roles"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    clerk_user_id: str = Field(index=True, unique=True, max_length=255)
    role: str = Field(default="viewer", max_length=32)
    disabled: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
