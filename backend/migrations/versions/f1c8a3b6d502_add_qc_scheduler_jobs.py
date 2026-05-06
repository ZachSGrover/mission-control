"""Add OF Daily QC scheduler job audit trail + safe-runner toggles.

Adds:
  • of_qc_scheduler_jobs — append-only ticks recorded by the scheduler /
    manual runner.  Lets the dashboard answer "when did it last run, did
    it skip, and why?" without a live probe.
  • of_qc_discord_status.daily_qc_enabled (bool, default false) — master
    scheduler kill switch.
  • of_qc_discord_status.live_send_enabled (bool, default false) — gate
    that prevents scheduler-context Discord/Telegram publishes from going
    live until the operator explicitly opts in.

Revision ID: f1c8a3b6d502
Revises: e9a4f2b8c103
Create Date: 2026-05-06 22:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f1c8a3b6d502"
down_revision = "e9a4f2b8c103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── of_qc_scheduler_jobs ────────────────────────────────────────────────
    if not inspector.has_table("of_qc_scheduler_jobs"):
        op.create_table(
            "of_qc_scheduler_jobs",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("job_kind", sa.String(length=32), nullable=False),
            sa.Column(
                "triggered_by",
                sa.String(length=16),
                nullable=False,
                server_default="scheduler",
            ),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("skipped_reason", sa.String(length=64), nullable=True),
            sa.Column("error_summary", sa.String(length=256), nullable=True),
            sa.Column("accounts_checked", sa.Integer(), nullable=True),
            sa.Column("findings_count", sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("of_qc_scheduler_jobs"):
        existing = {idx["name"] for idx in inspector.get_indexes("of_qc_scheduler_jobs")}
        if "ix_of_qc_scheduler_jobs_started_at" not in existing:
            op.create_index(
                "ix_of_qc_scheduler_jobs_started_at",
                "of_qc_scheduler_jobs",
                ["started_at"],
            )
        if "ix_of_qc_scheduler_jobs_kind_started" not in existing:
            op.create_index(
                "ix_of_qc_scheduler_jobs_kind_started",
                "of_qc_scheduler_jobs",
                ["job_kind", "started_at"],
            )

    # ── of_qc_discord_status: new toggles ──────────────────────────────────
    if inspector.has_table("of_qc_discord_status"):
        cols = {c["name"] for c in inspector.get_columns("of_qc_discord_status")}
        if "daily_qc_enabled" not in cols:
            op.add_column(
                "of_qc_discord_status",
                sa.Column(
                    "daily_qc_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )
        if "live_send_enabled" not in cols:
            op.add_column(
                "of_qc_discord_status",
                sa.Column(
                    "live_send_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("of_qc_discord_status"):
        cols = {c["name"] for c in inspector.get_columns("of_qc_discord_status")}
        if "live_send_enabled" in cols:
            op.drop_column("of_qc_discord_status", "live_send_enabled")
        if "daily_qc_enabled" in cols:
            op.drop_column("of_qc_discord_status", "daily_qc_enabled")

    if inspector.has_table("of_qc_scheduler_jobs"):
        existing = {idx["name"] for idx in inspector.get_indexes("of_qc_scheduler_jobs")}
        for name in (
            "ix_of_qc_scheduler_jobs_started_at",
            "ix_of_qc_scheduler_jobs_kind_started",
        ):
            if name in existing:
                op.drop_index(name, table_name="of_qc_scheduler_jobs")
        op.drop_table("of_qc_scheduler_jobs")
