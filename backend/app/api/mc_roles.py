"""Mission Control role-based access control API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth import AuthContext, get_auth_context
from app.core.auth_mode import AuthMode
from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import get_session
from app.models.mc_role import VALID_ROLES, MCUserRole

router = APIRouter(prefix="/roles", tags=["roles"])
logger = get_logger(__name__)

AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _clerk_id(auth: AuthContext) -> str:
    """Extract clerk_user_id from auth context; returns 'local' for local-auth mode."""
    if auth.user and auth.user.clerk_user_id:
        return auth.user.clerk_user_id
    return "local"


async def _resolve_role(clerk_id: str, session: AsyncSession) -> tuple[str, bool]:
    """
    Return (role, disabled) for a clerk_user_id.

    Priority:
    1. Local auth mode → always ("owner", False)
    2. Explicit OWNER_USER_ID env var → ("owner", False)
    3. DB row if found
    4. No rows in DB at all → first caller becomes owner (auto-seed)
    5. Default → ("viewer", False)
    """
    # Local auth: single-user, always owner
    if settings.auth_mode == AuthMode.LOCAL or clerk_id == "local":
        return "owner", False

    # Env-pinned owner
    owner_id = (settings.owner_user_id or "").strip()
    if owner_id and clerk_id == owner_id:
        return "owner", False

    # DB lookup
    result = await session.exec(select(MCUserRole).where(MCUserRole.clerk_user_id == clerk_id))
    row = result.first()
    if row:
        return row.role, row.disabled

    # Auto-seed: if the table is empty, first caller becomes owner
    count_result = await session.exec(select(MCUserRole))
    if not count_result.all():
        new_row = MCUserRole(clerk_user_id=clerk_id, role="owner")
        session.add(new_row)
        await session.commit()
        logger.info("[mc_roles] auto-seeded owner clerk_user_id=%s", clerk_id)
        return "owner", False

    # Unknown user → viewer by default (visible; not destructive)
    return "viewer", False


# ── Public dependency ─────────────────────────────────────────────────────────


async def get_mc_role(
    auth: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> str:
    """FastAPI dependency — returns the current user's role string."""
    cid = _clerk_id(auth)
    role, disabled = await _resolve_role(cid, session)
    if disabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled.")
    return role


async def require_owner(role: str = Depends(get_mc_role)) -> str:
    if role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner access required.",
        )
    return role


# ── Schemas ───────────────────────────────────────────────────────────────────


class MyRoleResponse(BaseModel):
    role: str
    disabled: bool


class UserRoleEntry(BaseModel):
    clerk_user_id: str
    email: str | None
    name: str | None
    role: str
    disabled: bool


class SetRoleRequest(BaseModel):
    role: str
    disabled: bool = False


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/me", response_model=MyRoleResponse)
async def get_my_role(
    auth: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> MyRoleResponse:
    """Return the current user's role and disabled status."""
    cid = _clerk_id(auth)
    role, disabled = await _resolve_role(cid, session)
    return MyRoleResponse(role=role, disabled=disabled)


@router.get("/users", response_model=list[UserRoleEntry])
async def list_users(
    _role: str = Depends(require_owner),
    session: AsyncSession = SESSION_DEP,
) -> list[UserRoleEntry]:
    """List all users who have an explicit role row, joined with their profile."""
    from app.models.users import User

    rows_result = await session.exec(select(MCUserRole))
    rows = rows_result.all()

    entries: list[UserRoleEntry] = []
    for row in rows:
        # Try to fetch name/email from users table
        user_result = await session.exec(
            select(User).where(User.clerk_user_id == row.clerk_user_id)
        )
        user = user_result.first()
        entries.append(
            UserRoleEntry(
                clerk_user_id=row.clerk_user_id,
                email=user.email if user else None,
                name=user.name or user.preferred_name if user else None,
                role=row.role,
                disabled=row.disabled,
            )
        )

    return sorted(entries, key=lambda e: (e.role != "owner", e.email or ""))


@router.put("/users/{clerk_user_id}", response_model=UserRoleEntry)
async def set_user_role(
    clerk_user_id: str,
    body: SetRoleRequest,
    auth: AuthContext = AUTH_DEP,
    _role: str = Depends(require_owner),
    session: AsyncSession = SESSION_DEP,
) -> UserRoleEntry:
    """Create or update a user's role. Owner only."""
    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{body.role}'. Valid: {sorted(VALID_ROLES)}",
        )

    # Prevent owner from demoting themselves
    my_id = _clerk_id(auth)
    if clerk_user_id == my_id and body.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role.",
        )

    result = await session.exec(select(MCUserRole).where(MCUserRole.clerk_user_id == clerk_user_id))
    row = result.first()

    if row:
        row.role = body.role
        row.disabled = body.disabled
        row.updated_at = utcnow()
        session.add(row)
    else:
        row = MCUserRole(
            clerk_user_id=clerk_user_id,
            role=body.role,
            disabled=body.disabled,
        )
        session.add(row)

    await session.commit()

    from app.models.users import User

    user_result = await session.exec(select(User).where(User.clerk_user_id == clerk_user_id))
    user = user_result.first()

    logger.info(
        "[mc_roles] set role clerk_user_id=%s role=%s disabled=%s",
        clerk_user_id,
        body.role,
        body.disabled,
    )

    return UserRoleEntry(
        clerk_user_id=clerk_user_id,
        email=user.email if user else None,
        name=user.name or user.preferred_name if user else None,
        role=row.role,
        disabled=row.disabled,
    )


@router.delete("/users/{clerk_user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user_role(
    clerk_user_id: str,
    auth: AuthContext = AUTH_DEP,
    _role: str = Depends(require_owner),
    session: AsyncSession = SESSION_DEP,
) -> None:
    """Remove a user's explicit role (they revert to viewer default)."""
    my_id = _clerk_id(auth)
    if clerk_user_id == my_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove your own role.",
        )
    result = await session.exec(select(MCUserRole).where(MCUserRole.clerk_user_id == clerk_user_id))
    row = result.first()
    if row:
        await session.delete(row)
        await session.commit()
