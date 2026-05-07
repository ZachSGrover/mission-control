"""OnlyMonster integration seam — Sprint 6.

Sprint 5 added :func:`app.services.gated_onlymonster_sync.gated_onlymonster_creator_sync`,
which wraps the connector gate around an arbitrary callable. Sprint 6
adds the **integration seam**: the typed adapter that the future real
OnlyMonster client (currently on the ``feat/of-intelligence`` branch)
must call.

Why a dedicated module instead of "just call the wrapper":

- The brief explicitly asked for an unmissable seam so post-merge
  integration is mechanical, not interpretive.
- It lets us document the contract (read-only, no writes, audit on
  block, audit on success) in one place that's easy to find.
- It lets us test the seam against a fake client *now*, so a Sprint 6
  reviewer can verify the gate flows end-to-end without an OnlyMonster
  account, network, or credentials.

When the OFI branch merges, the operator should:

1. Replace :data:`_FAKE_CLIENT_PATH` with the real import path.
2. Implement :func:`fetch_creator_snapshot` to call that real client
   with the resolved credential — **read-only**.
3. Run the existing tests in
   ``backend/tests/test_security_readiness.py`` to confirm the gate
   still blocks every disallowed path.
4. Run a single sandboxed read against a test account behind
   ``MC_ONLYMONSTER_GATED_SYNC_ENABLED=1``.

Until then, every call returns a blocked verdict and writes
``connector.run.blocked`` audit rows so an operator monitoring the
trail sees the gate is alive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.services.audit_log import record_audit_event
from app.services.gated_onlymonster_sync import (
    gated_onlymonster_creator_sync,
)

logger = get_logger(__name__)


# Used by the test suite to demonstrate the seam without a real client.
# Replace with the real OnlyMonster client import path (e.g.
# ``app.integrations.onlymonster.client.OnlyMonsterClient``) when the
# OFI branch merges.
_FAKE_CLIENT_PATH = "app.integrations.onlymonster.client (not yet present)"


@dataclass(frozen=True)
class CreatorSnapshot:
    """Read-only snapshot returned by a successful OnlyMonster fetch.

    Sprint 6 includes only the fields that are obviously safe to surface
    to the security audit metadata:
    - ``rows_read`` — count of items fetched.
    - ``last_event_at_iso`` — most-recent activity timestamp.
    - ``rows_written`` — **always 0**. The seam is read-only by design.

    The real OnlyMonster client (when wired) should never include
    fan PII, message bodies, or revenue breakdowns in this object —
    those go into the OFI-specific stores via the OFI sync code, not
    via this audit-bearing seam.
    """

    rows_read: int
    last_event_at_iso: str | None
    rows_written: int = 0  # MUST stay 0


async def fetch_creator_snapshot(
    session: AsyncSession,
    *,
    creator_id: str,
    organization_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    actor_email: str | None = None,
    fake_client: Any | None = None,
) -> CreatorSnapshot | None:
    """Fetch a read-only snapshot for ``creator_id`` through the gate.

    On block: returns ``None``. The block is audited by
    :func:`gated_onlymonster_creator_sync` (Sprint 5).

    On allow: invokes the configured client, audits a
    ``connector.run.finish`` event with the snapshot's safe fields,
    and returns the snapshot.

    ``fake_client`` is used by the Sprint 6 tests to demonstrate the
    seam without a real client. Production code should leave it as
    ``None`` and let the seam pick up the real client via the import
    path documented in :data:`_FAKE_CLIENT_PATH`.
    """

    async def _do_fetch() -> CreatorSnapshot:
        if fake_client is not None:
            # Test path — the fake client returns a deterministic snapshot.
            data = await fake_client.read_only_pull(creator_id=creator_id)
            return CreatorSnapshot(
                rows_read=int(data.get("rows_read", 0)),
                last_event_at_iso=data.get("last_event_at_iso"),
            )
        # No real client wired on this branch. The gate already blocks
        # before this function is reached (env flag default), so we only
        # get here in tests with a fake client. Refusing loudly catches
        # any future bug where the env flag is on but no real client
        # was wired.
        raise RuntimeError(
            "OnlyMonster real client is not wired in this branch. "
            f"Replace {_FAKE_CLIENT_PATH} with the real import path "
            "after the OFI branch merges."
        )

    result = await gated_onlymonster_creator_sync(
        session,
        organization_id=organization_id,
        creator_id=creator_id,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        sync_callable=_do_fetch,
    )
    if not result.allowed or result.value is None:
        # Block already audited by the gate wrapper; nothing more to do.
        return None

    # Allowed path — record the finish event with safe metadata only.
    snapshot = result.value
    await record_audit_event(
        session,
        event_type="connector.run.finish",
        category="connector",
        action="finish",
        result="success",
        severity="info",
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        organization_id=organization_id,
        creator_id=creator_id,
        resource_type="connector_run",
        resource_id=f"onlymonster:creator_sync:{creator_id}",
        metadata={
            "connector_type": "onlymonster",
            "requested_action": "creator_sync",
            "rows_read": snapshot.rows_read,
            "rows_written": snapshot.rows_written,
            "last_event_at_iso": snapshot.last_event_at_iso,
        },
    )
    await session.commit()
    return snapshot
