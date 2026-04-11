"""Add mc_user_roles table for Mission Control role-based access control.

Revision ID: c1d2e3f4a5b6
Revises: b2c3d4e5f6a8
Create Date: 2026-04-10 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "b2c3d4e5f6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create mc_user_roles table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("mc_user_roles"):
        op.create_table(
            "mc_user_roles",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("clerk_user_id", sa.String(length=255), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False, server_default="viewer"),
            sa.Column("disabled", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("clerk_user_id"),
        )
        op.create_index("ix_mc_user_roles_clerk_user_id", "mc_user_roles", ["clerk_user_id"])


def downgrade() -> None:
    """Drop mc_user_roles table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("mc_user_roles"):
        op.drop_index("ix_mc_user_roles_clerk_user_id", table_name="mc_user_roles")
        op.drop_table("mc_user_roles")
