"""Mission Control audit event model — security-grade record of sensitive actions.

Distinct from ``ActivityEvent``:
  • ``ActivityEvent`` is a board/task/agent activity feed surfaced to
    operators in the product (boards, mentions, approvals).  It never
    needed structured actor + outcome fields.
  • ``AuditEvent`` is an append-only record of *who did what* on
    privileged surfaces — role changes, allowlist mutations, integration
    credential writes, kill-switch flips, bot start/stop, etc.

Privacy guarantees:
  • Raw payloads are NEVER stored.  Callers must hash payloads with the
    helper in ``app.services.audit_log``; only the hex digest is
    persisted.
  • Secrets, message bodies, fan PII, and webhook URLs must never reach
    this table.  ``safe_summary`` is a short human-readable string and
    is the caller's responsibility to keep clean.
  • ``ip_address`` and ``user_agent`` are optional.  If captured, they
    come from the FastAPI ``Request`` object via the existing client-IP
    helper — no third-party services involved.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class AuditEvent(SQLModel, table=True):
    """One privileged-surface action by one actor.

    Append-only.  No update endpoint, no delete endpoint.
    """

    __tablename__ = "audit_events"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # ── Actor ──
    # ``actor_clerk_user_id`` may be ``"local"`` for local-auth deployments
    # or ``"system"`` for actions taken by background jobs (e.g. supervisor
    # ticks that auto-disable a bot).
    actor_clerk_user_id: str = Field(index=True, max_length=255)
    actor_email: str | None = Field(default=None, max_length=320)
    actor_role: str | None = Field(default=None, max_length=32)

    # ── Action ──
    # Free-form short identifier, lowercase dotted format e.g.
    # ``role.set``, ``allowlist.add``, ``integration.write``,
    # ``bot.start``, ``bot.stop``, ``bot.permission.set``,
    # ``kill_switch.flip``.
    action: str = Field(index=True, max_length=64)
    target_type: str | None = Field(default=None, index=True, max_length=64)
    target_id: str | None = Field(default=None, index=True, max_length=255)

    # ── Outcome ──
    # ``success``, ``denied``, or ``error``.  Free-form to allow
    # extension; current call sites stick to those three.
    outcome: str = Field(default="success", index=True, max_length=32)
    safe_summary: str | None = Field(default=None, max_length=512)
    payload_hash: str | None = Field(default=None, max_length=64)

    # ── Request metadata (optional, non-sensitive) ──
    ip_address: str | None = Field(default=None, max_length=64)
    user_agent: str | None = Field(default=None, max_length=512)

    # ── Timestamp ──
    created_at: datetime = Field(default_factory=utcnow, index=True)
