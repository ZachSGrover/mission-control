"""Usage / spend tracking models.

Three tables back the Usage Tracker feature:

* `usage_snapshots` — periodic billing snapshots fetched from each provider's
  Admin / Usage API (OpenAI, Anthropic) plus aggregated rollups for internal
  calls.  One row per refresh per provider.

* `usage_events` — fine-grained log of individual AI calls made by the system
  (synthesizer, agents, future internal tooling).  This is the "internal usage
  logging foundation" — nothing writes to it yet, but the schema is ready so
  future agent code can call `record_usage_event(...)`.

* `usage_alert_config` — per-organization spend thresholds and alert toggles.

Design notes:
- `organization_id` is nullable to accommodate self-hosted local-auth single-
  tenant installs.  Multi-tenant Clerk installs always populate it.
- Money is stored as float USD for now (matches the rest of the codebase).
  Migrate to numeric if we ever care about cent-perfect accounting.
- `raw` columns hold the unmodified provider response for forensics — never
  contains secrets, only usage counts and identifiers.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel


class UsageSnapshot(QueryModel, table=True):
    """A single provider-billing snapshot for a time window."""

    __tablename__ = "usage_snapshots"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID | None = Field(default=None, foreign_key="organizations.id", index=True)

    provider: str = Field(index=True, max_length=64)
    captured_at: datetime = Field(default_factory=utcnow, index=True)
    period_start: datetime
    period_end: datetime

    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    requests: int = Field(default=0)
    cost_usd: float = Field(default=0.0)

    source: str = Field(default="placeholder", max_length=32)
    status: str = Field(default="ok", max_length=32, index=True)
    error: str | None = Field(default=None)

    raw: str | None = Field(default=None)

    created_at: datetime = Field(default_factory=utcnow)


class UsageEvent(QueryModel, table=True):
    """One internal AI call.  Reserved for future agent-call logging."""

    __tablename__ = "usage_events"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID | None = Field(default=None, foreign_key="organizations.id", index=True)

    project: str | None = Field(default=None, max_length=128, index=True)
    feature: str | None = Field(default=None, max_length=128, index=True)
    agent_id: UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    agent_name: str | None = Field(default=None, max_length=128)

    provider: str = Field(index=True, max_length=64)
    model: str = Field(max_length=128, index=True)

    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)
    estimated_cost_usd: float = Field(default=0.0)

    status: str = Field(default="ok", max_length=32, index=True)
    error: str | None = Field(default=None)

    started_at: datetime = Field(default_factory=utcnow, index=True)
    ended_at: datetime | None = Field(default=None)
    duration_ms: int | None = Field(default=None)

    trigger_source: str | None = Field(default=None, max_length=64)
    environment: str | None = Field(default=None, max_length=64)
    request_id: str | None = Field(default=None, max_length=128)

    created_at: datetime = Field(default_factory=utcnow)


class UsageAlertConfig(QueryModel, table=True):
    """Per-organization spend alert thresholds.

    Stored separately from AppSetting because thresholds are organization-
    scoped numeric data, not encrypted secrets.  Discord webhook URLs (which
    *are* secrets) are stored via AppSetting under `alert.discord_webhook`
    when wired in Phase 2 — no plain-text webhook column lives here.
    """

    __tablename__ = "usage_alert_config"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            name="uq_usage_alert_config_org",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID | None = Field(default=None, foreign_key="organizations.id", index=True)

    daily_threshold_usd: float | None = Field(default=None)
    monthly_threshold_usd: float | None = Field(default=None)
    alerts_enabled: bool = Field(default=False)
    discord_webhook_configured: bool = Field(default=False)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
