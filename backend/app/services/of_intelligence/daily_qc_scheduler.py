"""Daily QC report scheduler.

A small supervisor that wakes once per minute and generates exactly one
QC report per UTC calendar day, at the operator-configured `HH:MM` time.

Idempotency contract:
  • At most one row in `of_intelligence_qc_reports` per `report_date`
    calendar-day, regardless of how often the supervisor ticks.
  • If the operator changes the configured time mid-day, the rule above
    still holds — once today's report exists, no second one is fired
    today.
  • Manual generations (via the "Generate report" button) also count as
    "today's report" for the supervisor.

Operator config:
  • DB key `of_intelligence.daily_qc_report_time` (HH:MM in 24-hour UTC).
  • DB key `of_intelligence.daily_qc_report_enabled` ("true" / "false";
    defaults to "true" when unset and a time is configured).
  • Both are read fresh on every tick — changing the config takes effect
    within ~60 seconds.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta
from typing import NamedTuple

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.secrets_store import get_secret
from app.core.time import utcnow
from app.db.session import async_session_maker
from app.models.of_intelligence import OfIntelligenceQcReport
from app.services.onlymonster.qc_bot import generate_qc_report

logger = logging.getLogger(__name__)

DAILY_QC_TIME_DB_KEY = "of_intelligence.daily_qc_report_time"
DAILY_QC_ENABLED_DB_KEY = "of_intelligence.daily_qc_report_enabled"

DEFAULT_TICK_SECONDS = 60.0


class DailyQcConfig(NamedTuple):
    enabled: bool
    target_time: time | None
    raw_time: str  # the original "HH:MM" string for round-tripping; "" when unset


# ── Config helpers ───────────────────────────────────────────────────────────


def _parse_hh_mm(value: str) -> time | None:
    """Parse an HH:MM 24-hour string. Returns None on any failure."""
    if not value:
        return None
    text = value.strip()
    if len(text) != 5 or text[2] != ":":
        return None
    try:
        hour = int(text[0:2])
        minute = int(text[3:5])
    except ValueError:
        return None
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return None
    return time(hour=hour, minute=minute)


async def load_config(session: AsyncSession) -> DailyQcConfig:
    """Read the current scheduler config from the DB (encrypted store)."""
    raw_time = (await get_secret(session, DAILY_QC_TIME_DB_KEY)).strip()
    target = _parse_hh_mm(raw_time)
    enabled_raw = (await get_secret(session, DAILY_QC_ENABLED_DB_KEY)).strip().lower()
    if enabled_raw in ("true", "1", "yes", "on"):
        enabled = True
    elif enabled_raw in ("false", "0", "no", "off"):
        enabled = False
    else:
        # Default: enabled iff a time is configured.
        enabled = target is not None
    return DailyQcConfig(enabled=enabled, target_time=target, raw_time=raw_time)


# ── Idempotency check ────────────────────────────────────────────────────────


async def _has_report_for_day(session: AsyncSession, day: datetime) -> bool:
    """True if any QC report row exists with `report_date` on the given day."""
    day_start = datetime.combine(day.date(), time.min)
    day_end = day_start + timedelta(days=1)
    existing = (
        await session.exec(
            select(OfIntelligenceQcReport)
            .where(col(OfIntelligenceQcReport.report_date) >= day_start)
            .where(col(OfIntelligenceQcReport.report_date) < day_end)
            .limit(1)
        )
    ).first()
    return existing is not None


# ── Single-tick decision ─────────────────────────────────────────────────────


async def maybe_generate_now(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> str:
    """Decide whether to generate today's report and do it if so.

    Returns a short status label for logging:
      • "disabled"        – feature off or no time configured
      • "too_early"       – current time hasn't reached today's target yet
      • "already_done"    – today's report already exists
      • "generated"       – fresh report was created in this tick
      • "error"           – generation crashed (logged with traceback)
    """
    when = now or utcnow()
    cfg = await load_config(session)
    if not cfg.enabled or cfg.target_time is None:
        return "disabled"

    target_dt = datetime.combine(when.date(), cfg.target_time)
    if when < target_dt:
        return "too_early"

    if await _has_report_for_day(session, when):
        return "already_done"

    try:
        report = await generate_qc_report(session, report_date=when)
    except Exception:
        logger.exception("of_intelligence.daily_qc.generate_failed")
        return "error"

    logger.info(
        "of_intelligence.daily_qc.generated report_id=%s report_date=%s target=%s",
        report.id,
        report.report_date.isoformat(),
        cfg.raw_time,
    )
    return "generated"


# ── Supervisor loop ──────────────────────────────────────────────────────────


async def run_supervisor(
    stop_event: asyncio.Event | None = None,
    *,
    tick_seconds: float = DEFAULT_TICK_SECONDS,
) -> None:
    """Wake once per *tick_seconds* and call `maybe_generate_now`.

    Designed to be launched from `app.main.lifespan` alongside the other
    `app.core.*` background supervisors.  The loop never raises — any
    error is logged and the loop continues.
    """
    stop = stop_event or asyncio.Event()
    logger.info("of_intelligence.daily_qc.supervisor.start tick=%.0fs", tick_seconds)

    while not stop.is_set():
        try:
            async with async_session_maker() as session:
                outcome = await maybe_generate_now(session)
            if outcome not in ("disabled", "too_early", "already_done"):
                logger.info("of_intelligence.daily_qc.tick outcome=%s", outcome)
        except Exception:
            logger.exception("of_intelligence.daily_qc.tick.crash")

        try:
            await asyncio.wait_for(stop.wait(), timeout=tick_seconds)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            break

    logger.info("of_intelligence.daily_qc.supervisor.stop")
