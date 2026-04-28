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


class OfIntelligenceChatter(SQLModel, table=True):
    """Team-member chatter (the human or agent operating an account)."""

    __tablename__ = "of_intelligence_chatters"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_ofi_chatters_source_id"),
    )

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


class OfIntelligenceQcReport(SQLModel, table=True):
    """Daily QC bot output — one row per generated report."""

    __tablename__ = "of_intelligence_qc_reports"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        Index("ix_ofi_qc_generated", "generated_at"),
    )

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
