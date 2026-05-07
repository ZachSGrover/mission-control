"""Gated OnlyMonster sync wrapper.

**This is a documented scaffold, not a connector.** OnlyMonster client
code lives on the ``feat/of-intelligence`` branch and is intentionally
not present on this security branch. What this module gives us is the
exact pattern future OnlyMonster code must follow when it lands here.

Two contracts:

1. :func:`gated_onlymonster_creator_sync` is the seam. Every real
   OnlyMonster ``creator_sync`` call MUST go through it. The function
   refuses to run any callable until **all** of:

   - ``MC_ONLYMONSTER_GATED_SYNC_ENABLED=1`` is set in the env.
   - The connector gate (kill switches, approval, consent, vault) returns
     ``allowed=True`` for ``(connector_type="onlymonster",
     requested_action="creator_sync", organization_id, creator_id)``.

   Both checks are independent. The env flag is the operator's "this code
   is wired up to a real client" opt-in; the gate is the
   approval-/consent-/kill-switch enforcement. Either failing returns a
   safe blocked verdict and audits.

2. The wrapper itself is **read-only**. It cannot perform a write,
   because it never has a write callable. The connector gate would also
   block any ``write`` action — but the wrapper hard-codes
   ``requested_action="creator_sync"`` so the call site can't accidentally
   request a write through this seam.

When the OFI branch merges and the OnlyMonster client appears under
``app.integrations.onlymonster``, the integration code should call this
function with a closure that performs the real read. Until then, every
call returns the blocked verdict and writes a ``connector.run.blocked``
audit row at category ``connector``.
"""

from __future__ import annotations

import os
from typing import Awaitable, Callable, TypeVar
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.connector_run import GatedRunResult, run_with_gate

T = TypeVar("T")

ENV_ENABLED = "MC_ONLYMONSTER_GATED_SYNC_ENABLED"
CONNECTOR_TYPE = "onlymonster"
REQUESTED_ACTION = "creator_sync"


def is_enabled() -> bool:
    """True iff the operator explicitly opted into running the wrapper."""
    return os.environ.get(ENV_ENABLED, "0").strip() == "1"


async def gated_onlymonster_creator_sync(
    session: AsyncSession,
    *,
    organization_id: UUID | None,
    creator_id: str,
    actor_user_id: UUID | None = None,
    actor_email: str | None = None,
    sync_callable: Callable[[], Awaitable[T]] | None = None,
) -> GatedRunResult[T]:
    """Run a gated OnlyMonster ``creator_sync`` action.

    Returns a :class:`GatedRunResult` mirroring
    :func:`app.services.connector_run.run_with_gate`. If the env flag
    is unset, returns a synthetic blocked verdict so callers always see
    the same shape regardless of why the action was refused.

    The sync callable is **never** invoked unless:

    - the env flag is set, AND
    - the connector gate returned allowed=True.

    On block, ``connector.run.blocked`` is recorded by ``run_with_gate``.
    On success, the wrapper does not record a finish event; the
    OnlyMonster client (when wired) is responsible for ``connector.run.finish``
    with whatever metrics it gathered.
    """
    if not is_enabled():
        # Mirror the gate's verdict shape so the caller can branch
        # uniformly on ``result.allowed``.
        from app.core.connector_gate import GateVerdict
        from app.services.audit_log import record_audit_event

        await record_audit_event(
            session,
            event_type="connector.run.blocked",
            category="connector",
            action="run",
            result="blocked",
            severity="info",
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            organization_id=organization_id,
            creator_id=creator_id,
            resource_type="connector_run",
            resource_id=f"{CONNECTOR_TYPE}:{REQUESTED_ACTION}",
            metadata={
                "connector_type": CONNECTOR_TYPE,
                "requested_action": REQUESTED_ACTION,
                "verdict_reason": "scaffold_disabled",
                "verdict_detail": (
                    f"set {ENV_ENABLED}=1 only after wiring a real OnlyMonster "
                    "read-only client behind this seam"
                ),
            },
        )
        await session.commit()
        return GatedRunResult(
            allowed=False,
            verdict=GateVerdict(False, "no_approval", "scaffold_disabled"),
            value=None,
        )

    return await run_with_gate(
        session,
        connector_type=CONNECTOR_TYPE,
        requested_action=REQUESTED_ACTION,
        organization_id=organization_id,
        creator_id=creator_id,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        run_callable=sync_callable,
    )
