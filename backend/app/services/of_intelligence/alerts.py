"""OnlyFans Intelligence — alert engine skeleton.

Walks the synced data, evaluates a small set of rules, and writes alerts to
`of_intelligence_alerts`.  All alerts are deduplicated by `code +
account_source_id` while open — a re-run will not create a second alert for
the same condition until the existing one is acknowledged or resolved.

Phase 1 rules (extend over time):
  • sync_failure       — any sync_log row in error within the last 24h
  • account_stale      — account hasn't synced in N hours
  • account_access     — access_status flags lost / blocked / expired
  • api_disconnected   — no successful sync_log row in last 24h
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.of_intelligence import (
    OfIntelligenceAccount,
    OfIntelligenceAlert,
    OfIntelligenceSyncLog,
)

logger = logging.getLogger(__name__)

DEFAULT_STALE_SYNC_HOURS = 6


@dataclass
class AlertCandidate:
    code: str
    severity: str
    title: str
    message: str
    account_source_id: str | None = None
    chatter_source_id: str | None = None
    fan_source_id: str | None = None
    context: dict[str, Any] | None = None


@dataclass
class AlertEvaluationSummary:
    evaluated_at: datetime
    rules_run: int
    alerts_created: int
    alerts_skipped_existing: int
    candidates: list[AlertCandidate]


# ── Public entrypoints ───────────────────────────────────────────────────────


async def evaluate_alerts(
    session: AsyncSession,
    *,
    stale_sync_hours: int = DEFAULT_STALE_SYNC_HOURS,
) -> AlertEvaluationSummary:
    """Run all alert rules and persist any newly fired alerts."""
    candidates: list[AlertCandidate] = []
    candidates.extend(await _rule_sync_failure(session))
    candidates.extend(await _rule_account_stale(session, stale_sync_hours))
    candidates.extend(await _rule_account_access(session))
    candidates.extend(await _rule_api_disconnected(session))

    created = skipped = 0
    for candidate in candidates:
        if await _has_open_alert(session, candidate.code, candidate.account_source_id):
            skipped += 1
            continue
        session.add(
            OfIntelligenceAlert(
                code=candidate.code,
                severity=candidate.severity,
                status="open",
                title=candidate.title,
                message=candidate.message,
                account_source_id=candidate.account_source_id,
                chatter_source_id=candidate.chatter_source_id,
                fan_source_id=candidate.fan_source_id,
                context=candidate.context,
            )
        )
        created += 1
    if created:
        await session.commit()

    summary = AlertEvaluationSummary(
        evaluated_at=utcnow(),
        rules_run=4,
        alerts_created=created,
        alerts_skipped_existing=skipped,
        candidates=candidates,
    )
    logger.info(
        "of_intelligence.alerts.evaluated rules=%s created=%s skipped=%s",
        summary.rules_run,
        summary.alerts_created,
        summary.alerts_skipped_existing,
    )
    return summary


async def acknowledge_alert(session: AsyncSession, alert_id: str) -> OfIntelligenceAlert | None:
    alert = (
        await session.exec(
            select(OfIntelligenceAlert).where(OfIntelligenceAlert.id == alert_id)  # type: ignore[arg-type]
        )
    ).first()
    if not alert:
        return None
    if alert.status == "open":
        alert.status = "acknowledged"
        alert.acknowledged_at = utcnow()
        session.add(alert)
        await session.commit()
        await session.refresh(alert)
    return alert


async def resolve_alert(session: AsyncSession, alert_id: str) -> OfIntelligenceAlert | None:
    alert = (
        await session.exec(
            select(OfIntelligenceAlert).where(OfIntelligenceAlert.id == alert_id)  # type: ignore[arg-type]
        )
    ).first()
    if not alert:
        return None
    if alert.status != "resolved":
        alert.status = "resolved"
        alert.resolved_at = utcnow()
        session.add(alert)
        await session.commit()
        await session.refresh(alert)
    return alert


# ── Rules ────────────────────────────────────────────────────────────────────


async def _rule_sync_failure(session: AsyncSession) -> list[AlertCandidate]:
    cutoff = utcnow() - timedelta(hours=24)
    rows = (
        await session.exec(
            select(OfIntelligenceSyncLog)
            .where(OfIntelligenceSyncLog.started_at >= cutoff)
            .where(OfIntelligenceSyncLog.status == "error")
        )
    ).all()
    return [
        AlertCandidate(
            code=f"sync_failure:{row.entity}",
            severity="warn",
            title=f"Sync failed for {row.entity}",
            message=row.error or row.reason or "Unknown sync error",
            context={"entity": row.entity, "run_id": str(row.run_id)},
        )
        for row in rows
    ]


async def _rule_account_stale(session: AsyncSession, hours: int) -> list[AlertCandidate]:
    cutoff = utcnow() - timedelta(hours=hours)
    rows = (
        await session.exec(
            select(OfIntelligenceAccount).where(OfIntelligenceAccount.last_synced_at < cutoff)
        )
    ).all()
    return [
        AlertCandidate(
            code="account_stale",
            severity="warn",
            title=f"{row.username or row.source_id} hasn't synced in {hours}h+",
            message=f"last_synced_at={row.last_synced_at.isoformat()}",
            account_source_id=row.source_id,
            context={"hours_since_sync": hours},
        )
        for row in rows
    ]


async def _rule_account_access(session: AsyncSession) -> list[AlertCandidate]:
    rows = (
        await session.exec(
            select(OfIntelligenceAccount).where(
                OfIntelligenceAccount.access_status.in_(["lost", "blocked", "expired"])  # type: ignore[attr-defined]
            )
        )
    ).all()
    return [
        AlertCandidate(
            code="account_access",
            severity="critical",
            title=f"{row.username or row.source_id} may have lost access",
            message=f"access_status={row.access_status}",
            account_source_id=row.source_id,
            context={"access_status": row.access_status},
        )
        for row in rows
    ]


async def _rule_api_disconnected(session: AsyncSession) -> list[AlertCandidate]:
    cutoff = utcnow() - timedelta(hours=24)
    rows = (
        await session.exec(
            select(OfIntelligenceSyncLog)
            .where(OfIntelligenceSyncLog.status == "success")
            .where(OfIntelligenceSyncLog.started_at >= cutoff)
            .limit(1)
        )
    ).all()
    if rows:
        return []

    # Only fire if there's been *any* sync activity ever — avoids alerting on
    # a brand-new install before the user has done anything.
    has_any = (await session.exec(select(OfIntelligenceSyncLog).limit(1))).first()
    if not has_any:
        return []

    return [
        AlertCandidate(
            code="api_disconnected",
            severity="critical",
            title="OnlyMonster API hasn't returned a successful sync in 24h",
            message="Check Settings → Integrations → OnlyMonster credentials and run a manual sync.",
        )
    ]


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _has_open_alert(
    session: AsyncSession,
    code: str,
    account_source_id: str | None,
) -> bool:
    stmt = select(OfIntelligenceAlert).where(
        OfIntelligenceAlert.code == code,
        OfIntelligenceAlert.status == "open",
    )
    if account_source_id is not None:
        stmt = stmt.where(OfIntelligenceAlert.account_source_id == account_source_id)
    return (await session.exec(stmt.limit(1))).first() is not None
