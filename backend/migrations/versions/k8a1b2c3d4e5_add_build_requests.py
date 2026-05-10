"""Add build_requests table for the COO build-request approval workflow.

Revision ID: k8a1b2c3d4e5
Revises: j7e0f1d2c5b8
Create Date: 2026-05-10 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "k8a1b2c3d4e5"
down_revision = "j7e0f1d2c5b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the ``build_requests`` table.

    Idempotent — silently no-ops if the table already exists, mirroring
    the rest of the migrations in this project.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("build_requests"):
        op.create_table(
            "build_requests",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("slug", sa.String(length=160), nullable=False),
            sa.Column("request_type", sa.String(length=32), nullable=False),
            sa.Column("summary", sa.String(length=500), nullable=False),
            sa.Column("description", sa.String(length=8000), nullable=True),
            sa.Column("business_reason", sa.String(length=4000), nullable=True),
            sa.Column("requested_by_user_id", sa.String(length=255), nullable=False),
            sa.Column("requested_by_email", sa.String(length=320), nullable=True),
            sa.Column("requested_by_role", sa.String(length=32), nullable=True),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="draft",
            ),
            sa.Column(
                "priority",
                sa.String(length=16),
                nullable=False,
                server_default="normal",
            ),
            sa.Column(
                "risk_level",
                sa.String(length=16),
                nullable=False,
                server_default="low",
            ),
            sa.Column("target_area", sa.String(length=160), nullable=True),
            sa.Column("related_bot_draft_id", sa.UUID(), nullable=True),
            sa.Column("related_agent_id", sa.UUID(), nullable=True),
            sa.Column("requested_branch_name", sa.String(length=160), nullable=True),
            sa.Column("approved_by_user_id", sa.String(length=255), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("rejected_by_user_id", sa.String(length=255), nullable=True),
            sa.Column("rejected_at", sa.DateTime(), nullable=True),
            sa.Column("rejection_reason", sa.String(length=2000), nullable=True),
            sa.Column("owner_notes", sa.String(length=4000), nullable=True),
            sa.Column(
                "safe_mode_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "external_actions_requested",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "secrets_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("platforms_requested", sa.JSON(), nullable=True),
            sa.Column("acceptance_criteria", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug"),
        )
        op.create_index("ix_build_requests_slug", "build_requests", ["slug"])
        op.create_index(
            "ix_build_requests_request_type",
            "build_requests",
            ["request_type"],
        )
        op.create_index("ix_build_requests_status", "build_requests", ["status"])
        op.create_index(
            "ix_build_requests_requested_by_user_id",
            "build_requests",
            ["requested_by_user_id"],
        )
        op.create_index(
            "ix_build_requests_related_bot_draft_id",
            "build_requests",
            ["related_bot_draft_id"],
        )
        op.create_index(
            "ix_build_requests_related_agent_id",
            "build_requests",
            ["related_agent_id"],
        )
        op.create_index(
            "ix_build_requests_created_at",
            "build_requests",
            ["created_at"],
        )


def downgrade() -> None:
    """Drop the ``build_requests`` table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("build_requests"):
        for ix in (
            "ix_build_requests_created_at",
            "ix_build_requests_related_agent_id",
            "ix_build_requests_related_bot_draft_id",
            "ix_build_requests_requested_by_user_id",
            "ix_build_requests_status",
            "ix_build_requests_request_type",
            "ix_build_requests_slug",
        ):
            op.drop_index(ix, table_name="build_requests")
        op.drop_table("build_requests")
