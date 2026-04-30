"""Direct OnlyFans connector — rate-limit and session-health policy.

Sprint 7: **scaffolding only.** No live request counting, no live
session probing. The constants and types here are the policy a
future Sprint 8+ implementation must respect; this module exists so
those values are reviewed once and then referenced from a single
place forever after.

Design notes:

- Numbers are **conservative**. The point is not to maximise
  throughput; the point is to stay well below any platform
  threshold that could flag the account. If we ever hit our local
  limit, we should be far short of OnlyFans' real one.
- Backoff is exponential with a hard ceiling. A future implementation
  should reset the backoff on a clean response and never reduce it
  inside a window.
- Session health is a small enum the UI and audit metadata can
  reason about. It is intentionally narrow — every state has a
  documented reaction; no "other" bucket.
- ``CHALLENGE_REACTION`` is the procedure to follow on any sign of
  bot detection or unusual response. It is enumerated here so
  reviewers can read it without digging into a future
  implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

# Per-account, per-request-window. These are deliberately well below
# typical platform thresholds. If you find yourself wanting to raise
# them, the right answer is almost always "no — fix the workload, not
# the budget."
DEFAULT_MAX_REQUESTS_PER_MINUTE: Final[int] = 10
DEFAULT_MAX_REQUESTS_PER_HOUR: Final[int] = 200


@dataclass(frozen=True)
class BackoffPolicy:
    """Exponential backoff with jitter and a hard ceiling.

    Used after any non-200 response, including 429 / 5xx / unexpected
    HTML / OnlyFans-specific challenge surfaces. A future
    implementation should:

    - Start at ``initial_seconds`` for the first retry.
    - Double on each subsequent retry.
    - Cap at ``max_seconds`` (never exceed).
    - Add up to ``jitter_fraction`` * delay random jitter to
      desynchronise multi-instance retries.
    - Stop after ``max_retries`` attempts and write a session-health
      audit.
    """

    initial_seconds: float
    max_seconds: float
    jitter_fraction: float
    max_retries: int


DEFAULT_BACKOFF: Final[BackoffPolicy] = BackoffPolicy(
    initial_seconds=2.0,
    max_seconds=300.0,
    jitter_fraction=0.2,
    max_retries=4,
)


# Narrow enum for the session-health UI and audit pipeline.
SessionHealth = Literal[
    "disabled",  # connector module disabled at policy layer (Sprint 7 default)
    "not_configured",  # creator credential not present in vault
    "healthy",  # last response was a clean 200 within the last window
    "challenged",  # OnlyFans served a CAPTCHA / login challenge
    "expired",  # credential expired or session marked stale by client
    "revoked",  # creator or operator revoked the credential
    "blocked",  # platform-side block / suspension
    "error",  # anything else; treat as unhealthy
]


# What a future implementation must do on a challenge response.
# Enumerated as constants so the procedure is reviewable in one place.
@dataclass(frozen=True)
class ChallengeReactionPolicy:
    """Procedure to follow on a CAPTCHA or suspicious-response signal.

    The implementation must NOT silently retry a challenge. Every
    challenge is a potential bot-detection event; the right reaction
    is to stop, audit, notify, and require a human review before
    resuming.
    """

    stop: bool  # halt the in-flight session immediately
    audit: bool  # write a connector.session.challenged row
    notify: bool  # alert the operator (Slack/Telegram/email — to be wired)
    require_manual_review: bool  # flip session_health to "challenged" and refuse new runs


CHALLENGE_REACTION: Final[ChallengeReactionPolicy] = ChallengeReactionPolicy(
    stop=True,
    audit=True,
    notify=True,
    require_manual_review=True,
)


def is_unhealthy(status: SessionHealth) -> bool:
    """True iff ``status`` should prevent a new run from starting.

    Used by the connector shell and the readiness UI.
    """
    return status not in ("healthy", "disabled", "not_configured")


def describe_session_health(status: SessionHealth) -> str:
    """Human-readable, audit-safe description of a session state.

    The message is intentionally short and contains no platform-side
    response bodies — those may carry user-supplied content we do not
    want round-tripped into audit metadata.
    """
    return {
        "disabled": "Direct OnlyFans connector is disabled at the policy layer.",
        "not_configured": "No creator credential present in the vault.",
        "healthy": "Last response was clean within the last window.",
        "challenged": "Platform served a CAPTCHA or login challenge.",
        "expired": "Credential expired; rotate via the creator vault.",
        "revoked": "Credential revoked; obtain new consent before re-pairing.",
        "blocked": "Platform-side block; investigate before any further attempt.",
        "error": "Last attempt failed for an unspecified reason.",
    }[status]
