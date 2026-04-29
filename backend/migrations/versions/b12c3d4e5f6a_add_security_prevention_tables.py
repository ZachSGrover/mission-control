"""Add security prevention tables: connector approvals, kill switches,
client consents, creator credentials.

Revision ID: b12c3d4e5f6a
Revises: a01b2c3d4e5f
Create Date: 2026-04-29 00:30:00.000000

This migration is part of Security Sprint 2. It introduces four
prevention tables used by the new gate at
``app.core.connector_gate.is_connector_action_allowed``. The migration
is fully idempotent — every create is guarded by an inspector check —
so re-runs are safe.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b12c3d4e5f6a"
down_revision = "a01b2c3d4e5f"
branch_labels = None
depends_on = None


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {item["name"] for item in inspector.get_indexes(table_name)}


def upgrade() -> None:  # noqa: C901  — flat list of guarded creates
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── connector_approvals ────────────────────────────────────────────
    if not inspector.has_table("connector_approvals"):
        op.create_table(
            "connector_approvals",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("organization_id", sa.Uuid(), nullable=True),
            sa.Column("creator_id", sa.String(), nullable=True),
            sa.Column("connector_type", sa.String(), nullable=False),
            sa.Column("requested_action", sa.String(), nullable=False),
            sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
            sa.Column("requested_by_email", sa.String(), nullable=True),
            sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
            sa.Column("approved_by_email", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("reason", sa.String(), nullable=True),
            sa.Column(
                "risk_level", sa.String(), nullable=False, server_default="medium"
            ),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("rejected_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column(
                "metadata_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = sa.inspect(bind)
    indexes = _index_names(inspector, "connector_approvals")
    for name, cols in {
        "ix_connector_approvals_organization_id": ["organization_id"],
        "ix_connector_approvals_creator_id": ["creator_id"],
        "ix_connector_approvals_connector_type": ["connector_type"],
        "ix_connector_approvals_requested_action": ["requested_action"],
        "ix_connector_approvals_requested_by_user_id": ["requested_by_user_id"],
        "ix_connector_approvals_status": ["status"],
        "ix_connector_approvals_risk_level": ["risk_level"],
        "ix_connector_approvals_expires_at": ["expires_at"],
        "ix_connector_approvals_created_at": ["created_at"],
    }.items():
        if name not in indexes:
            op.create_index(name, "connector_approvals", cols)

    # ── kill_switches ──────────────────────────────────────────────────
    if not inspector.has_table("kill_switches"):
        op.create_table(
            "kill_switches",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("scope", sa.String(), nullable=False),
            sa.Column("scope_id", sa.String(), nullable=True),
            sa.Column(
                "enabled", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column("reason", sa.String(), nullable=True),
            sa.Column("enabled_by_user_id", sa.Uuid(), nullable=True),
            sa.Column("enabled_by_email", sa.String(), nullable=True),
            sa.Column("disabled_by_user_id", sa.Uuid(), nullable=True),
            sa.Column("disabled_by_email", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("disabled_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = sa.inspect(bind)
    indexes = _index_names(inspector, "kill_switches")
    for name, cols in {
        "ix_kill_switches_scope": ["scope"],
        "ix_kill_switches_scope_id": ["scope_id"],
        "ix_kill_switches_enabled": ["enabled"],
        "ix_kill_switches_updated_at": ["updated_at"],
    }.items():
        if name not in indexes:
            op.create_index(name, "kill_switches", cols)

    # ── client_consents ────────────────────────────────────────────────
    if not inspector.has_table("client_consents"):
        op.create_table(
            "client_consents",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("organization_id", sa.Uuid(), nullable=True),
            sa.Column("creator_id", sa.String(), nullable=True),
            sa.Column("consent_type", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("granted_by_user_id", sa.Uuid(), nullable=True),
            sa.Column("granted_by_email", sa.String(), nullable=True),
            sa.Column("granted_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True),
            sa.Column("revoked_by_email", sa.String(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("source", sa.String(), nullable=True),
            sa.Column("document_reference", sa.String(), nullable=True),
            sa.Column("notes", sa.String(), nullable=True),
            sa.Column(
                "metadata_json", sa.JSON(), nullable=False, server_default="{}"
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = sa.inspect(bind)
    indexes = _index_names(inspector, "client_consents")
    for name, cols in {
        "ix_client_consents_organization_id": ["organization_id"],
        "ix_client_consents_creator_id": ["creator_id"],
        "ix_client_consents_consent_type": ["consent_type"],
        "ix_client_consents_status": ["status"],
        "ix_client_consents_expires_at": ["expires_at"],
    }.items():
        if name not in indexes:
            op.create_index(name, "client_consents", cols)

    # ── creator_credentials ────────────────────────────────────────────
    if not inspector.has_table("creator_credentials"):
        op.create_table(
            "creator_credentials",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("organization_id", sa.Uuid(), nullable=True),
            sa.Column("creator_id", sa.String(), nullable=False),
            sa.Column("provider", sa.String(), nullable=False),
            sa.Column("credential_type", sa.String(), nullable=False),
            sa.Column("encrypted_value", sa.Text(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="active"),
            sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
            sa.Column("created_by_email", sa.String(), nullable=True),
            sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True),
            sa.Column("revoked_by_email", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("rotated_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("last_used_at", sa.DateTime(), nullable=True),
            sa.Column(
                "metadata_json", sa.JSON(), nullable=False, server_default="{}"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    inspector = sa.inspect(bind)
    indexes = _index_names(inspector, "creator_credentials")
    for name, cols in {
        "ix_creator_credentials_organization_id": ["organization_id"],
        "ix_creator_credentials_creator_id": ["creator_id"],
        "ix_creator_credentials_provider": ["provider"],
        "ix_creator_credentials_credential_type": ["credential_type"],
        "ix_creator_credentials_status": ["status"],
    }.items():
        if name not in indexes:
            op.create_index(name, "creator_credentials", cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in (
        "creator_credentials",
        "client_consents",
        "kill_switches",
        "connector_approvals",
    ):
        if inspector.has_table(table):
            indexes = _index_names(inspector, table)
            for name in list(indexes):
                if name.startswith(f"ix_{table}_"):
                    op.drop_index(name, table_name=table)
            op.drop_table(table)
        inspector = sa.inspect(bind)
