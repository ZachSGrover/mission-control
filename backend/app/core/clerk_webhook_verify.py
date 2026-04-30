"""Clerk webhook signature verification.

Sprint 4 used a shared-secret HMAC compare for the webhook endpoint.
Sprint 5 promotes the verification to use Svix's library when it's
installed (Clerk's actual signing scheme), and falls back to the
shared-secret check only when Svix is missing AND the environment
explicitly opts in to the fallback.

Production hardening:
- :func:`verify_webhook` raises :class:`WebhookVerificationError` on
  any failure mode. The endpoint translates that into a 401 response.
- The fallback shared-secret path is **off by default in production**.
  The operator must set ``CLERK_WEBHOOK_ALLOW_SHARED_SECRET=1`` to use
  it; without that flag, missing Svix in production is a hard failure.

Why this is its own module: keeping the verification isolated lets us
unit-test the path-selection logic without standing up a FastAPI app,
and lets us swap implementations later (Svix → custom client → KMS
signed) without touching the endpoint handler.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Mapping

logger = logging.getLogger(__name__)


class WebhookVerificationError(RuntimeError):
    """Raised when a webhook payload cannot be verified."""


def _svix_available() -> bool:
    """True iff the ``svix`` package is importable in this interpreter."""
    try:
        import svix  # type: ignore[import-not-found] # noqa: F401

        return True
    except ImportError:
        return False


def _is_shared_secret_fallback_allowed() -> bool:
    """Production refuses the shared-secret fallback unless explicitly opted in."""
    from app.core.startup_guard import is_production

    if not is_production():
        return True
    return os.environ.get("CLERK_WEBHOOK_ALLOW_SHARED_SECRET", "0").strip() == "1"


def verify_webhook(
    *,
    payload: bytes,
    headers: Mapping[str, str],
    secret: str,
    shared_secret_header: str | None = None,
) -> None:
    """Verify a Clerk webhook payload. Raises on failure, returns None on success.

    Path selection:
    - If Svix is installed, use ``svix.Webhook(secret).verify(payload, headers)``.
      That's the proper Clerk verification scheme and rotates with
      Clerk's signing keys.
    - Else, if the environment allows the shared-secret fallback,
      compare ``shared_secret_header`` to ``secret`` in constant time.
      This is the Sprint 4 path; production refuses it unless
      ``CLERK_WEBHOOK_ALLOW_SHARED_SECRET=1``.
    - Else, hard-fail.
    """
    if not secret:
        raise WebhookVerificationError("CLERK_WEBHOOK_SECRET is not configured")

    if _svix_available():
        try:
            from svix.webhooks import Webhook  # type: ignore[import-not-found]

            Webhook(secret).verify(payload, dict(headers))
            return
        except Exception as exc:  # pragma: no cover — Svix failure surface
            raise WebhookVerificationError(
                f"svix verification failed: {type(exc).__name__}"
            ) from exc

    # Svix not installed.
    if not _is_shared_secret_fallback_allowed():
        raise WebhookVerificationError(
            "svix is not installed and the shared-secret fallback is not allowed in production. "
            "Install svix or set CLERK_WEBHOOK_ALLOW_SHARED_SECRET=1 (dev only)."
        )

    if not shared_secret_header:
        raise WebhookVerificationError("missing shared-secret header")
    if not hmac.compare_digest(secret.encode(), shared_secret_header.encode()):
        raise WebhookVerificationError("shared-secret mismatch")
    return
