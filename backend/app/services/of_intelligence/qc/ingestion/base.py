"""Daily QC ingestion contract — read-only, privacy-safe normalized input.

The ingestion layer lets the QC evaluator consume different *sources* of
account-level metrics (synthetic fixtures, local OFI database rows,
future external connectors) through a single dataclass interface.

Hard rules baked into ``AccountMetrics``:
  • NO message bodies.  NO fan handles.  NO raw API payloads.
  • Only aggregated counts, safe display names, timestamps, and a
    ``source_confidence`` rating.
  • ``account_id`` is the internal stable id (e.g. OnlyMonster
    ``source_id``); it is NEVER rendered to Discord/Telegram on its own.
  • ``account_label`` is a display-safe string (the OFI account
    ``username``/``display_name``).  This may render to Discord/Telegram
    via the existing publisher allowlist.
  • ``operator_id`` (chatter source_id) is internal-only for grouping
    findings; never rendered to outbound channels.

Source modes (string, persisted on ``of_qc_discord_status``):
  • ``synthetic``  — deterministic fixture, default and always safe
  • ``local_ofi`` — read existing OFI tables (no external network)
  • ``onlymonster_readonly`` — RESERVED, off by default; v1 returns
    a ``data_source_disconnected`` finding when selected
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal

from sqlmodel.ext.asyncio.session import AsyncSession

# ── Source modes ─────────────────────────────────────────────────────────────


class SourceMode(str, Enum):
    SYNTHETIC = "synthetic"
    LOCAL_OFI = "local_ofi"
    ONLYMONSTER_READONLY = "onlymonster_readonly"  # disabled by default

    @classmethod
    def coerce(cls, value: str | "SourceMode" | None) -> "SourceMode":
        if isinstance(value, cls):
            return value
        if not value:
            return cls.SYNTHETIC
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.SYNTHETIC


SourceConfidence = Literal["high", "medium", "low", "unknown"]


# ── Normalized input ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AccountMetrics:
    """Per-account snapshot used by the QC evaluator.

    Every field is privacy-safe by construction: no fan handles, no
    message bodies, no raw API payloads.
    """

    account_id: str  # internal stable id (e.g. OnlyMonster source_id)
    account_label: str | None  # display-safe; may render to Discord
    period_start: datetime
    period_end: datetime
    revenue_cents: int  # within (period_start, period_end]
    previous_revenue_cents: int  # 7-day prior daily-avg total
    message_count: int | None = None  # total messages in window (any direction)
    paid_message_count: int | None = None  # messages with revenue_cents > 0
    purchase_count: int | None = None  # mass-message purchases or PPV unlocks
    median_reply_minutes: int | None = None  # safe aggregate
    operator_id: str | None = None  # chatter source_id (internal only)
    source: str = "synthetic"  # mirrors SourceMode value
    source_confidence: SourceConfidence = "high"
    last_synced_at: datetime | None = None
    has_recent_sync_failure: bool = False


@dataclass(frozen=True)
class IngestionResult:
    """What an ingestion source returns to the scheduler tick."""

    source_mode: SourceMode
    source_confidence: SourceConfidence
    safe_mode: bool  # always True in v1
    accounts: list[AccountMetrics] = field(default_factory=list)
    skipped_reason: str | None = None  # e.g. "data_source_disconnected"
    notes: list[str] = field(default_factory=list)


# ── Source registration ─────────────────────────────────────────────────────


SourceFn = Callable[[AsyncSession], Awaitable[IngestionResult]]
