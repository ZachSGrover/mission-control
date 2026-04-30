"""Direct OnlyFans session-health: ``connector.session.challenged``
audit and notification stub.

Sprint 8B: scaffolding for the bot-detection / login-challenge /
suspicious-response signal a future Sprint 8C+ implementation will
emit. This module exposes:

- :func:`record_session_challenged` — the audit helper. Writes one
  ``connector.session.challenged`` row at severity ``warning`` with
  a fixed-vocabulary ``reason_category`` and a small set of
  scalar metadata fields. Refuses to log raw response bodies,
  cookies, session values, or any user-supplied content.
- :func:`notify_challenge_stub` — the notify stub. Returns one of
  ``"not_configured"`` / ``"skipped"`` and never sends anything in
  this sprint. A Sprint 8C+ wiring can replace the body with a
  Slack / Telegram / email send — but the audit row must still be
  the source of truth.

The reason vocabulary is small on purpose: a future operator
filtering audit rows by ``reason_category`` should see a finite
set of buckets, not free-form strings carrying details.
"""

from __future__ import annotations

import logging
from typing import Final, Literal
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.audit_log import record_audit

logger = logging.getLogger(__name__)


CONNECTOR_TYPE: Final[str] = "onlyfans_direct"


# Fixed vocabulary. Anything that doesn't fit one of these buckets
# should expand the set in code (and a test) — never as a free-form
# string in a metadata field.
ChallengeReason = Literal[
    "captcha",
    "login_required",
    "rate_limit_response",
    "unexpected_status",
    "unexpected_html",
    "session_expired",
    "session_revoked",
    "platform_block",
    "other",
]


# Fields a caller MUST NOT pass to ``record_session_challenged``.
# These are the keys most likely to leak platform response content
# into the audit pipeline. The function refuses any of them.
_FORBIDDEN_METADATA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "response_body",
        "raw_body",
        "html",
        "headers",
        "set_cookie",
        "cookie",
        "cookies",
        "session",
        "session_id",
        "session_token",
        "auth_token",
        "csrf",
        "csrf_token",
        "x-bc",
        "x_bc",
    }
)


class ChallengeMetadataContractViolation(RuntimeError):
    """Raised when a caller tries to log a forbidden field on a
    session-challenged event.
    """


async def record_session_challenged(
    session: AsyncSession,
    *,
    reason_category: ChallengeReason,
    creator_id: str | None = None,
    organization_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    actor_email: str | None = None,
    extra_metadata: dict[str, object] | None = None,
) -> str | None:
    """Write one ``connector.session.challenged`` audit row.

    The row is written at severity ``warning`` with category
    ``connector``. Metadata always includes:

    - ``connector_type`` (always ``"onlyfans_direct"``)
    - ``reason_category`` — one of :class:`ChallengeReason`.
    - ``creator_id`` (if present).
    - ``mode`` — always ``"dry_run"`` in Sprint 8B.

    ``extra_metadata`` may carry small scalar fields (counts,
    timestamps, status codes). It MUST NOT contain any key in
    :data:`_FORBIDDEN_METADATA_KEYS` — the function raises
    :class:`ChallengeMetadataContractViolation` if any are present.
    """
    extra = dict(extra_metadata or {})
    forbidden = _FORBIDDEN_METADATA_KEYS & {k.lower() for k in extra.keys()}
    if forbidden:
        raise ChallengeMetadataContractViolation(
            "record_session_challenged refuses extra_metadata with forbidden "
            f"keys {sorted(forbidden)}. Raw response bodies, cookies, and "
            "session tokens must never enter the audit pipeline."
        )

    metadata: dict[str, object] = {
        "connector_type": CONNECTOR_TYPE,
        "reason_category": reason_category,
        "mode": "dry_run",
    }
    metadata.update(extra)

    row = await record_audit(
        session,
        event_type="connector.session.challenged",
        category="connector",
        action="session_challenge",
        result="blocked",
        severity="warning",
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        organization_id=organization_id,
        creator_id=creator_id,
        resource_type="connector_run",
        resource_id=f"{CONNECTOR_TYPE}:session_challenge",
        metadata=metadata,
    )
    await session.commit()
    return str(row.id) if row is not None else None


# ── notification stub ──────────────────────────────────────────────────────


NotifyStubResult = Literal["not_configured", "skipped"]


def notify_challenge_stub(
    *,
    reason_category: ChallengeReason,
    creator_id: str | None = None,
) -> NotifyStubResult:
    """Notification stub for session challenges.

    Sprint 8B does NOT send any real notification. The function
    exists so a future Sprint 8C+ can wire in Slack / Telegram /
    email behind this single seam.

    Returns ``"not_configured"`` to make it obvious in admin UI and
    runbooks that the channel is not active. Logs a single line so
    operators tailing logs can see that the stub fired.
    """
    del reason_category, creator_id  # unused in stub; future wiring uses them
    logger.info(
        "of_direct.notify_challenge_stub: not_configured (Sprint 8B); "
        "audit row is the source of truth"
    )
    return "not_configured"


def notify_channel_status() -> NotifyStubResult:
    """Return the current notify-channel status for the security
    admin UI. Sprint 8B always returns ``"not_configured"``.
    """
    return "not_configured"
