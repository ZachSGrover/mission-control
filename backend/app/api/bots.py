"""Mission Control Bots API — unified bot dashboard surface for COO operator role.

Endpoints:
  GET    /api/v1/bots                       — list bot entries (auth required)
  GET    /api/v1/bots/{slug}                — single bot detail (auth required)
  POST   /api/v1/bots/{slug}/start          — start (operator+, permitted_roles)
  POST   /api/v1/bots/{slug}/stop           — stop (operator+, permitted_roles)
  PATCH  /api/v1/bots/{slug}/permissions    — edit permitted_roles (owner only)

Privacy contract:
  • Responses NEVER include secrets, webhook URLs, fan PII, message
    bodies, or credential previews.  Schemas below define the exact
    shape returned.
  • ``read_only_external`` bots reject start/stop with a coded
    ``managed_externally`` outcome — no path here can touch launchd /
    cloudflared / Hermes / Radar processes.
  • Every mutating endpoint writes an ``audit_events`` row.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import select

from app.api.mc_roles import get_mc_role, require_operator, require_owner
from app.core.auth import AuthContext, get_auth_context
from app.core.logging import get_logger
from app.db.session import get_session
from app.models.bot_registry import BotRegistryEntry
from app.models.mc_role import VALID_ROLES
from app.services.audit_log import actor_from_auth, record_audit
from app.services.bot_registry import (
    actuate_start,
    actuate_stop,
    can_role_operate,
    encode_permitted_roles,
    is_read_only_external,
    parse_permitted_roles,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/bots", tags=["bots"])
logger = get_logger(__name__)

AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)
ROLE_DEP = Depends(get_mc_role)
OPERATOR_DEP = Depends(require_operator)
OWNER_DEP = Depends(require_owner)


# ── Response schemas (no secrets) ───────────────────────────────────────────


class BotEntryResponse(BaseModel):
    """Public-safe view of a bot registry row.

    NOTE: every field below is reviewed for sensitivity.  Adding a new
    field requires re-confirming it does NOT carry secrets, webhook
    URLs, fan PII, or message bodies.
    """

    slug: str
    name: str
    kind: str
    description: str | None
    enabled: bool
    safe_mode: bool
    status: str
    last_status_detail: str | None
    last_run_at: datetime | None
    last_error_summary: str | None
    permitted_roles: list[str]
    can_operate: bool
    read_only_external: bool


class BotMutationResponse(BaseModel):
    slug: str
    ok: bool
    status: str
    detail: str
    enabled: bool


class PermissionsUpdateRequest(BaseModel):
    permitted_roles: list[str]


# ── Helpers ─────────────────────────────────────────────────────────────────


def _to_response(entry: BotRegistryEntry, *, viewer_role: str | None) -> BotEntryResponse:
    return BotEntryResponse(
        slug=entry.slug,
        name=entry.name,
        kind=entry.kind,
        description=entry.description,
        enabled=entry.enabled,
        safe_mode=entry.safe_mode,
        status=entry.status,
        last_status_detail=entry.last_status_detail,
        last_run_at=entry.last_run_at,
        last_error_summary=entry.last_error_summary,
        permitted_roles=parse_permitted_roles(entry.permitted_roles_json),
        can_operate=can_role_operate(viewer_role, entry),
        read_only_external=is_read_only_external(entry),
    )


async def _get_bot_or_404(
    slug: str,
    session: "AsyncSession",
) -> BotRegistryEntry:
    result = await session.exec(select(BotRegistryEntry).where(BotRegistryEntry.slug == slug))
    entry = result.first()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Bot '{slug}' not found."
        )
    return entry


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("", response_model=list[BotEntryResponse])
async def list_bots(
    _: AuthContext = AUTH_DEP,
    role: str = ROLE_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> list[BotEntryResponse]:
    """List all known bots.  Every authenticated user can see the directory.

    The ``can_operate`` flag in each entry tells the UI whether the
    current viewer's role is allowed to start/stop that specific bot.
    """
    result = await session.exec(select(BotRegistryEntry))
    entries = result.all()
    return [
        _to_response(entry, viewer_role=role)
        for entry in sorted(entries, key=lambda e: (e.kind, e.slug))
    ]


@router.get("/{slug}", response_model=BotEntryResponse)
async def get_bot(
    slug: str,
    _: AuthContext = AUTH_DEP,
    role: str = ROLE_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotEntryResponse:
    """Return a single bot entry by slug."""
    entry = await _get_bot_or_404(slug, session)
    return _to_response(entry, viewer_role=role)


@router.post(
    "/{slug}/start",
    response_model=BotMutationResponse,
    status_code=status.HTTP_200_OK,
)
async def start_bot(
    slug: str,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotMutationResponse:
    """Mark a bot as enabled.  Operator or owner only.

    ``read_only_external`` bots always reject with ``managed_externally``.
    Other bots flip the registry's ``enabled`` flag; downstream
    supervisors poll for that flag.
    """
    entry = await _get_bot_or_404(slug, session)
    actor_id, actor_email = actor_from_auth(auth)

    if not can_role_operate(role, entry):
        await record_audit(
            session,
            actor_clerk_user_id=actor_id,
            actor_email=actor_email,
            actor_role=role,
            action="bot.start",
            target_type="bot",
            target_id=slug,
            outcome="denied",
            safe_summary=f"start denied: role={role} not in permitted_roles or external bot",
            request=request,
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "managed_externally"
                if is_read_only_external(entry)
                else "Role not permitted to start this bot."
            ),
        )

    result = await actuate_start(session, entry)

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="bot.start",
        target_type="bot",
        target_id=slug,
        outcome="success" if result.ok else "denied",
        safe_summary=f"start {result.detail}",
        request=request,
    )
    await session.commit()
    await session.refresh(entry)

    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result.detail,
        )

    return BotMutationResponse(
        slug=entry.slug,
        ok=True,
        status=result.status,
        detail=result.detail,
        enabled=entry.enabled,
    )


@router.post(
    "/{slug}/stop",
    response_model=BotMutationResponse,
    status_code=status.HTTP_200_OK,
)
async def stop_bot(
    slug: str,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotMutationResponse:
    """Mark a bot as disabled.  Operator or owner only."""
    entry = await _get_bot_or_404(slug, session)
    actor_id, actor_email = actor_from_auth(auth)

    if not can_role_operate(role, entry):
        await record_audit(
            session,
            actor_clerk_user_id=actor_id,
            actor_email=actor_email,
            actor_role=role,
            action="bot.stop",
            target_type="bot",
            target_id=slug,
            outcome="denied",
            safe_summary=f"stop denied: role={role} not in permitted_roles or external bot",
            request=request,
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "managed_externally"
                if is_read_only_external(entry)
                else "Role not permitted to stop this bot."
            ),
        )

    result = await actuate_stop(session, entry)

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="bot.stop",
        target_type="bot",
        target_id=slug,
        outcome="success" if result.ok else "denied",
        safe_summary=f"stop {result.detail}",
        request=request,
    )
    await session.commit()
    await session.refresh(entry)

    if not result.ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result.detail,
        )

    return BotMutationResponse(
        slug=entry.slug,
        ok=True,
        status=result.status,
        detail=result.detail,
        enabled=entry.enabled,
    )


@router.patch("/{slug}/permissions", response_model=BotEntryResponse)
async def set_bot_permissions(
    slug: str,
    body: PermissionsUpdateRequest,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotEntryResponse:
    """Edit a bot's ``permitted_roles``.  Owner only.

    Owner is always implicitly permitted regardless of what is sent in
    the body — the encoder restores it.
    """
    invalid = [r for r in body.permitted_roles if r not in VALID_ROLES]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid roles: {sorted(invalid)}.  Valid: {sorted(VALID_ROLES)}.",
        )

    entry = await _get_bot_or_404(slug, session)
    actor_id, actor_email = actor_from_auth(auth)
    new_value = encode_permitted_roles(body.permitted_roles)
    entry.permitted_roles_json = new_value
    session.add(entry)

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="bot.permission.set",
        target_type="bot",
        target_id=slug,
        outcome="success",
        safe_summary=f"permissions set to {new_value}",
        request=request,
    )
    await session.commit()
    await session.refresh(entry)
    return _to_response(entry, viewer_role=role)
