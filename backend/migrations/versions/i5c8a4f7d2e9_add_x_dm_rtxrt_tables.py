"""Add X DM Bot RTxRT MVP tables + bot_registry sandbox columns.

Adds the sandbox-only run lifecycle tables for the X DM Bot RTxRT MVP
plus four new columns on the existing ``bot_registry`` table to express
the live-writes-disabled / sandbox-mode / kill-switch state.

New tables:
  • ``bot_runs``           — one row per draft/sandbox run.
  • ``bot_run_outputs``    — structured run output (dry-run lists,
                              scan summaries, error logs, run logs).
  • ``bot_contact_archive`` — per-(bot, profile, handle) archive used
                              by sandbox dedup + the operator contact
                              archive view.
  • ``safety_events``       — append-only safety/kill-switch trips.

New ``bot_registry`` columns (all defaults safe / off):
  • ``live_writes_enabled``  bool default false
  • ``sandbox_mode``         bool default true
  • ``kill_switch_active``   bool default false
  • ``version``              str  nullable

No data backfill — every new row is empty.  No existing row is mutated;
defaults are applied via ``server_default`` so already-seeded bots
keep working.

Privacy: nothing in these tables accepts secrets, cookies, tokens,
fan PII, message bodies, or platform credentials.  Enforcement is at
the application layer (``app.services.x_dm_rtxrt`` for the bot, plus
the privacy-clean response schemas in ``app.api.x_dm_rtxrt``).

Revision ID: i5c8a4f7d2e9
Revises: h4b9d3e1c802
Create Date: 2026-05-07 12:30:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "i5c8a4f7d2e9"
down_revision = "h4b9d3e1c802"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── bot_registry: add sandbox / live-write / kill-switch columns ────
    if inspector.has_table("bot_registry"):
        cols = {c["name"] for c in inspector.get_columns("bot_registry")}
        if "live_writes_enabled" not in cols:
            op.add_column(
                "bot_registry",
                sa.Column(
                    "live_writes_enabled",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )
        if "sandbox_mode" not in cols:
            op.add_column(
                "bot_registry",
                sa.Column(
                    "sandbox_mode",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                ),
            )
        if "kill_switch_active" not in cols:
            op.add_column(
                "bot_registry",
                sa.Column(
                    "kill_switch_active",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )
        if "version" not in cols:
            op.add_column(
                "bot_registry",
                sa.Column("version", sa.String(length=32), nullable=True),
            )

    existing_tables = set(inspector.get_table_names())

    # ── bot_runs ─────────────────────────────────────────────────────────
    if "bot_runs" not in existing_tables:
        op.create_table(
            "bot_runs",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column(
                "bot_id",
                sa.Uuid(),
                sa.ForeignKey("bot_registry.id"),
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="draft",
            ),
            sa.Column(
                "mode",
                sa.String(length=16),
                nullable=False,
                server_default="sandbox",
            ),
            sa.Column("profile_id", sa.String(length=64), nullable=False),
            sa.Column("profile_name", sa.String(length=128), nullable=False),
            sa.Column("message_preview", sa.String(length=100), nullable=True),
            sa.Column(
                "target_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "sent_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "scan_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "readonly_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("elapsed_seconds", sa.Integer(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.String(length=255), nullable=True),
            sa.Column("error_message", sa.String(length=512), nullable=True),
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
        op.create_index("ix_bot_runs_bot_id", "bot_runs", ["bot_id"])
        op.create_index("ix_bot_runs_status", "bot_runs", ["status"])
        op.create_index("ix_bot_runs_mode", "bot_runs", ["mode"])
        op.create_index("ix_bot_runs_profile_id", "bot_runs", ["profile_id"])
        op.create_index("ix_bot_runs_created_at", "bot_runs", ["created_at"])

    existing_tables = set(inspector.get_table_names())
    if "bot_run_outputs" not in existing_tables:
        op.create_table(
            "bot_run_outputs",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column(
                "run_id",
                sa.Uuid(),
                sa.ForeignKey("bot_runs.id"),
                nullable=False,
            ),
            sa.Column("output_type", sa.String(length=32), nullable=False),
            sa.Column("content_json", sa.String(length=8192), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index("ix_bot_run_outputs_run_id", "bot_run_outputs", ["run_id"])
        op.create_index(
            "ix_bot_run_outputs_output_type",
            "bot_run_outputs",
            ["output_type"],
        )
        op.create_index(
            "ix_bot_run_outputs_created_at",
            "bot_run_outputs",
            ["created_at"],
        )

    existing_tables = set(inspector.get_table_names())
    if "bot_contact_archive" not in existing_tables:
        op.create_table(
            "bot_contact_archive",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column(
                "bot_id",
                sa.Uuid(),
                sa.ForeignKey("bot_registry.id"),
                nullable=False,
            ),
            sa.Column("profile_id", sa.String(length=64), nullable=False),
            sa.Column("handle", sa.String(length=128), nullable=False),
            sa.Column("conversation_url", sa.String(length=512), nullable=False),
            sa.Column("last_sent_at", sa.DateTime(), nullable=True),
            sa.Column(
                "sent_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
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
            "ix_bot_contact_archive_bot_id",
            "bot_contact_archive",
            ["bot_id"],
        )
        op.create_index(
            "ix_bot_contact_archive_profile_id",
            "bot_contact_archive",
            ["profile_id"],
        )
        op.create_index(
            "ix_bot_contact_archive_handle",
            "bot_contact_archive",
            ["handle"],
        )

    existing_tables = set(inspector.get_table_names())
    if "safety_events" not in existing_tables:
        op.create_table(
            "safety_events",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("run_id", sa.Uuid(), nullable=True),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column(
                "severity",
                sa.String(length=16),
                nullable=False,
                server_default="info",
            ),
            sa.Column("description", sa.String(length=512), nullable=False),
            sa.Column(
                "resolved",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )
        op.create_index("ix_safety_events_run_id", "safety_events", ["run_id"])
        op.create_index(
            "ix_safety_events_event_type",
            "safety_events",
            ["event_type"],
        )
        op.create_index("ix_safety_events_severity", "safety_events", ["severity"])
        op.create_index(
            "ix_safety_events_created_at",
            "safety_events",
            ["created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "safety_events" in existing_tables:
        for ix in (
            "ix_safety_events_created_at",
            "ix_safety_events_severity",
            "ix_safety_events_event_type",
            "ix_safety_events_run_id",
        ):
            op.drop_index(ix, table_name="safety_events")
        op.drop_table("safety_events")

    existing_tables = set(inspector.get_table_names())
    if "bot_contact_archive" in existing_tables:
        for ix in (
            "ix_bot_contact_archive_handle",
            "ix_bot_contact_archive_profile_id",
            "ix_bot_contact_archive_bot_id",
        ):
            op.drop_index(ix, table_name="bot_contact_archive")
        op.drop_table("bot_contact_archive")

    existing_tables = set(inspector.get_table_names())
    if "bot_run_outputs" in existing_tables:
        for ix in (
            "ix_bot_run_outputs_created_at",
            "ix_bot_run_outputs_output_type",
            "ix_bot_run_outputs_run_id",
        ):
            op.drop_index(ix, table_name="bot_run_outputs")
        op.drop_table("bot_run_outputs")

    existing_tables = set(inspector.get_table_names())
    if "bot_runs" in existing_tables:
        for ix in (
            "ix_bot_runs_created_at",
            "ix_bot_runs_profile_id",
            "ix_bot_runs_mode",
            "ix_bot_runs_status",
            "ix_bot_runs_bot_id",
        ):
            op.drop_index(ix, table_name="bot_runs")
        op.drop_table("bot_runs")

    if inspector.has_table("bot_registry"):
        cols = {c["name"] for c in inspector.get_columns("bot_registry")}
        for col in ("version", "kill_switch_active", "sandbox_mode", "live_writes_enabled"):
            if col in cols:
                op.drop_column("bot_registry", col)
