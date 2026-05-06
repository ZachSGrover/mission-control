"""Clerk webhook receiver — login-success audit.

Sprint 4 deliverable. Records an ``auth.login.success`` audit event
when Clerk dispatches a ``session.created`` webhook. This is the
minimum-viable login audit hook that doesn't require touching
``get_auth_context`` (which would generate per-request noise).

**Disabled by default.** The endpoint refuses payloads unless
``CLERK_WEBHOOK_SECRET`` is set in the env. The signature
verification is a placeholder that compares a constant-time HMAC of
the configured secret against an ``X-Mission-Control-Webhook-Secret``
header — *not* the full Svix signature scheme Clerk uses in
production. Sprint 5 will replace this with the proper
``svix.Webhook(secret).verify(...)`` flow once the package is
approved as a dependency. Until then, the simple shared-secret check
is enough to keep the endpoint locked down on a private network.

Contracts:
- The webhook body is **not** logged. Only the event type, the user id,
  the email (if Clerk surfaces it), and the IP are stored.
- Tokens, cookies, and session ids are never recorded.
- Unknown event types are accepted with a ``skipped`` audit row so an
  operator can see "the webhook is alive but we don't audit this kind
  yet" rather than silent drops.
"""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.clerk_webhook_verify import (
    WebhookVerificationError,
    verify_webhook,
)
from app.core.logging import get_logger
from app.db.session import get_session
from app.services.audit_log import record_audit

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks/clerk", tags=["webhooks"])

SESSION_DEP = Depends(get_session)


class ClerkWebhookEnvelope(BaseModel):
    """Subset of the Clerk webhook envelope we actually use.

    Clerk sends much more than this; we only read the fields we need
    for the login audit. Any other key in the body is ignored.
    """

    type: str
    data: dict[str, Any] = {}


def _is_enabled() -> bool:
    return bool(os.environ.get("CLERK_WEBHOOK_SECRET", "").strip())


def _safe_ip(request: Request) -> str:
    return str(request.client.host) if request.client else "unknown"


@router.post("/", status_code=status.HTTP_204_NO_CONTENT)
async def receive_clerk_webhook(
    request: Request,
    body: ClerkWebhookEnvelope,
    session: AsyncSession = SESSION_DEP,
    x_mission_control_webhook_secret: str | None = Header(default=None),
) -> None:
    """Receive a Clerk webhook. Records a login audit on ``session.created``.

    Refuses every request unless ``CLERK_WEBHOOK_SECRET`` is set and the
    ``X-Mission-Control-Webhook-Secret`` header matches it.
    """
    if not _is_enabled():
        # Refuse loud — operator should know they pointed Clerk at an
        # endpoint that won't process anything.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Clerk webhook receiver is not configured. Set "
                "CLERK_WEBHOOK_SECRET in the backend env to enable."
            ),
        )

    # Sprint 5: verify via Svix when available; fall back to shared-secret
    # only when explicitly allowed (dev). Reconstruct the raw payload
    # bytes from the parsed body — Pydantic re-encoding is canonical
    # enough for HMAC purposes; for proper Svix verification the actual
    # raw request bytes are used via ``await request.body()`` below.
    raw_body = await request.body()
    if not raw_body:
        # FastAPI consumed it via the BaseModel. Re-encode from the parsed
        # envelope; Svix verifies the bytes that were signed, so this only
        # works if the producer signed JSON exactly the way Pydantic
        # serialises it. Operators using the Svix path should ensure their
        # proxy preserves request bodies; the shared-secret path doesn't
        # care.
        raw_body = json.dumps(body.model_dump(), sort_keys=True).encode()

    secret = os.environ.get("CLERK_WEBHOOK_SECRET", "").strip()
    try:
        verify_webhook(
            payload=raw_body,
            headers=dict(request.headers),
            secret=secret,
            shared_secret_header=x_mission_control_webhook_secret,
        )
    except WebhookVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    if body.type != "session.created":
        # Audit the skip so the operator can see the webhook is reaching us.
        await record_audit(
            session,
            event_type="auth.webhook.received",
            category="auth",
            action="webhook",
            result="skipped",
            severity="info",
            ip_address=_safe_ip(request),
            resource_type="clerk_webhook",
            resource_id=body.type,
            metadata={"event_type": body.type},
        )
        await session.commit()
        return None

    data = body.data or {}
    user_id = str(data.get("user_id") or data.get("user", {}).get("id") or "")
    email_addresses = data.get("user", {}).get("email_addresses") or []
    email = None
    if isinstance(email_addresses, list) and email_addresses:
        first = email_addresses[0]
        if isinstance(first, dict):
            email = first.get("email_address")

    await record_audit(
        session,
        event_type="auth.login.success",
        category="auth",
        action="login",
        result="success",
        severity="info",
        actor_email=email if isinstance(email, str) else None,
        ip_address=_safe_ip(request),
        user_agent=request.headers.get("user-agent", "")[:200] or None,
        resource_type="clerk_session",
        resource_id=user_id or None,
        metadata={
            "event_type": body.type,
            "clerk_user_id": user_id,
            # No tokens, no cookies, no session id.
        },
    )
    await session.commit()
    return None
