"""Add audit_events table.

Revision ID: a01b2c3d4e5f
Revises: g3a8e2c5b709
Create Date: 2026-04-29 00:00:00.000000

This migration is part of Security Sprint 1. It introduces the
``audit_events`` table used by ``app.services.audit_log.record_audit``.
No production data is altered; the migration only creates a new, empty
table and the indexes needed for forensic queries.

Re-parented during the merge from ``origin/main`` (commit 20bf0ac1):
the original tuple parent ``(99cd6df95f85, b4338be78eec, f5a7c3e8d1b2)``
fed into the (then-divergent) alembic heads.  Those heads have since
been linearised on ``main`` through ``g3a8e2c5b709``; pointing at the
new tip preserves the full ancestry without a redundant merge node.

Idempotent: every create is guarded by an inspector check so re-runs
are safe.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a01b2c3d4e5f"
down_revision = "g3a8e2c5b709"
branch_labels = None
depends_on = None


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {item["name"] for item in inspector.get_indexes(table_name)}


def upgrade() -> None:
    """Create the audit_events table and its lookup indexes."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("audit_events"):
        op.create_table(
            "audit_events",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("actor_user_id", sa.Uuid(), nullable=True),
            sa.Column("actor_email", sa.String(), nullable=True),
            sa.Column("actor_role", sa.String(), nullable=True),
            sa.Column("organization_id", sa.Uuid(), nullable=True),
            sa.Column("creator_id", sa.String(), nullable=True),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("category", sa.String(), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("result", sa.String(), nullable=False),
            sa.Column("severity", sa.String(), nullable=False, server_default="info"),
            sa.Column("resource_type", sa.String(), nullable=True),
            sa.Column("resource_id", sa.String(), nullable=True),
            sa.Column("ip_address", sa.String(), nullable=True),
            sa.Column("user_agent", sa.String(), nullable=True),
            sa.Column("request_id", sa.String(), nullable=True),
            sa.Column(
                "metadata_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "redacted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    indexes = _index_names(inspector, "audit_events")

    desired = {
        "ix_audit_events_actor_user_id": ["actor_user_id"],
        "ix_audit_events_actor_email": ["actor_email"],
        "ix_audit_events_organization_id": ["organization_id"],
        "ix_audit_events_creator_id": ["creator_id"],
        "ix_audit_events_event_type": ["event_type"],
        "ix_audit_events_category": ["category"],
        "ix_audit_events_result": ["result"],
        "ix_audit_events_severity": ["severity"],
        "ix_audit_events_resource_type": ["resource_type"],
        "ix_audit_events_redacted": ["redacted"],
        "ix_audit_events_created_at": ["created_at"],
    }
    for name, cols in desired.items():
        if name not in indexes:
            op.create_index(name, "audit_events", cols)


def downgrade() -> None:
    """Drop the audit_events table. Loses all audit history — never run in prod."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("audit_events"):
        indexes = _index_names(inspector, "audit_events")
        for name in (
            "ix_audit_events_created_at",
            "ix_audit_events_redacted",
            "ix_audit_events_resource_type",
            "ix_audit_events_severity",
            "ix_audit_events_result",
            "ix_audit_events_category",
            "ix_audit_events_event_type",
            "ix_audit_events_creator_id",
            "ix_audit_events_organization_id",
            "ix_audit_events_actor_email",
            "ix_audit_events_actor_user_id",
        ):
            if name in indexes:
                op.drop_index(name, table_name="audit_events")
        op.drop_table("audit_events")
