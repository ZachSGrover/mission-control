"""Mission Control bot run + run-output models — sandbox-safe execution records.

These tables capture *intent* and *dry-run* activity for Mission Control
bots that need an operator/owner-driven run lifecycle (draft → queued →
running → completed).  They are designed for the X DM Bot RTxRT MVP,
which runs **sandbox-only**: no live platform writes happen anywhere on
the path that touches these rows.

Privacy contract:
  • ``bot_runs.message_preview`` is capped at 100 chars on the column
    and the application layer truncates inputs to 80 chars.  The full
    user-supplied message is intentionally NOT stored — neither here
    nor in any other table — for this MVP.
  • ``bot_run_outputs.content_json`` only ever holds redacted dry-run
    summaries.  Mock conversation URLs use a ``redacted://`` scheme so
    no real X.com URL ever lands in the DB.
  • Tokens, cookies, AdsPower API keys, and account credentials are
    forbidden in every column.  Enforcement is at the service layer.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel

from app.core.time import utcnow

# Run lifecycle.  MVP only emits the subset documented below; the
# remaining values are reserved for future live-mode work and must not
# be reachable in this MVP's code paths.
RUN_STATUS_DRAFT = "draft"
RUN_STATUS_QUEUED = "queued"
RUN_STATUS_RUNNING_SCAN = "running_scan"
RUN_STATUS_RUNNING_SEND = "running_send"
RUN_STATUS_NEEDS_REVIEW = "needs_review"
RUN_STATUS_APPROVED = "approved"
RUN_STATUS_REJECTED = "rejected"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_PAUSED = "paused"
RUN_STATUS_ARCHIVED = "archived"

VALID_RUN_STATUSES: frozenset[str] = frozenset(
    {
        RUN_STATUS_DRAFT,
        RUN_STATUS_QUEUED,
        RUN_STATUS_RUNNING_SCAN,
        RUN_STATUS_RUNNING_SEND,
        RUN_STATUS_NEEDS_REVIEW,
        RUN_STATUS_APPROVED,
        RUN_STATUS_REJECTED,
        RUN_STATUS_COMPLETED,
        RUN_STATUS_FAILED,
        RUN_STATUS_PAUSED,
        RUN_STATUS_ARCHIVED,
    }
)

# Statuses the MVP is allowed to set or transition into.  Anything not
# in this set must be rejected by the service layer.
MVP_ALLOWED_RUN_STATUSES: frozenset[str] = frozenset(
    {
        RUN_STATUS_DRAFT,
        RUN_STATUS_QUEUED,
        RUN_STATUS_RUNNING_SCAN,
        RUN_STATUS_COMPLETED,
        RUN_STATUS_FAILED,
        RUN_STATUS_PAUSED,
        RUN_STATUS_REJECTED,
    }
)

# Run mode.  ``sandbox`` is the only legal value in MVP; ``live`` is
# rejected at every API entry point.
RUN_MODE_SANDBOX = "sandbox"
RUN_MODE_LIVE = "live"

# Output kinds for ``bot_run_outputs``.
OUTPUT_TYPE_DRY_RUN_LIST = "dry_run_list"
OUTPUT_TYPE_SCAN_SUMMARY = "scan_summary"
OUTPUT_TYPE_ERROR_LOG = "error_log"
OUTPUT_TYPE_RUN_LOG = "run_log"

VALID_OUTPUT_TYPES: frozenset[str] = frozenset(
    {
        OUTPUT_TYPE_DRY_RUN_LIST,
        OUTPUT_TYPE_SCAN_SUMMARY,
        OUTPUT_TYPE_ERROR_LOG,
        OUTPUT_TYPE_RUN_LOG,
    }
)


class BotRun(SQLModel, table=True):
    """One sandbox or (eventually) live run of a Mission Control bot.

    In MVP every row created here is a sandbox run; the service layer
    refuses to set ``mode`` to anything other than ``sandbox``.
    """

    __tablename__ = "bot_runs"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    bot_id: UUID = Field(index=True, foreign_key="bot_registry.id")

    # Lifecycle
    status: str = Field(default=RUN_STATUS_DRAFT, index=True, max_length=32)
    mode: str = Field(default=RUN_MODE_SANDBOX, index=True, max_length=16)

    # Profile metadata (mock profiles in MVP).  ``profile_id`` is a
    # short stable string we control — it is NOT an AdsPower profile id
    # and the service layer rejects anything that looks like one.
    profile_id: str = Field(index=True, max_length=64)
    profile_name: str = Field(max_length=128)

    # Privacy: 100-char column hard cap; service layer truncates
    # incoming messages to 80 chars before persisting.  Full message
    # body is never stored anywhere.
    message_preview: str | None = Field(default=None, max_length=100)

    # Counts.  ``sent_count`` is always 0 in MVP because no live sends
    # happen — kept on the schema so future live-mode rows have a place
    # to land without another migration.
    target_count: int = Field(default=0)
    sent_count: int = Field(default=0)
    scan_count: int = Field(default=0)
    readonly_count: int = Field(default=0)
    elapsed_seconds: int | None = Field(default=None)

    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    created_by: str | None = Field(default=None, max_length=255)
    error_message: str | None = Field(
        default=None,
        sa_column=Column("error_message", String(512), nullable=True),
    )

    created_at: datetime = Field(default_factory=utcnow, index=True)
    updated_at: datetime = Field(default_factory=utcnow)


class BotRunOutput(SQLModel, table=True):
    """A piece of structured output attached to a bot run.

    ``content_json`` is a JSON-encoded string holding redacted
    dry-run / scan summaries.  Real X.com URLs, cookies, tokens, and
    raw message bodies must never appear here — the service layer is
    responsible for redaction.
    """

    __tablename__ = "bot_run_outputs"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID = Field(index=True, foreign_key="bot_runs.id")
    output_type: str = Field(index=True, max_length=32)
    content_json: str = Field(
        sa_column=Column("content_json", String(8192), nullable=False),
    )
    created_at: datetime = Field(default_factory=utcnow, index=True)


__all__ = [
    "MVP_ALLOWED_RUN_STATUSES",
    "OUTPUT_TYPE_DRY_RUN_LIST",
    "OUTPUT_TYPE_ERROR_LOG",
    "OUTPUT_TYPE_RUN_LOG",
    "OUTPUT_TYPE_SCAN_SUMMARY",
    "RUN_MODE_LIVE",
    "RUN_MODE_SANDBOX",
    "RUN_STATUS_APPROVED",
    "RUN_STATUS_ARCHIVED",
    "RUN_STATUS_COMPLETED",
    "RUN_STATUS_DRAFT",
    "RUN_STATUS_FAILED",
    "RUN_STATUS_NEEDS_REVIEW",
    "RUN_STATUS_PAUSED",
    "RUN_STATUS_QUEUED",
    "RUN_STATUS_REJECTED",
    "RUN_STATUS_RUNNING_SCAN",
    "RUN_STATUS_RUNNING_SEND",
    "BotRun",
    "BotRunOutput",
    "VALID_OUTPUT_TYPES",
    "VALID_RUN_STATUSES",
]
