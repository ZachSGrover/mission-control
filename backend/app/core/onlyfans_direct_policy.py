"""Direct OnlyFans connector — policy module.

Sprint 7: the **policy boundary** for a future direct OnlyFans
connector. Defines exactly which actions a future read-only connector
*may* implement, and which actions are **structurally forbidden** in
this codebase.

The core invariants this module enforces:

1. **No write actions can ever be implemented through this surface.**
   Calling :func:`require_read_action` for a write action raises
   :class:`BlockedActionError`. Any future code that branches on the
   result of :func:`classify_action` must treat ``"write"`` and
   ``"unknown"`` the same as a refusal — the connector shell does this
   for the caller.
2. **Unknown actions fail closed.** A typo, a renamed action, or a
   future action that hasn't been added to either set is treated as
   blocked, never as "default to allow."
3. **The lists are explicit.** Adding a read action requires editing
   :data:`READ_ACTIONS`; adding a write action would require editing
   :data:`WRITE_ACTIONS`, but the code that runs would still refuse
   because :class:`OnlyFansDirectConnector` exposes no write methods.
   Both layers must change before a write could ship.

Why a separate module instead of folding into ``connector_gate.py``:

- The connector gate composes prevention controls (kill switch,
  approval, consent, vault). This module is the **action vocabulary** —
  what does "OnlyFans direct read" even mean? Keeping the vocabulary
  separate from the gate prevents either file from growing into a
  god-module.
- A future Sprint 8 reviewer can read this file alone and answer "what
  is allowed?" without reading the gate, the connector shell, or any
  fixtures.

This module performs **no I/O**, has **no FastAPI dependency**, and
takes **no credentials**. It is pure policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

# Read-only actions that a future direct OnlyFans connector MAY implement.
# Each is a metadata-or-content read; none of them mutate any state on
# OnlyFans. Adding to this list is a deliberate code change reviewed
# against the readiness checklist.
READ_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "account_profile_read",
        "account_stats_read",
        "revenue_summary_read",
        "fan_list_metadata_read",
        "chat_thread_metadata_read",
        "chat_message_read",
        "vault_metadata_read",
        "post_metadata_read",
        "story_metadata_read",
        "mass_message_metadata_read",
    }
)

# Write / state-changing actions that are STRUCTURALLY FORBIDDEN.
# Mission Control will not implement any of these through the direct
# OnlyFans connector — the connector shell exposes no methods that
# could call them, and the policy refuses them at the verdict layer
# even if a hypothetical caller tried to bypass the shell.
WRITE_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "message_send",
        "post_create",
        "post_edit",
        "post_delete",
        "story_create",
        "story_delete",
        "vault_upload",
        "vault_edit",
        "vault_delete",
        "mass_message_send",
        "price_change",
        "subscription_change",
        "tip_send",
        "fan_block",
        "fan_unblock",
        "follow",
        "unfollow",
        "account_settings_update",
        "payout_update",
        "login_change",
    }
)

# Defensive sanity: read and write sets must be disjoint. Misclassifying
# an action would be a serious policy bug, so we verify at import time.
_OVERLAP = READ_ACTIONS & WRITE_ACTIONS
if _OVERLAP:  # pragma: no cover — caught by tests, fail at import in dev
    raise RuntimeError(
        "onlyfans_direct_policy: READ_ACTIONS and WRITE_ACTIONS overlap on "
        f"{sorted(_OVERLAP)}. Each action must classify uniquely."
    )


ActionClass = Literal["read", "write", "unknown"]


@dataclass(frozen=True)
class PolicyVerdict:
    """Result of asking the policy module about one action.

    - ``classification`` is one of ``"read"``, ``"write"``, ``"unknown"``.
    - ``allowed`` is ``True`` only when ``classification == "read"``.
      Write actions and unknown actions are never allowed by this layer.
      Even when ``allowed=True``, the connector gate (kill switch /
      approval / consent / vault) must still be consulted before any
      real-world call.
    - ``reason`` is a short machine-readable string usable in audit rows
      and UI status badges.
    """

    action: str
    classification: ActionClass
    allowed: bool
    reason: str


class BlockedActionError(RuntimeError):
    """Raised when the caller asked for a non-read action via a
    function that requires read-only.

    This is a *programmer error* class — by the time it surfaces in
    production something has gone wrong with the connector shell's
    own checks. It exists primarily to make tests loud when they
    accidentally try to dry-run a write action.
    """


def classify_action(action: str) -> ActionClass:
    """Classify ``action`` into ``"read"`` / ``"write"`` / ``"unknown"``.

    Fails closed: anything not explicitly in :data:`READ_ACTIONS` or
    :data:`WRITE_ACTIONS` is ``"unknown"`` (which the gate-bearing
    callers must treat as blocked).
    """
    if action in READ_ACTIONS:
        return "read"
    if action in WRITE_ACTIONS:
        return "write"
    return "unknown"


def evaluate_action(action: str) -> PolicyVerdict:
    """Return a :class:`PolicyVerdict` for ``action``.

    Pure function. Performs no I/O, no audit, no gate check — those
    are downstream concerns. The verdict is what *this layer alone*
    has to say about the action's legitimacy.
    """
    classification = classify_action(action)
    if classification == "read":
        return PolicyVerdict(
            action=action,
            classification="read",
            allowed=True,
            reason="read_allowed_by_policy",
        )
    if classification == "write":
        return PolicyVerdict(
            action=action,
            classification="write",
            allowed=False,
            reason="write_blocked_by_policy",
        )
    return PolicyVerdict(
        action=action,
        classification="unknown",
        allowed=False,
        reason="unknown_action_fail_closed",
    )


def is_read_action(action: str) -> bool:
    """True iff ``action`` is in :data:`READ_ACTIONS`. Convenience wrapper."""
    return classify_action(action) == "read"


def is_write_action(action: str) -> bool:
    """True iff ``action`` is in :data:`WRITE_ACTIONS`. Convenience wrapper."""
    return classify_action(action) == "write"


def require_read_action(action: str) -> None:
    """Raise :class:`BlockedActionError` unless ``action`` is a read.

    Used by the connector shell as the first guard in any code path
    that *should* perform a read. If a caller passes a write or
    unknown action, this raises immediately — no chance of
    accidentally performing a state change because of a typo.
    """
    verdict = evaluate_action(action)
    if not verdict.allowed:
        raise BlockedActionError(
            f"action {action!r} is not a permitted read "
            f"(classification={verdict.classification!r}, "
            f"reason={verdict.reason!r})"
        )
