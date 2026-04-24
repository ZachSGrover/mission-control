"""Add pending_role column to mc_allowed_users.

Captures the intended role at invite time so email-only pending invites apply
the right role when the user first signs in — instead of silently defaulting
to viewer.

Revision ID: f5a7c3e8d1b2
Revises: e3f4a5b6c7d8
Create Date: 2026-04-23 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f5a7c3e8d1b2"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("mc_allowed_users"):
        return

    existing_cols = {col["name"] for col in inspector.get_columns("mc_allowed_users")}
    if "pending_role" not in existing_cols:
        op.add_column(
            "mc_allowed_users",
            sa.Column("pending_role", sa.String(length=32), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("mc_allowed_users"):
        return

    existing_cols = {col["name"] for col in inspector.get_columns("mc_allowed_users")}
    if "pending_role" in existing_cols:
        op.drop_column("mc_allowed_users", "pending_role")
