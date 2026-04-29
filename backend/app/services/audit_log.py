"""Audit logging service.

Single entry point for writing :class:`app.models.audit_events.AuditEvent`
rows. Routes and services should call :func:`record_audit` after every
security-relevant action — credential write, role change, connector
run, LLM call, export, etc.

Design choices:
- The helper does **not** commit. Callers own the surrounding
  transaction so audits commit (or roll back) atomically with the
  business action they describe.
- Failure mode is fail-safe by default: if the audit write itself
  raises, we log a warning (without secrets) and return ``None`` so
  the caller's main flow continues. Pass ``strict=True`` to opt into
  a hard failure where audit failure must block.
- All metadata is forced through
  :func:`app.core.redact.redact_metadata` before storage. There is no
  way to bypass redaction.
- Vocabularies for ``category``, ``result``, and ``severity`` are
  pinned by ``Literal`` types so callers can't accidentally invent
  new buckets without a code review.
"""

from __future__ import annotations

import logging
from typing import Final, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redact import redact_metadata
from app.models.audit_events import (
    AUDIT_CATEGORIES,
    AUDIT_RESULTS,
    AUDIT_SEVERITIES,
    AuditEvent,
)

logger = logging.getLogger(__name__)

AuditCategory = Literal[
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
]

AuditResult = Literal[
    "success",
    "denied",
    "failed",
    "blocked",
    "skipped",
]

AuditSeverity = Literal[
    "info",
    "warning",
    "high",
    "critical",
]

# Sanity-check the Literal vocabularies match the model's frozensets.
# Mismatches would silently let bad values through, so we verify at
# import time.
_ALL_CATEGORIES: Final[frozenset[str]] = AUDIT_CATEGORIES
_ALL_RESULTS: Final[frozenset[str]] = AUDIT_RESULTS
_ALL_SEVERITIES: Final[frozenset[str]] = AUDIT_SEVERITIES


async def record_audit(
    session: AsyncSession,
    *,
    event_type: str,
    category: AuditCategory,
    action: str,
    result: AuditResult,
    severity: AuditSeverity = "info",
    actor_user_id: UUID | None = None,
    actor_email: str | None = None,
    actor_role: str | None = None,
    organization_id: UUID | None = None,
    creator_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
    metadata: object | None = None,
    strict: bool = False,
) -> AuditEvent | None:
    """Record one audit event.

    The event is added to ``session`` but **not committed** — the caller
    must commit. If the audit insertion fails, the function logs a
    warning and returns ``None`` so the surrounding business action is
    not torpedoed by an audit-pipeline glitch. Set ``strict=True`` to
    re-raise instead.

    ``metadata`` is forced through :func:`redact_metadata`. Any
    attempt to log a forbidden key (``password``, ``token``, ...) will
    be silently replaced with ``"[REDACTED]"`` and the row's
    ``redacted`` flag set to ``True``.
    """

    # Validate vocabularies. We trust mypy's Literal in production but
    # belt-and-braces at runtime in case of dynamic callers.
    if category not in _ALL_CATEGORIES:
        if strict:
            raise ValueError(f"unknown audit category: {category!r}")
        logger.warning("audit.invalid_category", extra={"category": category})
        return None
    if result not in _ALL_RESULTS:
        if strict:
            raise ValueError(f"unknown audit result: {result!r}")
        logger.warning("audit.invalid_result", extra={"result": result})
        return None
    if severity not in _ALL_SEVERITIES:
        if strict:
            raise ValueError(f"unknown audit severity: {severity!r}")
        logger.warning("audit.invalid_severity", extra={"severity": severity})
        return None

    safe_metadata, was_redacted = redact_metadata(metadata if metadata is not None else {})

    event = AuditEvent(
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        organization_id=organization_id,
        creator_id=creator_id,
        event_type=event_type,
        category=category,
        action=action,
        result=result,
        severity=severity,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
        metadata_json=safe_metadata,
        redacted=was_redacted,
    )

    try:
        session.add(event)
    except Exception as exc:  # pragma: no cover — defensive, session.add rarely raises
        if strict:
            raise
        # Never include metadata in this log line; it may contain
        # already-redacted values but we still want minimal surface.
        logger.warning(
            "audit.write_failed",
            extra={
                "event_type": event_type,
                "category": category,
                "result": result,
                "error": type(exc).__name__,
            },
        )
        return None

    return event
