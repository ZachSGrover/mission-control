"""Audit-retention scheduler foundation.

Sprint 4 deliverable. **Default behaviour is dry-run** — the scheduler
never deletes rows unless an operator opts in via env var.

Two layers:

1. :func:`run_retention_pass` — the unit of work. Always audits the
   invocation. Defaults to ``dry_run=True``.
2. :func:`run_retention_supervisor` — long-running async loop the
   FastAPI lifespan can spawn (mirrors :mod:`app.core.telegram_polling`
   pattern). Wakes up every :data:`CHECK_INTERVAL_SECONDS`, runs a
   pass, sleeps. Cancels cleanly on the supplied stop event.

To opt into real deletes, the operator sets:

- ``MC_AUDIT_RETENTION_ENABLED=1`` — required to schedule the loop.
- ``MC_AUDIT_RETENTION_DRY_RUN=0`` — required to actually delete.

Both default to "off" / "dry-run". This sprint deliberately does NOT
register the supervisor in the lifespan; that's a Sprint 5 task once
the operational team has signed off on the retention windows.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Final

from app.db.session import async_session_maker
from app.services.audit_log import record_audit
from app.services.audit_retention import (
    preview_purge,
    purge_old_audit_events,
)

logger = logging.getLogger(__name__)

# How often the supervisor wakes up to run a pass. Default 24h — a
# weekly real purge is what the security plan calls for, but a daily
# dry-run gives us audit-row evidence that the scheduler is alive.
CHECK_INTERVAL_SECONDS: Final[int] = 24 * 60 * 60

# Env var names. Both default to the safest behaviour.
ENV_ENABLED: Final[str] = "MC_AUDIT_RETENTION_ENABLED"
ENV_DRY_RUN: Final[str] = "MC_AUDIT_RETENTION_DRY_RUN"


def is_scheduler_enabled() -> bool:
    """True iff the operator explicitly opted into running the supervisor."""
    return os.environ.get(ENV_ENABLED, "0").strip() == "1"


def is_dry_run() -> bool:
    """True unless the operator explicitly set ``MC_AUDIT_RETENTION_DRY_RUN=0``."""
    return os.environ.get(ENV_DRY_RUN, "1").strip() != "0"


async def run_retention_pass(*, dry_run: bool | None = None) -> dict[str, int]:
    """One retention pass. Always audits the invocation.

    ``dry_run`` defaults to :func:`is_dry_run`. Pass ``True`` / ``False``
    explicitly to override (used by tests and the admin endpoint).
    """
    effective_dry_run = is_dry_run() if dry_run is None else dry_run

    async with async_session_maker() as session:
        if effective_dry_run:
            preview = await preview_purge(session)
            await record_audit(
                session,
                event_type="audit.retention.preview",
                category="security",
                action="preview",
                result="success",
                severity="info",
                resource_type="audit_events",
                metadata={"preview": preview, "dry_run": True},
            )
            await session.commit()
            return preview

        deleted = await purge_old_audit_events(session, dry_run=False)
        await record_audit(
            session,
            event_type="audit.retention.purge",
            category="security",
            action="purge",
            result="success",
            severity="critical",
            resource_type="audit_events",
            metadata={"deleted": deleted, "dry_run": False},
        )
        await session.commit()
        return deleted


async def run_retention_supervisor(stop_event: asyncio.Event | None = None) -> None:
    """Long-running supervisor. Runs one pass per
    :data:`CHECK_INTERVAL_SECONDS` until ``stop_event`` is set.

    Refuses to start if :func:`is_scheduler_enabled` returns False —
    this is the explicit opt-in gate for the Sprint 5 rollout.
    """
    if not is_scheduler_enabled():
        logger.info(
            "audit_retention_scheduler.disabled " "(set MC_AUDIT_RETENTION_ENABLED=1 to enable)"
        )
        return

    stop = stop_event or asyncio.Event()
    logger.info(
        "audit_retention_scheduler.started interval_s=%d dry_run=%s",
        CHECK_INTERVAL_SECONDS,
        is_dry_run(),
    )
    try:
        while not stop.is_set():
            try:
                await run_retention_pass()
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning(
                    "audit_retention_scheduler.pass_failed error=%s",
                    type(exc).__name__,
                )
            try:
                await asyncio.wait_for(stop.wait(), timeout=CHECK_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                continue
    finally:
        logger.info("audit_retention_scheduler.stopped")
