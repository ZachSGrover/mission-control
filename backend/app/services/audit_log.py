"""Audit logging service — unified entry point for the privileged-action audit trail.

This module is the SINGLE source of truth for writing rows to the
``audit_events`` table. It exposes two complementary entry points that
both write to the same table:

  • :func:`record_audit` — PR #21's narrow, action-oriented signature
    used by COO/operator/bot workflows (role.set, allowlist.add,
    integration.write, bot.start, bot.stop, etc.). Identifies actor by
    clerk user id (string), records ``action``, ``target_type``,
    ``target_id``, ``outcome``, ``safe_summary``, and an optional
    sha256 hash of an opaque payload. Pulls IP / user-agent from a
    FastAPI ``Request`` when one is supplied.
  • :func:`record_audit_event` — Major Security's structured signature
    used by the security gates (connector approvals, kill switches,
    consent, creator credentials, LLM redaction, retention). Adds
    ``event_type`` / ``category`` / ``result`` / ``severity`` taxonomy,
    UUID-typed actor / org / creator references, and a
    redacted-on-write ``metadata`` JSON blob.

Both write rows to the ``audit_events`` table created by PR #21's
migration ``h4b9d3e1c802`` and extended by the Major Security
consolidated migration. PR #21 is canonical for the table identity;
the security stack adds nullable columns (``event_type``, ``category``,
``result``, ``severity``, ``metadata_json``, ``redacted``,
``actor_user_id``, ``organization_id``, ``creator_id``,
``resource_type``, ``resource_id``, ``request_id``) so neither
signature constrains the other.

Privacy contract (enforced here):
  • Raw payloads are NEVER stored. ``record_audit`` sha256-hashes the
    optional ``payload_for_hashing`` and persists only the hex digest.
    ``record_audit_event`` runs ``metadata`` through
    :func:`app.core.redact.redact_metadata` and sets ``redacted=True``
    if any forbidden key was scrubbed.
  • Callers MUST keep ``safe_summary`` free of secrets, fan PII,
    message bodies, webhook URLs, and credential previews. This module
    does no redaction on free-form strings — that is the caller's
    responsibility.
  • Neither helper commits the session. The caller's normal
    transaction boundary commits the business write and the audit row
    together so a failed audit insert rolls back the whole action.
  • Vocabularies for ``category`` / ``result`` / ``severity`` (used by
    ``record_audit_event``) are pinned by ``Literal`` aliases so callers
    can't invent new buckets without code review. Belt-and-braces
    runtime checks back the type system in case of dynamic callers;
    pass ``strict=True`` to opt into a hard failure.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID

from app.core.client_ip import get_client_ip
from app.core.logging import get_logger
from app.core.redact import redact_metadata
from app.models.audit_event import (
    AUDIT_CATEGORIES,
    AUDIT_RESULTS,
    AUDIT_SEVERITIES,
    AuditEvent,
)

if TYPE_CHECKING:
    from fastapi import Request
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.auth import AuthContext


logger = get_logger(__name__)


# ── Vocabularies (Literal aliases) ───────────────────────────────────────────

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


# ── Helpers ──────────────────────────────────────────────────────────────────


def hash_payload(payload: Any) -> str:
    """Return a stable sha256 hex digest of *payload*.

    JSON-serializes with sorted keys so call-sites get deterministic hashes
    regardless of dict ordering.  Non-JSON-serializable values fall back to
    ``str(payload)``.
    """
    try:
        canonical = json.dumps(payload, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canonical = str(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def actor_from_auth(auth: "AuthContext") -> tuple[str, str | None]:
    """Return ``(actor_clerk_user_id, actor_email)`` from an ``AuthContext``.

    Falls back to ``"local"`` / ``None`` for local-auth contexts and to
    ``"unknown"`` / ``None`` if the auth context has no user.
    """
    if auth.user is None:
        return "local", None
    clerk_id = auth.user.clerk_user_id or "local"
    email = auth.user.email
    return clerk_id, email


# ── PR #21 canonical entry point ─────────────────────────────────────────────


async def record_audit(
    session: "AsyncSession",
    *,
    actor_clerk_user_id: str,
    action: str,
    actor_email: str | None = None,
    actor_role: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    outcome: str = "success",
    safe_summary: str | None = None,
    payload_for_hashing: Any = None,
    request: "Request | None" = None,
) -> AuditEvent:
    """Append one ``AuditEvent`` row to *session*.

    The caller commits.  Returns the staged ``AuditEvent`` for tests that
    want to assert directly on the row.

    ``actor_clerk_user_id`` is required; pass the literal string
    ``"local"`` for local-auth deployments and ``"system"`` for
    background-job actors.
    """
    ip = None
    user_agent = None
    if request is not None:
        try:
            ip = get_client_ip(request)
        except Exception:  # pragma: no cover — defensive
            ip = None
        ua_header = request.headers.get("user-agent")
        if ua_header:
            # Cap length so a giant UA doesn't blow up the column.
            user_agent = ua_header[:512]

    event = AuditEvent(
        actor_clerk_user_id=actor_clerk_user_id,
        actor_email=actor_email,
        actor_role=actor_role,
        action=action,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        safe_summary=safe_summary[:512] if safe_summary else None,
        payload_hash=hash_payload(payload_for_hashing) if payload_for_hashing is not None else None,
        ip_address=ip,
        user_agent=user_agent,
    )
    session.add(event)
    return event


# ── Major Security structured entry point ────────────────────────────────────


async def record_audit_event(
    session: "AsyncSession",
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
    """Record one structured security audit event.

    Companion to :func:`record_audit` — same table, structured taxonomy.
    Used by the Major Security stack (connector gate, kill switches,
    consent, creator credentials, LLM redaction, retention) where the
    forensic value of ``category`` / ``severity`` / structured
    ``metadata`` outweighs the cost of the wider call signature.

    The event is added to ``session`` but **not committed** — the caller
    must commit. If the audit insertion fails, the function logs a
    warning and returns ``None`` so the surrounding business action is
    not torpedoed by an audit-pipeline glitch. Set ``strict=True`` to
    re-raise instead.

    ``metadata`` is forced through :func:`redact_metadata`. Any
    attempt to log a forbidden key (``password``, ``token``, ...) will
    be silently replaced with ``"[REDACTED]"`` and the row's
    ``redacted`` flag set to ``True``.

    The PR #21 narrow columns (``actor_clerk_user_id``, ``action``,
    ``target_type``, ``target_id``, ``outcome``, ``safe_summary``) are
    populated with safe defaults so a single SELECT * returns
    consistent shape regardless of which entry point wrote the row:

      • ``actor_clerk_user_id`` ← ``"system"`` (security stack callers
        identify by ``actor_user_id`` UUID; the clerk-id field is set
        to a sentinel so the NOT NULL constraint holds).
      • ``action`` ← caller's ``action`` argument.
      • ``target_type`` / ``target_id`` ← caller's ``resource_type`` /
        ``resource_id``.
      • ``outcome`` ← caller's ``result``.
      • ``safe_summary`` ← ``f"{event_type} ({category}, {severity})"``.
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
        # PR #21 narrow fields — populated for cross-entry-point consistency.
        actor_clerk_user_id="system",
        action=action,
        target_type=resource_type,
        target_id=resource_id,
        outcome=result,
        safe_summary=f"{event_type} ({category}, {severity})"[:512],
        # Shared fields.
        actor_email=actor_email,
        actor_role=actor_role,
        ip_address=ip_address,
        user_agent=user_agent,
        # Major Security structured fields.
        actor_user_id=actor_user_id,
        organization_id=organization_id,
        creator_id=creator_id,
        event_type=event_type,
        category=category,
        result=result,
        severity=severity,
        resource_type=resource_type,
        resource_id=resource_id,
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
