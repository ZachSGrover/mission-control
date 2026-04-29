"""OnlyFans Intelligence — persistent memory layer.

Single source-agnostic schema that powers the OnlyFans Intelligence product.
The first data source is OnlyMonster; future sources (direct OnlyFans,
Infloww, Supercreator, etc.) write into the same tables tagged with their
own `source` value.

Conventions:
  • Every entity row carries `(source, source_id)` so we can reconcile against
    whichever upstream system originated it.
  • A `raw` JSON column preserves the full upstream payload — schema
    evolution from the upstream API does not require a migration.
  • Time-series tables (`of_intelligence_revenue`, `of_intelligence_sync_logs`,
    `of_intelligence_qc_reports`, `of_intelligence_alerts`) are append-only;
    they never overwrite history.
  • Mutable entity tables (`of_intelligence_accounts`, `..._fans`, etc.) are
    upserted by `(source, source_id)` and snapshot via the `raw` column on
    each sync.

These tables are scoped to the OnlyFans Intelligence product area and are
not foreign-keyed to other parts of Mission Control — keeps the product
loosely coupled and easy to evolve.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, Index, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.time import utcnow

# Default `source` value for the v1 build — OnlyMonster is the sole data
# source today.  New integrations should set their own constant here.
SOURCE_ONLYMONSTER = "onlymonster"


# ── Mutable entity tables (upsert by source + source_id) ──────────────────────


class OfIntelligenceAccount(SQLModel, table=True):
    """Connected creator account (one row per OnlyMonster account)."""

    __tablename__ = "of_intelligence_accounts"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_ofi_accounts_source_id"),
        Index("ix_ofi_accounts_source_username", "source", "username"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source: str = Field(default=SOURCE_ONLYMONSTER, index=True, max_length=64)
    source_id: str = Field(index=True, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, max_length=64, index=True)
    access_status: str | None = Field(default=None, max_length=64, index=True)
    raw: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_synced_at: datetime = Field(default_factory=utcnow, index=True)


class OfIntelligenceCreatorProfile(SQLModel, table=True):
    """Permanent intelligence profile for a creator account.

    One row per `(source, source_account_id)`.  Identity columns are
    auto-populated from `of_intelligence_accounts` on each sync (or via
    lazy reconcile on read).  Strategy / brand / notes columns are
    operator-managed and never touched by sync.

    Linked back to `of_intelligence_accounts` by
    `(source, source_account_id) → (source, source_id)`.
    """

    __tablename__ = "of_intelligence_creator_profiles"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "source",
            "source_account_id",
            name="uq_ofi_creator_profiles_source_account",
        ),
        Index("ix_ofi_creator_profiles_username", "username"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # ── Linkage / identity (auto) ────────────────────────────────────────
    source: str = Field(default=SOURCE_ONLYMONSTER, index=True, max_length=64)
    source_account_id: str = Field(index=True, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = Field(default=None, sa_column=Column(Text))
    platform: str | None = Field(default=None, max_length=64)
    organisation_id: str | None = Field(default=None, max_length=255)
    subscribe_price_cents: int | None = Field(default=None)
    subscription_expiration_date: datetime | None = Field(default=None)
    access_status: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, max_length=64)
    last_account_sync_at: datetime | None = Field(default=None)

    # ── Operator-managed strategy / brand fields ─────────────────────────
    brand_persona: str | None = Field(default=None, sa_column=Column(Text))
    content_pillars: str | None = Field(default=None, sa_column=Column(Text))
    voice_tone: str | None = Field(default=None, sa_column=Column(Text))
    audience_summary: str | None = Field(default=None, sa_column=Column(Text))
    monetization_focus: str | None = Field(default=None, sa_column=Column(Text))
    posting_cadence: str | None = Field(default=None, sa_column=Column(Text))
    strategy_summary: str | None = Field(default=None, sa_column=Column(Text))
    off_limits: str | None = Field(default=None, sa_column=Column(Text))
    vault_notes: str | None = Field(default=None, sa_column=Column(Text))
    agency_notes: str | None = Field(default=None, sa_column=Column(Text))

    # ── External presence (manual) ───────────────────────────────────────
    onlyfans_url: str | None = Field(default=None, sa_column=Column(Text))
    instagram_url: str | None = Field(default=None, sa_column=Column(Text))
    twitter_url: str | None = Field(default=None, sa_column=Column(Text))
    tiktok_url: str | None = Field(default=None, sa_column=Column(Text))
    threads_url: str | None = Field(default=None, sa_column=Column(Text))
    reddit_url: str | None = Field(default=None, sa_column=Column(Text))

    # ── Audit / lineage ──────────────────────────────────────────────────
    raw_source_payload: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow, index=True)


class OfIntelligenceFan(SQLModel, table=True):
    """Fan / subscriber record."""

    __tablename__ = "of_intelligence_fans"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_ofi_fans_source_id"),
        Index("ix_ofi_fans_account", "source", "account_source_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source: str = Field(default=SOURCE_ONLYMONSTER, index=True, max_length=64)
    source_id: str = Field(index=True, max_length=255)
    account_source_id: str | None = Field(default=None, max_length=255, index=True)
    username: str | None = Field(default=None, max_length=255)
    lifetime_value_cents: int | None = Field(default=None, index=True)
    last_message_at: datetime | None = Field(default=None, index=True)
    is_subscribed: bool | None = Field(default=None, index=True)
    raw: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_synced_at: datetime = Field(default_factory=utcnow, index=True)


class OfIntelligenceChat(SQLModel, table=True):
    """DM thread between an account and a fan."""

    __tablename__ = "of_intelligence_chats"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_ofi_chats_source_id"),
        Index("ix_ofi_chats_account_fan", "source", "account_source_id", "fan_source_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source: str = Field(default=SOURCE_ONLYMONSTER, index=True, max_length=64)
    source_id: str = Field(index=True, max_length=255)
    account_source_id: str | None = Field(default=None, max_length=255, index=True)
    fan_source_id: str | None = Field(default=None, max_length=255, index=True)
    last_message_at: datetime | None = Field(default=None, index=True)
    unread_count: int | None = Field(default=None)
    raw: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_synced_at: datetime = Field(default_factory=utcnow, index=True)


class OfIntelligenceMessage(SQLModel, table=True):
    """Individual DM message — append-only by (source, source_id)."""

    __tablename__ = "of_intelligence_messages"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_ofi_messages_source_id"),
        Index("ix_ofi_messages_chat_sent", "source", "chat_source_id", "sent_at"),
        Index("ix_ofi_messages_chatter", "source", "chatter_source_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source: str = Field(default=SOURCE_ONLYMONSTER, index=True, max_length=64)
    source_id: str = Field(index=True, max_length=255)
    chat_source_id: str | None = Field(default=None, max_length=255, index=True)
    account_source_id: str | None = Field(default=None, max_length=255, index=True)
    fan_source_id: str | None = Field(default=None, max_length=255, index=True)
    chatter_source_id: str | None = Field(default=None, max_length=255, index=True)
    direction: str | None = Field(default=None, max_length=16, index=True)  # "in" | "out"
    sent_at: datetime | None = Field(default=None, index=True)
    body: str | None = Field(default=None, sa_column=Column(Text))
    revenue_cents: int | None = Field(default=None)
    raw: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    synced_at: datetime = Field(default_factory=utcnow, index=True)
    # Imported via Chat QC Lab — null for live-synced rows.
    import_id: UUID | None = Field(default=None, index=True)


class OfIntelligenceChatImport(SQLModel, table=True):
    """One row per uploaded chat-data batch (Chat QC Lab).

    Carries metadata only — counts, fingerprints, status — never the raw
    uploaded message bodies.  Bodies live in `of_intelligence_messages`
    via the standard messages persister.
    """

    __tablename__ = "of_intelligence_chat_imports"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (Index("ix_ofi_chat_imports_started_at", "started_at"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    label: str | None = Field(default=None, max_length=255)
    source_kind: str = Field(max_length=64)
    # 'manual_json' | 'manual_csv' | 'paste' | 'fixture'
    status: str = Field(default="pending", max_length=32, index=True)
    # 'pending' | 'running' | 'success' | 'partial' | 'error'
    notes: str | None = Field(default=None, sa_column=Column(Text))
    error: str | None = Field(default=None, sa_column=Column(Text))
    total_chats: int = Field(default=0)
    total_messages: int = Field(default=0)
    messages_inserted: int = Field(default=0)
    messages_skipped_dup: int = Field(default=0)
    findings_count: int = Field(default=0)
    payload_sha256: str | None = Field(default=None, max_length=64)
    payload_size_bytes: int | None = Field(default=None)
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = Field(default=None)
    triggered_by: str | None = Field(default=None, max_length=64)


class OfIntelligenceChatQcFinding(SQLModel, table=True):
    """One row per finding emitted by the chat-message QC engine."""

    __tablename__ = "of_intelligence_chat_qc_findings"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        Index("ix_ofi_chat_qc_findings_severity", "severity"),
        Index("ix_ofi_chat_qc_findings_chatter", "chatter_source_id"),
        Index("ix_ofi_chat_qc_findings_rule", "rule_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    import_id: UUID | None = Field(default=None, index=True)
    message_source_id: str | None = Field(default=None, max_length=255)
    source: str = Field(default=SOURCE_ONLYMONSTER, max_length=64)
    chat_source_id: str | None = Field(default=None, max_length=255)
    account_source_id: str | None = Field(default=None, max_length=255)
    fan_source_id: str | None = Field(default=None, max_length=255)
    chatter_source_id: str | None = Field(default=None, max_length=255)
    rule_id: str = Field(max_length=64)
    severity: str = Field(default="info", max_length=16)  # info|warn|critical
    title: str = Field(max_length=255)
    issue: str = Field(sa_column=Column(Text))
    why_it_matters: str = Field(sa_column=Column(Text))
    suggested_better: str | None = Field(default=None, sa_column=Column(Text))
    recommended_action: str | None = Field(default=None, sa_column=Column(Text))
    message_excerpt: str | None = Field(default=None, sa_column=Column(Text))
    context: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class OfIntelligenceChatter(SQLModel, table=True):
    """Team-member chatter (the human or agent operating an account)."""

    __tablename__ = "of_intelligence_chatters"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_ofi_chatters_source_id"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source: str = Field(default=SOURCE_ONLYMONSTER, index=True, max_length=64)
    source_id: str = Field(index=True, max_length=255)
    name: str | None = Field(default=None, max_length=255, index=True)
    email: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, max_length=64)
    active: bool | None = Field(default=None, index=True)
    raw: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_synced_at: datetime = Field(default_factory=utcnow, index=True)


class OfIntelligenceMassMessage(SQLModel, table=True):
    """Mass DM blast — append-only snapshot of stats at sync time."""

    __tablename__ = "of_intelligence_mass_messages"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("source", "source_id", "snapshot_at", name="uq_ofi_mm_source_snapshot"),
        Index("ix_ofi_mm_account_sent", "source", "account_source_id", "sent_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source: str = Field(default=SOURCE_ONLYMONSTER, index=True, max_length=64)
    source_id: str = Field(index=True, max_length=255)
    account_source_id: str | None = Field(default=None, max_length=255, index=True)
    sent_at: datetime | None = Field(default=None, index=True)
    recipients_count: int | None = Field(default=None)
    purchases_count: int | None = Field(default=None)
    revenue_cents: int | None = Field(default=None)
    body_preview: str | None = Field(default=None, sa_column=Column(Text))
    raw: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    snapshot_at: datetime = Field(default_factory=utcnow, index=True)


class OfIntelligencePost(SQLModel, table=True):
    """Wall post — append-only snapshot of stats at sync time."""

    __tablename__ = "of_intelligence_posts"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("source", "source_id", "snapshot_at", name="uq_ofi_posts_source_snapshot"),
        Index("ix_ofi_posts_account_published", "source", "account_source_id", "published_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source: str = Field(default=SOURCE_ONLYMONSTER, index=True, max_length=64)
    source_id: str = Field(index=True, max_length=255)
    account_source_id: str | None = Field(default=None, max_length=255, index=True)
    published_at: datetime | None = Field(default=None, index=True)
    likes_count: int | None = Field(default=None)
    comments_count: int | None = Field(default=None)
    revenue_cents: int | None = Field(default=None)
    raw: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    snapshot_at: datetime = Field(default_factory=utcnow, index=True)


class OfIntelligenceTrackingLink(SQLModel, table=True):
    """Trial / tracking link with append-only conversion snapshots."""

    __tablename__ = "of_intelligence_tracking_links"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("source", "source_id", "snapshot_at", name="uq_ofi_tl_source_snapshot"),
        Index("ix_ofi_tl_account", "source", "account_source_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source: str = Field(default=SOURCE_ONLYMONSTER, index=True, max_length=64)
    source_id: str = Field(index=True, max_length=255)
    account_source_id: str | None = Field(default=None, max_length=255, index=True)
    name: str | None = Field(default=None, max_length=255)
    url: str | None = Field(default=None, sa_column=Column(Text))
    clicks: int | None = Field(default=None)
    conversions: int | None = Field(default=None)
    revenue_cents: int | None = Field(default=None)
    raw: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    snapshot_at: datetime = Field(default_factory=utcnow, index=True)


# ── Time-series / append-only tables ─────────────────────────────────────────


class OfIntelligenceRevenue(SQLModel, table=True):
    """Per-event revenue rows.  Made idempotent via `source_external_id`.

    Historically append-only.  As of migration `b1f2e3d4c5a6`, rows
    originating from a known upstream identifier (transactions, chargebacks)
    are deduplicated through `source_external_id` — a partial unique index
    enforces `(source, source_external_id)` uniqueness when the column is
    set.  Rows without an upstream id (e.g. computed roll-ups) remain
    append-only.
    """

    __tablename__ = "of_intelligence_revenue"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        Index("ix_ofi_revenue_account_period", "source", "account_source_id", "period_start"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source: str = Field(default=SOURCE_ONLYMONSTER, index=True, max_length=64)
    source_external_id: str | None = Field(default=None, max_length=255, index=True)
    account_source_id: str | None = Field(default=None, max_length=255, index=True)
    period_start: datetime | None = Field(default=None, index=True)
    period_end: datetime | None = Field(default=None, index=True)
    revenue_cents: int = Field(default=0)
    transactions_count: int | None = Field(default=None)
    tips_cents: int | None = Field(default=None)
    subscriptions_cents: int | None = Field(default=None)
    ppv_cents: int | None = Field(default=None)
    breakdown: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    raw: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    captured_at: datetime = Field(default_factory=utcnow, index=True)


class OfIntelligenceUserMetrics(SQLModel, table=True):
    """Per-user activity / sales / chargeback metrics over a window.

    Sourced from `GET /api/v0/users/metrics`.  The API aggregates over a
    `from`/`to` window and returns one item per user.  We store one row
    per `(source, user_id, period_start, period_end)`; same-day re-runs
    upsert because the client snaps the window to UTC-day boundaries.

    Money fields are stored as **cents** (int) to match the convention
    in `of_intelligence_revenue`.  Time fields (`reply_time_avg`,
    `work_time`, `break_time`) are stored as integer seconds.
    """

    __tablename__ = "of_intelligence_user_metrics"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "source",
            "user_id",
            "period_start",
            "period_end",
            name="uq_ofi_user_metrics_window",
        ),
        Index("ix_ofi_user_metrics_user_period", "user_id", "period_start"),
        Index("ix_ofi_user_metrics_period_end", "period_end"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source: str = Field(default=SOURCE_ONLYMONSTER, index=True, max_length=64)
    source_external_id: str | None = Field(
        default=None,
        max_length=255,
        index=True,
        description=(
            "Deterministic SHA-256 of (source, user_id, period_start, period_end) — "
            "kept as a stable backup signal even though the unique constraint above "
            "is the authoritative dedup."
        ),
    )
    user_id: str = Field(max_length=64, index=True)
    creator_ids: list[Any] | None = Field(default=None, sa_column=Column(JSON))
    period_start: datetime = Field(index=True)
    period_end: datetime = Field(index=True)

    # Top-line activity
    fans_count: int | None = Field(default=None)
    messages_count: int | None = Field(default=None)
    posts_count: int | None = Field(default=None)
    deleted_posts_count: int | None = Field(default=None)

    # Style breakdown
    template_messages_count: int | None = Field(default=None)
    ai_generated_messages_count: int | None = Field(default=None)
    copied_messages_count: int | None = Field(default=None)
    media_messages_count: int | None = Field(default=None)

    # Speed / quality
    reply_time_avg_seconds: int | None = Field(default=None)
    purchase_interval_avg_seconds: int | None = Field(default=None)
    work_time_seconds: int | None = Field(default=None)
    break_time_seconds: int | None = Field(default=None)
    words_count_sum: int | None = Field(default=None)
    unsent_messages_count: int | None = Field(default=None)

    # Sales (cents)
    paid_messages_count: int | None = Field(default=None)
    paid_messages_price_sum_cents: int | None = Field(default=None)
    sold_messages_count: int | None = Field(default=None)
    sold_messages_price_sum_cents: int | None = Field(default=None)
    sold_posts_count: int | None = Field(default=None)
    sold_posts_price_sum_cents: int | None = Field(default=None)
    tips_amount_sum_cents: int | None = Field(default=None)

    # Chargebacks (cents / counts)
    chargedback_messages_count: int | None = Field(default=None)
    chargedback_messages_price_sum_cents: int | None = Field(default=None)
    chargedback_posts_count: int | None = Field(default=None)
    chargedback_posts_price_sum_cents: int | None = Field(default=None)
    chargedback_tips_amount_sum_cents: int | None = Field(default=None)

    raw: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    captured_at: datetime = Field(default_factory=utcnow, index=True)


class OfIntelligenceQcReport(SQLModel, table=True):
    """Daily QC bot output — one row per generated report."""

    __tablename__ = "of_intelligence_qc_reports"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (Index("ix_ofi_qc_generated", "generated_at"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    report_date: datetime = Field(index=True)
    summary: str | None = Field(default=None, sa_column=Column(Text))
    critical_alerts_count: int = Field(default=0)
    accounts_reviewed: int = Field(default=0)
    chatters_reviewed: int = Field(default=0)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    markdown: str | None = Field(default=None, sa_column=Column(Text))
    generated_at: datetime = Field(default_factory=utcnow, index=True)


class OfIntelligenceAlert(SQLModel, table=True):
    """Operational alert — emitted by the alert engine."""

    __tablename__ = "of_intelligence_alerts"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        Index("ix_ofi_alerts_status_severity", "status", "severity"),
        Index("ix_ofi_alerts_account_created", "account_source_id", "created_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    code: str = Field(max_length=128, index=True)
    severity: str = Field(default="info", max_length=16, index=True)  # info|warn|critical
    status: str = Field(default="open", max_length=16, index=True)  # open|acknowledged|resolved
    title: str = Field(max_length=255)
    message: str | None = Field(default=None, sa_column=Column(Text))
    account_source_id: str | None = Field(default=None, max_length=255, index=True)
    chatter_source_id: str | None = Field(default=None, max_length=255, index=True)
    fan_source_id: str | None = Field(default=None, max_length=255, index=True)
    context: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow, index=True)
    acknowledged_at: datetime | None = Field(default=None)
    resolved_at: datetime | None = Field(default=None)


class OfIntelligenceSyncLog(SQLModel, table=True):
    """Append-only sync run log — one row per (run, entity)."""

    __tablename__ = "of_intelligence_sync_logs"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        Index("ix_ofi_sync_run_entity", "run_id", "entity"),
        Index("ix_ofi_sync_status_started", "status", "started_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID = Field(index=True)
    source: str = Field(default=SOURCE_ONLYMONSTER, index=True, max_length=64)
    entity: str = Field(max_length=64, index=True)
    status: str = Field(default="pending", max_length=32, index=True)
    # pending | running | success | partial | error | not_available_from_api | skipped
    items_synced: int = Field(default=0)
    # Idempotent-sync counters — populated by `_run_one`.  `items_synced`
    # remains the gross "rows we received" count for backward compat;
    # the per-bucket counters describe what actually happened on persist.
    created_count: int = Field(default=0)
    updated_count: int = Field(default=0)
    skipped_duplicate_count: int = Field(default=0)
    error_count: int = Field(default=0)
    pages_fetched: int = Field(default=0)
    error: str | None = Field(default=None, sa_column=Column(Text))
    reason: str | None = Field(default=None, max_length=64)
    source_endpoint: str | None = Field(default=None, max_length=255)
    started_at: datetime = Field(default_factory=utcnow, index=True)
    finished_at: datetime | None = Field(default=None)
    triggered_by: str | None = Field(default=None, max_length=64)  # 'manual' | 'scheduled'


class BusinessMemoryEntry(SQLModel, table=True):
    """Structured business-memory note — searchable AI memory atoms.

    Generic across all Mission Control products (not just OF Intelligence).
    Each entry pairs a short headline with optional structured tags so AI
    agents can retrieve it later without re-deriving it from raw data.
    """

    __tablename__ = "business_memory_entries"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        Index("ix_bme_product_kind_created", "product", "kind", "created_at"),
        Index("ix_bme_account", "account_source_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    product: str = Field(default="of_intelligence", max_length=64, index=True)
    kind: str = Field(max_length=64, index=True)  # 'qc_report' | 'alert' | 'daily_note' | etc.
    title: str = Field(max_length=255)
    body: str | None = Field(default=None, sa_column=Column(Text))
    source: str | None = Field(default=None, max_length=64, index=True)
    account_source_id: str | None = Field(default=None, max_length=255, index=True)
    chatter_source_id: str | None = Field(default=None, max_length=255, index=True)
    fan_source_id: str | None = Field(default=None, max_length=255, index=True)
    period_start: datetime | None = Field(default=None, index=True)
    period_end: datetime | None = Field(default=None)
    tags: list[str] | None = Field(default=None, sa_column=Column(JSON))
    metadata_: dict[str, Any] | None = Field(default=None, sa_column=Column("metadata", JSON))
    obsidian_path: str | None = Field(default=None, max_length=512)
    created_at: datetime = Field(default_factory=utcnow, index=True)
