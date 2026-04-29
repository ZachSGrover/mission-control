"""Add of_intelligence_qc_findings table for Layer 2 chatter QC.

Revision ID: c2e5f9a3b471
Revises: b1d4f9a8e072
Create Date: 2026-04-29 09:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c2e5f9a3b471"
down_revision = "b1d4f9a8e072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Append-only QC findings table.  One row per detector match per message."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("of_intelligence_qc_findings"):
        op.create_table(
            "of_intelligence_qc_findings",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("severity", sa.String(length=16), nullable=False),
            sa.Column("account_source_id", sa.String(length=255), nullable=True),
            sa.Column("chatter_source_id", sa.String(length=255), nullable=True),
            sa.Column("message_source_id", sa.String(length=255), nullable=True),
            sa.Column("detection_phrase", sa.String(length=128), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("rolled_up_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    existing = {idx["name"] for idx in inspector.get_indexes("of_intelligence_qc_findings")}
    for name, cols in (
        ("ix_of_intelligence_qc_findings_code", ["code"]),
        ("ix_of_intelligence_qc_findings_created_at", ["created_at"]),
        ("ix_ofi_qcf_code_created", ["code", "created_at"]),
        ("ix_ofi_qcf_chatter_code", ["chatter_source_id", "code"]),
        ("ix_ofi_qcf_account", ["account_source_id"]),
        ("ix_ofi_qcf_rolled", ["rolled_up_at"]),
    ):
        if name not in existing:
            op.create_index(name, "of_intelligence_qc_findings", cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("of_intelligence_qc_findings"):
        op.drop_table("of_intelligence_qc_findings")
