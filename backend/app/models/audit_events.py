"""Durable audit event row.

One row per security-relevant action. Insert-only by convention; never
update or delete. Used by ``app.services.audit_log.record_audit`` and
queried by future incident-response tooling.

Design notes:
- Mirrors :class:`app.models.activity_events.ActivityEvent` for column-
  level conventions (UUID PK via ``uuid4``, ``created_at`` via
  :func:`app.core.time.utcnow`, nullable foreign refs).
- ``actor_user_id`` is intentionally **not** a hard FK. Audit rows must
  outlive user deletions so investigations remain possible after a row
  is removed elsewhere.
- ``metadata_json`` holds redacted JSON only — never a credential, token,
  cookie, or secret. Producers must run input through
  :func:`app.core.redact.redact_metadata` before passing it here.
- ``redacted`` is True iff the original metadata contained one or more
  redacted keys. Useful for forensic searches like "show me every event
  that tried to log a credential".
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

# ── Vocabularies ────────────────────────────────────────────────────────────
# Stored as plain strings for forward-compatibility; validated at the
# service boundary in ``record_audit``.

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


class AuditEvent(QueryModel, table=True):
    """Durable audit event for security-relevant actions."""

    __tablename__ = "audit_events"

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Actor — soft references; preserved across user deletion.
    actor_user_id: UUID | None = Field(default=None, index=True)
    actor_email: str | None = Field(default=None, index=True)
    actor_role: str | None = Field(default=None)

    # Scope — also soft references.
    organization_id: UUID | None = Field(default=None, index=True)
    creator_id: str | None = Field(default=None, index=True)

    # Event taxonomy.
    event_type: str = Field(index=True)
    category: str = Field(index=True)
    action: str
    result: str = Field(index=True)
    severity: str = Field(default="info", index=True)

    # Resource — what was acted upon. Optional.
    resource_type: str | None = Field(default=None, index=True)
    resource_id: str | None = Field(default=None)

    # Request context — optional, populated when safely available.
    ip_address: str | None = Field(default=None)
    user_agent: str | None = Field(default=None)
    request_id: str | None = Field(default=None)

    # Redacted JSON metadata. Never raw secrets.
    metadata_json: dict[str, object] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    redacted: bool = Field(default=False, index=True)

    created_at: datetime = Field(default_factory=utcnow, index=True)
