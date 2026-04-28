"""OnlyFans Intelligence QC Bot — daily report skeleton.

Produces a structured, opinionated report from the synced data.  This is the
*skeleton* — the heuristics here are intentionally simple so the surface
exists for downstream consumers (UI, alerts, Obsidian export) while the
concrete signal logic gets refined against real data.

Tone: direct and operational — short sentences, action-oriented.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.of_intelligence import (
    BusinessMemoryEntry,
    OfIntelligenceAccount,
    OfIntelligenceAlert,
    OfIntelligenceChatter,
    OfIntelligenceFan,
    OfIntelligenceMassMessage,
    OfIntelligenceQcReport,
    OfIntelligenceRevenue,
    OfIntelligenceSyncLog,
    OfIntelligenceTrackingLink,
)

# Constants for "interesting" thresholds.  Kept conservative so a quiet
# day doesn't generate noise — operator can tune later.
REVENUE_DROP_THRESHOLD_PCT = 25.0  # account flagged when 7d-revenue ≤ -25% vs prior 7d
STALE_SYNC_HOURS = 6

logger = logging.getLogger(__name__)


@dataclass
class QcReportPayload:
    report_date: datetime
    summary: str
    agency_summary: dict[str, Any] = field(default_factory=dict)
    revenue_summary: dict[str, Any] = field(default_factory=dict)
    fan_growth: dict[str, Any] = field(default_factory=dict)
    chargebacks_summary: dict[str, Any] = field(default_factory=dict)
    tracking_links_summary: dict[str, Any] = field(default_factory=dict)
    trial_links_summary: dict[str, Any] = field(default_factory=dict)
    sync_health: dict[str, Any] = field(default_factory=dict)
    critical_alerts: list[dict[str, Any]] = field(default_factory=list)
    account_reviews: list[dict[str, Any]] = field(default_factory=list)
    chatter_reviews: list[dict[str, Any]] = field(default_factory=list)
    chatter_qc_note: str = ""
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
            "agency_summary": payload.agency_summary,
            "revenue_summary": payload.revenue_summary,
            "fan_growth": payload.fan_growth,
            "chargebacks_summary": payload.chargebacks_summary,
            "tracking_links_summary": payload.tracking_links_summary,
            "trial_links_summary": payload.trial_links_summary,
            "sync_health": payload.sync_health,
            "critical_alerts": payload.critical_alerts,
            "account_reviews": payload.account_reviews,
            "chatter_reviews": payload.chatter_reviews,
            "chatter_qc_note": payload.chatter_qc_note,
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
    session.add(
        BusinessMemoryEntry(
            product="of_intelligence",
            kind="qc_report",
            title=f"QC Report — {target_date.date().isoformat()}",
            body=markdown,
            period_start=target_date.replace(hour=0, minute=0, second=0, microsecond=0),
            period_end=target_date,
            tags=["qc_report", f"critical:{len(payload.critical_alerts)}"],
            metadata_={"qc_report_id": str(report.id)},
        )
    )
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
        summary=(
            "No data synced yet — pending OnlyMonster API connection."
            if not accounts
            else "Daily QC summary."
        ),
        accounts_reviewed=len(accounts),
        chatters_reviewed=len(chatters),
        chatter_qc_note=(
            "Message-level chatter QC unavailable until chat discovery is wired. "
            "Counts and access-status flags below come from the accounts/members "
            "endpoints; response-time and conversation-depth metrics will activate "
            "once the OnlyMonster `/chats` listing is exposed."
        ),
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

    payload.revenue_summary = await _summarize_revenue(session, target_date)
    payload.chargebacks_summary = await _summarize_chargebacks(session, target_date)
    payload.fan_growth = await _summarize_fan_growth(session, target_date)
    payload.tracking_links_summary = await _summarize_links(session, kind="tracking")
    payload.trial_links_summary = await _summarize_links(session, kind="trial")
    payload.sync_health = await _summarize_sync_health(session)
    payload.agency_summary = _build_agency_summary(payload, accounts)

    # Account-level revenue drops feed back into critical alerts so they
    # show up in the action list automatically.
    drop_alerts = await _detect_revenue_drops(session, target_date, accounts)
    payload.critical_alerts.extend(drop_alerts)

    payload.action_list = _build_action_list(payload)
    return payload


async def _detect_sync_failures(session: AsyncSession) -> list[dict[str, Any]]:
    """Surface any sync_log error rows from the last 24h."""
    cutoff = utcnow() - timedelta(hours=24)
    rows = (
        await session.exec(
            select(OfIntelligenceSyncLog)
            .where(OfIntelligenceSyncLog.started_at >= cutoff)
            .where(OfIntelligenceSyncLog.status == "error")
        )
    ).all()
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
    accounts: Sequence[OfIntelligenceAccount],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    stale_cutoff = utcnow() - timedelta(hours=6)
    for account in accounts:
        if (account.access_status or "").lower() in {"lost", "blocked", "expired"}:
            issues.append(
                {
                    "code": "access_lost",
                    "severity": "critical",
                    "title": f"{account.username or account.source_id} may have lost access",
                    "detail": f"access_status={account.access_status}",
                    "account_source_id": account.source_id,
                }
            )
        elif account.last_synced_at < stale_cutoff:
            issues.append(
                {
                    "code": "stale_sync",
                    "severity": "warn",
                    "title": f"{account.username or account.source_id} hasn't synced in 6h+",
                    "detail": f"last_synced_at={account.last_synced_at.isoformat()}",
                    "account_source_id": account.source_id,
                }
            )
    return issues


async def _summarize_accounts(
    session: AsyncSession,
    accounts: Sequence[OfIntelligenceAccount],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    if not accounts:
        return summaries

    yesterday = utcnow() - timedelta(days=1)
    for account in accounts:
        revenue_rows = (
            await session.exec(
                select(OfIntelligenceRevenue)
                .where(OfIntelligenceRevenue.account_source_id == account.source_id)
                .where(OfIntelligenceRevenue.captured_at >= yesterday)
            )
        ).all()
        revenue_24h_cents = sum(r.revenue_cents for r in revenue_rows)
        summaries.append(
            {
                "account_source_id": account.source_id,
                "username": account.username,
                "status": account.status,
                "access_status": account.access_status,
                "revenue_24h_cents": revenue_24h_cents,
                "problems": [
                    p
                    for p in (
                        (
                            "stale_sync"
                            if account.last_synced_at < utcnow() - timedelta(hours=6)
                            else None
                        ),
                        "no_revenue_24h" if revenue_24h_cents == 0 else None,
                    )
                    if p
                ],
                "recommended_action": (
                    "Investigate sync — possible access issue."
                    if account.last_synced_at < utcnow() - timedelta(hours=6)
                    else None
                ),
            }
        )
    return summaries


def _summarize_chatters(chatters: Sequence[OfIntelligenceChatter]) -> list[dict[str, Any]]:
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
    rows = (
        await session.exec(
            select(OfIntelligenceMassMessage)
            .order_by(col(OfIntelligenceMassMessage.snapshot_at).desc())
            .limit(50)
        )
    ).all()
    if not rows:
        return {
            "best": None,
            "worst": None,
            "recommended_changes": [],
            "note": "No mass-message data yet.",
        }

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
            actions.append(
                f"{review['username'] or review['account_source_id']}: {review['recommended_action']}"
            )
    sh = payload.sync_health
    if sh and sh.get("entities_failed"):
        actions.append(f"Investigate {len(sh['entities_failed'])} sync failure(s) since last run.")
    return actions


def _build_agency_summary(
    payload: QcReportPayload,
    accounts: Sequence[OfIntelligenceAccount],
) -> dict[str, Any]:
    """Top-line agency snapshot — single-line readable summary plus structured KPIs."""
    rev = payload.revenue_summary
    fan = payload.fan_growth
    needing_attention = sum(
        1
        for a in accounts
        if (a.access_status or "").lower() in {"lost", "blocked", "expired"}
        or (utcnow() - a.last_synced_at).total_seconds() > STALE_SYNC_HOURS * 3600
    )
    return {
        "accounts_total": len(accounts),
        "accounts_needing_attention": needing_attention,
        "revenue_today_cents": rev.get("today_cents", 0),
        "revenue_7d_cents": rev.get("seven_day_cents", 0),
        "revenue_30d_cents": rev.get("thirty_day_cents", 0),
        "fans_total": fan.get("total", 0),
        "fans_added_7d": fan.get("added_7d", 0),
        "critical_alerts_count": len(payload.critical_alerts),
    }


# ── New summarizers (Daily QC scheduler — full report) ───────────────────────


async def _summarize_revenue(session: AsyncSession, target_date: datetime) -> dict[str, Any]:
    """Bucket revenue by transaction time (period_start) into today / 7d / 30d.

    Excludes chargeback rows (kind=chargeback) — those are reported in
    `chargebacks_summary` separately so the headline revenue isn't
    distorted by negative refunds.
    """
    rows = (await session.exec(select(OfIntelligenceRevenue))).all()
    today_cents = seven_cents = thirty_cents = 0
    today_start = datetime.combine(target_date.date(), datetime.min.time())
    seven_cutoff = target_date - timedelta(days=7)
    thirty_cutoff = target_date - timedelta(days=30)
    for r in rows:
        if r.breakdown and r.breakdown.get("kind") == "chargeback":
            continue
        when = r.period_start or r.captured_at
        if when >= today_start:
            today_cents += r.revenue_cents
        if when >= seven_cutoff:
            seven_cents += r.revenue_cents
        if when >= thirty_cutoff:
            thirty_cents += r.revenue_cents
    return {
        "today_cents": today_cents,
        "seven_day_cents": seven_cents,
        "thirty_day_cents": thirty_cents,
    }


async def _summarize_chargebacks(session: AsyncSession, target_date: datetime) -> dict[str, Any]:
    """Negative-revenue rows tagged `breakdown.kind=chargeback`."""
    rows = (await session.exec(select(OfIntelligenceRevenue))).all()
    seven_cutoff = target_date - timedelta(days=7)
    thirty_cutoff = target_date - timedelta(days=30)
    seven_count = thirty_count = 0
    seven_cents = thirty_cents = 0
    for r in rows:
        if not (r.breakdown and r.breakdown.get("kind") == "chargeback"):
            continue
        when = r.period_start or r.captured_at
        if when >= seven_cutoff:
            seven_count += 1
            seven_cents += r.revenue_cents
        if when >= thirty_cutoff:
            thirty_count += 1
            thirty_cents += r.revenue_cents
    return {
        "seven_day_count": seven_count,
        "seven_day_cents": seven_cents,
        "thirty_day_count": thirty_count,
        "thirty_day_cents": thirty_cents,
    }


async def _summarize_fan_growth(session: AsyncSession, target_date: datetime) -> dict[str, Any]:
    """Fan totals + how many were first seen in the last 7 / 30 days."""
    rows = (await session.exec(select(OfIntelligenceFan))).all()
    seven_cutoff = target_date - timedelta(days=7)
    thirty_cutoff = target_date - timedelta(days=30)
    added_7d = sum(1 for f in rows if f.first_seen_at >= seven_cutoff)
    added_30d = sum(1 for f in rows if f.first_seen_at >= thirty_cutoff)
    return {
        "total": len(rows),
        "added_7d": added_7d,
        "added_30d": added_30d,
    }


async def _summarize_links(session: AsyncSession, *, kind: str) -> dict[str, Any]:
    """Roll up trial or tracking link performance.

    The `kind` arg matches the `raw.kind` value set by the persister
    (`"trial"` or `"tracking"`) and the `source_id` prefix
    (`trial:<id>` / `tracking:<id>`).
    """
    rows = (await session.exec(select(OfIntelligenceTrackingLink))).all()
    matching = [r for r in rows if r.source_id.startswith(f"{kind}:")]
    if not matching:
        return {"count": 0, "total_clicks": 0, "total_conversions": 0, "best": None}

    total_clicks = sum(r.clicks or 0 for r in matching)
    total_conversions = sum(r.conversions or 0 for r in matching)
    best = max(matching, key=lambda r: (r.conversions or 0, r.clicks or 0))
    return {
        "count": len(matching),
        "total_clicks": total_clicks,
        "total_conversions": total_conversions,
        "best": {
            "name": best.name,
            "url": best.url,
            "clicks": best.clicks,
            "conversions": best.conversions,
            "account_source_id": best.account_source_id,
        },
    }


async def _summarize_sync_health(session: AsyncSession) -> dict[str, Any]:
    """Most recent sync run's per-entity status mix."""
    rows = (
        await session.exec(
            select(OfIntelligenceSyncLog)
            .order_by(col(OfIntelligenceSyncLog.started_at).desc())
            .limit(200)
        )
    ).all()
    if not rows:
        return {
            "last_run_id": None,
            "entities_success": [],
            "entities_failed": [],
            "entities_skipped": [],
            "note": "No sync runs yet.",
        }

    latest_run_id = rows[0].run_id
    in_run = [r for r in rows if r.run_id == latest_run_id]
    success: list[str] = []
    failed: list[dict[str, Any]] = []
    skipped: list[str] = []
    for row in in_run:
        if row.status == "success":
            success.append(row.entity)
        elif row.status in ("error", "partial"):
            failed.append({"entity": row.entity, "reason": row.reason, "error": row.error})
        else:
            skipped.append(f"{row.entity} ({row.status})")

    return {
        "last_run_id": str(latest_run_id),
        "last_run_started_at": rows[0].started_at.isoformat(),
        "entities_success": success,
        "entities_failed": failed,
        "entities_skipped": skipped,
    }


async def _detect_revenue_drops(
    session: AsyncSession,
    target_date: datetime,
    accounts: Sequence[OfIntelligenceAccount],
) -> list[dict[str, Any]]:
    """Flag accounts whose 7-day revenue dropped >threshold% vs prior 7d."""
    if not accounts:
        return []
    rows = (await session.exec(select(OfIntelligenceRevenue))).all()
    seven_cutoff = target_date - timedelta(days=7)
    fourteen_cutoff = target_date - timedelta(days=14)

    by_account: dict[str, dict[str, int]] = {}
    for r in rows:
        if r.breakdown and r.breakdown.get("kind") == "chargeback":
            continue
        if not r.account_source_id:
            continue
        when = r.period_start or r.captured_at
        bucket = by_account.setdefault(r.account_source_id, {"recent": 0, "prior": 0})
        if when >= seven_cutoff:
            bucket["recent"] += r.revenue_cents
        elif when >= fourteen_cutoff:
            bucket["prior"] += r.revenue_cents

    alerts: list[dict[str, Any]] = []
    for account_id, b in by_account.items():
        prior = b["prior"]
        recent = b["recent"]
        # Only flag when there's meaningful prior revenue to compare against.
        if prior < 100:  # less than $1 prior — too noisy
            continue
        delta_pct = ((recent - prior) / prior) * 100.0
        if delta_pct <= -REVENUE_DROP_THRESHOLD_PCT:
            username = next(
                (a.username for a in accounts if a.source_id == account_id and a.username),
                account_id,
            )
            alerts.append(
                {
                    "code": "revenue_drop",
                    "severity": "warn",
                    "title": f"{username} revenue dropped {abs(delta_pct):.0f}% week-over-week",
                    "detail": f"prior ${prior / 100:.2f} → recent ${recent / 100:.2f}",
                    "account_source_id": account_id,
                }
            )
    return alerts


# ── Markdown renderer ────────────────────────────────────────────────────────


def _render_markdown(payload: QcReportPayload) -> str:
    a = payload.agency_summary
    rev = payload.revenue_summary
    cb = payload.chargebacks_summary
    fan = payload.fan_growth
    sh = payload.sync_health
    tl = payload.tracking_links_summary
    trial = payload.trial_links_summary

    lines = [
        "# OnlyFans Intelligence — QC Report",
        f"**Date:** {payload.report_date.date().isoformat()}",
        "",
        f"_{payload.summary}_",
        "",
        "## Agency Summary",
    ]
    if a:
        lines.extend(
            [
                f"- Accounts: **{a.get('accounts_total', 0)}** "
                f"({a.get('accounts_needing_attention', 0)} needing attention)",
                f"- Revenue today: **${(a.get('revenue_today_cents') or 0) / 100:.2f}**",
                f"- Revenue 7d: ${(a.get('revenue_7d_cents') or 0) / 100:.2f} · "
                f"30d: ${(a.get('revenue_30d_cents') or 0) / 100:.2f}",
                f"- Fans: {a.get('fans_total', 0)} total · +{a.get('fans_added_7d', 0)} in last 7d",
                f"- Critical alerts: **{a.get('critical_alerts_count', 0)}**",
            ]
        )
    else:
        lines.append("- (No data)")

    lines.extend(
        [
            "",
            "## Revenue",
            f"- Today: ${(rev.get('today_cents') or 0) / 100:.2f}",
            f"- Last 7 days: ${(rev.get('seven_day_cents') or 0) / 100:.2f}",
            f"- Last 30 days: ${(rev.get('thirty_day_cents') or 0) / 100:.2f}",
            "",
            "## Chargebacks",
            f"- Last 7d: {cb.get('seven_day_count', 0)} chargebacks "
            f"(${(cb.get('seven_day_cents') or 0) / 100:.2f})",
            f"- Last 30d: {cb.get('thirty_day_count', 0)} chargebacks "
            f"(${(cb.get('thirty_day_cents') or 0) / 100:.2f})",
            "",
            "## Fan Growth",
            f"- Total fans: {fan.get('total', 0)}",
            f"- New in last 7d: {fan.get('added_7d', 0)}",
            f"- New in last 30d: {fan.get('added_30d', 0)}",
            "",
            "## Critical Alerts",
        ]
    )
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
    if payload.chatter_qc_note:
        lines.append(f"_{payload.chatter_qc_note}_")
        lines.append("")
    if not payload.chatter_reviews:
        lines.append("- No chatters synced.")
    else:
        for chatter in payload.chatter_reviews:
            lines.append(f"- {chatter.get('name') or chatter['chatter_source_id']} (score=pending)")

    lines.extend(
        [
            "",
            "## Tracking Links",
            (
                f"- {tl.get('count', 0)} active · {tl.get('total_clicks', 0)} clicks · "
                f"{tl.get('total_conversions', 0)} conversions"
                if tl.get("count")
                else "- None synced."
            ),
        ]
    )
    if tl.get("best"):
        b = tl["best"]
        lines.append(
            f"- Best: **{b.get('name') or '(unnamed)'}** "
            f"({b.get('clicks', 0)} clicks → {b.get('conversions', 0)} conversions)"
        )

    lines.extend(
        [
            "",
            "## Trial Links",
            (
                f"- {trial.get('count', 0)} active · {trial.get('total_clicks', 0)} clicks · "
                f"{trial.get('total_conversions', 0)} conversions"
                if trial.get("count")
                else "- None synced."
            ),
        ]
    )
    if trial.get("best"):
        b = trial["best"]
        lines.append(
            f"- Best: **{b.get('name') or '(unnamed)'}** "
            f"({b.get('clicks', 0)} clicks → {b.get('conversions', 0)} conversions)"
        )

    lines.extend(["", "## Sync Health"])
    if not sh or sh.get("note"):
        lines.append(f"- {sh.get('note') if sh else 'No sync activity recorded.'}")
    else:
        success_n = len(sh.get("entities_success", []))
        failed_n = len(sh.get("entities_failed", []))
        skipped_n = len(sh.get("entities_skipped", []))
        lines.append(f"- Latest run: {success_n} success / {failed_n} failed / {skipped_n} skipped")
        for f in sh.get("entities_failed", [])[:5]:
            lines.append(
                f"  - ❌ {f.get('entity')}: {f.get('reason') or f.get('error') or 'error'}"
            )

    lines.extend(
        [
            "",
            "## Posting Insights",
            f"_{payload.posting_insights.get('note', '')}_",
            "",
            "## Mass Message Insights",
        ]
    )
    mm = payload.mass_message_insights
    if mm.get("note"):
        lines.append(f"_{mm['note']}_")
    else:
        if mm.get("best"):
            best = mm["best"]
            lines.append(
                f"- **Best:** ${(best.get('revenue_cents') or 0) / 100:.2f} from {best.get('recipients_count')} recipients"
            )
        if mm.get("worst"):
            worst = mm["worst"]
            lines.append(
                f"- **Worst:** ${(worst.get('revenue_cents') or 0) / 100:.2f} from {worst.get('recipients_count')} recipients"
            )

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
