"""Add app_settings table for encrypted runtime configuration.

Revision ID: b2c3d4e5f6a8
Revises: a9b1c2d3e4f7
Create Date: 2026-04-09 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a8"
down_revision = "a9b1c2d3e4f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create app_settings table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("app_settings"):
        op.create_table(
            "app_settings",
            sa.Column("key", sa.String(length=255), nullable=False),
            sa.Column("value", sa.Text(), nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("key"),
        )


def downgrade() -> None:
    """Drop app_settings table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("app_settings"):
        op.drop_table("app_settings")
