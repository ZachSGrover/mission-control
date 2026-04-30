"""Mission Control allowlist API — owner-only CRUD for invite-only access control.

An allowlist row represents a pre-authorization. Two lookup keys are supported:
- `clerk_user_id` — known once a user has signed in at least once.
- `email` — used to invite someone before they have a Clerk account.

On first sign-in of an email-only row, `clerk_user_id` is backfilled.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, model_validator
from sqlalchemy import or_
from sqlmodel import col, select
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
    clerk_user_id: str | None
    email: str | None
    name: str | None
    role: str
    added_by_clerk_user_id: str | None
    created_at: str
    pending: bool


class AddAllowedUserRequest(BaseModel):
    email: str | None = None
    clerk_user_id: str | None = None
    role: str = "viewer"

    @model_validator(mode="after")
    def _require_one_key(self) -> "AddAllowedUserRequest":
        if not (self.email and self.email.strip()) and not (
            self.clerk_user_id and self.clerk_user_id.strip()
        ):
            raise ValueError("Provide either 'email' or 'clerk_user_id'.")
        return self


# ── Helpers ───────────────────────────────────────────────────────────────────


def _normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


async def _enrich(row: MCAllowedUser, session: AsyncSession) -> AllowedUserEntry:
    """Join with users + mc_user_roles to get display fields.

    Role precedence for display:
      1. mc_user_roles.role if the user has signed in (source of truth post-login)
      2. pending_role captured at invite time (displayed while pending)
      3. "viewer" fallback (legacy rows created before pending_role existed)
    """
    from app.models.users import User

    user = None
    if row.clerk_user_id:
        user_result = await session.exec(
            select(User).where(User.clerk_user_id == row.clerk_user_id)
        )
        user = user_result.first()

    role_row = None
    if row.clerk_user_id:
        role_result = await session.exec(
            select(MCUserRole).where(MCUserRole.clerk_user_id == row.clerk_user_id)
        )
        role_row = role_result.first()

    email = row.email or (user.email if user else None)
    display_role = role_row.role if role_row else (row.pending_role or "viewer")

    return AllowedUserEntry(
        clerk_user_id=row.clerk_user_id,
        email=email,
        name=(user.name or user.preferred_name) if user else None,
        role=display_role,
        added_by_clerk_user_id=row.added_by_clerk_user_id,
        created_at=row.created_at.isoformat(),
        pending=row.clerk_user_id is None,
    )


async def _find_row(
    session: AsyncSession,
    *,
    clerk_user_id: str | None = None,
    email: str | None = None,
) -> MCAllowedUser | None:
    conditions = []
    if clerk_user_id:
        conditions.append(col(MCAllowedUser.clerk_user_id) == clerk_user_id)
    if email:
        conditions.append(col(MCAllowedUser.email) == email)
    if not conditions:
        return None
    result = await session.exec(select(MCAllowedUser).where(or_(*conditions)))
    return result.first()


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
    return sorted(
        entries,
        key=lambda e: (
            e.role != "owner",
            e.pending,
            e.email or e.clerk_user_id or "",
        ),
    )


@router.post("", response_model=AllowedUserEntry, status_code=status.HTTP_201_CREATED)
async def add_allowed_user(
    body: AddAllowedUserRequest,
    auth: AuthContext = AUTH_DEP,
    _role: str = Depends(require_owner),
    session: AsyncSession = SESSION_DEP,
) -> AllowedUserEntry:
    """Add a user to the allowlist. Owner only.

    Accepts either an email (invite before sign-up) or a Clerk user ID (for
    already-signed-in users). If the row already exists it is updated rather
    than duplicated.
    """
    from app.models.mc_role import VALID_ROLES

    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role '{body.role}'. Valid: {sorted(VALID_ROLES)}",
        )

    clerk_user_id = (body.clerk_user_id or "").strip() or None
    email = _normalize_email(body.email)
    adder_id = _clerk_id(auth)

    allowed_row = await _find_row(session, clerk_user_id=clerk_user_id, email=email)

    if not allowed_row:
        allowed_row = MCAllowedUser(
            clerk_user_id=clerk_user_id,
            email=email,
            added_by_clerk_user_id=adder_id,
            pending_role=body.role,
        )
        session.add(allowed_row)
    else:
        if clerk_user_id and not allowed_row.clerk_user_id:
            allowed_row.clerk_user_id = clerk_user_id
        if email and not allowed_row.email:
            allowed_row.email = email
        # Update pending_role so re-invites / role edits on pending rows stick.
        allowed_row.pending_role = body.role
        session.add(allowed_row)

    # If the invitee has already signed in (clerk_user_id known), write the role
    # straight into mc_user_roles. Otherwise pending_role above carries it until
    # first sign-in, where _check_allowlist applies it.
    if clerk_user_id:
        role_result = await session.exec(
            select(MCUserRole).where(MCUserRole.clerk_user_id == clerk_user_id)
        )
        role_row = role_result.first()
        if role_row:
            role_row.role = body.role
            role_row.disabled = False
            role_row.updated_at = utcnow()
            session.add(role_row)
        else:
            session.add(
                MCUserRole(
                    clerk_user_id=clerk_user_id,
                    role=body.role,
                    disabled=False,
                )
            )

    await session.commit()
    await session.refresh(allowed_row)

    logger.info(
        "[mc_allowed_users] added clerk_user_id=%s email=%s role=%s by=%s",
        clerk_user_id,
        email,
        body.role,
        adder_id,
    )
    return await _enrich(allowed_row, session)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_allowed_user(
    key: str,
    auth: AuthContext = AUTH_DEP,
    _role: str = Depends(require_owner),
    session: AsyncSession = SESSION_DEP,
) -> None:
    """Remove a user from the allowlist and revoke their role. Owner only.

    `key` may be either a Clerk user ID (e.g. `user_abc123`) or an email
    address. Email-only (pending) invites are identified by email.
    """
    my_id = _clerk_id(auth)
    if key == my_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove yourself from the allowlist.",
        )

    key_clean = key.strip()
    is_email = "@" in key_clean
    lookup_email = _normalize_email(key_clean) if is_email else None
    lookup_clerk_id = key_clean if not is_email else None

    allowed_row = await _find_row(
        session,
        clerk_user_id=lookup_clerk_id,
        email=lookup_email,
    )

    if not allowed_row:
        return

    clerk_user_id = allowed_row.clerk_user_id
    await session.delete(allowed_row)

    if clerk_user_id:
        role_result = await session.exec(
            select(MCUserRole).where(MCUserRole.clerk_user_id == clerk_user_id)
        )
        role_row = role_result.first()
        if role_row:
            await session.delete(role_row)

    await session.commit()

    logger.info(
        "[mc_allowed_users] removed clerk_user_id=%s email=%s by=%s",
        clerk_user_id,
        allowed_row.email,
        my_id,
    )
