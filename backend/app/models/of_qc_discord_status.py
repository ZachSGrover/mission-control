"""Single-row settings table for the OF Intelligence QC Discord card.

Holds the operator-facing kill-switch toggle and the most recent test-alert
outcome (success timestamp / failure timestamp + reason + status code) so
the Settings UI can render an accurate "Connected" / "Last test failed"
state without re-probing Discord.

The webhook URL itself is never stored here — it lives encrypted in the
``app_settings`` row keyed by ``discord.qc.webhook_url`` (see
``app.core.secrets_store``).

Why a dedicated table:
  • Toggle and timestamps are typed, indexed values — not secrets, so
    ``app_settings`` (encrypted KV) would be the wrong fit.
  • Single-row pattern: we always read/write the row with id=1.  Any
    historical rows are ignored by the API layer.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class OfQcDiscordStatus(SQLModel, table=True):
    """Operator state for the QC Discord integration card.

    Single-row table.  The API layer always reads/writes ``id == 1``.
    """

    __tablename__ = "of_qc_discord_status"  # pyright: ignore[reportAssignmentType]

    id: int = Field(default=1, primary_key=True)
    enabled: bool = Field(default=False)
    last_success_at: datetime | None = Field(default=None)
    last_failure_at: datetime | None = Field(default=None)
    last_failure_reason: str | None = Field(default=None, max_length=64)
    last_failure_status: int | None = Field(default=None)
    # Privacy mode for Discord rendering.  ``safe_summary`` (default) shows
    # only display names + counts + refs.  ``internal_detail`` requires an
    # additional env-var assertion at render time before any extra detail
    # is included; see ``services/of_intelligence/qc/privacy_modes.py``.
    privacy_mode: str = Field(default="safe_summary", max_length=32)
    # Per-channel toggle for the Telegram daily-summary publisher.  Default
    # off; flipping requires an existing Telegram bot token + chat id.
    telegram_enabled: bool = Field(default=False)
    # Master toggle for the Daily QC scheduler — when False, the scheduler
    # background loop records ``skipped`` rows and never runs evaluate /
    # daily-summary jobs.  Independent from per-channel toggles.
    daily_qc_enabled: bool = Field(default=False)
    # Live-send permission.  When False, scheduler-context publishes return
    # ``skipped(reason=live_send_disabled)`` regardless of the per-channel
    # toggles above.  Operator-initiated test alerts (Send Test Alert
    # button) bypass this gate via ``bypass_kill_switch=True`` so the
    # operator can verify a webhook before flipping live sending on.
    live_send_enabled: bool = Field(default=False)
    updated_at: datetime = Field(default_factory=utcnow)
