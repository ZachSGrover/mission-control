"""OnlyFans Intelligence QC Bot — daily report skeleton.

Produces a structured, opinionated report from the synced data.  This is the
*skeleton* — the heuristics here are intentionally simple so the surface
exists for downstream consumers (UI, alerts, Obsidian export) while the
concrete signal logic gets refined against real data.

Tone: direct and operational — short sentences, action-oriented.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.of_intelligence import (
    BusinessMemoryEntry,
    OfIntelligenceAccount,
    OfIntelligenceAlert,
    OfIntelligenceChatter,
    OfIntelligenceMassMessage,
    OfIntelligenceQcReport,
    OfIntelligenceRevenue,
    OfIntelligenceSyncLog,
)

logger = logging.getLogger(__name__)


@dataclass
class QcReportPayload:
    report_date: datetime
    summary: str
    critical_alerts: list[dict[str, Any]] = field(default_factory=list)
    account_reviews: list[dict[str, Any]] = field(default_factory=list)
    chatter_reviews: list[dict[str, Any]] = field(default_factory=list)
    posting_insights: dict[str, Any] = field(default_factory=dict)
    mass_message_insights: dict[str, Any] = field(default_factory=dict)
    action_list: list[str] = field(default_factory=list)
    accounts_reviewed: int = 0
    chatters_reviewed: int = 0


# ── Public entrypoint ────────────────────────────────────────────────────────


async def generate_qc_report(
    session: AsyncSession,
    *,
    report_date: datetime | None = None,
) -> OfIntelligenceQcReport:
    """Generate, persist, and return a QC report row.

    The skeleton always succeeds — when no data has been synced yet, the
    report renders empty sections with a clear "no data" status so the UI
    has something useful to show on day one.
    """
    target_date = report_date or utcnow()
    payload = await _build_payload(session, target_date=target_date)
    markdown = _render_markdown(payload)

    report = OfIntelligenceQcReport(
        report_date=target_date,
        summary=payload.summary,
        critical_alerts_count=len(payload.critical_alerts),
        accounts_reviewed=payload.accounts_reviewed,
        chatters_reviewed=payload.chatters_reviewed,
        payload={
            "summary": payload.summary,
            "critical_alerts": payload.critical_alerts,
            "account_reviews": payload.account_reviews,
            "chatter_reviews": payload.chatter_reviews,
            "posting_insights": payload.posting_insights,
            "mass_message_insights": payload.mass_message_insights,
            "action_list": payload.action_list,
        },
        markdown=markdown,
        generated_at=utcnow(),
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)

    # Mirror into the searchable memory store so AI agents can recall it.
    session.add(BusinessMemoryEntry(
        product="of_intelligence",
        kind="qc_report",
        title=f"QC Report — {target_date.date().isoformat()}",
        body=markdown,
        period_start=target_date.replace(hour=0, minute=0, second=0, microsecond=0),
        period_end=target_date,
        tags=["qc_report", f"critical:{len(payload.critical_alerts)}"],
        metadata_={"qc_report_id": str(report.id)},
    ))
    await session.commit()

    logger.info(
        "of_intelligence.qc.generated date=%s critical=%s accounts=%s chatters=%s",
        target_date.date().isoformat(),
        len(payload.critical_alerts),
        payload.accounts_reviewed,
        payload.chatters_reviewed,
    )
    return report


# ── Heuristic skeletons ──────────────────────────────────────────────────────


async def _build_payload(session: AsyncSession, *, target_date: datetime) -> QcReportPayload:
    accounts = (await session.exec(select(OfIntelligenceAccount))).all()
    chatters = (await session.exec(select(OfIntelligenceChatter))).all()

    payload = QcReportPayload(
        report_date=target_date,
        summary="No data synced yet — pending OnlyMonster API connection." if not accounts else "Daily QC summary.",
        accounts_reviewed=len(accounts),
        chatters_reviewed=len(chatters),
    )

    payload.critical_alerts.extend(await _detect_sync_failures(session))
    payload.critical_alerts.extend(await _detect_access_issues(session, accounts))

    payload.account_reviews = await _summarize_accounts(session, accounts)
    payload.chatter_reviews = _summarize_chatters(chatters)
    payload.mass_message_insights = await _summarize_mass_messages(session)
    payload.posting_insights = {
        "best_windows": [],
        "weak_windows": [],
        "recommended_changes": [],
        "note": "Posting heuristics will activate once posts and post-engagement data are syncing.",
    }

    payload.action_list = _build_action_list(payload)
    return payload


async def _detect_sync_failures(session: AsyncSession) -> list[dict[str, Any]]:
    """Surface any sync_log error rows from the last 24h."""
    cutoff = utcnow() - timedelta(hours=24)
    rows = (await session.exec(
        select(OfIntelligenceSyncLog)
        .where(OfIntelligenceSyncLog.started_at >= cutoff)
        .where(OfIntelligenceSyncLog.status == "error")
    )).all()
    return [
        {
            "code": "sync_error",
            "severity": "critical",
            "title": f"Sync failed: {row.entity}",
            "detail": row.error or row.reason or "unknown error",
            "entity": row.entity,
        }
        for row in rows
    ]


async def _detect_access_issues(
    session: AsyncSession,
    accounts: list[OfIntelligenceAccount],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    stale_cutoff = utcnow() - timedelta(hours=6)
    for account in accounts:
        if (account.access_status or "").lower() in {"lost", "blocked", "expired"}:
            issues.append({
                "code": "access_lost",
                "severity": "critical",
                "title": f"{account.username or account.source_id} may have lost access",
                "detail": f"access_status={account.access_status}",
                "account_source_id": account.source_id,
            })
        elif account.last_synced_at < stale_cutoff:
            issues.append({
                "code": "stale_sync",
                "severity": "warn",
                "title": f"{account.username or account.source_id} hasn't synced in 6h+",
                "detail": f"last_synced_at={account.last_synced_at.isoformat()}",
                "account_source_id": account.source_id,
            })
    return issues


async def _summarize_accounts(
    session: AsyncSession,
    accounts: list[OfIntelligenceAccount],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    if not accounts:
        return summaries

    yesterday = utcnow() - timedelta(days=1)
    for account in accounts:
        revenue_rows = (await session.exec(
            select(OfIntelligenceRevenue)
            .where(OfIntelligenceRevenue.account_source_id == account.source_id)
            .where(OfIntelligenceRevenue.captured_at >= yesterday)
        )).all()
        revenue_24h_cents = sum(r.revenue_cents for r in revenue_rows)
        summaries.append({
            "account_source_id": account.source_id,
            "username": account.username,
            "status": account.status,
            "access_status": account.access_status,
            "revenue_24h_cents": revenue_24h_cents,
            "problems": [
                p for p in (
                    "stale_sync" if account.last_synced_at < utcnow() - timedelta(hours=6) else None,
                    "no_revenue_24h" if revenue_24h_cents == 0 else None,
                ) if p
            ],
            "recommended_action": (
                "Investigate sync — possible access issue."
                if account.last_synced_at < utcnow() - timedelta(hours=6)
                else None
            ),
        })
    return summaries


def _summarize_chatters(chatters: list[OfIntelligenceChatter]) -> list[dict[str, Any]]:
    if not chatters:
        return []
    return [
        {
            "chatter_source_id": c.source_id,
            "name": c.name,
            "active": c.active,
            "score": None,  # populated once response-time + conversion heuristics land
            "issues": [],
            "examples": [],
            "recommended_fix": None,
        }
        for c in chatters
    ]


async def _summarize_mass_messages(session: AsyncSession) -> dict[str, Any]:
    rows = (await session.exec(
        select(OfIntelligenceMassMessage)
        .order_by(OfIntelligenceMassMessage.snapshot_at.desc())
        .limit(50)
    )).all()
    if not rows:
        return {"best": None, "worst": None, "recommended_changes": [], "note": "No mass-message data yet."}

    ranked = sorted(
        rows,
        key=lambda r: ((r.revenue_cents or 0) / max(r.recipients_count or 1, 1)),
        reverse=True,
    )
    return {
        "best": _mm_summary(ranked[0]) if ranked else None,
        "worst": _mm_summary(ranked[-1]) if ranked else None,
        "recommended_changes": [],
    }


def _mm_summary(row: OfIntelligenceMassMessage) -> dict[str, Any]:
    return {
        "source_id": row.source_id,
        "account_source_id": row.account_source_id,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "recipients_count": row.recipients_count,
        "purchases_count": row.purchases_count,
        "revenue_cents": row.revenue_cents,
        "body_preview": (row.body_preview or "")[:120],
    }


def _build_action_list(payload: QcReportPayload) -> list[str]:
    actions: list[str] = []
    for alert in payload.critical_alerts:
        actions.append(alert["title"])
    for review in payload.account_reviews:
        if review.get("recommended_action"):
            actions.append(f"{review['username'] or review['account_source_id']}: {review['recommended_action']}")
    return actions


# ── Markdown renderer ────────────────────────────────────────────────────────


def _render_markdown(payload: QcReportPayload) -> str:
    lines = [
        "# OnlyFans Intelligence — QC Report",
        f"**Date:** {payload.report_date.date().isoformat()}",
        "",
        f"_{payload.summary}_",
        "",
        "## Critical Alerts",
    ]
    if not payload.critical_alerts:
        lines.append("- None")
    else:
        for idx, alert in enumerate(payload.critical_alerts, 1):
            lines.append(f"{idx}. **{alert['title']}** — {alert.get('detail', '')}")

    lines.extend(["", "## Account Review"])
    if not payload.account_reviews:
        lines.append("- No accounts synced.")
    else:
        for review in payload.account_reviews:
            lines.append(
                f"- **{review.get('username') or review['account_source_id']}** "
                f"(status={review.get('status')}, access={review.get('access_status')}): "
                f"revenue 24h ${(review.get('revenue_24h_cents') or 0) / 100:.2f} — "
                f"{', '.join(review.get('problems') or []) or 'no flags'}"
            )

    lines.extend(["", "## Chatter Review"])
    if not payload.chatter_reviews:
        lines.append("- No chatters synced.")
    else:
        for chatter in payload.chatter_reviews:
            lines.append(f"- {chatter.get('name') or chatter['chatter_source_id']} (score=pending)")

    lines.extend([
        "",
        "## Posting Insights",
        f"_{payload.posting_insights.get('note', '')}_",
        "",
        "## Mass Message Insights",
    ])
    mm = payload.mass_message_insights
    if mm.get("note"):
        lines.append(f"_{mm['note']}_")
    else:
        if mm.get("best"):
            best = mm["best"]
            lines.append(f"- **Best:** ${(best.get('revenue_cents') or 0) / 100:.2f} from {best.get('recipients_count')} recipients")
        if mm.get("worst"):
            worst = mm["worst"]
            lines.append(f"- **Worst:** ${(worst.get('revenue_cents') or 0) / 100:.2f} from {worst.get('recipients_count')} recipients")

    lines.extend(["", "## Action List"])
    if not payload.action_list:
        lines.append("- None")
    else:
        for idx, item in enumerate(payload.action_list, 1):
            lines.append(f"{idx}. {item}")

    return "\n".join(lines)


# Re-export type for the alerts module so it can mirror QC findings.
__all__ = ["generate_qc_report", "QcReportPayload"]


# Suppress unused-import warning for OfIntelligenceAlert — kept here to keep
# the module's surface area clear when adding future alert mirroring.
_ = OfIntelligenceAlert
