"""Connector-run wrapper that enforces the Sprint 2 gate.

The Sprint 2 gate at :mod:`app.core.connector_gate` was a *building
block* — a verdict-only function. This module is the **call-site
wrapper** that future connector code should use to actually run an
action with the gate enforced.

Sprint 3 deliverable: the wrapper exists, is tested, and is **not**
yet wired into any production hot path. The reasons:

- There is no OnlyMonster / OnlyFans connector code on this branch (it
  lives on ``feat/of-intelligence``). Wiring there is part of that
  work, not Sprint 3.
- The closest existing integration on this branch is the gateway
  template-sync flow (`/api/v1/gateways/{id}/templates/sync`). That is
  a hot production path; gating it without an opt-in would risk
  breaking active gateway operations.

So this sprint provides the wrapper, the tests, and a documented
opt-in seam. Sprint 4 will wire it into the OnlyMonster sync as the
first production proof, before any direct OF connector exists.

Usage::

    from app.services.connector_run import run_with_gate

    async def my_sync_action():
        return await of_client.read_only_pull(...)

    result = await run_with_gate(
        session,
        connector_type="onlymonster",
        requested_action="creator_sync",
        organization_id=org_id,
        creator_id=creator_id,
        actor_user_id=auth.user.id,
        actor_email=auth.user.email,
        run_callable=my_sync_action,
    )
    if not result.allowed:
        # The audit row is already written. Caller decides UX.
        raise HTTPException(409, f"connector blocked: {result.reason}")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.connector_gate import (
    GateVerdict,
    is_connector_action_allowed,
)
from app.services.audit_log import record_audit_event

T = TypeVar("T")


@dataclass(frozen=True)
class GatedRunResult(Generic[T]):
    """Outcome of a gated run: either the verdict-blocked path or the success path."""

    allowed: bool
    verdict: GateVerdict
    value: T | None = None


async def run_with_gate(
    session: AsyncSession,
    *,
    connector_type: str,
    requested_action: str,
    organization_id: UUID | None = None,
    creator_id: str | None = None,
    actor_user_id: UUID | None = None,
    actor_email: str | None = None,
    run_callable: Callable[[], Awaitable[T]] | None = None,
) -> GatedRunResult[T]:
    """Check the connector gate; if allowed, run ``run_callable`` and return its
    result. If not allowed, write a ``connector.run.blocked`` audit row and
    return without running.

    Either way the caller gets a ``GatedRunResult`` so the same call
    site can produce a uniform UX (e.g. an HTTP 409 with the verdict
    reason, or a successful response with the wrapped result).

    The audit row for the *block* path is written here. Audit rows for
    the *success* path are the caller's responsibility — typically the
    connector itself will record a richer ``connector.run.finish``
    event with whatever metrics it gathered.
    """
    verdict = await is_connector_action_allowed(
        session,
        connector_type=connector_type,
        requested_action=requested_action,
        organization_id=organization_id,
        creator_id=creator_id,
    )

    if not verdict.allowed:
        await record_audit_event(
            session,
            event_type="connector.run.blocked",
            category="connector",
            action="run",
            result="blocked",
            severity="high",
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            organization_id=organization_id,
            creator_id=creator_id,
            resource_type="connector_run",
            resource_id=f"{connector_type}:{requested_action}",
            metadata={
                "connector_type": connector_type,
                "requested_action": requested_action,
                "verdict_reason": verdict.reason,
                "verdict_detail": verdict.detail,
            },
        )
        await session.commit()
        return GatedRunResult(allowed=False, verdict=verdict, value=None)

    if run_callable is None:
        # The caller wanted only the verdict; no actual run requested.
        return GatedRunResult(allowed=True, verdict=verdict, value=None)

    value = await run_callable()
    return GatedRunResult(allowed=True, verdict=verdict, value=value)
