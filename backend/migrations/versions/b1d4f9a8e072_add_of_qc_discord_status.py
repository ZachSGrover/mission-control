"""Add of_qc_discord_status singleton table.

Revision ID: b1d4f9a8e072
Revises: a8c4f1e2d703
Create Date: 2026-04-28 19:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b1d4f9a8e072"
down_revision = "a8c4f1e2d703"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the operator state row for the QC Discord integration card."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("of_qc_discord_status"):
        op.create_table(
            "of_qc_discord_status",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("last_success_at", sa.DateTime(), nullable=True),
            sa.Column("last_failure_at", sa.DateTime(), nullable=True),
            sa.Column("last_failure_reason", sa.String(length=64), nullable=True),
            sa.Column("last_failure_status", sa.Integer(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    """Drop the QC Discord integration status table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("of_qc_discord_status"):
        op.drop_table("of_qc_discord_status")
