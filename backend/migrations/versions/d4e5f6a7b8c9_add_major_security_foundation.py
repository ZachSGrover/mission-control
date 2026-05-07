"""Add Major Security foundation (prevention + hardening + audit columns).

Revision ID: d4e5f6a7b8c9
Revises: h4b9d3e1c802
Create Date: 2026-05-07 00:00:00.000000

This migration consolidates the Major Security lane (Sprints 1-3) into
ONE file per PR-policy (``scripts/ci/one_migration_per_pr.sh``), and is
re-parented onto PR #21's ``h4b9d3e1c802`` head so the post-merge chain
remains linear.

Sprint 1 (audit_events table) is NO LONGER created here. PR #21 already
creates ``audit_events`` and ``bot_registry`` in
``h4b9d3e1c802_add_audit_events_and_bot_registry.py``. The Major Security
lane reuses that single table and adds the columns it needs as nullable
extras so neither audit-write API constrains the other:

  • ``record_audit`` (PR #21's narrow signature, used by COO/operator/
    bot workflows) populates ``actor_clerk_user_id``, ``action``,
    ``target_type``, ``target_id``, ``outcome``, ``safe_summary``,
    ``payload_hash``.
  • ``record_audit_event`` (Major Security's structured signature,
    used by the security gates) ALSO populates the wider columns added
    here: ``actor_user_id``, ``organization_id``, ``creator_id``,
    ``event_type``, ``category``, ``result``, ``severity``,
    ``resource_type``, ``resource_id``, ``request_id``,
    ``metadata_json``, ``redacted``.

The two original Sprint-1 audit-events indexes that overlap with PR
#21's set (``ix_audit_events_action``, ``ix_audit_events_created_at``)
are NOT re-added here — PR #21 already created them. The other Major
Security indexes (organization_id, creator_id, event_type, category,
result, severity, resource_type, redacted, actor_user_id) are added
fresh.

Sprint 2 prevention tables and Sprint 3 hardening columns continue to
live in this migration unchanged from the pre-PR-21 design:

    Sprint 2:
      • connector_approvals + indexes
      • kill_switches + indexes
      • client_consents + indexes
      • creator_credentials + indexes

    Sprint 3:
      • gateways.encrypted_token
      • app_settings.organization_id + index

The downgrade reverses the upgrade in strict LIFO order. The audit
columns are dropped, but the audit_events table itself is left in
place because PR #21 owns its lifecycle.

Idempotency baked in: every create / add is guarded by an inspector
check, so re-runs are safe and partially-applied environments converge
without manual cleanup.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "h4b9d3e1c802"
branch_labels = None
depends_on = None


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {item["name"] for item in inspector.get_indexes(table_name)}


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {col["name"] for col in inspector.get_columns(table)}


# ── Upgrade ──────────────────────────────────────────────────────────────────


def upgrade() -> None:  # noqa: C901 — flat list of guarded creates
    """Add Major Security columns to audit_events, create prevention
    tables, add hardening columns. Idempotent."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── Sprint 1 → extension: add Major Security columns to PR #21's
    #    ``audit_events`` table. All nullable so PR #21's writes still work.
    if inspector.has_table("audit_events"):
        cols = _column_names(inspector, "audit_events")
        # Wider actor / scope.
        if "actor_user_id" not in cols:
            op.add_column(
                "audit_events",
                sa.Column("actor_user_id", sa.Uuid(), nullable=True),
            )
        if "organization_id" not in cols:
            op.add_column(
                "audit_events",
                sa.Column("organization_id", sa.Uuid(), nullable=True),
            )
        if "creator_id" not in cols:
            op.add_column(
                "audit_events",
                sa.Column("creator_id", sa.String(), nullable=True),
            )
        # Major Security event taxonomy (all nullable — PR #21 callers
        # leave them ``None``; security callers populate them).
        if "event_type" not in cols:
            op.add_column(
                "audit_events",
                sa.Column("event_type", sa.String(), nullable=True),
            )
        if "category" not in cols:
            op.add_column(
                "audit_events",
                sa.Column("category", sa.String(), nullable=True),
            )
        if "result" not in cols:
            op.add_column(
                "audit_events",
                sa.Column("result", sa.String(), nullable=True),
            )
        if "severity" not in cols:
            op.add_column(
                "audit_events",
                sa.Column("severity", sa.String(), nullable=True),
            )
        # Resource columns — PR #21 has target_type/target_id; security
        # uses resource_type/resource_id. Both columns coexist; the
        # service layer populates whichever the call site expects.
        if "resource_type" not in cols:
            op.add_column(
                "audit_events",
                sa.Column("resource_type", sa.String(), nullable=True),
            )
        if "resource_id" not in cols:
            op.add_column(
                "audit_events",
                sa.Column("resource_id", sa.String(), nullable=True),
            )
        if "request_id" not in cols:
            op.add_column(
                "audit_events",
                sa.Column("request_id", sa.String(), nullable=True),
            )
        if "metadata_json" not in cols:
            op.add_column(
                "audit_events",
                sa.Column("metadata_json", sa.JSON(), nullable=True),
            )
        if "redacted" not in cols:
            op.add_column(
                "audit_events",
                sa.Column("redacted", sa.Boolean(), nullable=True),
            )

        # Add the Major Security indexes that PR #21 didn't create.
        inspector = sa.inspect(bind)
        idx = _index_names(inspector, "audit_events")
        for name, cols_for_index in {
            "ix_audit_events_actor_user_id": ["actor_user_id"],
            "ix_audit_events_organization_id": ["organization_id"],
            "ix_audit_events_creator_id": ["creator_id"],
            "ix_audit_events_event_type": ["event_type"],
            "ix_audit_events_category": ["category"],
            "ix_audit_events_result": ["result"],
            "ix_audit_events_severity": ["severity"],
            "ix_audit_events_resource_type": ["resource_type"],
            "ix_audit_events_redacted": ["redacted"],
        }.items():
            if name not in idx:
                op.create_index(name, "audit_events", cols_for_index)

    # ── Sprint 2: prevention tables ─────────────────────────────────────
    inspector = sa.inspect(bind)

    # connector_approvals
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
            sa.Column("risk_level", sa.String(), nullable=False, server_default="medium"),
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

    # kill_switches
    if not inspector.has_table("kill_switches"):
        op.create_table(
            "kill_switches",
            sa.Column("id", sa.Uuid(), nullable=False),
            sa.Column("scope", sa.String(), nullable=False),
            sa.Column("scope_id", sa.String(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
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

    # client_consents
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
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
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

    # creator_credentials
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
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
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

    # ── Sprint 3: hardening columns ─────────────────────────────────────
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


# ── Downgrade ────────────────────────────────────────────────────────────────


def downgrade() -> None:
    """Reverse the upgrade in strict LIFO order: hardening → prevention →
    audit columns. The ``audit_events`` table itself is NOT dropped — PR
    #21 owns its lifecycle. We only remove the Major Security extension
    columns and indexes."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── Sprint 3: hardening columns (reverse) ───────────────────────────
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

    # ── Sprint 2: prevention tables (reverse) ───────────────────────────
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

    # ── Sprint 1 extension: drop Major Security columns from
    #    audit_events. Leave the table itself (PR #21 owns it).
    if inspector.has_table("audit_events"):
        idx = _index_names(inspector, "audit_events")
        for name in (
            "ix_audit_events_redacted",
            "ix_audit_events_resource_type",
            "ix_audit_events_severity",
            "ix_audit_events_result",
            "ix_audit_events_category",
            "ix_audit_events_event_type",
            "ix_audit_events_creator_id",
            "ix_audit_events_organization_id",
            "ix_audit_events_actor_user_id",
        ):
            if name in idx:
                op.drop_index(name, table_name="audit_events")
        cols = _column_names(inspector, "audit_events")
        for col in (
            "redacted",
            "metadata_json",
            "request_id",
            "resource_id",
            "resource_type",
            "severity",
            "result",
            "category",
            "event_type",
            "creator_id",
            "organization_id",
            "actor_user_id",
        ):
            if col in cols:
                op.drop_column("audit_events", col)
