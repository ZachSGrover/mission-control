"""Add OF QC dashboard + alerting tables (consolidated).

Single migration covering everything Daily QC needs on top of the OnlyFans
Intelligence foundation:

  • ``of_qc_discord_status`` — singleton operator state row carrying:
      - enabled (master kill switch, default false)
      - last_success_at / last_failure_at / last_failure_reason / last_failure_status
        (drives the Settings card "Connected" / "Last test failed" pill)
      - privacy_mode (default ``safe_summary``; ``internal_detail`` is
        scaffolded but refused at render time)
      - telegram_enabled (per-channel toggle, default false)
  • ``of_intelligence_qc_findings`` — append-only Layer 2 detector findings
    with operator-review fields (reviewed_at / reviewed_by) and the indexes
    the rollup engine + dashboard expect.

Consolidated from the four feature-branch migrations
``b1d4f9a8e072``, ``c2e5f9a3b471``, ``c8a9d0e1f5b3``, ``d7e3b1c4a902``
to comply with the project's "one migration per PR" CI gate.

Revision ID: e9a4f2b8c103
Revises: a8c4f1e2d703
Create Date: 2026-05-06 19:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e9a4f2b8c103"
down_revision = "a8c4f1e2d703"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── of_qc_discord_status ────────────────────────────────────────────────
    if not inspector.has_table("of_qc_discord_status"):
        op.create_table(
            "of_qc_discord_status",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("last_success_at", sa.DateTime(), nullable=True),
            sa.Column("last_failure_at", sa.DateTime(), nullable=True),
            sa.Column("last_failure_reason", sa.String(length=64), nullable=True),
            sa.Column("last_failure_status", sa.Integer(), nullable=True),
            sa.Column(
                "privacy_mode",
                sa.String(length=32),
                nullable=False,
                server_default="safe_summary",
            ),
            sa.Column(
                "telegram_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    # ── of_intelligence_qc_findings ─────────────────────────────────────────
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
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("reviewed_by", sa.String(length=255), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("of_intelligence_qc_findings"):
        existing = {idx["name"] for idx in inspector.get_indexes("of_intelligence_qc_findings")}
        for name, cols in (
            ("ix_of_intelligence_qc_findings_code", ["code"]),
            ("ix_of_intelligence_qc_findings_created_at", ["created_at"]),
            ("ix_of_intelligence_qc_findings_reviewed_at", ["reviewed_at"]),
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
        existing = {idx["name"] for idx in inspector.get_indexes("of_intelligence_qc_findings")}
        for name in (
            "ix_of_intelligence_qc_findings_code",
            "ix_of_intelligence_qc_findings_created_at",
            "ix_of_intelligence_qc_findings_reviewed_at",
            "ix_ofi_qcf_code_created",
            "ix_ofi_qcf_chatter_code",
            "ix_ofi_qcf_account",
            "ix_ofi_qcf_rolled",
        ):
            if name in existing:
                op.drop_index(name, table_name="of_intelligence_qc_findings")
        op.drop_table("of_intelligence_qc_findings")

    if inspector.has_table("of_qc_discord_status"):
        op.drop_table("of_qc_discord_status")
