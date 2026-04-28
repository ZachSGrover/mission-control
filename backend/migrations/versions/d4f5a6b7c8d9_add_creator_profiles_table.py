"""Add of_intelligence_creator_profiles.

Permanent intelligence profile per creator account.  One row per
`(source, source_account_id)` — auto-populated identity fields come from
the synced `of_intelligence_accounts.raw` payload, the rest are operator-
managed strategy / brand / notes fields that never get overwritten by a
sync.

Design notes:
  • Separate table (instead of extending `of_intelligence_accounts`) so
    machine-managed sync data and human-managed notes have clear
    ownership and can never be clobbered by a sync.
  • Profile rows are reconciled lazily — the list endpoint creates a
    profile for any synced account that lacks one.
  • `raw_source_payload` snapshots the most-recent OnlyMonster account
    payload at reconcile time, useful for audits without joining
    `of_intelligence_accounts`.
  • UNIQUE on `(source, source_account_id)` mirrors the convention
    used everywhere else in OFI.

Revision ID: d4f5a6b7c8d9
Revises: c3e4f5a6b7c8
Create Date: 2026-04-28 16:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d4f5a6b7c8d9"
down_revision = "c3e4f5a6b7c8"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return inspector.has_table(name)


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    json_type = postgresql.JSONB(astext_type=sa.Text()) if is_postgres else sa.JSON()
    uuid_type = postgresql.UUID(as_uuid=True) if is_postgres else sa.String(length=36)

    if _has_table("of_intelligence_creator_profiles"):
        return

    op.create_table(
        "of_intelligence_creator_profiles",
        sa.Column("id", uuid_type, primary_key=True),
        # ── Linkage / identity (auto, from synced accounts) ─────────────
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("source_account_id", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("platform", sa.String(length=64), nullable=True),
        sa.Column("organisation_id", sa.String(length=255), nullable=True),
        sa.Column("subscribe_price_cents", sa.Integer(), nullable=True),
        sa.Column("subscription_expiration_date", sa.DateTime(), nullable=True),
        sa.Column("access_status", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("last_account_sync_at", sa.DateTime(), nullable=True),
        # ── Operator-managed strategy / brand fields ────────────────────
        sa.Column("brand_persona", sa.Text(), nullable=True),
        sa.Column("content_pillars", sa.Text(), nullable=True),
        sa.Column("voice_tone", sa.Text(), nullable=True),
        sa.Column("audience_summary", sa.Text(), nullable=True),
        sa.Column("monetization_focus", sa.Text(), nullable=True),
        sa.Column("posting_cadence", sa.Text(), nullable=True),
        sa.Column("strategy_summary", sa.Text(), nullable=True),
        sa.Column("off_limits", sa.Text(), nullable=True),
        sa.Column("vault_notes", sa.Text(), nullable=True),
        sa.Column("agency_notes", sa.Text(), nullable=True),
        # ── External presence (manual) ──────────────────────────────────
        sa.Column("onlyfans_url", sa.Text(), nullable=True),
        sa.Column("instagram_url", sa.Text(), nullable=True),
        sa.Column("twitter_url", sa.Text(), nullable=True),
        sa.Column("tiktok_url", sa.Text(), nullable=True),
        sa.Column("threads_url", sa.Text(), nullable=True),
        sa.Column("reddit_url", sa.Text(), nullable=True),
        # ── Audit / lineage ─────────────────────────────────────────────
        sa.Column("raw_source_payload", json_type, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "source",
            "source_account_id",
            name="uq_ofi_creator_profiles_source_account",
        ),
    )
    op.create_index(
        "ix_ofi_creator_profiles_source",
        "of_intelligence_creator_profiles",
        ["source"],
    )
    op.create_index(
        "ix_ofi_creator_profiles_source_account_id",
        "of_intelligence_creator_profiles",
        ["source_account_id"],
    )
    op.create_index(
        "ix_ofi_creator_profiles_username",
        "of_intelligence_creator_profiles",
        ["username"],
    )
    op.create_index(
        "ix_ofi_creator_profiles_updated_at",
        "of_intelligence_creator_profiles",
        ["updated_at"],
    )


def downgrade() -> None:
    if _has_table("of_intelligence_creator_profiles"):
        op.drop_table("of_intelligence_creator_profiles")
