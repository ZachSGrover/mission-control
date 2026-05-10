"""Build Request model — structured COO/operator change-request workflow.

A ``BuildRequest`` is a *spec* describing a change an operator (typically
the COO) wants made to Mission Control: a new bot, an agent, a feature,
a bug fix, a UI tweak.  Owners review, approve, reject, or send back
requests for revision.  v1 is intentionally the *intake + approval*
surface only — no code is generated, no branch is pushed, no PR is
opened, no deploy happens.

Privacy contract:
  • Caller-supplied free-text fields are scrubbed for anything that
    looks like a secret (API keys, bearer tokens, cookie material,
    database URLs, webhook URLs) before persistence.  See
    ``app.services.build_requests.validate_no_secrets``.
  • This table never stores tokens, webhooks, fan PII, message bodies,
    OnlyFans/OnlyMonster/X creds, or production code.
  • ``platforms_requested`` and ``acceptance_criteria`` are JSON arrays
    of short strings (platform names, AC bullets) — they are validated
    for secret-like substrings on every write.
  • There is NO branch creation endpoint in v1.  ``requested_branch_name``
    is metadata only; nothing on the server consumes it.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.core.time import utcnow

# ── Status vocabulary ──────────────────────────────────────────────────────

STATUS_DRAFT = "draft"
STATUS_SUBMITTED = "submitted"
STATUS_NEEDS_CHANGES = "needs_changes"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_BUILDING = "building"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"

VALID_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_DRAFT,
        STATUS_SUBMITTED,
        STATUS_NEEDS_CHANGES,
        STATUS_APPROVED,
        STATUS_REJECTED,
        STATUS_BUILDING,
        STATUS_COMPLETED,
        STATUS_CANCELLED,
    }
)

# Statuses an operator may have authored & still mutate.
EDITABLE_BY_OPERATOR_STATUSES: frozenset[str] = frozenset({STATUS_DRAFT, STATUS_NEEDS_CHANGES})

# Statuses an operator may cancel themselves.
CANCELLABLE_BY_OPERATOR_STATUSES: frozenset[str] = frozenset(
    {STATUS_DRAFT, STATUS_SUBMITTED, STATUS_NEEDS_CHANGES}
)

# Statuses considered "open" for default list filtering.
OPEN_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_DRAFT,
        STATUS_SUBMITTED,
        STATUS_NEEDS_CHANGES,
        STATUS_APPROVED,
        STATUS_BUILDING,
    }
)


# ── Request type vocabulary ────────────────────────────────────────────────

REQUEST_TYPE_BOT_BUILD = "bot_build"
REQUEST_TYPE_AGENT_BUILD = "agent_build"
REQUEST_TYPE_FEATURE = "feature"
REQUEST_TYPE_BUG_FIX = "bug_fix"
REQUEST_TYPE_UI_CHANGE = "ui_change"
REQUEST_TYPE_WORKFLOW = "workflow"
REQUEST_TYPE_INTEGRATION = "integration"
REQUEST_TYPE_DOCUMENTATION = "documentation"
REQUEST_TYPE_OTHER = "other"

VALID_REQUEST_TYPES: frozenset[str] = frozenset(
    {
        REQUEST_TYPE_BOT_BUILD,
        REQUEST_TYPE_AGENT_BUILD,
        REQUEST_TYPE_FEATURE,
        REQUEST_TYPE_BUG_FIX,
        REQUEST_TYPE_UI_CHANGE,
        REQUEST_TYPE_WORKFLOW,
        REQUEST_TYPE_INTEGRATION,
        REQUEST_TYPE_DOCUMENTATION,
        REQUEST_TYPE_OTHER,
    }
)


# ── Priority + risk vocabularies ───────────────────────────────────────────

PRIORITY_LOW = "low"
PRIORITY_NORMAL = "normal"
PRIORITY_HIGH = "high"
PRIORITY_URGENT = "urgent"

VALID_PRIORITIES: frozenset[str] = frozenset(
    {PRIORITY_LOW, PRIORITY_NORMAL, PRIORITY_HIGH, PRIORITY_URGENT}
)

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

VALID_RISK_LEVELS: frozenset[str] = frozenset({RISK_LOW, RISK_MEDIUM, RISK_HIGH})


class BuildRequest(SQLModel, table=True):
    """One structured change-request submitted by an operator/owner.

    Status transitions only via the dedicated endpoints in
    ``app.api.build_requests``.  No path through this table activates
    code generation, branch creation, or deploy in v1.
    """

    __tablename__ = "build_requests"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # ── Identification ──
    title: str = Field(max_length=200)
    slug: str = Field(index=True, unique=True, max_length=160)
    request_type: str = Field(max_length=32, index=True)

    # ── Description ──
    summary: str = Field(max_length=500)
    description: str | None = Field(default=None, max_length=8000)
    business_reason: str | None = Field(default=None, max_length=4000)

    # ── Authorship (immutable after create) ──
    requested_by_user_id: str = Field(max_length=255, index=True)
    requested_by_email: str | None = Field(default=None, max_length=320)
    requested_by_role: str | None = Field(default=None, max_length=32)

    # ── Lifecycle ──
    status: str = Field(default=STATUS_DRAFT, max_length=32, index=True)
    priority: str = Field(default=PRIORITY_NORMAL, max_length=16)
    risk_level: str = Field(default=RISK_LOW, max_length=16)

    # ── Targeting / linkage ──
    target_area: str | None = Field(default=None, max_length=160)
    related_bot_draft_id: UUID | None = Field(default=None, index=True)
    related_agent_id: UUID | None = Field(default=None, index=True)
    requested_branch_name: str | None = Field(
        default=None,
        max_length=160,
        description=(
            "METADATA ONLY in v1.  No branch is ever created from this field. "
            "Stored so the owner can see what name the requester proposed."
        ),
    )

    # ── Approval state (set by owner endpoints) ──
    approved_by_user_id: str | None = Field(default=None, max_length=255)
    approved_at: datetime | None = Field(default=None)
    rejected_by_user_id: str | None = Field(default=None, max_length=255)
    rejected_at: datetime | None = Field(default=None)
    rejection_reason: str | None = Field(default=None, max_length=2000)
    owner_notes: str | None = Field(default=None, max_length=4000)

    # ── Safety / scope flags ──
    safe_mode_required: bool = Field(default=True)
    external_actions_requested: bool = Field(default=False)
    secrets_required: bool = Field(default=False)

    # ── JSON arrays (TEXT for portability across SQLite-test/Postgres-prod) ──
    platforms_requested: list[str] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    acceptance_criteria: list[str] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )

    # ── Timestamps ──
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)
