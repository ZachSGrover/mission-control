"""Kill-switch service.

Maps the four scopes (global / organization / creator / connector) to
rows in :class:`app.models.kill_switches.KillSwitch` and exposes:

- :func:`enable` / :func:`disable` — toggle a scope, audit always.
- :func:`is_active` — single-scope check.
- :func:`check_action_allowed` — composite check used by the connector
  gate. **Returns the first active scope** (so callers know *why* an
  action was blocked) or ``None`` if every relevant scope is clear.

Toggles always audit, with severity ``critical`` because flipping a
kill switch is the highest-stakes operation in the system.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.kill_switches import KILL_SWITCH_SCOPES, KillSwitch
from app.services.audit_log import record_audit_event

KillSwitchScope = Literal["global", "organization", "creator", "connector"]


def _validate_scope(scope: str, scope_id: str | None) -> None:
    if scope not in KILL_SWITCH_SCOPES:
        raise ValueError(f"unknown kill-switch scope: {scope!r}")
    if scope == "global" and scope_id is not None:
        raise ValueError("global kill switch must have scope_id=None")
    if scope != "global" and not scope_id:
        raise ValueError(f"{scope} kill switch requires a scope_id")


async def _get_or_create(session: AsyncSession, scope: str, scope_id: str | None) -> KillSwitch:
    stmt = select(KillSwitch).where(KillSwitch.scope == scope)
    if scope_id is None:
        stmt = stmt.where(KillSwitch.scope_id.is_(None))  # type: ignore[union-attr]
    else:
        stmt = stmt.where(KillSwitch.scope_id == scope_id)
    result = await session.exec(stmt)
    row = result.first()
    if row is None:
        row = KillSwitch(scope=scope, scope_id=scope_id, enabled=False)
        session.add(row)
        await session.flush()
    return row


async def enable(
    session: AsyncSession,
    *,
    scope: KillSwitchScope,
    scope_id: str | None = None,
    actor_user_id: UUID | None = None,
    actor_email: str | None = None,
    reason: str | None = None,
) -> KillSwitch:
    _validate_scope(scope, scope_id)
    row = await _get_or_create(session, scope, scope_id)
    row.enabled = True
    row.enabled_by_user_id = actor_user_id
    row.enabled_by_email = actor_email
    row.disabled_by_user_id = None
    row.disabled_by_email = None
    row.disabled_at = None
    row.reason = reason
    row.updated_at = utcnow()
    session.add(row)

    await record_audit_event(
        session,
        event_type="kill_switch.enable",
        category="security",
        action="enable",
        result="success",
        severity="critical",
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        resource_type="kill_switch",
        resource_id=f"{scope}:{scope_id or 'all'}",
        metadata={"scope": scope, "scope_id": scope_id, "reason": reason},
    )
    return row


async def disable(
    session: AsyncSession,
    *,
    scope: KillSwitchScope,
    scope_id: str | None = None,
    actor_user_id: UUID | None = None,
    actor_email: str | None = None,
    reason: str | None = None,
) -> KillSwitch:
    _validate_scope(scope, scope_id)
    row = await _get_or_create(session, scope, scope_id)
    if row.enabled:
        row.enabled = False
        row.disabled_by_user_id = actor_user_id
        row.disabled_by_email = actor_email
        row.disabled_at = utcnow()
        row.updated_at = utcnow()
        if reason is not None:
            row.reason = reason
        session.add(row)

    await record_audit_event(
        session,
        event_type="kill_switch.disable",
        category="security",
        action="disable",
        result="success",
        severity="critical",
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        resource_type="kill_switch",
        resource_id=f"{scope}:{scope_id or 'all'}",
        metadata={"scope": scope, "scope_id": scope_id, "reason": reason},
    )
    return row


async def is_active(
    session: AsyncSession,
    *,
    scope: KillSwitchScope,
    scope_id: str | None = None,
) -> bool:
    """Return True iff a kill-switch row exists for this scope and is enabled."""
    _validate_scope(scope, scope_id)
    stmt = select(KillSwitch).where(KillSwitch.scope == scope)
    if scope_id is None:
        stmt = stmt.where(KillSwitch.scope_id.is_(None))  # type: ignore[union-attr]
    else:
        stmt = stmt.where(KillSwitch.scope_id == scope_id)
    result = await session.exec(stmt)
    row = result.first()
    return bool(row and row.enabled)


async def check_action_allowed(
    session: AsyncSession,
    *,
    connector_type: str | None = None,
    organization_id: UUID | None = None,
    creator_id: str | None = None,
) -> tuple[KillSwitchScope, str | None] | None:
    """Composite check.

    Returns the first ``(scope, scope_id)`` of the active kill switch
    that blocks this action, or ``None`` if every relevant scope is clear.

    Order of checks (broadest blast radius first):
    1. global
    2. connector
    3. organization
    4. creator
    """
    if await is_active(session, scope="global"):
        return ("global", None)
    if connector_type is not None and await is_active(
        session, scope="connector", scope_id=connector_type
    ):
        return ("connector", connector_type)
    if organization_id is not None and await is_active(
        session, scope="organization", scope_id=str(organization_id)
    ):
        return ("organization", str(organization_id))
    if creator_id is not None and await is_active(session, scope="creator", scope_id=creator_id):
        return ("creator", creator_id)
    return None
