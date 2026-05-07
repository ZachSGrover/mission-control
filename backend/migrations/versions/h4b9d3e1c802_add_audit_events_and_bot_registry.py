"""Add audit_events + bot_registry tables for COO Bot Access v1.

Adds two append-only / reference tables that underpin the operator role
+ unified bot dashboard work:

  • ``audit_events`` — privileged-action audit log (role changes,
    allowlist mutations, integration writes, bot start/stop, kill
    switch flips).  Append-only; no UPDATE / DELETE callers.
  • ``bot_registry`` — single source of truth for "which bots does
    Mission Control know about".  Status fields (``enabled``,
    ``status``, ``last_run_at``) are mutated by the actuator;
    ``permitted_roles_json`` is owner-managed.

No data backfill — both tables start empty.  Bot registry rows are
seeded at startup by ``app.services.bot_registry.bootstrap_seed`` (idempotent).

Privacy: neither table accepts secrets, fan PII, message bodies, or
webhook URLs.  Enforcement is at the application layer, not the schema —
see ``app.services.audit_log`` and ``app.services.bot_registry``.

Revision ID: h4b9d3e1c802
Revises: g3a8e2c5b709
Create Date: 2026-05-06 23:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "h4b9d3e1c802"
down_revision = "g3a8e2c5b709"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "audit_events" not in existing_tables:
        op.create_table(
            "audit_events",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("actor_clerk_user_id", sa.String(length=255), nullable=False),
            sa.Column("actor_email", sa.String(length=320), nullable=True),
            sa.Column("actor_role", sa.String(length=32), nullable=True),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("target_type", sa.String(length=64), nullable=True),
            sa.Column("target_id", sa.String(length=255), nullable=True),
            sa.Column(
                "outcome",
                sa.String(length=32),
                nullable=False,
                server_default="success",
            ),
            sa.Column("safe_summary", sa.String(length=512), nullable=True),
            sa.Column("payload_hash", sa.String(length=64), nullable=True),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=512), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index(
            "ix_audit_events_actor_clerk_user_id",
            "audit_events",
            ["actor_clerk_user_id"],
        )
        op.create_index("ix_audit_events_action", "audit_events", ["action"])
        op.create_index(
            "ix_audit_events_target_type",
            "audit_events",
            ["target_type"],
        )
        op.create_index(
            "ix_audit_events_target_id",
            "audit_events",
            ["target_id"],
        )
        op.create_index("ix_audit_events_outcome", "audit_events", ["outcome"])
        op.create_index(
            "ix_audit_events_created_at",
            "audit_events",
            ["created_at"],
        )

    existing_tables = set(inspector.get_table_names())
    if "bot_registry" not in existing_tables:
        op.create_table(
            "bot_registry",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("slug", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column(
                "kind",
                sa.String(length=32),
                nullable=False,
                server_default="read_only_external",
            ),
            sa.Column("description", sa.String(length=512), nullable=True),
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "safe_mode",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="unknown",
            ),
            sa.Column("last_status_detail", sa.String(length=256), nullable=True),
            sa.Column("last_run_at", sa.DateTime(), nullable=True),
            sa.Column("last_error_summary", sa.String(length=256), nullable=True),
            sa.Column(
                "permitted_roles_json",
                sa.String(length=256),
                nullable=False,
                server_default='["owner"]',
            ),
            sa.Column("config_json", sa.String(length=2048), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index(
            "ix_bot_registry_slug",
            "bot_registry",
            ["slug"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "bot_registry" in existing_tables:
        op.drop_index("ix_bot_registry_slug", table_name="bot_registry")
        op.drop_table("bot_registry")

    existing_tables = set(inspector.get_table_names())
    if "audit_events" in existing_tables:
        for ix in (
            "ix_audit_events_created_at",
            "ix_audit_events_outcome",
            "ix_audit_events_target_id",
            "ix_audit_events_target_type",
            "ix_audit_events_action",
            "ix_audit_events_actor_clerk_user_id",
        ):
            op.drop_index(ix, table_name="audit_events")
        op.drop_table("audit_events")
