"""Mission Control bot registry — unified directory of bots / agents / publishers.

This is intentionally a *reference* registry, not an actuator.  Rows describe
what bots Mission Control knows about, who is allowed to operate them, and
their last observed status.  Actual orchestration of bot processes
(scheduler ticks, supervisor loops, launchd services) happens elsewhere —
the registry only records intent + outcome.

Privacy contract:
  • No secrets or webhook URLs in any column.  ``config_json`` is
    free-form but must hold only non-sensitive operational config
    (display names, slugs, doc references).
  • No fan PII, no message bodies, no API responses.
  • ``last_error_summary`` is a short coded reason; never raw stack
    traces or upstream payloads.

Roles (operator semantics):
  • ``permitted_roles`` defaults to ``["owner"]``; owner can edit it to
    grant operator (or others) permission to start/stop a specific bot.
  • Bots marked ``read_only_external`` always reject start/stop requests
    regardless of role (e.g. Hermes, Radar — managed by launchd, not
    by Mission Control).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel

from app.core.time import utcnow

# Bot kinds — kept as plain strings so we can extend without a migration.
# Conventions:
#   scheduler          — in-process tick loop (e.g. Daily QC scheduler)
#   publisher          — message/webhook publisher (Discord / Telegram QC)
#   bridge             — inter-service bridge process
#   control_loop       — a Mission Control orchestration loop
#   read_only_external — managed by an external supervisor (launchd,
#                        cloudflared, systemd); MC only reflects status
BOT_KIND_SCHEDULER = "scheduler"
BOT_KIND_PUBLISHER = "publisher"
BOT_KIND_BRIDGE = "bridge"
BOT_KIND_CONTROL_LOOP = "control_loop"
BOT_KIND_READ_ONLY_EXTERNAL = "read_only_external"

VALID_BOT_KINDS: frozenset[str] = frozenset(
    {
        BOT_KIND_SCHEDULER,
        BOT_KIND_PUBLISHER,
        BOT_KIND_BRIDGE,
        BOT_KIND_CONTROL_LOOP,
        BOT_KIND_READ_ONLY_EXTERNAL,
    }
)

# Status values used by the actuator and surfaced to the UI.
BOT_STATUS_IDLE = "idle"
BOT_STATUS_RUNNING = "running"
BOT_STATUS_DISABLED = "disabled"
BOT_STATUS_ERROR = "error"
BOT_STATUS_UNKNOWN = "unknown"

VALID_BOT_STATUSES: frozenset[str] = frozenset(
    {
        BOT_STATUS_IDLE,
        BOT_STATUS_RUNNING,
        BOT_STATUS_DISABLED,
        BOT_STATUS_ERROR,
        BOT_STATUS_UNKNOWN,
    }
)


class BotRegistryEntry(SQLModel, table=True):
    """One row per known Mission Control bot.

    Seeded at startup (see ``app.services.bot_registry.bootstrap_seed``).
    Owner can edit ``permitted_roles`` to grant operators access on a
    per-bot basis.  Status fields are updated by the actuator.
    """

    __tablename__ = "bot_registry"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    slug: str = Field(index=True, unique=True, max_length=64)
    name: str = Field(max_length=128)
    kind: str = Field(default=BOT_KIND_READ_ONLY_EXTERNAL, max_length=32)
    description: str | None = Field(default=None, max_length=512)

    # Operational state
    enabled: bool = Field(default=False)
    safe_mode: bool = Field(default=True)
    status: str = Field(default=BOT_STATUS_UNKNOWN, max_length=32)
    last_status_detail: str | None = Field(default=None, max_length=256)
    last_run_at: datetime | None = Field(default=None)
    last_error_summary: str | None = Field(default=None, max_length=256)

    # Sandbox / live-write gates (added for X DM Bot RTxRT MVP).
    #
    #   live_writes_enabled — hardcoded ``False`` in MVP for every bot
    #     that exposes a sandbox/live distinction.  Service + API layers
    #     refuse any path that would flip this to ``True``.
    #   sandbox_mode        — when ``True``, run logic must produce only
    #     dry-run output: no AdsPower calls, no Playwright, no X.com
    #     navigation, no platform writes.
    #   kill_switch_active  — when ``True``, queued runs are cancelled
    #     and new runs are rejected.  Owner-only flip.
    #   version             — display string for the UI; not a schema
    #     version.  Free-form ``"1.0.0"``-style.
    live_writes_enabled: bool = Field(default=False)
    sandbox_mode: bool = Field(default=True)
    kill_switch_active: bool = Field(default=False)
    version: str | None = Field(default=None, max_length=32)

    # Permissions — JSON-encoded list of role strings.  We keep this as
    # ``Column(String)`` with JSON-encoded text on SQLite for portability;
    # Postgres production gets the same string type and we json.loads()
    # in the service layer.  Default = owner-only.
    permitted_roles_json: str = Field(
        default='["owner"]',
        sa_column=Column("permitted_roles_json", String(256), nullable=False, default='["owner"]'),
    )

    # Free-form non-sensitive config (display hints, doc URLs, etc.).
    # Stored as JSON-text for the same portability reason.
    config_json: str | None = Field(
        default=None,
        sa_column=Column("config_json", String(2048), nullable=True),
    )

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


__all__ = [
    "BOT_KIND_BRIDGE",
    "BOT_KIND_CONTROL_LOOP",
    "BOT_KIND_PUBLISHER",
    "BOT_KIND_READ_ONLY_EXTERNAL",
    "BOT_KIND_SCHEDULER",
    "BOT_STATUS_DISABLED",
    "BOT_STATUS_ERROR",
    "BOT_STATUS_IDLE",
    "BOT_STATUS_RUNNING",
    "BOT_STATUS_UNKNOWN",
    "BotRegistryEntry",
    "VALID_BOT_KINDS",
    "VALID_BOT_STATUSES",
]
