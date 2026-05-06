"""Layer 3 — daily QC scorecard.

Single-shot generator.  Pulls Layer 1 (system health) and Layer 2 (chatter
QC) signals from the database, builds a structured digest, and ships it
to Discord (when called via the daily endpoint / scheduler).

Privacy: only privacy-safe fields render — display names, code names,
counts, severities.  Bodies, fan handles, raw payloads — never.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.of_intelligence import (
    OfIntelligenceAccount,
    OfIntelligenceAlert,
    OfIntelligenceChatter,
    OfIntelligenceMessage,
)
from app.models.of_qc_finding import OfIntelligenceQcFinding
from app.services.of_intelligence.qc.formatters import (
    RolledUpPayload,
    format_rollup,
)
from app.services.of_intelligence.qc.publisher import PublishResult, publish
from app.services.of_intelligence.qc.severity import Severity

logger = get_logger(__name__)

DAILY_SUMMARY_CODE = "qc_daily_summary"


@dataclass
class DailySummary:
    generated_at: datetime
    accounts_reviewed: int
    chats_reviewed: int  # distinct chat_source_ids in last 24h
    total_findings: int
    critical_alert_count: int
    worst_accounts: list[tuple[str, int]] = field(default_factory=list)  # (display, count)
    worst_chatters: list[tuple[str, int]] = field(default_factory=list)
    repeat_offenders: list[str] = field(default_factory=list)
    missed_sales_signals: int = 0
    follow_ups_needed: int = 0  # missed_follow_up findings in window
    slow_responses: int = 0  # slow_response findings in window
    layer1_open_alerts: list[str] = field(default_factory=list)  # codes
    layer2_open_alerts: list[str] = field(default_factory=list)  # codes
    actions: list[str] = field(default_factory=list)


# Severity strings considered "critical" for the summary count.
_CRITICAL_SEVERITIES = {"critical"}
# Layer-2 codes (everything else is Layer 1).
_LAYER2_CODES = {
    "refund_risk",
    "banned_content_risk",
    "rude_reply",
    "serious_escalation_risk",
    "missed_buying_signal",
    "weak_sales_handling",
    "chatter_qc_rollup",
}


# ── Build ───────────────────────────────────────────────────────────────────


async def build_daily_summary(
    session: AsyncSession,
    *,
    window_hours: int = 24,
) -> DailySummary:
    cutoff = utcnow() - timedelta(hours=window_hours)

    # Accounts + chatters reviewed (anything synced in the window).
    account_rows = (
        await session.exec(
            select(OfIntelligenceAccount).where(OfIntelligenceAccount.last_synced_at >= cutoff)
        )
    ).all()
    chatters_seen_chat = (
        await session.exec(
            select(OfIntelligenceMessage.chat_source_id).where(
                OfIntelligenceMessage.sent_at >= cutoff
            )
        )
    ).all()
    chats_reviewed = len({c for c in chatters_seen_chat if c})

    # Findings (Layer 2 details).
    findings = (
        await session.exec(
            select(OfIntelligenceQcFinding).where(OfIntelligenceQcFinding.created_at >= cutoff)
        )
    ).all()

    findings_by_account: Counter[str] = Counter()
    findings_by_chatter: Counter[str] = Counter()
    pair_codes: Counter[tuple[str | None, str | None, str]] = Counter()
    for f in findings:
        if f.account_source_id:
            findings_by_account[f.account_source_id] += 1
        if f.chatter_source_id:
            findings_by_chatter[f.chatter_source_id] += 1
        pair_codes[(f.chatter_source_id, f.account_source_id, f.code)] += 1

    repeat_pairs = [
        (ch_id, acct_id, code) for (ch_id, acct_id, code), n in pair_codes.items() if n >= 3
    ]

    # Resolve display names for the worst lists.
    account_names = {a.source_id: a.username for a in account_rows}
    extra_account_ids = [a for a in findings_by_account.keys() if a not in account_names]
    if extra_account_ids:
        more = (
            await session.exec(
                select(OfIntelligenceAccount).where(
                    col(OfIntelligenceAccount.source_id).in_(set(extra_account_ids))
                )
            )
        ).all()
        for a in more:
            account_names[a.source_id] = a.username

    chatter_rows = (
        (
            await session.exec(
                select(OfIntelligenceChatter).where(
                    col(OfIntelligenceChatter.source_id).in_(set(findings_by_chatter.keys()))
                )
            )
        ).all()
        if findings_by_chatter
        else []
    )
    chatter_names = {c.source_id: c.name for c in chatter_rows}

    worst_accounts = [
        (account_names.get(aid) or "<account>", n) for aid, n in findings_by_account.most_common(3)
    ]
    worst_chatters = [
        (chatter_names.get(cid) or "<chatter>", n) for cid, n in findings_by_chatter.most_common(3)
    ]
    repeat_offenders = sorted(
        {chatter_names.get(ch_id) or "<chatter>" for ch_id, _, _ in repeat_pairs}
    )

    # Open alerts (both layers).
    open_alerts = (
        await session.exec(select(OfIntelligenceAlert).where(OfIntelligenceAlert.status == "open"))
    ).all()
    critical_count = sum(1 for a in open_alerts if a.severity in _CRITICAL_SEVERITIES)
    layer1_open: list[str] = []
    layer2_open: list[str] = []
    for a in open_alerts:
        # Layer 2 codes are an explicit set; everything else (sync_failure:*,
        # account_blocked, api_disconnected, …) is Layer 1.
        if a.code in _LAYER2_CODES:
            layer2_open.append(a.code)
        else:
            layer1_open.append(a.code)

    missed_sales = sum(
        n
        for (ch, ac, code), n in pair_codes.items()
        if code in ("missed_buying_signal", "weak_sales_handling")
    )
    slow_responses = sum(n for (ch, ac, code), n in pair_codes.items() if code == "slow_response")
    follow_ups_needed = sum(
        n for (ch, ac, code), n in pair_codes.items() if code == "missed_follow_up"
    )

    actions: list[str] = []
    if repeat_offenders:
        actions.append(f"Coach repeat offenders: {', '.join(repeat_offenders)}")
    if "account_blocked" in layer1_open or "account_disconnected" in layer1_open:
        actions.append("Restore lost account access first.")
    if missed_sales:
        actions.append("Review missed buying-signal conversations in dashboard.")
    if follow_ups_needed:
        actions.append("Resume cold high-intent conversations from missed_follow_up findings.")
    if slow_responses:
        actions.append("Tighten chat response times — slow_response findings open.")
    if critical_count == 0 and not findings:
        actions.append("All clear — no QC issues in the last 24h.")

    return DailySummary(
        generated_at=utcnow(),
        accounts_reviewed=len(account_rows),
        chats_reviewed=chats_reviewed,
        total_findings=len(findings),
        critical_alert_count=critical_count,
        worst_accounts=worst_accounts,
        worst_chatters=worst_chatters,
        repeat_offenders=repeat_offenders,
        missed_sales_signals=missed_sales,
        follow_ups_needed=follow_ups_needed,
        slow_responses=slow_responses,
        layer1_open_alerts=sorted(set(layer1_open)),
        layer2_open_alerts=sorted(set(layer2_open)),
        actions=actions,
    )


# ── Render + ship ───────────────────────────────────────────────────────────


def render_daily_summary(summary: DailySummary) -> str:
    lines: list[str] = [
        f"Accounts reviewed: {summary.accounts_reviewed}",
        f"Chats reviewed: {summary.chats_reviewed}",
        f"Total QC findings: {summary.total_findings}",
        f"Critical alerts open: {summary.critical_alert_count}",
        f"Missed sales signals: {summary.missed_sales_signals}",
        f"Slow responses: {summary.slow_responses}",
        f"Follow-ups needed: {summary.follow_ups_needed}",
    ]
    if summary.worst_accounts:
        lines.append(
            "Worst accounts: " + ", ".join(f"{n} ({c})" for n, c in summary.worst_accounts)
        )
    if summary.worst_chatters:
        lines.append(
            "Worst chatters: " + ", ".join(f"{n} ({c})" for n, c in summary.worst_chatters)
        )
    if summary.repeat_offenders:
        lines.append("Repeat offenders: " + ", ".join(summary.repeat_offenders))
    if summary.layer1_open_alerts:
        lines.append("System health open: " + ", ".join(summary.layer1_open_alerts))
    if summary.layer2_open_alerts:
        lines.append("Business QC open: " + ", ".join(summary.layer2_open_alerts))

    payload = RolledUpPayload(
        severity=Severity.MEDIUM if summary.critical_alert_count == 0 else Severity.HIGH,
        window_label="last 24h",
        total_findings=summary.total_findings,
        chatter_count=len(summary.worst_chatters),
        account_count=len(summary.worst_accounts),
        lines=tuple(lines),
        action="; ".join(summary.actions) if summary.actions else None,
        refs=tuple(),
        title="Daily QC scorecard",
    )
    return format_rollup(payload)


async def ship_daily_summary(
    session: AsyncSession,
    *,
    window_hours: int = 24,
    bypass_kill_switch: bool = False,
) -> tuple[DailySummary, PublishResult]:
    """Build and ship the daily summary.  Returns (summary, publish_result)."""
    summary = await build_daily_summary(session, window_hours=window_hours)
    rendered = render_daily_summary(summary)
    severity = Severity.HIGH if summary.critical_alert_count > 0 else Severity.MEDIUM
    result = await publish(
        rendered,
        code=DAILY_SUMMARY_CODE,
        severity=severity.value,
        log_extra={
            "accounts": summary.accounts_reviewed,
            "findings": summary.total_findings,
            "critical": summary.critical_alert_count,
        },
        bypass_kill_switch=bypass_kill_switch,
    )
    return summary, result
