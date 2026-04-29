"""Add chat-import bridge tables + import_id linkage on messages.

Adds the two new tables required for the Chat QC Lab manual-import path:
  • of_intelligence_chat_imports    — one row per uploaded batch
  • of_intelligence_chat_qc_findings — per-message text-QC findings

Also adds a nullable `import_id` column to `of_intelligence_messages` so
messages persisted via an import can be attributed back to their batch
(existing live-synced rows remain NULL).

The pre-existing tables `of_intelligence_chats` and
`of_intelligence_messages` are *not* re-created here — they already
exist via the foundation migration `a8c4f1e2d703`.

Revision ID: e5a7b8c9d1f3
Revises: d4f5a6b7c8d9
Create Date: 2026-04-28 23:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e5a7b8c9d1f3"
down_revision = "d4f5a6b7c8d9"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(name)


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = postgresql.JSONB(astext_type=sa.Text()) if is_postgres else sa.JSON()
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(length=36)

    # ── of_intelligence_chat_imports ─────────────────────────────────────
    if not _has_table("of_intelligence_chat_imports"):
        op.create_table(
            "of_intelligence_chat_imports",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("label", sa.String(length=255), nullable=True),
            sa.Column("source_kind", sa.String(length=64), nullable=False),
            # 'manual_json' | 'manual_csv' | 'paste' | 'fixture'
            sa.Column("status", sa.String(length=32), nullable=False),
            # 'pending' | 'running' | 'success' | 'partial' | 'error'
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("total_chats", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_messages", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("messages_inserted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("messages_skipped_dup", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("findings_count", sa.Integer(), nullable=False, server_default="0"),
            # We deliberately do NOT persist raw uploaded message bodies in
            # this table.  The metadata only carries counts + non-content
            # fingerprints (e.g. file-size, sha256 of the upload payload).
            sa.Column("payload_sha256", sa.String(length=64), nullable=True),
            sa.Column("payload_size_bytes", sa.Integer(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("triggered_by", sa.String(length=64), nullable=True),
        )
        op.create_index(
            "ix_ofi_chat_imports_status",
            "of_intelligence_chat_imports",
            ["status"],
        )
        op.create_index(
            "ix_ofi_chat_imports_started_at",
            "of_intelligence_chat_imports",
            ["started_at"],
        )

    # ── of_intelligence_messages.import_id  (nullable, additive) ─────────
    if _has_table("of_intelligence_messages") and not _has_column(
        "of_intelligence_messages", "import_id"
    ):
        op.add_column(
            "of_intelligence_messages",
            sa.Column("import_id", uuid_type, nullable=True),
        )
        op.create_index(
            "ix_ofi_messages_import_id",
            "of_intelligence_messages",
            ["import_id"],
        )

    # ── of_intelligence_chat_qc_findings ─────────────────────────────────
    if not _has_table("of_intelligence_chat_qc_findings"):
        op.create_table(
            "of_intelligence_chat_qc_findings",
            sa.Column("id", uuid_type, primary_key=True),
            sa.Column("import_id", uuid_type, nullable=True),
            sa.Column("message_source_id", sa.String(length=255), nullable=True),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("chat_source_id", sa.String(length=255), nullable=True),
            sa.Column("account_source_id", sa.String(length=255), nullable=True),
            sa.Column("fan_source_id", sa.String(length=255), nullable=True),
            sa.Column("chatter_source_id", sa.String(length=255), nullable=True),
            sa.Column("rule_id", sa.String(length=64), nullable=False),
            sa.Column("severity", sa.String(length=16), nullable=False),
            # 'info' | 'warn' | 'critical'
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("issue", sa.Text(), nullable=False),
            sa.Column("why_it_matters", sa.Text(), nullable=False),
            sa.Column("suggested_better", sa.Text(), nullable=True),
            sa.Column("recommended_action", sa.Text(), nullable=True),
            # Excerpt is bounded (≤280 chars) so the findings table never
            # carries a full message body — useful for casual review while
            # keeping the surface area of leaked content small.
            sa.Column("message_excerpt", sa.Text(), nullable=True),
            sa.Column("context", json_type, nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_ofi_chat_qc_findings_import",
            "of_intelligence_chat_qc_findings",
            ["import_id"],
        )
        op.create_index(
            "ix_ofi_chat_qc_findings_severity",
            "of_intelligence_chat_qc_findings",
            ["severity"],
        )
        op.create_index(
            "ix_ofi_chat_qc_findings_chatter",
            "of_intelligence_chat_qc_findings",
            ["chatter_source_id"],
        )
        op.create_index(
            "ix_ofi_chat_qc_findings_rule",
            "of_intelligence_chat_qc_findings",
            ["rule_id"],
        )


def downgrade() -> None:
    if _has_table("of_intelligence_chat_qc_findings"):
        op.drop_table("of_intelligence_chat_qc_findings")
    if _has_table("of_intelligence_messages") and _has_column(
        "of_intelligence_messages", "import_id"
    ):
        op.drop_index(
            "ix_ofi_messages_import_id",
            table_name="of_intelligence_messages",
        )
        op.drop_column("of_intelligence_messages", "import_id")
    if _has_table("of_intelligence_chat_imports"):
        op.drop_table("of_intelligence_chat_imports")
