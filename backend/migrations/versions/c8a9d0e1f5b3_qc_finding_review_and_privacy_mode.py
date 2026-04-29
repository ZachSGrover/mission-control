"""Add reviewed_at / reviewed_by to qc findings + privacy_mode to discord status.

Revision ID: c8a9d0e1f5b3
Revises: c2e5f9a3b471
Create Date: 2026-04-29 12:30:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c8a9d0e1f5b3"
down_revision = "c2e5f9a3b471"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("of_intelligence_qc_findings"):
        cols = {c["name"] for c in inspector.get_columns("of_intelligence_qc_findings")}
        if "reviewed_at" not in cols:
            op.add_column(
                "of_intelligence_qc_findings",
                sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            )
        if "reviewed_by" not in cols:
            op.add_column(
                "of_intelligence_qc_findings",
                sa.Column("reviewed_by", sa.String(length=255), nullable=True),
            )
        # Index reviewed_at so dashboard can filter open findings cheaply.
        existing_idx = {idx["name"] for idx in inspector.get_indexes("of_intelligence_qc_findings")}
        if "ix_of_intelligence_qc_findings_reviewed_at" not in existing_idx:
            op.create_index(
                "ix_of_intelligence_qc_findings_reviewed_at",
                "of_intelligence_qc_findings",
                ["reviewed_at"],
            )

    if inspector.has_table("of_qc_discord_status"):
        cols = {c["name"] for c in inspector.get_columns("of_qc_discord_status")}
        if "privacy_mode" not in cols:
            op.add_column(
                "of_qc_discord_status",
                sa.Column(
                    "privacy_mode",
                    sa.String(length=32),
                    nullable=False,
                    server_default="safe_summary",
                ),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("of_qc_discord_status"):
        cols = {c["name"] for c in inspector.get_columns("of_qc_discord_status")}
        if "privacy_mode" in cols:
            op.drop_column("of_qc_discord_status", "privacy_mode")

    if inspector.has_table("of_intelligence_qc_findings"):
        existing_idx = {idx["name"] for idx in inspector.get_indexes("of_intelligence_qc_findings")}
        if "ix_of_intelligence_qc_findings_reviewed_at" in existing_idx:
            op.drop_index(
                "ix_of_intelligence_qc_findings_reviewed_at",
                table_name="of_intelligence_qc_findings",
            )
        cols = {c["name"] for c in inspector.get_columns("of_intelligence_qc_findings")}
        if "reviewed_by" in cols:
            op.drop_column("of_intelligence_qc_findings", "reviewed_by")
        if "reviewed_at" in cols:
            op.drop_column("of_intelligence_qc_findings", "reviewed_at")
