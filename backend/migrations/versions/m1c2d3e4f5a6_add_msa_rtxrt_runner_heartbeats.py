"""Add msa_rtxrt_runner_heartbeats table for runner online/idle/busy signal.

Revision ID: m1c2d3e4f5a6
Revises: l9b2c3d4e5f6
Create Date: 2026-05-13 14:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m1c2d3e4f5a6"
down_revision = "l9b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the ``msa_rtxrt_runner_heartbeats`` table.

    Idempotent — silently no-ops if the table already exists, matching the
    rest of the migrations in this project.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("msa_rtxrt_runner_heartbeats"):
        op.create_table(
            "msa_rtxrt_runner_heartbeats",
            sa.Column("runner_id", sa.String(length=128), nullable=False),
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=False),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "last_poll_at",
                sa.DateTime(timezone=False),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "last_status",
                sa.String(length=16),
                nullable=False,
                server_default="idle",
            ),
            sa.PrimaryKeyConstraint("runner_id", name="pk_msa_rtxrt_runner_heartbeats"),
        )


def downgrade() -> None:
    """Drop the ``msa_rtxrt_runner_heartbeats`` table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("msa_rtxrt_runner_heartbeats"):
        op.drop_table("msa_rtxrt_runner_heartbeats")
