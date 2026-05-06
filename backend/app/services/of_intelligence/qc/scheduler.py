"""OF Daily QC scheduler — disabled-by-default safe runner.

The scheduler ticks on a fixed interval (default 30 min).  Each tick:
  1. Loads ``OfQcDiscordStatus`` and reads ``daily_qc_enabled``.
  2. If False → records a single ``skipped`` job row and returns.
  3. If True → calls ``evaluate_alerts`` and (when within the daily window)
     ``ship_daily_summary`` — but ``live_send_enabled`` gates the actual
     network calls inside the publishers, so a tick with
     ``daily_qc_enabled=True`` AND ``live_send_enabled=False`` runs the
     evaluator and writes findings to the DB without hitting Discord or
     Telegram.

Public surface:
  • ``run_one_tick(session, *, triggered_by)`` — runs one scheduler tick,
    persists a job row, returns the job.  Exposed for the API run-now
    endpoint AND the background task.  Never raises.
  • ``run_supervisor()`` — async background loop entrypoint.  Wired in
    ``app/main.py`` lifecycle.  Off by default — sleeps even when the
    scheduler is disabled (so flipping the toggle takes effect on the
    next tick).
  • ``current_status(session)`` — returns the data the API surfaces:
    last run, latest status, recent counters, computed next run time.

Privacy: jobs persist only counters + a coded skipped/error reason.  No
fan handles, no message bodies, no API responses, no webhook URLs.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import async_session_maker
from app.models.of_qc_discord_status import OfQcDiscordStatus
from app.models.of_qc_scheduler_job import OfQcSchedulerJob

logger = get_logger(__name__)

# Tunables — kept module-level so tests can monkeypatch them.
TICK_INTERVAL_SECONDS = 30 * 60  # default 30 minutes between ticks
DAILY_SUMMARY_HOUR_UTC = 9  # ship the daily-summary digest once after this hour
_RECENT_LIMIT = 10
_STATUS_ROW_ID = 1


# ── Public API ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SchedulerStatus:
    daily_qc_enabled: bool
    live_send_enabled: bool
    discord_enabled: bool  # mirrors of_qc_discord_status.enabled
    telegram_enabled: bool
    daily_qc_source_mode: str
    onlymonster_readonly_enabled: bool
    onlyfans_readonly_enabled: bool
    platform_write_enabled: bool
    safe_mode: bool
    last_run_at: datetime | None
    last_status: str | None
    last_skipped_reason: str | None
    last_error_summary: str | None
    last_findings_count: int | None
    last_accounts_checked: int | None
    last_source_mode: str | None
    last_source_confidence: str | None
    next_run_at: datetime | None
    tick_interval_seconds: int


async def current_status(session: AsyncSession) -> SchedulerStatus:
    """Compose the operator-visible scheduler state."""
    row = await session.get(OfQcDiscordStatus, _STATUS_ROW_ID)
    daily_qc_enabled = bool(row and row.daily_qc_enabled)
    live_send_enabled = bool(row and row.live_send_enabled)
    discord_enabled = bool(row and row.enabled)
    telegram_enabled = bool(row and row.telegram_enabled)

    latest_jobs: Sequence[OfQcSchedulerJob] = (
        await session.exec(
            select(OfQcSchedulerJob).order_by(col(OfQcSchedulerJob.started_at).desc()).limit(1)
        )
    ).all()
    latest = latest_jobs[0] if latest_jobs else None

    next_run_at: datetime | None = None
    if daily_qc_enabled and latest is not None and latest.finished_at is not None:
        next_run_at = latest.finished_at + timedelta(seconds=TICK_INTERVAL_SECONDS)
    elif daily_qc_enabled and latest is None:
        next_run_at = utcnow()

    return SchedulerStatus(
        daily_qc_enabled=daily_qc_enabled,
        live_send_enabled=live_send_enabled,
        discord_enabled=discord_enabled,
        telegram_enabled=telegram_enabled,
        daily_qc_source_mode=(
            getattr(row, "daily_qc_source_mode", None) if row is not None else None
        )
        or "synthetic",
        onlymonster_readonly_enabled=bool(
            row and getattr(row, "onlymonster_readonly_enabled", False)
        ),
        onlyfans_readonly_enabled=bool(row and getattr(row, "onlyfans_readonly_enabled", False)),
        platform_write_enabled=bool(row and getattr(row, "platform_write_enabled", False)),
        safe_mode=bool(latest.safe_mode) if latest is not None else True,
        last_run_at=latest.started_at if latest else None,
        last_status=latest.status if latest else None,
        last_skipped_reason=latest.skipped_reason if latest else None,
        last_error_summary=latest.error_summary if latest else None,
        last_findings_count=latest.findings_count if latest else None,
        last_accounts_checked=latest.accounts_checked if latest else None,
        last_source_mode=latest.source_mode if latest else None,
        last_source_confidence=latest.source_confidence if latest else None,
        next_run_at=next_run_at,
        tick_interval_seconds=TICK_INTERVAL_SECONDS,
    )


async def run_one_tick(
    session: AsyncSession,
    *,
    triggered_by: str = "scheduler",
    job_kind: str = "daily_evaluate",
) -> OfQcSchedulerJob:
    """Run a single scheduler tick and persist its outcome.

    Never raises — failures are recorded as ``status='failed'`` rows so the
    operator can see them via ``GET /qc/scheduler/status``.

    ``triggered_by`` accepts ``"scheduler"`` (the background loop),
    ``"manual"`` (the run-now endpoint), or ``"test"`` (test fixtures).
    """
    job = OfQcSchedulerJob(
        job_kind=job_kind,
        triggered_by=triggered_by,
        started_at=utcnow(),
        status="running",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    try:
        row = await session.get(OfQcDiscordStatus, _STATUS_ROW_ID)
        daily_qc_enabled = bool(row and row.daily_qc_enabled)

        if not daily_qc_enabled:
            job.status = "skipped"
            job.skipped_reason = "daily_qc_disabled"
            job.finished_at = utcnow()
            session.add(job)
            await session.commit()
            await session.refresh(job)
            logger.info(
                "of_qc.scheduler.skipped reason=%s triggered_by=%s",
                "daily_qc_disabled",
                triggered_by,
            )
            return job

        # Lazy imports keep this module cheap to load and avoid circulars.
        from app.services.of_intelligence.alerts import evaluate_alerts
        from app.services.of_intelligence.qc.ingestion import ingest_for_status
        from app.services.of_intelligence.qc.ingestion_evaluator import (
            evaluate_ingestion,
        )

        # Source-aware ingestion: pull AccountMetrics through the read-only
        # adapter layer, then run the (existing) per-row alert engine.
        ingestion = await ingest_for_status(session)
        evaluated = evaluate_ingestion(ingestion)

        summary = await evaluate_alerts(session)
        # Combine the ingestion-evaluator's account count with the alert
        # engine's count of evaluated candidates so the dashboard shows
        # the broader of the two.  Findings count likewise: prefer the
        # ingestion findings (privacy-safe) when the source is non-empty.
        job.accounts_checked = max(evaluated.accounts_checked, len(summary.candidates))
        job.findings_count = max(len(evaluated.findings), summary.alerts_created)
        job.source_mode = ingestion.source_mode.value
        job.source_confidence = ingestion.source_confidence
        job.safe_mode = bool(ingestion.safe_mode)
        if ingestion.skipped_reason and not evaluated.findings:
            job.status = "skipped"
            job.skipped_reason = ingestion.skipped_reason
        else:
            job.status = "completed"
        job.finished_at = utcnow()
        session.add(job)
        await session.commit()
        await session.refresh(job)
        logger.info(
            "of_qc.scheduler.tick.completed triggered_by=%s source_mode=%s "
            "rules_run=%s alerts_created=%s findings=%s",
            triggered_by,
            ingestion.source_mode.value,
            summary.rules_run,
            summary.alerts_created,
            len(evaluated.findings),
        )
        return job
    except Exception as exc:  # noqa: BLE001 — bullet-proof against detector regressions
        job.status = "failed"
        job.error_summary = _safe_error_summary(exc)
        job.finished_at = utcnow()
        try:
            session.add(job)
            await session.commit()
            await session.refresh(job)
        except Exception:
            logger.exception("of_qc.scheduler.failed_to_persist_job_row")
        logger.exception("of_qc.scheduler.tick.failed triggered_by=%s", triggered_by)
        return job


def _safe_error_summary(exc: Exception) -> str:
    """Truncate exception type + message; never include payloads."""
    text = f"{type(exc).__name__}: {exc}"
    return text[:256]


# ── Background supervisor ───────────────────────────────────────────────────


_DISABLE_SCHEDULER_ENV = "MC_OF_QC_SCHEDULER_DISABLE"


def _supervisor_globally_disabled() -> bool:
    """Hard env-level kill switch that prevents the supervisor from even
    starting.  Independent from the DB toggle so operators can disable
    on a per-deploy basis without DB access."""
    return (os.environ.get(_DISABLE_SCHEDULER_ENV) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def run_supervisor(stop_event: asyncio.Event | None = None) -> None:
    """Long-running background loop.  Wired into the app lifecycle.

    Always sleeps in fixed ticks.  Each tick opens its own session so the
    main app event loop is unaffected.  When the DB toggle is off the
    supervisor still ticks (and records ``skipped`` rows) — that way the
    operator can see "yes, the loop is healthy, it just isn't running
    QC yet" via the dashboard.
    """
    stop_event = stop_event or asyncio.Event()
    if _supervisor_globally_disabled():
        logger.info(
            "of_qc.scheduler.supervisor.disabled_by_env env=%s",
            _DISABLE_SCHEDULER_ENV,
        )
        return

    logger.info("of_qc.scheduler.supervisor.start interval_s=%s", TICK_INTERVAL_SECONDS)
    try:
        while not stop_event.is_set():
            try:
                async with async_session_maker() as session:
                    await run_one_tick(session, triggered_by="scheduler")
            except Exception:
                logger.exception("of_qc.scheduler.supervisor.tick_outer_failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=TICK_INTERVAL_SECONDS)
                break  # stop_event was set
            except asyncio.TimeoutError:
                continue
    finally:
        logger.info("of_qc.scheduler.supervisor.stop")
