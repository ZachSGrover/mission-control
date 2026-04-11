"""Add mc_allowed_users table for Mission Control invite-only access control.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-04-10 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create mc_allowed_users table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("mc_allowed_users"):
        op.create_table(
            "mc_allowed_users",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("clerk_user_id", sa.String(length=255), nullable=False),
            sa.Column("added_by_clerk_user_id", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("clerk_user_id"),
        )
        op.create_index(
            "ix_mc_allowed_users_clerk_user_id",
            "mc_allowed_users",
            ["clerk_user_id"],
        )


def downgrade() -> None:
    """Drop mc_allowed_users table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("mc_allowed_users"):
        op.drop_index("ix_mc_allowed_users_clerk_user_id", table_name="mc_allowed_users")
        op.drop_table("mc_allowed_users")
