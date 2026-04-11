"""Mission Control allowlist API — owner-only CRUD for invite-only access control."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.mc_roles import _clerk_id, require_owner
from app.core.auth import AuthContext, get_auth_context
from app.core.time import utcnow
from app.db.session import get_session
from app.models.mc_allowed_user import MCAllowedUser
from app.models.mc_role import MCUserRole

router = APIRouter(prefix="/allowed-users", tags=["allowed-users"])
logger = logging.getLogger(__name__)

AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)


# ── Schemas ───────────────────────────────────────────────────────────────────

class AllowedUserEntry(BaseModel):
    clerk_user_id: str
    email: str | None
    name: str | None
    role: str
    added_by_clerk_user_id: str | None
    created_at: str


class AddAllowedUserRequest(BaseModel):
    clerk_user_id: str
    role: str = "viewer"


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _enrich(row: MCAllowedUser, session: AsyncSession) -> AllowedUserEntry:
    """Join with users + mc_user_roles to get display fields."""
    from app.models.users import User

    user_result = await session.exec(
        select(User).where(User.clerk_user_id == row.clerk_user_id)
    )
    user = user_result.first()

    role_result = await session.exec(
        select(MCUserRole).where(MCUserRole.clerk_user_id == row.clerk_user_id)
    )
    role_row = role_result.first()

    return AllowedUserEntry(
        clerk_user_id=row.clerk_user_id,
        email=user.email if user else None,
        name=(user.name or user.preferred_name) if user else None,
        role=role_row.role if role_row else "viewer",
        added_by_clerk_user_id=row.added_by_clerk_user_id,
        created_at=row.created_at.isoformat(),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=list[AllowedUserEntry])
async def list_allowed_users(
    _role: str = Depends(require_owner),
    session: AsyncSession = SESSION_DEP,
) -> list[AllowedUserEntry]:
    """List all users on the allowlist. Owner only."""
    rows_result = await session.exec(select(MCAllowedUser))
    rows = rows_result.all()
    entries = []
    for row in rows:
        entries.append(await _enrich(row, session))
    return sorted(entries, key=lambda e: (e.role != "owner", e.email or e.clerk_user_id))


@router.post("", response_model=AllowedUserEntry, status_code=status.HTTP_201_CREATED)
async def add_allowed_user(
    body: AddAllowedUserRequest,
    auth: AuthContext = AUTH_DEP,
    _role: str = Depends(require_owner),
    session: AsyncSession = SESSION_DEP,
) -> AllowedUserEntry:
    """Add a user to the allowlist and create/update their role. Owner only."""
    from app.models.mc_role import VALID_ROLES

    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{body.role}'. Valid: {sorted(VALID_ROLES)}",
        )

    adder_id = _clerk_id(auth)

    # Upsert allowlist row
    existing_result = await session.exec(
        select(MCAllowedUser).where(MCAllowedUser.clerk_user_id == body.clerk_user_id)
    )
    allowed_row = existing_result.first()
    if not allowed_row:
        allowed_row = MCAllowedUser(
            clerk_user_id=body.clerk_user_id,
            added_by_clerk_user_id=adder_id,
        )
        session.add(allowed_row)

    # Upsert mc_user_roles row (viewer by default unless specified)
    role_result = await session.exec(
        select(MCUserRole).where(MCUserRole.clerk_user_id == body.clerk_user_id)
    )
    role_row = role_result.first()
    if role_row:
        role_row.role = body.role
        role_row.disabled = False
        role_row.updated_at = utcnow()
        session.add(role_row)
    else:
        role_row = MCUserRole(
            clerk_user_id=body.clerk_user_id,
            role=body.role,
            disabled=False,
        )
        session.add(role_row)

    await session.commit()
    await session.refresh(allowed_row)

    logger.info(
        "[mc_allowed_users] added clerk_user_id=%s role=%s by=%s",
        body.clerk_user_id,
        body.role,
        adder_id,
    )
    return await _enrich(allowed_row, session)


@router.delete("/{clerk_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_allowed_user(
    clerk_user_id: str,
    auth: AuthContext = AUTH_DEP,
    _role: str = Depends(require_owner),
    session: AsyncSession = SESSION_DEP,
) -> None:
    """Remove a user from the allowlist and revoke their role. Owner only."""
    my_id = _clerk_id(auth)
    if clerk_user_id == my_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove yourself from the allowlist.",
        )

    # Remove from allowlist
    allowed_result = await session.exec(
        select(MCAllowedUser).where(MCAllowedUser.clerk_user_id == clerk_user_id)
    )
    allowed_row = allowed_result.first()
    if allowed_row:
        await session.delete(allowed_row)

    # Remove from mc_user_roles too
    role_result = await session.exec(
        select(MCUserRole).where(MCUserRole.clerk_user_id == clerk_user_id)
    )
    role_row = role_result.first()
    if role_row:
        await session.delete(role_row)

    await session.commit()

    logger.info(
        "[mc_allowed_users] removed clerk_user_id=%s by=%s",
        clerk_user_id,
        my_id,
    )
