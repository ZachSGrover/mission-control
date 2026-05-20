"""Add target_runner_id to msa_rtxrt_jobs for multi-runner assignment.

Revision ID: n2d3e4f5a6b7
Revises: m1c2d3e4f5a6
Create Date: 2026-05-20 12:30:00.000000

The MSA RT/X bridge originally claimed the oldest queued job globally,
which only works when there's exactly one runner (claw-1). Multi-runner
support adds an explicit ``target_runner_id`` column so the poll
endpoint can filter rows to the requesting runner. ``None`` preserves
back-compat: rows without a target are still claimable by any runner
(used by older claw-1 deploys and by smoke tests).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "n2d3e4f5a6b7"
down_revision = "m1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the ``target_runner_id`` column + supporting index.

    Idempotent — checks before each step. Safe to run twice. Matches the
    style of the existing MSA RT/X migrations.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("msa_rtxrt_jobs"):
        # The table will be created by the earlier l9b2c3d4e5f6 migration;
        # if that hasn't run yet we have nothing to do here.
        return

    existing_columns = {col["name"] for col in inspector.get_columns("msa_rtxrt_jobs")}
    if "target_runner_id" not in existing_columns:
        op.add_column(
            "msa_rtxrt_jobs",
            sa.Column("target_runner_id", sa.String(length=128), nullable=True),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("msa_rtxrt_jobs")}
    if "ix_msa_rtxrt_jobs_target_runner_id" not in existing_indexes:
        op.create_index(
            "ix_msa_rtxrt_jobs_target_runner_id",
            "msa_rtxrt_jobs",
            ["target_runner_id"],
        )


def downgrade() -> None:
    """Drop the ``target_runner_id`` column + its index."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("msa_rtxrt_jobs"):
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("msa_rtxrt_jobs")}
    if "ix_msa_rtxrt_jobs_target_runner_id" in existing_indexes:
        op.drop_index("ix_msa_rtxrt_jobs_target_runner_id", table_name="msa_rtxrt_jobs")

    existing_columns = {col["name"] for col in inspector.get_columns("msa_rtxrt_jobs")}
    if "target_runner_id" in existing_columns:
        op.drop_column("msa_rtxrt_jobs", "target_runner_id")
