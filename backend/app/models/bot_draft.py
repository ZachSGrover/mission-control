"""Bot draft model — sandbox-only specs authored from the Bot Builder UI.

A ``BotDraft`` is a non-operational *spec* for a future Mission Control
bot.  Drafts never run, never call live platform APIs, never execute
code.  They capture intent — name, purpose, prompt template, tools
needed, risk level — so an operator can author a bot proposal that an
owner reviews before any live wiring happens.

Privacy contract:
  • Caller-supplied free-text fields are scrubbed for anything that
    looks like a secret (API keys, bearer tokens, cookie material,
    database URLs, webhook URLs) before persistence.  See
    ``app.services.bot_drafts._reject_secret_like`` for the rejected
    patterns.
  • This table never stores tokens, webhooks, fan PII, message
    bodies, OnlyFans/OnlyMonster/X creds, or production code.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from app.core.time import utcnow

# ── Status / risk vocabularies ───────────────────────────────────────────────

DRAFT_STATUS_DRAFT = "draft"
DRAFT_STATUS_PENDING = "pending_approval"
DRAFT_STATUS_APPROVED = "approved"
DRAFT_STATUS_ARCHIVED = "archived"

VALID_DRAFT_STATUSES: frozenset[str] = frozenset(
    {
        DRAFT_STATUS_DRAFT,
        DRAFT_STATUS_PENDING,
        DRAFT_STATUS_APPROVED,
        DRAFT_STATUS_ARCHIVED,
    },
)

RISK_LOW = "low"
RISK_MEDIUM = "medium"
RISK_HIGH = "high"

VALID_RISK_LEVELS: frozenset[str] = frozenset({RISK_LOW, RISK_MEDIUM, RISK_HIGH})


class BotDraft(SQLModel, table=True):
    """A sandbox-only proposal for a future bot.

    Never controllable from production endpoints; v1 has no activation
    path.  Status transitions only via the dedicated endpoints in
    ``app.api.bot_drafts``.
    """

    __tablename__ = "bot_drafts"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # ── Identification ──
    slug: str = Field(index=True, unique=True, max_length=128)
    name: str = Field(max_length=200)
    purpose: str = Field(max_length=500)
    category: str = Field(max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    owner: str | None = Field(
        default=None,
        max_length=255,
        description="Free-text owner label (e.g. team or individual). NOT a credential.",
    )

    # ── Lifecycle ──
    status: str = Field(default=DRAFT_STATUS_DRAFT, max_length=32)
    sandbox_mode: bool = Field(default=True)
    risk_level: str = Field(default=RISK_LOW, max_length=16)
    approval_required: bool = Field(default=True)

    # ── Behaviour spec (free text, validated for secret-like substrings) ──
    trigger_type: str | None = Field(default=None, max_length=64)
    input_requirements: str | None = Field(default=None, max_length=2000)
    output_requirements: str | None = Field(default=None, max_length=2000)
    prompt_template: str | None = Field(default=None, max_length=8000)
    dashboard_notes: str | None = Field(default=None, max_length=2000)
    # JSON-encoded list of tool names (storing as TEXT keeps the schema
    # portable across SQLite-test and Postgres-prod, mirroring how
    # ``bot_registry.permitted_roles_json`` is stored.)
    tools_needed_json: str | None = Field(default=None, max_length=2000)

    # ── Authorship ──
    created_by: str = Field(max_length=255)
    updated_by: str = Field(max_length=255)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)
