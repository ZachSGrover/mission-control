"""MSA RT/X job-queue row.

Each row represents one queued, running, or finished MSA RT/X bot job.
The Mission Control web UI enqueues rows here. The local Claw-computer
runner polls for ``queued`` rows, executes the matching local command,
and PATCHes status back.

Privacy contract:
    * Rows never store secrets. The runner-auth token is shared-secret
      header material only — it never lands in the DB.
    * ``summary`` and ``stdout_excerpt`` / ``error_excerpt`` are
      operator-facing strings that the runner itself must truncate +
      sanitize before sending. The service layer caps the byte length
      again on write.
    * Mass-live job kinds (``live_all_*``, ``live_mass_*``,
      ``live_batch_*``, ``live_many``) cannot be persisted — the
      service layer rejects them and the SQLModel ``Literal``-style
      validation in :func:`app.services.msa_rtxrt_jobs.validate_kind`
      forbids them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Column, Index
from sqlmodel import Field, SQLModel

from app.core.time import utcnow

# ── Status vocabulary ───────────────────────────────────────────────────────

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"
STATUS_CANCELLED = "cancelled"

VALID_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_QUEUED,
        STATUS_RUNNING,
        STATUS_SUCCEEDED,
        STATUS_FAILED,
        STATUS_BLOCKED,
        STATUS_CANCELLED,
    }
)

# Terminal statuses cannot transition further.
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {STATUS_SUCCEEDED, STATUS_FAILED, STATUS_BLOCKED, STATUS_CANCELLED}
)

# Allowed transitions. The dispatcher (runner-poll) atomically flips
# ``queued`` → ``running``; the runner PATCH then flips
# ``running`` → ``succeeded|failed|blocked``. Operators can
# ``queued|running`` → ``cancelled`` via the cancel route (not in v1).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_QUEUED: frozenset({STATUS_RUNNING, STATUS_BLOCKED, STATUS_CANCELLED}),
    STATUS_RUNNING: frozenset({STATUS_SUCCEEDED, STATUS_FAILED, STATUS_BLOCKED, STATUS_CANCELLED}),
}


# ── Job-kind vocabulary ─────────────────────────────────────────────────────

DRY_RUN_KINDS: frozenset[str] = frozenset(
    {
        "smoke",
        "dry_run_blast",
        "dry_run_dm",
        "dry_run_repost",
        "dry_run_builder",
        "dry_run_scan",
    }
)

LIVE_ONE_KINDS: frozenset[str] = frozenset(
    {
        "live_one_blast",
        "live_one_dm",
        "live_one_repost",
        "live_one_builder",
        "live_one_scan",
    }
)

VALID_KINDS: frozenset[str] = DRY_RUN_KINDS | LIVE_ONE_KINDS

# ── Privacy caps ────────────────────────────────────────────────────────────

# Operators must see a *short* sanitized summary; full output never reaches
# Mission Control. These caps are enforced by the service layer too.
MAX_SUMMARY_LEN = 256
MAX_EXCERPT_LEN = 2048


# ── Table ────────────────────────────────────────────────────────────────────


class MsaRtxrtJob(SQLModel, table=True):
    """One row per MSA RT/X bot job (queued, running, or finished)."""

    __tablename__ = "msa_rtxrt_jobs"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        Index("ix_msa_rtxrt_jobs_status_created", "status", "created_at"),
        Index("ix_msa_rtxrt_jobs_created_at", "created_at"),
        # Lookup path for the multi-runner poll filter:
        # ``WHERE status=queued AND (target_runner_id IS NULL OR target_runner_id=?)``.
        Index("ix_msa_rtxrt_jobs_target_runner_id", "target_runner_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Job kind: one of VALID_KINDS. Validated on write by the service layer.
    kind: str = Field(max_length=32)

    status: str = Field(default=STATUS_QUEUED, max_length=16)

    # Author. ``"local"`` for local-auth deployments, ``"system"`` for
    # any future auto-enqueued job (none today).
    requested_by_user_id: str = Field(max_length=255)

    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)

    # Privacy-safe operator-facing strings. Truncated by the service layer
    # to MAX_SUMMARY_LEN / MAX_EXCERPT_LEN on every write.
    summary: str | None = Field(default=None, max_length=MAX_SUMMARY_LEN)
    stdout_excerpt: str | None = Field(default=None, max_length=MAX_EXCERPT_LEN)
    error_excerpt: str | None = Field(default=None, max_length=MAX_EXCERPT_LEN)

    # The runner identifies itself with a stable name when it claims a job.
    # ``None`` until the first poll picks the row up.
    runner_id: str | None = Field(default=None, max_length=128)

    # Multi-runner assignment: which runner is this job *intended* for?
    # ``None`` means "any runner may claim it" — the back-compat path for
    # rows enqueued before multi-runner targeting landed. The Mission
    # Control UI sets this from a selected-runner dropdown on every
    # create. Distinct from ``runner_id`` (which is the runner that
    # actually picked it up).
    target_runner_id: str | None = Field(default=None, max_length=128)

    # Mirrors of the safety posture for fast audit / list rendering. The
    # service layer sets these on insert.
    dry_run: bool = Field(default=True)
    live_one: bool = Field(default=False)
    max_test_actions: int = Field(default=0)

    # Free-form structured metadata (always a dict). Reserved for future
    # use; the API today writes an empty object on insert.
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata_json", JSON, nullable=False, default=dict),
    )
