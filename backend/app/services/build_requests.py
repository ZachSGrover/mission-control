"""Service helpers for ``BuildRequest`` — slug normalization, secret-pattern
rejection, list visibility filtering, and transition validation.

Privacy contract:
  • Free-text fields submitted by operators must not contain anything
    that looks like a secret.  ``validate_no_secrets`` reuses the
    pattern set from ``app.services.bot_drafts`` so the rejection
    surface is consistent across both authoring flows.
  • The visibility filter restricts non-owners to rows they themselves
    authored.  Owners see everything.
  • Transition guards encode the request-type lifecycle so an operator
    cannot, for example, mark their own request "approved" via PATCH.

Nothing in this module runs git, gh, or any external command.  v1 is
intake + approval only.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from app.models.build_request import (
    EDITABLE_BY_OPERATOR_STATUSES,
    STATUS_APPROVED,
    STATUS_BUILDING,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_DRAFT,
    STATUS_NEEDS_CHANGES,
    STATUS_REJECTED,
    STATUS_SUBMITTED,
    VALID_PRIORITIES,
    VALID_REQUEST_TYPES,
    VALID_RISK_LEVELS,
    BuildRequest,
)
from app.services.bot_drafts import (
    SecretLikeFieldError,
    reject_secret_like,
)

# Re-export so callers don't have to import from two modules.
__all__ = [
    "BuildRequestFields",
    "SecretLikeFieldError",
    "can_view",
    "is_owner_role",
    "normalize_slug",
    "validate_no_secrets",
    "validate_priority",
    "validate_request_type",
    "validate_risk_level",
    "validate_string_list",
    "validate_transition",
]


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,159}$")
_SLUG_FALLBACK_RE = re.compile(r"[^a-z0-9]+")


# ── Slug ────────────────────────────────────────────────────────────────────


def normalize_slug(slug: str | None, *, fallback_from: str | None = None) -> str:
    """Lowercase + validate a build-request slug.

    If *slug* is empty/None and *fallback_from* is provided, derive a
    slug from the title.  Raises ``ValueError`` on bad input.
    """
    cleaned = (slug or "").strip().lower()
    if not cleaned and fallback_from:
        derived = _SLUG_FALLBACK_RE.sub("-", fallback_from.strip().lower()).strip("-")
        cleaned = derived[:160]
    if not _SLUG_RE.match(cleaned):
        raise ValueError(
            "Slug must be 2-160 chars, lowercase letters/digits/'_'/'-', "
            "starting with a letter or digit.",
        )
    return cleaned


# ── Vocabularies ────────────────────────────────────────────────────────────


def validate_request_type(value: str) -> None:
    if value not in VALID_REQUEST_TYPES:
        raise ValueError(
            f"Invalid request_type '{value}'. Valid: {sorted(VALID_REQUEST_TYPES)}",
        )


def validate_priority(value: str) -> None:
    if value not in VALID_PRIORITIES:
        raise ValueError(
            f"Invalid priority '{value}'. Valid: {sorted(VALID_PRIORITIES)}",
        )


def validate_risk_level(value: str) -> None:
    if value not in VALID_RISK_LEVELS:
        raise ValueError(
            f"Invalid risk_level '{value}'. Valid: {sorted(VALID_RISK_LEVELS)}",
        )


# ── Secret rejection ────────────────────────────────────────────────────────


class BuildRequestFields:
    """Bundle of caller-supplied free-text fields for batch validation.

    Keeping this as a plain class (not a dataclass) lets us add fields
    incrementally without breaking older test call-sites.
    """

    def __init__(
        self,
        *,
        title: str | None = None,
        summary: str | None = None,
        description: str | None = None,
        business_reason: str | None = None,
        target_area: str | None = None,
        requested_branch_name: str | None = None,
        rejection_reason: str | None = None,
        owner_notes: str | None = None,
        platforms_requested: Sequence[str] | None = None,
        acceptance_criteria: Sequence[str] | None = None,
    ) -> None:
        self.title = title
        self.summary = summary
        self.description = description
        self.business_reason = business_reason
        self.target_area = target_area
        self.requested_branch_name = requested_branch_name
        self.rejection_reason = rejection_reason
        self.owner_notes = owner_notes
        self.platforms_requested = (
            list(platforms_requested) if platforms_requested is not None else None
        )
        self.acceptance_criteria = (
            list(acceptance_criteria) if acceptance_criteria is not None else None
        )


def validate_no_secrets(fields: BuildRequestFields) -> None:
    """Run the secret-pattern check across every free-text field.

    Raises ``SecretLikeFieldError`` on first match so the operator gets
    a focused error message identifying which field tripped the rule.
    """
    items: list[tuple[str, str | None]] = [
        ("title", fields.title),
        ("summary", fields.summary),
        ("description", fields.description),
        ("business_reason", fields.business_reason),
        ("target_area", fields.target_area),
        ("requested_branch_name", fields.requested_branch_name),
        ("rejection_reason", fields.rejection_reason),
        ("owner_notes", fields.owner_notes),
    ]
    for field, value in items:
        reject_secret_like(field, value)
    for entry in fields.platforms_requested or ():
        reject_secret_like("platforms_requested", entry)
    for entry in fields.acceptance_criteria or ():
        reject_secret_like("acceptance_criteria", entry)


def validate_string_list(values: Iterable[str] | None, *, field: str) -> list[str] | None:
    """Trim, dedupe-preserving-order, and reject empties for a JSON string list."""
    if values is None:
        return None
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            raise ValueError(f"{field} entries must be strings")
        s = raw.strip()
        if not s:
            continue
        if len(s) > 200:
            raise ValueError(f"{field} entries must be ≤ 200 chars")
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out or None


# ── Visibility ──────────────────────────────────────────────────────────────


def is_owner_role(role: str | None) -> bool:
    return role == "owner"


def can_view(role: str | None, actor_user_id: str, row: BuildRequest) -> bool:
    """Return True iff *actor_user_id* in *role* may see *row*.

    Owner: sees everything.
    Operator/builder/viewer: sees only rows they themselves authored.
    """
    if is_owner_role(role):
        return True
    return row.requested_by_user_id == actor_user_id


# ── Transitions ─────────────────────────────────────────────────────────────


# Allowed source statuses for each owner/operator action.
_ALLOWED_FROM = {
    "submit": {STATUS_DRAFT, STATUS_NEEDS_CHANGES},
    "approve": {STATUS_SUBMITTED, STATUS_NEEDS_CHANGES},
    "reject": {STATUS_SUBMITTED, STATUS_NEEDS_CHANGES},
    "request_changes": {STATUS_SUBMITTED},
    "cancel_operator": {STATUS_DRAFT, STATUS_SUBMITTED, STATUS_NEEDS_CHANGES},
    "cancel_owner": {
        STATUS_DRAFT,
        STATUS_SUBMITTED,
        STATUS_NEEDS_CHANGES,
        STATUS_APPROVED,
        STATUS_BUILDING,
    },
    "mark_building": {STATUS_APPROVED},
    "mark_completed": {STATUS_BUILDING, STATUS_APPROVED},
}


def validate_transition(action: str, current_status: str) -> None:
    """Raise ``ValueError`` if *action* cannot be applied to *current_status*."""
    allowed = _ALLOWED_FROM.get(action)
    if allowed is None:
        raise ValueError(f"Unknown transition action '{action}'")
    if current_status in {STATUS_REJECTED, STATUS_CANCELLED, STATUS_COMPLETED}:
        # Terminal — no further mutations.
        raise ValueError(
            f"Build request is in terminal state '{current_status}' and cannot be modified.",
        )
    if current_status not in allowed:
        raise ValueError(
            f"Action '{action}' not allowed from status '{current_status}'.",
        )


def is_operator_editable(status: str) -> bool:
    return status in EDITABLE_BY_OPERATOR_STATUSES
