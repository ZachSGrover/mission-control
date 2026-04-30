"""Pydantic response/request schemas for the Usage Tracker API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# ── Common ──────────────────────────────────────────────────────────────────

ProviderStatus = Literal["ok", "error", "not_configured"]
SnapshotSource = Literal["live", "manual", "placeholder"]
RangeKey = Literal["24h", "7d", "30d", "mtd"]


class ProviderTotals(BaseModel):
    """Aggregated usage totals for a single provider over a window."""

    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0
    cost_usd: float = 0.0
    last_captured_at: datetime | None = None
    last_status: ProviderStatus = "not_configured"
    last_error: str | None = None
    last_source: SnapshotSource | None = None
    configured: bool = False


# ── Overview ────────────────────────────────────────────────────────────────


class UsageOverviewResponse(BaseModel):
    """High-level dashboard payload."""

    range_key: RangeKey
    range_start: datetime
    range_end: datetime
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_requests: int = 0
    providers: list[ProviderTotals] = Field(default_factory=list)
    daily_threshold_usd: float | None = None
    monthly_threshold_usd: float | None = None
    daily_threshold_breached: bool = False
    monthly_threshold_breached: bool = False
    last_refresh_at: datetime | None = None


# ── Providers ───────────────────────────────────────────────────────────────


class ProviderListResponse(BaseModel):
    providers: list[ProviderTotals]


# ── Daily ───────────────────────────────────────────────────────────────────


class DailyBucket(BaseModel):
    day: datetime
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0


class DailyUsageResponse(BaseModel):
    start: datetime
    end: datetime
    buckets: list[DailyBucket] = Field(default_factory=list)


# ── Project / Feature ───────────────────────────────────────────────────────


class ProjectTotals(BaseModel):
    project: str | None = None
    feature: str | None = None
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0


class ProjectListResponse(BaseModel):
    range_key: RangeKey
    rows: list[ProjectTotals] = Field(default_factory=list)


# ── Alerts ──────────────────────────────────────────────────────────────────


class AlertsResponse(BaseModel):
    alerts_enabled: bool = False
    daily_threshold_usd: float | None = None
    monthly_threshold_usd: float | None = None
    daily_spend_usd: float = 0.0
    monthly_spend_usd: float = 0.0
    daily_breached: bool = False
    monthly_breached: bool = False
    last_error: str | None = None
    last_error_provider: str | None = None
    last_error_at: datetime | None = None
    last_successful_check_at: datetime | None = None


# ── Settings ────────────────────────────────────────────────────────────────


class UsageSettingsResponse(BaseModel):
    """Configuration page payload — never includes raw secrets."""

    daily_threshold_usd: float | None = None
    monthly_threshold_usd: float | None = None
    alerts_enabled: bool = False
    discord_webhook_configured: bool = False

    openai_admin_configured: bool = False
    openai_admin_source: Literal["db", "env", "none"] = "none"
    # Masked preview of the saved admin key (never the full value).
    openai_admin_preview: str | None = None
    openai_org_id_set: bool = False
    openai_org_id_source: Literal["db", "env", "none"] = "none"
    # Org ID is a public identifier (`org-…`); safe to surface in full.
    openai_org_id_value: str | None = None

    anthropic_admin_configured: bool = False
    anthropic_admin_source: Literal["db", "env", "none"] = "none"
    # Masked preview of the saved Anthropic admin key (never the full value).
    anthropic_admin_preview: str | None = None
    anthropic_org_id_set: bool = False
    anthropic_org_id_source: Literal["db", "env", "none"] = "none"
    # Anthropic does not require an organization id — admin keys are
    # scoped to a single organization automatically.  We persist the value
    # only when supplied so it can be used as a future workspace filter.
    anthropic_org_id_value: str | None = None

    gemini_supported: bool = False
    gemini_note: str = (
        "Google does not yet expose a public usage/billing API for Gemini. "
        "Internal calls will be tracked via the events log only."
    )


class UsageSettingsUpdate(BaseModel):
    daily_threshold_usd: float | None = Field(default=None, ge=0)
    monthly_threshold_usd: float | None = Field(default=None, ge=0)
    alerts_enabled: bool | None = None


class OpenAiCredentialsUpdate(BaseModel):
    """Partial update for the OpenAI Usage Tracking credentials.

    Only fields that are present and non-empty are persisted; omitted or
    blank fields leave the existing value untouched.  Use the DELETE
    endpoint to clear both at once.
    """

    admin_key: str | None = Field(default=None)
    org_id: str | None = Field(default=None)


class AnthropicCredentialsUpdate(BaseModel):
    """Partial update for the Anthropic Usage Tracking credentials.

    Same partial-update contract as the OpenAI variant.  ``org_id`` is
    optional for Anthropic — the admin key is org-scoped already; org id
    is only useful as a future workspace filter.
    """

    admin_key: str | None = Field(default=None)
    org_id: str | None = Field(default=None)


class CredentialsStatus(BaseModel):
    """Lightweight status payload returned from credentials write endpoints."""

    admin_configured: bool = False
    admin_source: Literal["db", "env", "none"] = "none"
    admin_preview: str | None = None
    org_id_set: bool = False
    org_id_source: Literal["db", "env", "none"] = "none"
    org_id_value: str | None = None


# ── Refresh ─────────────────────────────────────────────────────────────────


class ProviderRefreshResult(BaseModel):
    provider: str
    status: ProviderStatus
    snapshot_id: UUID | None = None
    captured_at: datetime | None = None
    cost_usd: float = 0.0
    total_tokens: int = 0
    error: str | None = None
    source: SnapshotSource = "placeholder"


class RefreshResponse(BaseModel):
    started_at: datetime
    finished_at: datetime
    results: list[ProviderRefreshResult] = Field(default_factory=list)
