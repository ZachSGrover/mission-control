"""add usage tracking tables

Revision ID: d7a3b9c2e5f1
Revises: f5a7c3e8d1b2
Create Date: 2026-04-28 00:00:00.000000

Creates three new tables for the Usage / Spend Tracker feature:

* ``usage_snapshots``    — provider billing snapshots (live or placeholder).
* ``usage_events``       — per-call internal AI usage log (reserved for
                            future agent logging; nothing writes yet).
* ``usage_alert_config`` — per-org spend-threshold + alert toggle config.

All operations are idempotent (gated on ``_has_table`` / ``_has_index``) and
non-destructive — the migration only ``CREATE``s new tables/indexes.  No
existing tables are altered.  Downgrade simply drops what upgrade created.
"""

from __future__ import annotations

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision = "d7a3b9c2e5f1"
down_revision = "f5a7c3e8d1b2"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    indexes = sa.inspect(op.get_bind()).get_indexes(table_name)
    return any(index["name"] == index_name for index in indexes)


def upgrade() -> None:
    # ── usage_snapshots ──────────────────────────────────────────────────────
    if not _has_table("usage_snapshots"):
        op.create_table(
            "usage_snapshots",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("organization_id", sa.Uuid(), nullable=True),
            sa.Column(
                "provider",
                sqlmodel.sql.sqltypes.AutoString(length=64),
                nullable=False,
            ),
            sa.Column("captured_at", sa.DateTime(), nullable=False),
            sa.Column("period_start", sa.DateTime(), nullable=False),
            sa.Column("period_end", sa.DateTime(), nullable=False),
            sa.Column(
                "input_tokens",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "output_tokens",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "total_tokens",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "requests",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "cost_usd",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0.0"),
            ),
            sa.Column(
                "source",
                sqlmodel.sql.sqltypes.AutoString(length=32),
                nullable=False,
                server_default=sa.text("'placeholder'"),
            ),
            sa.Column(
                "status",
                sqlmodel.sql.sqltypes.AutoString(length=32),
                nullable=False,
                server_default=sa.text("'ok'"),
            ),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("raw", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    snap_org_idx = op.f("ix_usage_snapshots_organization_id")
    if not _has_index("usage_snapshots", snap_org_idx):
        op.create_index(
            snap_org_idx, "usage_snapshots", ["organization_id"], unique=False
        )

    snap_provider_idx = op.f("ix_usage_snapshots_provider")
    if not _has_index("usage_snapshots", snap_provider_idx):
        op.create_index(
            snap_provider_idx, "usage_snapshots", ["provider"], unique=False
        )

    snap_captured_idx = op.f("ix_usage_snapshots_captured_at")
    if not _has_index("usage_snapshots", snap_captured_idx):
        op.create_index(
            snap_captured_idx, "usage_snapshots", ["captured_at"], unique=False
        )

    snap_status_idx = op.f("ix_usage_snapshots_status")
    if not _has_index("usage_snapshots", snap_status_idx):
        op.create_index(snap_status_idx, "usage_snapshots", ["status"], unique=False)

    # ── usage_events ─────────────────────────────────────────────────────────
    if not _has_table("usage_events"):
        op.create_table(
            "usage_events",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("organization_id", sa.Uuid(), nullable=True),
            sa.Column(
                "project",
                sqlmodel.sql.sqltypes.AutoString(length=128),
                nullable=True,
            ),
            sa.Column(
                "feature",
                sqlmodel.sql.sqltypes.AutoString(length=128),
                nullable=True,
            ),
            sa.Column("agent_id", sa.Uuid(), nullable=True),
            sa.Column(
                "agent_name",
                sqlmodel.sql.sqltypes.AutoString(length=128),
                nullable=True,
            ),
            sa.Column(
                "provider",
                sqlmodel.sql.sqltypes.AutoString(length=64),
                nullable=False,
            ),
            sa.Column(
                "model",
                sqlmodel.sql.sqltypes.AutoString(length=128),
                nullable=False,
            ),
            sa.Column(
                "input_tokens",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "output_tokens",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "total_tokens",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "estimated_cost_usd",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0.0"),
            ),
            sa.Column(
                "status",
                sqlmodel.sql.sqltypes.AutoString(length=32),
                nullable=False,
                server_default=sa.text("'ok'"),
            ),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column(
                "trigger_source",
                sqlmodel.sql.sqltypes.AutoString(length=64),
                nullable=True,
            ),
            sa.Column(
                "environment",
                sqlmodel.sql.sqltypes.AutoString(length=64),
                nullable=True,
            ),
            sa.Column(
                "request_id",
                sqlmodel.sql.sqltypes.AutoString(length=128),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    for col in ("organization_id", "project", "feature", "agent_id",
                "provider", "model", "status", "started_at"):
        idx_name = op.f(f"ix_usage_events_{col}")
        if not _has_index("usage_events", idx_name):
            op.create_index(idx_name, "usage_events", [col], unique=False)

    # ── usage_alert_config ───────────────────────────────────────────────────
    if not _has_table("usage_alert_config"):
        op.create_table(
            "usage_alert_config",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("organization_id", sa.Uuid(), nullable=True),
            sa.Column("daily_threshold_usd", sa.Float(), nullable=True),
            sa.Column("monthly_threshold_usd", sa.Float(), nullable=True),
            sa.Column(
                "alerts_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "discord_webhook_configured",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "organization_id", name="uq_usage_alert_config_org"
            ),
        )

    alert_org_idx = op.f("ix_usage_alert_config_organization_id")
    if not _has_index("usage_alert_config", alert_org_idx):
        op.create_index(
            alert_org_idx, "usage_alert_config", ["organization_id"], unique=False
        )


def downgrade() -> None:
    if _has_table("usage_alert_config"):
        op.drop_table("usage_alert_config")
    if _has_table("usage_events"):
        op.drop_table("usage_events")
    if _has_table("usage_snapshots"):
        op.drop_table("usage_snapshots")
