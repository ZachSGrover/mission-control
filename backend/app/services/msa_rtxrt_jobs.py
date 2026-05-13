"""MSA RT/X job-queue service layer.

Pure functions for validating job kinds, status transitions, and the
live-one safety contract. The router thin-wraps these so logic stays
testable without spinning up the FastAPI app.

Hard safety rules (kept here so the router cannot accidentally drift):

    1. Mass-live job kinds are rejected outright. Any string containing
       ``live_all`` / ``live_mass`` / ``live_batch`` / ``live_many`` is
       refused even if it sneaks into ``VALID_KINDS`` in the future.
    2. Live-one jobs require *all three* request flags:
           confirm_live == "YES"
           max_test_actions == 1
           kind in LIVE_ONE_KINDS
       Missing or wrong → ``LiveOneSafetyError``.
    3. Status transitions are gated against
       :data:`app.models.msa_rtxrt_job.ALLOWED_TRANSITIONS`.
    4. Operator-facing strings (summary, stdout_excerpt, error_excerpt)
       are truncated to the model's caps so a chatty runner cannot blow
       up the DB or leak too much content.
"""

from __future__ import annotations

from typing import Final

from app.models.msa_rtxrt_job import (
    ALLOWED_TRANSITIONS,
    DRY_RUN_KINDS,
    LIVE_ONE_KINDS,
    MAX_EXCERPT_LEN,
    MAX_SUMMARY_LEN,
    STATUS_RUNNING,
    TERMINAL_STATUSES,
    VALID_KINDS,
    VALID_STATUSES,
)

# ── Errors ──────────────────────────────────────────────────────────────────


class UnknownKindError(ValueError):
    """Raised when a caller posts a job ``kind`` outside ``VALID_KINDS``."""


class MassLiveBlockedError(ValueError):
    """Raised when a caller posts a job kind that looks like a mass live run."""


class LiveOneSafetyError(ValueError):
    """Raised when a live-one job fails the three-flag safety gate."""


class IllegalTransitionError(ValueError):
    """Raised when a status transition is not in ``ALLOWED_TRANSITIONS``."""


# ── Kind validation ─────────────────────────────────────────────────────────

_MASS_LIVE_TOKENS: Final[tuple[str, ...]] = (
    "live_all",
    "live_mass",
    "live_batch",
    "live_many",
)


def is_mass_live_kind(kind: str) -> bool:
    """Defensive check matching the local runner's :func:`is_mass_live_kind`.

    Returns True for any string that looks like a mass-live request,
    regardless of whether it appears in ``VALID_KINDS``. The router
    uses this as an *additional* gate on top of the membership check.
    """
    lowered = kind.lower()
    return any(token in lowered for token in _MASS_LIVE_TOKENS)


def validate_kind(kind: str) -> None:
    """Raise if ``kind`` is unknown or looks like a mass-live request.

    Mass-live is checked first so the caller sees the safer error
    message ("mass live runs are not supported") instead of the
    generic "unknown kind".
    """
    if is_mass_live_kind(kind):
        raise MassLiveBlockedError(f"mass live runs are not supported: {kind!r}")
    if kind not in VALID_KINDS:
        raise UnknownKindError(f"unknown job kind: {kind!r}")


def is_live_one_kind(kind: str) -> bool:
    """True iff ``kind`` is a member of ``LIVE_ONE_KINDS``."""
    return kind in LIVE_ONE_KINDS


def is_dry_run_kind(kind: str) -> bool:
    """True iff ``kind`` is a member of ``DRY_RUN_KINDS``."""
    return kind in DRY_RUN_KINDS


# ── Live-one safety gate ────────────────────────────────────────────────────


def validate_live_one_request(
    *,
    kind: str,
    confirm_live: str | None,
    max_test_actions: int | None,
) -> None:
    """Enforce the three-flag live-one safety gate.

    Caller may pass ``confirm_live`` / ``max_test_actions`` as raw
    request fields; we accept ``None`` and reject explicitly so a
    missing flag is treated identically to a wrong flag. Raises
    ``LiveOneSafetyError`` with a privacy-safe, specific reason.
    """
    if not is_live_one_kind(kind):
        raise LiveOneSafetyError(f"live-one safety gate called for non-live-one kind: {kind!r}")
    if confirm_live != "YES":
        raise LiveOneSafetyError("CONFIRM_LIVE_TEST != YES")
    if max_test_actions != 1:
        raise LiveOneSafetyError("MAX_TEST_ACTIONS != 1")


# ── Status transitions ─────────────────────────────────────────────────────


def validate_transition(current: str, target: str) -> None:
    """Raise if ``current`` → ``target`` is not allowed."""
    if current not in VALID_STATUSES:
        raise IllegalTransitionError(f"unknown current status: {current!r}")
    if target not in VALID_STATUSES:
        raise IllegalTransitionError(f"unknown target status: {target!r}")
    if current in TERMINAL_STATUSES:
        raise IllegalTransitionError(f"cannot transition from terminal status {current!r}")
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise IllegalTransitionError(f"illegal transition: {current!r} -> {target!r}")


def is_claimable(current: str) -> bool:
    """Whether the dispatcher can flip the row to ``running``.

    The dispatcher path is ``queued`` → ``running``; nothing else
    can be claimed by the runner.
    """
    return current == "queued" and "running" in ALLOWED_TRANSITIONS.get(current, frozenset())


_ = STATUS_RUNNING  # re-export indirection; keep import live for IDEs


# ── Privacy caps ────────────────────────────────────────────────────────────


def cap_summary(text: str | None) -> str | None:
    """Truncate ``text`` to ``MAX_SUMMARY_LEN`` bytes-ish."""
    if text is None:
        return None
    return text[:MAX_SUMMARY_LEN]


def cap_excerpt(text: str | None) -> str | None:
    """Truncate ``text`` to ``MAX_EXCERPT_LEN`` bytes-ish."""
    if text is None:
        return None
    return text[:MAX_EXCERPT_LEN]
