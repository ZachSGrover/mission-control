"""Add bot_drafts table for the Bot Builder v1 surface.

Revision ID: j7e0f1d2c5b8
Revises: d4e5f6a7b8c9
Create Date: 2026-05-08 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "j7e0f1d2c5b8"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the ``bot_drafts`` table.

    Idempotent — silently no-ops if the table already exists, mirroring
    the rest of the migrations in this project.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("bot_drafts"):
        op.create_table(
            "bot_drafts",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("slug", sa.String(length=128), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("purpose", sa.String(length=500), nullable=False),
            sa.Column("category", sa.String(length=64), nullable=False),
            sa.Column("description", sa.String(length=2000), nullable=True),
            sa.Column("owner", sa.String(length=255), nullable=True),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="draft",
            ),
            sa.Column(
                "sandbox_mode",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "risk_level",
                sa.String(length=16),
                nullable=False,
                server_default="low",
            ),
            sa.Column(
                "approval_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column("trigger_type", sa.String(length=64), nullable=True),
            sa.Column("input_requirements", sa.String(length=2000), nullable=True),
            sa.Column("output_requirements", sa.String(length=2000), nullable=True),
            sa.Column("prompt_template", sa.String(length=8000), nullable=True),
            sa.Column("dashboard_notes", sa.String(length=2000), nullable=True),
            sa.Column("tools_needed_json", sa.String(length=2000), nullable=True),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("updated_by", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )
        op.create_index("ix_bot_drafts_slug", "bot_drafts", ["slug"])
        op.create_index("ix_bot_drafts_created_at", "bot_drafts", ["created_at"])


def downgrade() -> None:
    """Drop the ``bot_drafts`` table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("bot_drafts"):
        op.drop_index("ix_bot_drafts_created_at", table_name="bot_drafts")
        op.drop_index("ix_bot_drafts_slug", table_name="bot_drafts")
        op.drop_table("bot_drafts")
