"""OF Daily QC scheduler API — safe runner surface.

Endpoints (all owner-only):
  GET  /api/v1/of-qc-scheduler/status       — operator-visible state
  GET  /api/v1/of-qc-scheduler/recent-jobs  — recent scheduler ticks (audit)
  PUT  /api/v1/of-qc-scheduler/enabled      — flip master + live-send toggles
  POST /api/v1/of-qc-scheduler/run-now      — manual sandbox tick (synthetic)
  POST /api/v1/of-qc-scheduler/run-now-real — manual DB tick (gated by toggles)

The sandbox run-now endpoint never reads real synced rows and never
publishes to Discord or Telegram.  ``run-now-real`` reuses the supervisor
code path; when ``daily_qc_enabled`` is False it records a
``skipped(daily_qc_disabled)`` job and detector code never runs.  Live
sends are gated separately by ``live_send_enabled`` inside the
publishers themselves.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.mc_roles import require_owner
from app.core.auth import AuthContext, get_auth_context
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import get_session
from app.models.of_qc_discord_status import OfQcDiscordStatus
from app.models.of_qc_scheduler_job import OfQcSchedulerJob
from app.services.of_intelligence.qc.sandbox import run_sandbox_summary
from app.services.of_intelligence.qc.scheduler import current_status, run_one_tick

router = APIRouter(prefix="/of-qc-scheduler", tags=["of-qc-scheduler"])
AUTH_DEP = Depends(get_auth_context)
OWNER_DEP = Depends(require_owner)
SESSION_DEP = Depends(get_session)
logger = get_logger(__name__)

_STATUS_ROW_ID = 1
_RECENT_LIMIT = 10


# ── Schemas ──────────────────────────────────────────────────────────────────


class SchedulerJobRow(BaseModel):
    id: UUID
    job_kind: str
    triggered_by: str
    status: str
    skipped_reason: str | None = None
    error_summary: str | None = None
    accounts_checked: int | None = None
    findings_count: int | None = None
    source_mode: str | None = None
    source_confidence: str | None = None
    safe_mode: bool = True
    started_at: datetime
    finished_at: datetime | None = None


class SchedulerStatusResponse(BaseModel):
    daily_qc_enabled: bool
    live_send_enabled: bool
    discord_enabled: bool
    telegram_enabled: bool
    # Read-only ingestion mode + per-source flags (added with PR for
    # the read-only ingestion v1 slice).
    daily_qc_source_mode: str = "synthetic"
    onlymonster_readonly_enabled: bool = False
    onlyfans_readonly_enabled: bool = False
    platform_write_enabled: bool = False
    safe_mode: bool = True  # mirrors the latest job's safe_mode
    last_run_at: datetime | None = None
    last_status: str | None = None
    last_skipped_reason: str | None = None
    last_error_summary: str | None = None
    last_findings_count: int | None = None
    last_accounts_checked: int | None = None
    last_source_mode: str | None = None
    last_source_confidence: str | None = None
    next_run_at: datetime | None = None
    tick_interval_seconds: int
    recent_jobs: list[SchedulerJobRow] = Field(default_factory=list)


class SetEnabledRequest(BaseModel):
    daily_qc_enabled: bool | None = None
    live_send_enabled: bool | None = None
    daily_qc_source_mode: str | None = None  # "synthetic" | "local_ofi"


class SandboxRunResponse(BaseModel):
    job_id: str
    job_kind: Literal["manual_sandbox"]
    triggered_by: Literal["manual"]
    accounts_checked: int
    findings_simulated: int
    summary_total_findings: int
    summary_critical_alerts: int
    summary_actions: list[str]
    note: str = (
        "Sandbox run uses synthetic data only.  No real OF / OnlyMonster "
        "rows were read and no Discord or Telegram messages were sent."
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _recent_jobs(session: AsyncSession) -> list[OfQcSchedulerJob]:
    rows = (
        await session.exec(
            select(OfQcSchedulerJob)
            .order_by(col(OfQcSchedulerJob.started_at).desc())
            .limit(_RECENT_LIMIT)
        )
    ).all()
    return list(rows)


def _to_row(job: OfQcSchedulerJob) -> SchedulerJobRow:
    return SchedulerJobRow.model_validate(job, from_attributes=True)


async def _build_status_response(session: AsyncSession) -> SchedulerStatusResponse:
    s = await current_status(session)
    recent = await _recent_jobs(session)
    return SchedulerStatusResponse(
        daily_qc_enabled=s.daily_qc_enabled,
        live_send_enabled=s.live_send_enabled,
        discord_enabled=s.discord_enabled,
        telegram_enabled=s.telegram_enabled,
        daily_qc_source_mode=s.daily_qc_source_mode,
        onlymonster_readonly_enabled=s.onlymonster_readonly_enabled,
        onlyfans_readonly_enabled=s.onlyfans_readonly_enabled,
        platform_write_enabled=s.platform_write_enabled,
        safe_mode=s.safe_mode,
        last_run_at=s.last_run_at,
        last_status=s.last_status,
        last_skipped_reason=s.last_skipped_reason,
        last_error_summary=s.last_error_summary,
        last_findings_count=s.last_findings_count,
        last_accounts_checked=s.last_accounts_checked,
        last_source_mode=s.last_source_mode,
        last_source_confidence=s.last_source_confidence,
        next_run_at=s.next_run_at,
        tick_interval_seconds=s.tick_interval_seconds,
        recent_jobs=[_to_row(j) for j in recent],
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/status", response_model=SchedulerStatusResponse)
async def get_scheduler_status(
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> SchedulerStatusResponse:
    """Return operator-visible scheduler state."""
    return await _build_status_response(session)


@router.get("/recent-jobs", response_model=list[SchedulerJobRow])
async def list_recent_jobs(
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> list[SchedulerJobRow]:
    """Audit-trail view: the most recent scheduler ticks."""
    rows = await _recent_jobs(session)
    return [_to_row(r) for r in rows]


@router.put("/enabled", response_model=SchedulerStatusResponse)
async def set_scheduler_enabled(
    body: SetEnabledRequest,
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> SchedulerStatusResponse:
    """Flip ``daily_qc_enabled`` and/or ``live_send_enabled`` on the
    singleton ``of_qc_discord_status`` row.  Both default to off.  No
    other side effects — the supervisor reads these on each tick."""
    if (
        body.daily_qc_enabled is None
        and body.live_send_enabled is None
        and body.daily_qc_source_mode is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide daily_qc_enabled, live_send_enabled, or daily_qc_source_mode.",
        )
    row = await session.get(OfQcDiscordStatus, _STATUS_ROW_ID)
    if row is None:
        row = OfQcDiscordStatus(id=_STATUS_ROW_ID)
        session.add(row)
        await session.flush()
    if body.daily_qc_enabled is not None:
        row.daily_qc_enabled = bool(body.daily_qc_enabled)
    if body.live_send_enabled is not None:
        row.live_send_enabled = bool(body.live_send_enabled)
    if body.daily_qc_source_mode is not None:
        candidate = (body.daily_qc_source_mode or "").strip().lower()
        if candidate not in {"synthetic", "local_ofi", "onlymonster_readonly"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "daily_qc_source_mode must be one of: "
                    "synthetic, local_ofi, onlymonster_readonly."
                ),
            )
        row.daily_qc_source_mode = candidate
    row.updated_at = utcnow()
    session.add(row)
    await session.commit()
    logger.info(
        "of_qc.scheduler.toggles.updated daily_qc_enabled=%s live_send_enabled=%s",
        row.daily_qc_enabled,
        row.live_send_enabled,
    )
    return await _build_status_response(session)


@router.post("/run-now", response_model=SandboxRunResponse)
async def manual_sandbox_run(
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> SandboxRunResponse:
    """Synthetic-data sandbox tick.

    Persists a ``manual_sandbox`` job row (so the dashboard sees "last
    run = sandbox") but never reads real synced rows and never publishes
    to Discord or Telegram.  Use ``POST /qc/daily-summary`` for an
    operator-initiated send against real data.
    """
    sandbox = run_sandbox_summary()

    started = utcnow()
    job = OfQcSchedulerJob(
        job_kind="manual_sandbox",
        triggered_by="manual",
        started_at=started,
        finished_at=utcnow(),
        status="completed",
        accounts_checked=sandbox.accounts_checked,
        findings_count=sandbox.findings_simulated,
        source_mode="synthetic",
        source_confidence="high",
        safe_mode=True,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    logger.info(
        "of_qc.scheduler.manual_sandbox.completed accounts=%s findings=%s",
        sandbox.accounts_checked,
        sandbox.findings_simulated,
    )
    return SandboxRunResponse(
        job_id=str(job.id),
        job_kind="manual_sandbox",
        triggered_by="manual",
        accounts_checked=sandbox.accounts_checked,
        findings_simulated=sandbox.findings_simulated,
        summary_total_findings=sandbox.summary.total_findings,
        summary_critical_alerts=sandbox.summary.critical_alert_count,
        summary_actions=list(sandbox.summary.actions),
    )


@router.post("/run-now-real", response_model=SchedulerStatusResponse)
async def manual_real_run(
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> SchedulerStatusResponse:
    """Run one real scheduler tick on demand.

    Same code path as the background supervisor.  Respects
    ``daily_qc_enabled`` (records ``skipped`` if off) and
    ``live_send_enabled`` (no Discord/Telegram publishes if off).
    Useful for "I just enabled the scheduler — run a tick now without
    waiting 30 minutes" without flipping ``live_send_enabled``.
    """
    await run_one_tick(session, triggered_by="manual", job_kind="daily_evaluate")
    return await _build_status_response(session)
