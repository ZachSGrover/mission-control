"""OnlyMonster gated production proof.

Sprint 8A: the **production-proof entrypoint** for the OnlyMonster
read path. It wraps the Sprint 6 seam
(:func:`app.services.onlymonster_integration.fetch_creator_snapshot`)
with operator-friendly safety:

- Resolves the real-or-fake OnlyMonster client via
  :func:`app.services.onlymonster_fake_client.resolve_onlymonster_client`.
  In production, the fake is refused unless the operator has
  explicitly set ``MC_ONLYMONSTER_ALLOW_FAKE_CLIENT=1``.
- Returns a typed :class:`GatedProofResult` carrying the safe
  metadata the security admin UI needs to render the outcome:
  allowed, reason, connector type, action, audit event id, row
  counts, error category. **No fan PII, no message bodies, no
  revenue breakdowns.** The seam already enforces
  ``rows_written = 0``; this layer enforces the same on its own
  output.
- Audits a "gated proof" event in addition to the seam's own
  audits, so a forensic reviewer can see the operator's intent
  separately from the seam's mechanical record.

This module is intentionally narrow: one function, one shape. It
is the surface a future Sprint 8C+ will wrap into a recurring sync
job — but only after a real client is wired and a sandbox creator
has run cleanly.

What this module does NOT do:

- It does not perform writes.
- It does not run unless the env flag, the gate, AND the production
  guard all approve.
- It does not log fixture or fan data.
- It does not bypass the connector gate. Every block reason
  surfaces from the seam → wrapper → here unmodified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.services.audit_log import record_audit
from app.services.onlymonster_fake_client import (
    FakeClientRefusedInProductionError,
    OnlyMonsterReadOnlyClient,
    resolve_onlymonster_client,
)
from app.services.onlymonster_integration import fetch_creator_snapshot

logger = get_logger(__name__)


CONNECTOR_TYPE: Final[str] = "onlymonster"
REQUESTED_ACTION: Final[str] = "creator_sync"


@dataclass(frozen=True)
class GatedProofResult:
    """Outcome of a single gated OnlyMonster proof run.

    All fields are safe to surface in audit rows and admin UI.
    There is no ``payload`` / ``data`` / ``raw`` field — the seam
    discards row-level content and only carries the safe
    aggregates.
    """

    allowed: bool
    connector_type: str
    requested_action: str
    creator_id: str | None
    organization_id: str | None
    rows_read: int
    rows_written: int  # always 0; invariant
    last_event_at_iso: str | None
    audit_event_id: str | None
    error_category: (
        str | None
    )  # None on allowed; e.g. "no_approval", "no_consent", "kill_switch_global", "fake_refused_in_production"
    notes: str
    used_fake_client: bool


async def run_onlymonster_gated_proof(
    session: AsyncSession,
    *,
    creator_id: str,
    organization_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    actor_email: str | None = None,
    real_client: OnlyMonsterReadOnlyClient | None = None,
    fake_client: OnlyMonsterReadOnlyClient | None = None,
) -> GatedProofResult:
    """Run one gated OnlyMonster read against the configured client.

    Resolution order:

    1. Production guard. If running in production and only a fake
       client is available, the fake-allow flag must be set or the
       call is refused with an audited "blocked" result.
    2. Seam. Calls
       :func:`app.services.onlymonster_integration.fetch_creator_snapshot`,
       which itself routes through Sprint 5's gated wrapper
       (env-flag + connector gate). The seam writes
       ``connector.run.blocked`` on block and
       ``connector.run.finish`` on allow.
    3. Outcome. This wrapper records a single
       ``connector.gated_proof.{success|blocked}`` event so the
       operator's intent (a deliberate proof run) is visible
       separately from the seam's mechanical record. Both rows
       carry the same ``creator_id`` / ``organization_id`` so a
       forensic reviewer can join them.

    The function never raises for ordinary block reasons; it
    returns a :class:`GatedProofResult` with ``allowed=False`` and a
    populated ``error_category``. It DOES raise for
    fake-refused-in-production *if no real client was passed* — the
    caller would be at fault for asking for a production proof
    against the fake.
    """
    used_fake = real_client is None and fake_client is not None
    try:
        client = resolve_onlymonster_client(real_client=real_client, fake_client=fake_client)
    except FakeClientRefusedInProductionError:
        # Audit the refusal so a forensic reviewer can see it; then
        # re-raise. This is a structural error, not a normal block.
        await record_audit(
            session,
            event_type="connector.gated_proof.blocked",
            category="connector",
            action=REQUESTED_ACTION,
            result="blocked",
            severity="warning",
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            organization_id=organization_id,
            creator_id=creator_id,
            resource_type="connector_run",
            resource_id=f"{CONNECTOR_TYPE}:{REQUESTED_ACTION}",
            metadata={
                "connector_type": CONNECTOR_TYPE,
                "requested_action": REQUESTED_ACTION,
                "error_category": "fake_refused_in_production",
                "used_fake_client": True,
            },
        )
        await session.commit()
        raise

    snapshot = await fetch_creator_snapshot(
        session,
        creator_id=creator_id,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        fake_client=client,
    )

    if snapshot is None:
        # Seam returned blocked. The seam's gated wrapper has already
        # written ``connector.run.blocked``; we add a proof-level row
        # so the operator's intent is visible too.
        proof_row = await record_audit(
            session,
            event_type="connector.gated_proof.blocked",
            category="connector",
            action=REQUESTED_ACTION,
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
                "error_category": "gate_blocked_or_disabled",
                "used_fake_client": used_fake,
            },
        )
        await session.commit()
        return GatedProofResult(
            allowed=False,
            connector_type=CONNECTOR_TYPE,
            requested_action=REQUESTED_ACTION,
            creator_id=creator_id,
            organization_id=str(organization_id) if organization_id else None,
            rows_read=0,
            rows_written=0,
            last_event_at_iso=None,
            audit_event_id=str(proof_row.id) if proof_row is not None else None,
            error_category="gate_blocked_or_disabled",
            notes=(
                "Gate blocked the run. Inspect the matching "
                "connector.run.blocked audit row for the seam's "
                "verdict_reason / verdict_detail."
            ),
            used_fake_client=used_fake,
        )

    # Allowed path. The seam already audited connector.run.finish.
    # We record a gated_proof.success row so the operator's intent
    # is visible. ``rows_written`` MUST be 0 by the seam's invariant.
    if snapshot.rows_written != 0:
        # Defensive — should be impossible. If we ever see this,
        # fail loudly rather than silently emit an audit that says
        # "rows_written=N" with N != 0.
        raise RuntimeError(
            "OnlyMonster seam returned rows_written != 0; this is a "
            "read-only path and should never happen. Refusing to audit."
        )

    proof_row = await record_audit(
        session,
        event_type="connector.gated_proof.success",
        category="connector",
        action=REQUESTED_ACTION,
        result="success",
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
            "rows_read": snapshot.rows_read,
            "rows_written": snapshot.rows_written,
            "last_event_at_iso": snapshot.last_event_at_iso,
            "used_fake_client": used_fake,
        },
    )
    await session.commit()
    return GatedProofResult(
        allowed=True,
        connector_type=CONNECTOR_TYPE,
        requested_action=REQUESTED_ACTION,
        creator_id=creator_id,
        organization_id=str(organization_id) if organization_id else None,
        rows_read=snapshot.rows_read,
        rows_written=snapshot.rows_written,
        last_event_at_iso=snapshot.last_event_at_iso,
        audit_event_id=str(proof_row.id) if proof_row is not None else None,
        error_category=None,
        notes=(
            "Gated proof passed. The fake client was used; replace with "
            "the real OnlyMonsterClient before any production sync."
            if used_fake
            else "Gated proof passed against the real OnlyMonster client."
        ),
        used_fake_client=used_fake,
    )
