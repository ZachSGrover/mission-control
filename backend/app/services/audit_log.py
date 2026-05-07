"""Audit log helper — records privileged actions to ``audit_events``.

Use this from any handler that mutates roles, allowlist, integration
credentials, kill switches, or bot state.

Privacy contract enforced here:
  • The caller MAY pass a ``payload`` for hashing only — we sha256 it and
    persist only the hex digest.  We never store the raw payload.
  • Callers MUST keep ``safe_summary`` free of secrets, fan PII, message
    bodies, webhook URLs, and credential previews.  This module does no
    redaction; it is the caller's responsibility to send safe text.
  • ``record_audit`` does not commit the session.  The caller's normal
    transaction boundary commits both the business write and the audit
    row together, so a failed audit insert rolls back the whole action.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from app.core.client_ip import get_client_ip
from app.models.audit_event import AuditEvent

if TYPE_CHECKING:
    from fastapi import Request
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.core.auth import AuthContext


# ── Public API ──────────────────────────────────────────────────────────────


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
