"""Add Daily QC read-only ingestion columns + scheduler-job source metadata.

Adds (all defaults safe / off):
  • of_qc_discord_status.daily_qc_source_mode (str, default "synthetic")
  • of_qc_discord_status.onlymonster_readonly_enabled (bool, default false)
  • of_qc_discord_status.onlyfans_readonly_enabled (bool, default false)
  • of_qc_discord_status.platform_write_enabled (bool, default false)
  • of_qc_scheduler_jobs.source_mode (str, nullable)
  • of_qc_scheduler_jobs.source_confidence (str, nullable)
  • of_qc_scheduler_jobs.safe_mode (bool, default true)

Revision ID: g3a8e2c5b709
Revises: f1c8a3b6d502
Create Date: 2026-05-06 23:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "g3a8e2c5b709"
down_revision = "f1c8a3b6d502"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── of_qc_discord_status: source-mode + per-source readonly flags ──────
    if inspector.has_table("of_qc_discord_status"):
        cols = {c["name"] for c in inspector.get_columns("of_qc_discord_status")}
        if "daily_qc_source_mode" not in cols:
            op.add_column(
                "of_qc_discord_status",
                sa.Column(
                    "daily_qc_source_mode",
                    sa.String(length=32),
                    nullable=False,
                    server_default="synthetic",
                ),
            )
        for col_name in (
            "onlymonster_readonly_enabled",
            "onlyfans_readonly_enabled",
            "platform_write_enabled",
        ):
            if col_name not in cols:
                op.add_column(
                    "of_qc_discord_status",
                    sa.Column(
                        col_name,
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.false(),
                    ),
                )

    # ── of_qc_scheduler_jobs: source metadata ──────────────────────────────
    if inspector.has_table("of_qc_scheduler_jobs"):
        cols = {c["name"] for c in inspector.get_columns("of_qc_scheduler_jobs")}
        if "source_mode" not in cols:
            op.add_column(
                "of_qc_scheduler_jobs",
                sa.Column("source_mode", sa.String(length=32), nullable=True),
            )
        if "source_confidence" not in cols:
            op.add_column(
                "of_qc_scheduler_jobs",
                sa.Column("source_confidence", sa.String(length=16), nullable=True),
            )
        if "safe_mode" not in cols:
            op.add_column(
                "of_qc_scheduler_jobs",
                sa.Column(
                    "safe_mode",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("of_qc_scheduler_jobs"):
        cols = {c["name"] for c in inspector.get_columns("of_qc_scheduler_jobs")}
        for col_name in ("safe_mode", "source_confidence", "source_mode"):
            if col_name in cols:
                op.drop_column("of_qc_scheduler_jobs", col_name)

    if inspector.has_table("of_qc_discord_status"):
        cols = {c["name"] for c in inspector.get_columns("of_qc_discord_status")}
        for col_name in (
            "platform_write_enabled",
            "onlyfans_readonly_enabled",
            "onlymonster_readonly_enabled",
            "daily_qc_source_mode",
        ):
            if col_name in cols:
                op.drop_column("of_qc_discord_status", col_name)
