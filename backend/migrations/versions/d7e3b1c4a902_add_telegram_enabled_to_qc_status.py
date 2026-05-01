"""Add telegram_enabled to of_qc_discord_status.

Revision ID: d7e3b1c4a902
Revises: c8a9d0e1f5b3
Create Date: 2026-04-30 09:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d7e3b1c4a902"
down_revision = "c8a9d0e1f5b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("of_qc_discord_status"):
        return
    cols = {c["name"] for c in inspector.get_columns("of_qc_discord_status")}
    if "telegram_enabled" not in cols:
        op.add_column(
            "of_qc_discord_status",
            sa.Column(
                "telegram_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("of_qc_discord_status"):
        return
    cols = {c["name"] for c in inspector.get_columns("of_qc_discord_status")}
    if "telegram_enabled" in cols:
        op.drop_column("of_qc_discord_status", "telegram_enabled")
