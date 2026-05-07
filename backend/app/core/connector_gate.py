"""Connector action gate.

The single chokepoint a future connector must call before taking any
real-world action. It composes the four prevention controls added in
Sprint 2 (kill switch, approval, consent, vault availability) and
returns a typed verdict.

Designed to **fail closed** in every dimension: if any required check
cannot be made (e.g. unknown connector type), the verdict is "blocked"
with a reason. The caller never has to remember "did I check X?";
calling :func:`is_connector_action_allowed` is the contract.

This module is intentionally framework-light. It takes a session and
plain values; it has no Depends, no FastAPI, no router. That keeps it
testable in isolation and reusable from anywhere — RQ workers, CLI
scripts, future connectors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.secrets_store import is_dedicated_encryption_key_configured
from app.models.connector_approvals import CONNECTOR_TYPES
from app.services import connector_approvals as approvals_svc
from app.services import consent as consent_svc
from app.services import kill_switch as kill_switch_svc

# Map (connector_type, requested_action) → required consent type, when one
# is required at all. Anything not listed here does not require consent
# (e.g. ``onlymonster`` global sync, internal cron). Future connectors
# can extend this table.
CONSENT_REQUIREMENTS: dict[tuple[str, str], str] = {
    ("onlyfans_direct", "read"): "onlyfans_direct_read",
    ("onlyfans_direct", "write"): "onlyfans_direct_write",
    ("onlyfans_direct", "sync"): "onlyfans_direct_read",
    ("onlymonster", "creator_sync"): "onlymonster_sync",
}

# Connectors whose actions need a creator-scoped credential vault entry
# to even be attemptable. Keeps the gate honest about the path's full
# preconditions.
VAULT_REQUIREMENTS: frozenset[str] = frozenset(
    {"onlyfans_direct"},
)

VerdictReason = Literal[
    "ok",
    "unknown_connector",
    "kill_switch_global",
    "kill_switch_connector",
    "kill_switch_organization",
    "kill_switch_creator",
    "no_approval",
    "approval_expired",
    "approval_revoked",
    "no_consent",
    "vault_unavailable",
]


@dataclass(frozen=True)
class GateVerdict:
    """Composite verdict from the gate."""

    allowed: bool
    reason: VerdictReason
    detail: str | None = None


async def is_connector_action_allowed(
    session: AsyncSession,
    *,
    connector_type: str,
    requested_action: str,
    organization_id: UUID | None = None,
    creator_id: str | None = None,
) -> GateVerdict:
    """Composite check. Fail-closed: any failure produces ``allowed=False``.

    Order matters — kill switches first (broadest blast radius), then
    approval, then consent, then vault availability. The first failure
    short-circuits, so the verdict's ``reason`` always points at the
    *nearest* gating cause for the caller to fix.
    """
    if connector_type not in CONNECTOR_TYPES:
        return GateVerdict(False, "unknown_connector", connector_type)

    # 1. Kill switches.
    blocked = await kill_switch_svc.check_action_allowed(
        session,
        connector_type=connector_type,
        organization_id=organization_id,
        creator_id=creator_id,
    )
    if blocked is not None:
        scope, scope_id = blocked
        reason: VerdictReason = (
            "kill_switch_global"
            if scope == "global"
            else (
                "kill_switch_connector"
                if scope == "connector"
                else (
                    "kill_switch_organization" if scope == "organization" else "kill_switch_creator"
                )
            )
        )
        return GateVerdict(False, reason, scope_id)

    # 2. Approval.
    approval = await approvals_svc.is_approved(
        session,
        connector_type=connector_type,
        requested_action=requested_action,
        organization_id=organization_id,
        creator_id=creator_id,
    )
    if approval is None:
        return GateVerdict(False, "no_approval", f"{connector_type}:{requested_action}")

    # 3. Consent (only when required for this action).
    consent_type = CONSENT_REQUIREMENTS.get((connector_type, requested_action))
    if consent_type is not None:
        live = await consent_svc.is_granted(
            session,
            consent_type=consent_type,
            organization_id=organization_id,
            creator_id=creator_id,
        )
        if live is None:
            return GateVerdict(False, "no_consent", consent_type)

    # 4. Vault availability for high-sensitivity connectors.
    if connector_type in VAULT_REQUIREMENTS:
        if not is_dedicated_encryption_key_configured():
            return GateVerdict(False, "vault_unavailable", "SETTINGS_ENCRYPTION_KEY")

    return GateVerdict(True, "ok", None)
