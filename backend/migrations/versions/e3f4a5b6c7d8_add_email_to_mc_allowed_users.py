"""Add email column to mc_allowed_users and make clerk_user_id nullable.

Enables invite-by-email: an owner can pre-authorize a person before they have
a Clerk account. On first sign-in, the allowlist match is made by email and
clerk_user_id is backfilled onto the existing row.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-04-23 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("mc_allowed_users"):
        return

    existing_cols = {col["name"] for col in inspector.get_columns("mc_allowed_users")}
    if "email" not in existing_cols:
        op.add_column(
            "mc_allowed_users",
            sa.Column("email", sa.String(length=320), nullable=True),
        )
        op.create_index(
            "ix_mc_allowed_users_email",
            "mc_allowed_users",
            ["email"],
            unique=True,
        )

    op.alter_column(
        "mc_allowed_users",
        "clerk_user_id",
        existing_type=sa.String(length=255),
        nullable=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("mc_allowed_users"):
        return

    existing_cols = {col["name"] for col in inspector.get_columns("mc_allowed_users")}
    if "email" in existing_cols:
        op.drop_index("ix_mc_allowed_users_email", table_name="mc_allowed_users")
        op.drop_column("mc_allowed_users", "email")

    op.alter_column(
        "mc_allowed_users",
        "clerk_user_id",
        existing_type=sa.String(length=255),
        nullable=False,
    )
