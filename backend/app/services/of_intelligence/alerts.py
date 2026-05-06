"""OnlyFans Intelligence — alert engine.

Walks the synced data, evaluates a small set of rules, and writes alerts to
``of_intelligence_alerts``.  All alerts are deduplicated by ``code +
account_source_id`` while open — a re-run will not create a second alert
for the same condition until the existing one is acknowledged or resolved.

After commit, every newly-created alert is shipped to Discord via
``app.services.of_intelligence.qc.dispatch.ship_account_or_sync_alert``.
Dedup'd alerts (already open) are NOT re-shipped, so a single incident
produces one Discord message across many evaluation runs.

Active rules:
  Account / sync health:
    • sync_failure              — any sync_log row in error within the last 24h
    • account_stale             — account hasn't synced in N hours
    • account_blocked           — access_status == "blocked"
    • account_expired           — access_status == "expired"
    • account_disconnected      — access_status == "lost"
    • api_disconnected          — no successful sync_log row in last 24h
  Critical QC risks (per-message scan, dedup'd per account):
    • refund_risk               — fan inbound mentions refund/chargeback
    • banned_content_risk       — chatter outbound hits a policy-term category
    • rude_reply                — chatter outbound flagged as harsh
    • serious_escalation_risk   — fan inbound mentions safety/legal escalation

Privacy: only allowlisted fields (account.username, chatter.name, code,
severity, hours, status, generic detection phrase) reach Discord.  Message
bodies, fan handles, matched keywords, and raw API payloads are NEVER
passed to the dispatcher.  Operators open the dashboard via the alert
ref for full detail.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.of_intelligence import (
    OfIntelligenceAccount,
    OfIntelligenceAlert,
    OfIntelligenceSyncLog,
)
from app.services.of_intelligence.qc.chatter_findings import (
    persist_findings,
    scan_all_chatter_findings,
)
from app.services.of_intelligence.qc.detectors import scan_critical_qc
from app.services.of_intelligence.qc.dispatch import ship_account_or_sync_alert
from app.services.of_intelligence.qc.revenue import (
    ACCOUNT_REVENUE_DROP_CODE,
    detect_revenue_drops,
)
from app.services.of_intelligence.qc.rollups import RollupResult, fire_rollup_if_due

logger = get_logger(__name__)

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
    # Resolved display names when available.  Allowed in Discord messages.
    # Source_ids are internal — never rendered.
    account_username: str | None = None
    chatter_name: str | None = None


@dataclass
class AlertEvaluationSummary:
    evaluated_at: datetime
    rules_run: int
    alerts_created: int
    alerts_skipped_existing: int
    candidates: list[AlertCandidate]
    chatter_findings_persisted: int = 0
    rollup_findings: int = 0
    rollup_alert_id: str | None = None


# ── Public entrypoints ───────────────────────────────────────────────────────


async def evaluate_alerts(
    session: AsyncSession,
    *,
    stale_sync_hours: int = DEFAULT_STALE_SYNC_HOURS,
) -> AlertEvaluationSummary:
    """Run all alert rules, persist new alerts, and ship them to Discord."""
    candidates: list[AlertCandidate] = []
    candidates.extend(await _rule_sync_failure(session))
    candidates.extend(await _rule_account_stale(session, stale_sync_hours))
    candidates.extend(await _rule_account_blocked(session))
    candidates.extend(await _rule_account_expired(session))
    candidates.extend(await _rule_account_disconnected(session))
    candidates.extend(await _rule_api_disconnected(session))
    candidates.extend(await _rule_critical_qc_risks(session))
    candidates.extend(await _rule_revenue_drop(session))

    # Track (candidate, alert) pairs for post-commit Discord shipping.
    pending: list[tuple[AlertCandidate, OfIntelligenceAlert]] = []
    skipped = 0

    for candidate in candidates:
        if await _has_open_alert(session, candidate.code, candidate.account_source_id):
            skipped += 1
            continue
        alert = OfIntelligenceAlert(
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
        session.add(alert)
        pending.append((candidate, alert))

    if pending:
        await session.commit()
        for _, alert in pending:
            await session.refresh(alert)

    # Ship to Discord post-commit so a Discord outage can never roll back the
    # alert row.  Each call is wrapped — ``ship_account_or_sync_alert`` and
    # the publisher both never raise, so one failed send doesn't break the
    # rest of the loop.
    for candidate, alert in pending:
        try:
            await ship_account_or_sync_alert(
                code=candidate.code,
                title=candidate.title,
                account_username=candidate.account_username,
                chatter_name=candidate.chatter_name,
                alert_id=alert.id,
                context=candidate.context,
            )
        except Exception:
            # Defensive — dispatcher already swallows errors, but keep the
            # evaluation loop bullet-proof against future regressions.
            logger.exception(
                "of_intelligence.alerts.discord_dispatch_failed code=%s alert_id=%s",
                candidate.code,
                alert.id,
            )

    # ── Layer 2: chatter findings + rollup ──────────────────────────────
    findings_persisted = 0
    rollup: RollupResult | None = None
    try:
        chatter_candidates = await scan_all_chatter_findings(session)
        findings_persisted = await persist_findings(session, chatter_candidates)
        rollup = await fire_rollup_if_due(session)
    except Exception:
        logger.exception("of_intelligence.alerts.layer2_failed (Layer 1 ships completed already)")

    summary = AlertEvaluationSummary(
        evaluated_at=utcnow(),
        rules_run=8,
        alerts_created=len(pending),
        alerts_skipped_existing=skipped,
        candidates=candidates,
        chatter_findings_persisted=findings_persisted,
        rollup_findings=rollup.findings_rolled if rollup else 0,
        rollup_alert_id=str(rollup.alert_id) if rollup and rollup.alert_id else None,
    )
    logger.info(
        "of_intelligence.alerts.evaluated rules=%s created=%s skipped=%s findings=%s rolled=%s",
        summary.rules_run,
        summary.alerts_created,
        summary.alerts_skipped_existing,
        summary.chatter_findings_persisted,
        summary.rollup_findings,
    )
    return summary


async def acknowledge_alert(session: AsyncSession, alert_id: str) -> OfIntelligenceAlert | None:
    alert = (
        await session.exec(select(OfIntelligenceAlert).where(OfIntelligenceAlert.id == alert_id))
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
        await session.exec(select(OfIntelligenceAlert).where(OfIntelligenceAlert.id == alert_id))
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
            severity="high",
            title=f"Sync failed for {row.entity}",
            # ``message`` is stored on the alert row for the dashboard and
            # may include the raw error.  ``context`` is what the Discord
            # dispatcher reads — keep PII-bearing strings out of context.
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
            severity="high",
            title=f"{row.username or row.source_id} hasn't synced in {hours}h+",
            message=f"last_synced_at={row.last_synced_at.isoformat()}",
            account_source_id=row.source_id,
            account_username=row.username,
            context={"hours_since_sync": hours},
        )
        for row in rows
    ]


async def _rule_account_blocked(session: AsyncSession) -> list[AlertCandidate]:
    rows = await _accounts_with_status(session, "blocked")
    return [
        AlertCandidate(
            code="account_blocked",
            severity="critical",
            title=f"{row.username or row.source_id} access blocked",
            message="access_status=blocked",
            account_source_id=row.source_id,
            account_username=row.username,
            context={"access_status": "blocked"},
        )
        for row in rows
    ]


async def _rule_account_expired(session: AsyncSession) -> list[AlertCandidate]:
    rows = await _accounts_with_status(session, "expired")
    return [
        AlertCandidate(
            code="account_expired",
            severity="critical",
            title=f"{row.username or row.source_id} access expired",
            message="access_status=expired",
            account_source_id=row.source_id,
            account_username=row.username,
            context={"access_status": "expired"},
        )
        for row in rows
    ]


async def _rule_account_disconnected(session: AsyncSession) -> list[AlertCandidate]:
    # OnlyMonster reports lost connections as access_status="lost".
    rows = await _accounts_with_status(session, "lost")
    return [
        AlertCandidate(
            code="account_disconnected",
            severity="critical",
            title=f"{row.username or row.source_id} disconnected",
            message="access_status=lost",
            account_source_id=row.source_id,
            account_username=row.username,
            context={"access_status": "lost"},
        )
        for row in rows
    ]


async def _rule_revenue_drop(session: AsyncSession) -> list[AlertCandidate]:
    """Per-account 24h-vs-7d revenue drop → AlertCandidate(code=account_revenue_drop).

    Dedup gate is the existing ``code + account_source_id`` check — once an
    account is flagged, we don't fire again until the operator
    acknowledges or resolves.
    """
    warnings = await detect_revenue_drops(session)
    return [
        AlertCandidate(
            code=ACCOUNT_REVENUE_DROP_CODE,
            severity=w.severity,
            title=(
                f"{w.username or w.account_source_id} revenue drop"
                if w.username
                else "Account revenue drop"
            ),
            message=w.reason,
            account_source_id=w.account_source_id,
            account_username=w.username,
            context={
                "revenue_24h_cents": w.revenue_24h_cents,
                "revenue_7d_avg_cents": w.revenue_7d_avg_cents,
                "reason": w.reason,
            },
        )
        for w in warnings
    ]


async def _rule_critical_qc_risks(session: AsyncSession) -> list[AlertCandidate]:
    """Critical QC risks — refund / banned / rude / escalation.

    Delegates pattern matching to ``qc.detectors.scan_critical_qc``.  The
    detector reads message bodies but emits only privacy-safe candidate
    fields (account_username, chatter_name, generic detection phrase).
    The matched keyword and message body NEVER appear in the candidate.
    """
    findings = await scan_critical_qc(session)
    return [
        AlertCandidate(
            code=f.code,
            severity=f.severity,
            title=f.title,
            # ``message`` is stored on the alert row for the dashboard.
            # Keep it generic — never the matched keyword or body.
            message=f.detection_phrase,
            account_source_id=f.account_source_id,
            account_username=f.account_username,
            chatter_source_id=f.chatter_source_id,
            chatter_name=f.chatter_name,
            context={"detection_phrase": f.detection_phrase},
        )
        for f in findings
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
            title="OnlyMonster API: no successful sync in 24h",
            message="Check Settings → Integrations → OnlyMonster credentials and run a manual sync.",
        )
    ]


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _accounts_with_status(
    session: AsyncSession,
    status_value: str,
) -> list[OfIntelligenceAccount]:
    return list(
        (
            await session.exec(
                select(OfIntelligenceAccount).where(
                    col(OfIntelligenceAccount.access_status) == status_value
                )
            )
        ).all()
    )


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
