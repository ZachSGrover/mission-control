"""Add msa_rtxrt_jobs table for the MSA RT/X bot job-queue bridge.

Revision ID: l9b2c3d4e5f6
Revises: k8a1b2c3d4e5
Create Date: 2026-05-12 18:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "l9b2c3d4e5f6"
down_revision = "k8a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the ``msa_rtxrt_jobs`` table.

    Idempotent — silently no-ops if the table already exists, matching the
    rest of the migrations in this project.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("msa_rtxrt_jobs"):
        op.create_table(
            "msa_rtxrt_jobs",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="queued",
            ),
            sa.Column(
                "requested_by_user_id", sa.String(length=255), nullable=False
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=False),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column("started_at", sa.DateTime(timezone=False), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=False), nullable=True),
            sa.Column("summary", sa.String(length=256), nullable=True),
            sa.Column("stdout_excerpt", sa.String(length=2048), nullable=True),
            sa.Column("error_excerpt", sa.String(length=2048), nullable=True),
            sa.Column("runner_id", sa.String(length=128), nullable=True),
            sa.Column(
                "dry_run",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "live_one",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            sa.Column(
                "max_test_actions",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "metadata_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.PrimaryKeyConstraint("id", name="pk_msa_rtxrt_jobs"),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("msa_rtxrt_jobs")}
    if "ix_msa_rtxrt_jobs_status_created" not in existing_indexes:
        op.create_index(
            "ix_msa_rtxrt_jobs_status_created",
            "msa_rtxrt_jobs",
            ["status", "created_at"],
        )
    if "ix_msa_rtxrt_jobs_created_at" not in existing_indexes:
        op.create_index(
            "ix_msa_rtxrt_jobs_created_at",
            "msa_rtxrt_jobs",
            ["created_at"],
        )


def downgrade() -> None:
    """Drop the ``msa_rtxrt_jobs`` table and its indexes."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("msa_rtxrt_jobs"):
        existing_indexes = {idx["name"] for idx in inspector.get_indexes("msa_rtxrt_jobs")}
        if "ix_msa_rtxrt_jobs_created_at" in existing_indexes:
            op.drop_index("ix_msa_rtxrt_jobs_created_at", "msa_rtxrt_jobs")
        if "ix_msa_rtxrt_jobs_status_created" in existing_indexes:
            op.drop_index("ix_msa_rtxrt_jobs_status_created", "msa_rtxrt_jobs")
        op.drop_table("msa_rtxrt_jobs")
