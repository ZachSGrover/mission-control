"""Job-status row for the OF Daily QC scheduler.

Append-only audit trail of every tick the scheduler considers — including
ticks that were skipped because the operator hasn't enabled the scheduler
yet.  This is the single source of truth for ``GET /qc/scheduler/status``
("when did it last run?  did it skip?  why?").

Privacy: rows carry only counts + a short skipped/error reason.  No fan
handles, no message bodies, no secrets, no webhook URLs ever land here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, Index, SQLModel

from app.core.time import utcnow


class OfQcSchedulerJob(SQLModel, table=True):
    """One row per scheduler tick (ran, skipped, or errored)."""

    __tablename__ = "of_qc_scheduler_jobs"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        Index("ix_of_qc_scheduler_jobs_started_at", "started_at"),
        Index("ix_of_qc_scheduler_jobs_kind_started", "job_kind", "started_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    # ``daily_evaluate`` | ``daily_summary`` | ``manual_sandbox``.
    job_kind: str = Field(max_length=32)
    # ``scheduler`` | ``manual`` | ``test``.
    triggered_by: str = Field(default="scheduler", max_length=16)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = Field(default=None)
    # ``running`` | ``completed`` | ``skipped`` | ``failed``.
    status: str = Field(max_length=16)
    # When ``status == "skipped"``: short coded reason (no PII).  Examples:
    # ``daily_qc_disabled``, ``live_send_disabled``, ``no_webhook``.
    skipped_reason: str | None = Field(default=None, max_length=64)
    # When ``status == "failed"``: short summary string (already privacy-safe).
    error_summary: str | None = Field(default=None, max_length=256)
    # Counters surfaced to the dashboard.
    accounts_checked: int | None = Field(default=None)
    findings_count: int | None = Field(default=None)
    # Source-mode metadata (added by the read-only ingestion layer).
    # ``synthetic`` | ``local_ofi`` | ``onlymonster_readonly`` | ``unknown``.
    source_mode: str | None = Field(default=None, max_length=32)
    # ``high`` | ``medium`` | ``low`` | ``unknown``.
    source_confidence: str | None = Field(default=None, max_length=16)
    # Always True in v1 — reserved for future privacy-mode overrides.
    safe_mode: bool = Field(default=True)
