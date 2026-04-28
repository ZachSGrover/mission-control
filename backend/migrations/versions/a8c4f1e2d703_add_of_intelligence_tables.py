"""Add OnlyFans Intelligence tables.

Creates the persistent memory layer for the OnlyFans Intelligence product
(13 entity / time-series tables + the generic `business_memory_entries`
table).  Schema is source-agnostic: every row carries `source` so future
data sources can write into the same tables alongside OnlyMonster.

Idempotency baked in from day one:
  • `of_intelligence_revenue.source_external_id` carries the upstream
    transaction id; a partial unique index on
    `(source, source_external_id) WHERE source_external_id IS NOT NULL`
    rejects duplicates at the DB level.
  • `of_intelligence_sync_logs` carries `created_count`, `updated_count`,
    `skipped_duplicate_count`, `error_count`, and `source_endpoint` so
    the UI can show exactly what each run did.

Revision ID: a8c4f1e2d703
Revises: f5a7c3e8d1b2
Create Date: 2026-04-27 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a8c4f1e2d703"
down_revision = "f5a7c3e8d1b2"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(name)


def upgrade() -> None:
    # Use PostgreSQL JSONB for the JSON columns so we get GIN indexing later
    # without a follow-up migration.  Falls back to SQLite/JSON in tests.
    bind = op.get_bind()
    json_type = postgresql.JSONB(astext_type=sa.Text()) if bind.dialect.name == "postgresql" else sa.JSON()

    # ── of_intelligence_accounts ─────────────────────────────────────────────
    if not _has_table("of_intelligence_accounts"):
        op.create_table(
            "of_intelligence_accounts",
            sa.Column("id", postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.String(length=36), primary_key=True),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("source_id", sa.String(length=255), nullable=False),
            sa.Column("username", sa.String(length=255), nullable=True),
            sa.Column("display_name", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=64), nullable=True),
            sa.Column("access_status", sa.String(length=64), nullable=True),
            sa.Column("raw", json_type, nullable=True),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_synced_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("source", "source_id", name="uq_ofi_accounts_source_id"),
        )
        op.create_index("ix_of_intelligence_accounts_source", "of_intelligence_accounts", ["source"])
        op.create_index("ix_of_intelligence_accounts_source_id", "of_intelligence_accounts", ["source_id"])
        op.create_index("ix_of_intelligence_accounts_status", "of_intelligence_accounts", ["status"])
        op.create_index("ix_of_intelligence_accounts_access_status", "of_intelligence_accounts", ["access_status"])
        op.create_index("ix_of_intelligence_accounts_last_synced_at", "of_intelligence_accounts", ["last_synced_at"])
        op.create_index("ix_ofi_accounts_source_username", "of_intelligence_accounts", ["source", "username"])

    # ── of_intelligence_fans ─────────────────────────────────────────────────
    if not _has_table("of_intelligence_fans"):
        op.create_table(
            "of_intelligence_fans",
            sa.Column("id", postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.String(length=36), primary_key=True),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("source_id", sa.String(length=255), nullable=False),
            sa.Column("account_source_id", sa.String(length=255), nullable=True),
            sa.Column("username", sa.String(length=255), nullable=True),
            sa.Column("lifetime_value_cents", sa.Integer(), nullable=True),
            sa.Column("last_message_at", sa.DateTime(), nullable=True),
            sa.Column("is_subscribed", sa.Boolean(), nullable=True),
            sa.Column("raw", json_type, nullable=True),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_synced_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("source", "source_id", name="uq_ofi_fans_source_id"),
        )
        op.create_index("ix_of_intelligence_fans_source", "of_intelligence_fans", ["source"])
        op.create_index("ix_of_intelligence_fans_source_id", "of_intelligence_fans", ["source_id"])
        op.create_index("ix_of_intelligence_fans_account_source_id", "of_intelligence_fans", ["account_source_id"])
        op.create_index("ix_of_intelligence_fans_lifetime_value_cents", "of_intelligence_fans", ["lifetime_value_cents"])
        op.create_index("ix_of_intelligence_fans_last_message_at", "of_intelligence_fans", ["last_message_at"])
        op.create_index("ix_of_intelligence_fans_is_subscribed", "of_intelligence_fans", ["is_subscribed"])
        op.create_index("ix_of_intelligence_fans_last_synced_at", "of_intelligence_fans", ["last_synced_at"])
        op.create_index("ix_ofi_fans_account", "of_intelligence_fans", ["source", "account_source_id"])

    # ── of_intelligence_chats ────────────────────────────────────────────────
    if not _has_table("of_intelligence_chats"):
        op.create_table(
            "of_intelligence_chats",
            sa.Column("id", postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.String(length=36), primary_key=True),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("source_id", sa.String(length=255), nullable=False),
            sa.Column("account_source_id", sa.String(length=255), nullable=True),
            sa.Column("fan_source_id", sa.String(length=255), nullable=True),
            sa.Column("last_message_at", sa.DateTime(), nullable=True),
            sa.Column("unread_count", sa.Integer(), nullable=True),
            sa.Column("raw", json_type, nullable=True),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_synced_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("source", "source_id", name="uq_ofi_chats_source_id"),
        )
        op.create_index("ix_of_intelligence_chats_source", "of_intelligence_chats", ["source"])
        op.create_index("ix_of_intelligence_chats_source_id", "of_intelligence_chats", ["source_id"])
        op.create_index("ix_of_intelligence_chats_account_source_id", "of_intelligence_chats", ["account_source_id"])
        op.create_index("ix_of_intelligence_chats_fan_source_id", "of_intelligence_chats", ["fan_source_id"])
        op.create_index("ix_of_intelligence_chats_last_message_at", "of_intelligence_chats", ["last_message_at"])
        op.create_index("ix_of_intelligence_chats_last_synced_at", "of_intelligence_chats", ["last_synced_at"])
        op.create_index("ix_ofi_chats_account_fan", "of_intelligence_chats", ["source", "account_source_id", "fan_source_id"])

    # ── of_intelligence_messages ─────────────────────────────────────────────
    if not _has_table("of_intelligence_messages"):
        op.create_table(
            "of_intelligence_messages",
            sa.Column("id", postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.String(length=36), primary_key=True),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("source_id", sa.String(length=255), nullable=False),
            sa.Column("chat_source_id", sa.String(length=255), nullable=True),
            sa.Column("account_source_id", sa.String(length=255), nullable=True),
            sa.Column("fan_source_id", sa.String(length=255), nullable=True),
            sa.Column("chatter_source_id", sa.String(length=255), nullable=True),
            sa.Column("direction", sa.String(length=16), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("revenue_cents", sa.Integer(), nullable=True),
            sa.Column("raw", json_type, nullable=True),
            sa.Column("synced_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("source", "source_id", name="uq_ofi_messages_source_id"),
        )
        op.create_index("ix_of_intelligence_messages_source", "of_intelligence_messages", ["source"])
        op.create_index("ix_of_intelligence_messages_source_id", "of_intelligence_messages", ["source_id"])
        op.create_index("ix_of_intelligence_messages_chat_source_id", "of_intelligence_messages", ["chat_source_id"])
        op.create_index("ix_of_intelligence_messages_account_source_id", "of_intelligence_messages", ["account_source_id"])
        op.create_index("ix_of_intelligence_messages_fan_source_id", "of_intelligence_messages", ["fan_source_id"])
        op.create_index("ix_of_intelligence_messages_chatter_source_id", "of_intelligence_messages", ["chatter_source_id"])
        op.create_index("ix_of_intelligence_messages_direction", "of_intelligence_messages", ["direction"])
        op.create_index("ix_of_intelligence_messages_sent_at", "of_intelligence_messages", ["sent_at"])
        op.create_index("ix_of_intelligence_messages_synced_at", "of_intelligence_messages", ["synced_at"])
        op.create_index("ix_ofi_messages_chat_sent", "of_intelligence_messages", ["source", "chat_source_id", "sent_at"])
        op.create_index("ix_ofi_messages_chatter", "of_intelligence_messages", ["source", "chatter_source_id"])

    # ── of_intelligence_chatters ─────────────────────────────────────────────
    if not _has_table("of_intelligence_chatters"):
        op.create_table(
            "of_intelligence_chatters",
            sa.Column("id", postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.String(length=36), primary_key=True),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("source_id", sa.String(length=255), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=True),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("role", sa.String(length=64), nullable=True),
            sa.Column("active", sa.Boolean(), nullable=True),
            sa.Column("raw", json_type, nullable=True),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_synced_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("source", "source_id", name="uq_ofi_chatters_source_id"),
        )
        op.create_index("ix_of_intelligence_chatters_source", "of_intelligence_chatters", ["source"])
        op.create_index("ix_of_intelligence_chatters_source_id", "of_intelligence_chatters", ["source_id"])
        op.create_index("ix_of_intelligence_chatters_name", "of_intelligence_chatters", ["name"])
        op.create_index("ix_of_intelligence_chatters_active", "of_intelligence_chatters", ["active"])
        op.create_index("ix_of_intelligence_chatters_last_synced_at", "of_intelligence_chatters", ["last_synced_at"])

    # ── of_intelligence_mass_messages ────────────────────────────────────────
    if not _has_table("of_intelligence_mass_messages"):
        op.create_table(
            "of_intelligence_mass_messages",
            sa.Column("id", postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.String(length=36), primary_key=True),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("source_id", sa.String(length=255), nullable=False),
            sa.Column("account_source_id", sa.String(length=255), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("recipients_count", sa.Integer(), nullable=True),
            sa.Column("purchases_count", sa.Integer(), nullable=True),
            sa.Column("revenue_cents", sa.Integer(), nullable=True),
            sa.Column("body_preview", sa.Text(), nullable=True),
            sa.Column("raw", json_type, nullable=True),
            sa.Column("snapshot_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("source", "source_id", "snapshot_at", name="uq_ofi_mm_source_snapshot"),
        )
        op.create_index("ix_of_intelligence_mass_messages_source", "of_intelligence_mass_messages", ["source"])
        op.create_index("ix_of_intelligence_mass_messages_source_id", "of_intelligence_mass_messages", ["source_id"])
        op.create_index("ix_of_intelligence_mass_messages_account_source_id", "of_intelligence_mass_messages", ["account_source_id"])
        op.create_index("ix_of_intelligence_mass_messages_sent_at", "of_intelligence_mass_messages", ["sent_at"])
        op.create_index("ix_of_intelligence_mass_messages_snapshot_at", "of_intelligence_mass_messages", ["snapshot_at"])
        op.create_index("ix_ofi_mm_account_sent", "of_intelligence_mass_messages", ["source", "account_source_id", "sent_at"])

    # ── of_intelligence_posts ────────────────────────────────────────────────
    if not _has_table("of_intelligence_posts"):
        op.create_table(
            "of_intelligence_posts",
            sa.Column("id", postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.String(length=36), primary_key=True),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("source_id", sa.String(length=255), nullable=False),
            sa.Column("account_source_id", sa.String(length=255), nullable=True),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.Column("likes_count", sa.Integer(), nullable=True),
            sa.Column("comments_count", sa.Integer(), nullable=True),
            sa.Column("revenue_cents", sa.Integer(), nullable=True),
            sa.Column("raw", json_type, nullable=True),
            sa.Column("snapshot_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("source", "source_id", "snapshot_at", name="uq_ofi_posts_source_snapshot"),
        )
        op.create_index("ix_of_intelligence_posts_source", "of_intelligence_posts", ["source"])
        op.create_index("ix_of_intelligence_posts_source_id", "of_intelligence_posts", ["source_id"])
        op.create_index("ix_of_intelligence_posts_account_source_id", "of_intelligence_posts", ["account_source_id"])
        op.create_index("ix_of_intelligence_posts_published_at", "of_intelligence_posts", ["published_at"])
        op.create_index("ix_of_intelligence_posts_snapshot_at", "of_intelligence_posts", ["snapshot_at"])
        op.create_index("ix_ofi_posts_account_published", "of_intelligence_posts", ["source", "account_source_id", "published_at"])

    # ── of_intelligence_tracking_links ───────────────────────────────────────
    if not _has_table("of_intelligence_tracking_links"):
        op.create_table(
            "of_intelligence_tracking_links",
            sa.Column("id", postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.String(length=36), primary_key=True),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("source_id", sa.String(length=255), nullable=False),
            sa.Column("account_source_id", sa.String(length=255), nullable=True),
            sa.Column("name", sa.String(length=255), nullable=True),
            sa.Column("url", sa.Text(), nullable=True),
            sa.Column("clicks", sa.Integer(), nullable=True),
            sa.Column("conversions", sa.Integer(), nullable=True),
            sa.Column("revenue_cents", sa.Integer(), nullable=True),
            sa.Column("raw", json_type, nullable=True),
            sa.Column("snapshot_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("source", "source_id", "snapshot_at", name="uq_ofi_tl_source_snapshot"),
        )
        op.create_index("ix_of_intelligence_tracking_links_source", "of_intelligence_tracking_links", ["source"])
        op.create_index("ix_of_intelligence_tracking_links_source_id", "of_intelligence_tracking_links", ["source_id"])
        op.create_index("ix_of_intelligence_tracking_links_account_source_id", "of_intelligence_tracking_links", ["account_source_id"])
        op.create_index("ix_of_intelligence_tracking_links_snapshot_at", "of_intelligence_tracking_links", ["snapshot_at"])
        op.create_index("ix_ofi_tl_account", "of_intelligence_tracking_links", ["source", "account_source_id"])

    # ── of_intelligence_revenue ──────────────────────────────────────────────
    if not _has_table("of_intelligence_revenue"):
        op.create_table(
            "of_intelligence_revenue",
            sa.Column("id", postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.String(length=36), primary_key=True),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("source_external_id", sa.String(length=255), nullable=True),
            sa.Column("account_source_id", sa.String(length=255), nullable=True),
            sa.Column("period_start", sa.DateTime(), nullable=True),
            sa.Column("period_end", sa.DateTime(), nullable=True),
            sa.Column("revenue_cents", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("transactions_count", sa.Integer(), nullable=True),
            sa.Column("tips_cents", sa.Integer(), nullable=True),
            sa.Column("subscriptions_cents", sa.Integer(), nullable=True),
            sa.Column("ppv_cents", sa.Integer(), nullable=True),
            sa.Column("breakdown", json_type, nullable=True),
            sa.Column("raw", json_type, nullable=True),
            sa.Column("captured_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_of_intelligence_revenue_source", "of_intelligence_revenue", ["source"])
        op.create_index("ix_of_intelligence_revenue_source_external_id", "of_intelligence_revenue", ["source_external_id"])
        op.create_index("ix_of_intelligence_revenue_account_source_id", "of_intelligence_revenue", ["account_source_id"])
        op.create_index("ix_of_intelligence_revenue_period_start", "of_intelligence_revenue", ["period_start"])
        op.create_index("ix_of_intelligence_revenue_period_end", "of_intelligence_revenue", ["period_end"])
        op.create_index("ix_of_intelligence_revenue_captured_at", "of_intelligence_revenue", ["captured_at"])
        op.create_index("ix_ofi_revenue_account_period", "of_intelligence_revenue", ["source", "account_source_id", "period_start"])
        # Partial unique index — Postgres-only syntax.  On other dialects the
        # persister-level dedup is the safety net.
        if bind.dialect.name == "postgresql":
            op.execute(
                """
                CREATE UNIQUE INDEX uq_ofi_revenue_source_external_id
                ON of_intelligence_revenue (source, source_external_id)
                WHERE source_external_id IS NOT NULL
                """
            )

    # ── of_intelligence_qc_reports ───────────────────────────────────────────
    if not _has_table("of_intelligence_qc_reports"):
        op.create_table(
            "of_intelligence_qc_reports",
            sa.Column("id", postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.String(length=36), primary_key=True),
            sa.Column("report_date", sa.DateTime(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("critical_alerts_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("accounts_reviewed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("chatters_reviewed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("payload", json_type, nullable=False),
            sa.Column("markdown", sa.Text(), nullable=True),
            sa.Column("generated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_of_intelligence_qc_reports_report_date", "of_intelligence_qc_reports", ["report_date"])
        op.create_index("ix_of_intelligence_qc_reports_generated_at", "of_intelligence_qc_reports", ["generated_at"])
        op.create_index("ix_ofi_qc_generated", "of_intelligence_qc_reports", ["generated_at"])

    # ── of_intelligence_alerts ───────────────────────────────────────────────
    if not _has_table("of_intelligence_alerts"):
        op.create_table(
            "of_intelligence_alerts",
            sa.Column("id", postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.String(length=36), primary_key=True),
            sa.Column("code", sa.String(length=128), nullable=False),
            sa.Column("severity", sa.String(length=16), nullable=False, server_default="info"),
            sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("account_source_id", sa.String(length=255), nullable=True),
            sa.Column("chatter_source_id", sa.String(length=255), nullable=True),
            sa.Column("fan_source_id", sa.String(length=255), nullable=True),
            sa.Column("context", json_type, nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_of_intelligence_alerts_code", "of_intelligence_alerts", ["code"])
        op.create_index("ix_of_intelligence_alerts_severity", "of_intelligence_alerts", ["severity"])
        op.create_index("ix_of_intelligence_alerts_status", "of_intelligence_alerts", ["status"])
        op.create_index("ix_of_intelligence_alerts_account_source_id", "of_intelligence_alerts", ["account_source_id"])
        op.create_index("ix_of_intelligence_alerts_chatter_source_id", "of_intelligence_alerts", ["chatter_source_id"])
        op.create_index("ix_of_intelligence_alerts_fan_source_id", "of_intelligence_alerts", ["fan_source_id"])
        op.create_index("ix_of_intelligence_alerts_created_at", "of_intelligence_alerts", ["created_at"])
        op.create_index("ix_ofi_alerts_status_severity", "of_intelligence_alerts", ["status", "severity"])
        op.create_index("ix_ofi_alerts_account_created", "of_intelligence_alerts", ["account_source_id", "created_at"])

    # ── of_intelligence_sync_logs ────────────────────────────────────────────
    if not _has_table("of_intelligence_sync_logs"):
        op.create_table(
            "of_intelligence_sync_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.String(length=36), primary_key=True),
            sa.Column("run_id", postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.String(length=36), nullable=False),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("entity", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("items_synced", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_duplicate_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("reason", sa.String(length=64), nullable=True),
            sa.Column("source_endpoint", sa.String(length=255), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("triggered_by", sa.String(length=64), nullable=True),
        )
        op.create_index("ix_of_intelligence_sync_logs_run_id", "of_intelligence_sync_logs", ["run_id"])
        op.create_index("ix_of_intelligence_sync_logs_source", "of_intelligence_sync_logs", ["source"])
        op.create_index("ix_of_intelligence_sync_logs_entity", "of_intelligence_sync_logs", ["entity"])
        op.create_index("ix_of_intelligence_sync_logs_status", "of_intelligence_sync_logs", ["status"])
        op.create_index("ix_of_intelligence_sync_logs_started_at", "of_intelligence_sync_logs", ["started_at"])
        op.create_index("ix_ofi_sync_run_entity", "of_intelligence_sync_logs", ["run_id", "entity"])
        op.create_index("ix_ofi_sync_status_started", "of_intelligence_sync_logs", ["status", "started_at"])

    # ── business_memory_entries ──────────────────────────────────────────────
    if not _has_table("business_memory_entries"):
        op.create_table(
            "business_memory_entries",
            sa.Column("id", postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.String(length=36), primary_key=True),
            sa.Column("product", sa.String(length=64), nullable=False, server_default="of_intelligence"),
            sa.Column("kind", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("source", sa.String(length=64), nullable=True),
            sa.Column("account_source_id", sa.String(length=255), nullable=True),
            sa.Column("chatter_source_id", sa.String(length=255), nullable=True),
            sa.Column("fan_source_id", sa.String(length=255), nullable=True),
            sa.Column("period_start", sa.DateTime(), nullable=True),
            sa.Column("period_end", sa.DateTime(), nullable=True),
            sa.Column("tags", json_type, nullable=True),
            sa.Column("metadata", json_type, nullable=True),
            sa.Column("obsidian_path", sa.String(length=512), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_business_memory_entries_product", "business_memory_entries", ["product"])
        op.create_index("ix_business_memory_entries_kind", "business_memory_entries", ["kind"])
        op.create_index("ix_business_memory_entries_source", "business_memory_entries", ["source"])
        op.create_index("ix_business_memory_entries_account_source_id", "business_memory_entries", ["account_source_id"])
        op.create_index("ix_business_memory_entries_chatter_source_id", "business_memory_entries", ["chatter_source_id"])
        op.create_index("ix_business_memory_entries_fan_source_id", "business_memory_entries", ["fan_source_id"])
        op.create_index("ix_business_memory_entries_period_start", "business_memory_entries", ["period_start"])
        op.create_index("ix_business_memory_entries_created_at", "business_memory_entries", ["created_at"])
        op.create_index("ix_bme_product_kind_created", "business_memory_entries", ["product", "kind", "created_at"])
        op.create_index("ix_bme_account", "business_memory_entries", ["account_source_id"])


def downgrade() -> None:
    for table in (
        "business_memory_entries",
        "of_intelligence_sync_logs",
        "of_intelligence_alerts",
        "of_intelligence_qc_reports",
        "of_intelligence_revenue",
        "of_intelligence_tracking_links",
        "of_intelligence_posts",
        "of_intelligence_mass_messages",
        "of_intelligence_chatters",
        "of_intelligence_messages",
        "of_intelligence_chats",
        "of_intelligence_fans",
        "of_intelligence_accounts",
    ):
        if _has_table(table):
            op.drop_table(table)
