"""Add of_intelligence_user_metrics.

Per-user activity / sales / chargeback metrics from
`GET /api/v0/users/metrics`.  Source-agnostic schema (carries `source`)
so future data sources can write into the same table.

Idempotency: unique constraint on `(source, user_id, period_start, period_end)`.
The client snaps the API request window to UTC-day boundaries so re-runs
on the same day match the same row and UPDATE rather than appending.

Revision ID: c3e4f5a6b7c8
Revises: a8c4f1e2d703
Create Date: 2026-04-28 15:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c3e4f5a6b7c8"
down_revision = "a8c4f1e2d703"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = (
        postgresql.JSONB(astext_type=sa.Text()) if is_postgres else sa.JSON()
    )
    uuid_type = (
        postgresql.UUID(as_uuid=True) if is_postgres else sa.String(length=36)
    )

    if not _has_table("of_intelligence_user_metrics"):
        op.create_table(
            "of_intelligence_user_metrics",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("source_external_id", sa.String(length=255), nullable=True),
            sa.Column("user_id", sa.String(length=64), nullable=False),
            sa.Column("creator_ids", json_type, nullable=True),
            sa.Column("period_start", sa.DateTime(), nullable=False),
            sa.Column("period_end", sa.DateTime(), nullable=False),
            # Top-line activity
            sa.Column("fans_count", sa.Integer(), nullable=True),
            sa.Column("messages_count", sa.Integer(), nullable=True),
            sa.Column("posts_count", sa.Integer(), nullable=True),
            sa.Column("deleted_posts_count", sa.Integer(), nullable=True),
            # Style breakdown
            sa.Column("template_messages_count", sa.Integer(), nullable=True),
            sa.Column("ai_generated_messages_count", sa.Integer(), nullable=True),
            sa.Column("copied_messages_count", sa.Integer(), nullable=True),
            sa.Column("media_messages_count", sa.Integer(), nullable=True),
            # Speed / quality
            sa.Column("reply_time_avg_seconds", sa.Integer(), nullable=True),
            sa.Column("purchase_interval_avg_seconds", sa.Integer(), nullable=True),
            sa.Column("work_time_seconds", sa.Integer(), nullable=True),
            sa.Column("break_time_seconds", sa.Integer(), nullable=True),
            sa.Column("words_count_sum", sa.Integer(), nullable=True),
            sa.Column("unsent_messages_count", sa.Integer(), nullable=True),
            # Sales (cents)
            sa.Column("paid_messages_count", sa.Integer(), nullable=True),
            sa.Column("paid_messages_price_sum_cents", sa.BigInteger(), nullable=True),
            sa.Column("sold_messages_count", sa.Integer(), nullable=True),
            sa.Column("sold_messages_price_sum_cents", sa.BigInteger(), nullable=True),
            sa.Column("sold_posts_count", sa.Integer(), nullable=True),
            sa.Column("sold_posts_price_sum_cents", sa.BigInteger(), nullable=True),
            sa.Column("tips_amount_sum_cents", sa.BigInteger(), nullable=True),
            # Chargebacks
            sa.Column("chargedback_messages_count", sa.Integer(), nullable=True),
            sa.Column("chargedback_messages_price_sum_cents", sa.BigInteger(), nullable=True),
            sa.Column("chargedback_posts_count", sa.Integer(), nullable=True),
            sa.Column("chargedback_posts_price_sum_cents", sa.BigInteger(), nullable=True),
            sa.Column("chargedback_tips_amount_sum_cents", sa.BigInteger(), nullable=True),
            sa.Column("raw", json_type, nullable=True),
            sa.Column("captured_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "source",
                "user_id",
                "period_start",
                "period_end",
                name="uq_ofi_user_metrics_window",
            ),
        )
        op.create_index(
            "ix_of_intelligence_user_metrics_source",
            "of_intelligence_user_metrics",
            ["source"],
        )
        op.create_index(
            "ix_of_intelligence_user_metrics_source_external_id",
            "of_intelligence_user_metrics",
            ["source_external_id"],
        )
        op.create_index(
            "ix_of_intelligence_user_metrics_user_id",
            "of_intelligence_user_metrics",
            ["user_id"],
        )
        op.create_index(
            "ix_of_intelligence_user_metrics_period_start",
            "of_intelligence_user_metrics",
            ["period_start"],
        )
        op.create_index(
            "ix_of_intelligence_user_metrics_captured_at",
            "of_intelligence_user_metrics",
            ["captured_at"],
        )
        op.create_index(
            "ix_ofi_user_metrics_user_period",
            "of_intelligence_user_metrics",
            ["user_id", "period_start"],
        )
        op.create_index(
            "ix_ofi_user_metrics_period_end",
            "of_intelligence_user_metrics",
            ["period_end"],
        )


def downgrade() -> None:
    if _has_table("of_intelligence_user_metrics"):
        op.drop_table("of_intelligence_user_metrics")
