"""Add hardening columns: gateways.encrypted_token, app_settings.organization_id.

Revision ID: c23d4e5f6a7b
Revises: b12c3d4e5f6a
Create Date: 2026-04-29 02:00:00.000000

Sprint 3 hardening migration. Two additive changes:

1. ``gateways.encrypted_token`` (nullable). New writes go here as Fernet
   ciphertext via ``app.services.gateway_tokens.set_token``. Reads
   prefer this column and fall back to the legacy plaintext ``token``
   column so existing rows keep working until the operator runs the
   one-shot migrator (``app.services.gateway_tokens.migrate_legacy_tokens``).

2. ``app_settings.organization_id`` (nullable, indexed). NULL means
   "global / legacy". Sprint 3 writes pass an org_id when an
   organization context is available; reads prefer org-specific then
   fall back to global.

The migration is fully idempotent — every column/index check is
guarded by inspector queries — so re-runs are safe.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c23d4e5f6a7b"
down_revision = "b12c3d4e5f6a"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {col["name"] for col in inspector.get_columns(table)}


def _index_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {idx["name"] for idx in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("gateways"):
        cols = _column_names(inspector, "gateways")
        if "encrypted_token" not in cols:
            op.add_column(
                "gateways",
                sa.Column("encrypted_token", sa.Text(), nullable=True),
            )

    if inspector.has_table("app_settings"):
        cols = _column_names(inspector, "app_settings")
        if "organization_id" not in cols:
            op.add_column(
                "app_settings",
                sa.Column("organization_id", sa.Uuid(), nullable=True),
            )
        inspector = sa.inspect(bind)
        indexes = _index_names(inspector, "app_settings")
        if "ix_app_settings_organization_id" not in indexes:
            op.create_index(
                "ix_app_settings_organization_id",
                "app_settings",
                ["organization_id"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("app_settings"):
        indexes = _index_names(inspector, "app_settings")
        if "ix_app_settings_organization_id" in indexes:
            op.drop_index("ix_app_settings_organization_id", table_name="app_settings")
        cols = _column_names(inspector, "app_settings")
        if "organization_id" in cols:
            op.drop_column("app_settings", "organization_id")

    if inspector.has_table("gateways"):
        cols = _column_names(inspector, "gateways")
        if "encrypted_token" in cols:
            op.drop_column("gateways", "encrypted_token")
