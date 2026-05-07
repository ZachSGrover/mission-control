"""Mission Control audit event model — security-grade record of sensitive actions.

Distinct from ``ActivityEvent``:
  • ``ActivityEvent`` is a board/task/agent activity feed surfaced to
    operators in the product (boards, mentions, approvals).  It never
    needed structured actor + outcome fields.
  • ``AuditEvent`` is an append-only record of *who did what* on
    privileged surfaces — role changes, allowlist mutations, integration
    credential writes, kill-switch flips, bot start/stop,
    creator-credential vault operations, connector approvals, consent
    changes, etc.

Two complementary audit-write paths share this single row shape (see
``app.services.audit_log``):

  • PR #21's ``record_audit`` populates the narrow columns
    (``actor_clerk_user_id``, ``action``, ``target_type``, ``target_id``,
    ``outcome``, ``safe_summary``, ``payload_hash``).
  • Major Security's ``record_audit_event`` ALSO populates the wider
    structured columns (``actor_user_id`` UUID, ``organization_id``,
    ``creator_id``, ``event_type``, ``category``, ``result``,
    ``severity``, ``resource_type``, ``resource_id``, ``request_id``,
    ``metadata_json``, ``redacted``).

All wider columns are nullable so PR #21's writes continue to work
unchanged. The vocabularies pinned by ``AUDIT_CATEGORIES`` /
``AUDIT_RESULTS`` / ``AUDIT_SEVERITIES`` are validated at the service
boundary in ``record_audit_event``; this module only stores strings.

Privacy guarantees:
  • Raw payloads are NEVER stored.  Callers must hash payloads with the
    helper in ``app.services.audit_log``; only the hex digest is
    persisted.
  • ``metadata_json`` is forced through
    :func:`app.core.redact.redact_metadata` before storage.  If any
    forbidden key was scrubbed, ``redacted`` is set to ``True``.
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

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.core.time import utcnow

# ── Vocabularies ────────────────────────────────────────────────────────────
# Stored as plain strings for forward-compatibility; validated at the
# service boundary in ``record_audit_event``.

AUDIT_CATEGORIES: frozenset[str] = frozenset(
    {
        "auth",
        "credential",
        "role",
        "permission",
        "export",
        "connector",
        "llm",
        "creator_data",
        "fan_data",
        "system",
        "security",
        "integration",
    }
)

AUDIT_RESULTS: frozenset[str] = frozenset(
    {
        "success",
        "denied",
        "failed",
        "blocked",
        "skipped",
    }
)

AUDIT_SEVERITIES: frozenset[str] = frozenset(
    {
        "info",
        "warning",
        "high",
        "critical",
    }
)


class AuditEvent(SQLModel, table=True):
    """One privileged-surface action by one actor.

    Append-only.  No update endpoint, no delete endpoint.
    """

    __tablename__ = "audit_events"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # ── PR #21 narrow actor identity ──
    # ``actor_clerk_user_id`` may be ``"local"`` for local-auth deployments
    # or ``"system"`` for actions taken by background jobs (e.g. supervisor
    # ticks that auto-disable a bot).  Major-Security writes set this to
    # ``"system"`` and supply the structured ``actor_user_id`` UUID below.
    actor_clerk_user_id: str = Field(index=True, max_length=255)
    actor_email: str | None = Field(default=None, max_length=320)
    actor_role: str | None = Field(default=None, max_length=32)

    # ── Major Security wider actor / scope (all nullable) ──
    actor_user_id: UUID | None = Field(default=None, index=True)
    organization_id: UUID | None = Field(default=None, index=True)
    creator_id: str | None = Field(default=None, index=True)

    # ── Action / event ──
    # ``action`` is free-form short identifier (lowercase dotted), e.g.
    # ``role.set``, ``allowlist.add``, ``integration.write``,
    # ``bot.start``, ``kill_switch.flip``.
    action: str = Field(index=True, max_length=64)

    # Major Security adds an explicit ``event_type`` (often the same
    # string as ``action`` but not constrained to PR #21's
    # ``target_type``-driven shape) plus a ``category`` taxonomy.
    event_type: str | None = Field(default=None, index=True, max_length=64)
    category: str | None = Field(default=None, index=True, max_length=32)

    # ── Resource — what was acted upon (PR #21 + Major Security) ──
    target_type: str | None = Field(default=None, index=True, max_length=64)
    target_id: str | None = Field(default=None, index=True, max_length=255)
    resource_type: str | None = Field(default=None, index=True, max_length=64)
    resource_id: str | None = Field(default=None, max_length=255)

    # ── Outcome / result / severity ──
    outcome: str = Field(default="success", index=True, max_length=32)
    result: str | None = Field(default=None, index=True, max_length=32)
    severity: str | None = Field(default=None, index=True, max_length=16)

    # ── Free-form / hashed payload ──
    safe_summary: str | None = Field(default=None, max_length=512)
    payload_hash: str | None = Field(default=None, max_length=64)

    # ── Request metadata (optional, non-sensitive) ──
    ip_address: str | None = Field(default=None, max_length=64)
    user_agent: str | None = Field(default=None, max_length=512)
    request_id: str | None = Field(default=None, max_length=64)

    # ── Major Security redacted metadata blob ──
    # JSON only — never raw secrets. ``redacted=True`` iff one or more
    # keys were scrubbed by ``redact_metadata`` before storage.
    metadata_json: dict[str, object] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=True),
    )
    redacted: bool | None = Field(default=None, index=True)

    # ── Timestamp ──
    created_at: datetime = Field(default_factory=utcnow, index=True)
