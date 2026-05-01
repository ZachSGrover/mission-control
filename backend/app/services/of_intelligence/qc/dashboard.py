"""Daily QC Dashboard payload assembler — Layer 3 read-only view.

Composes already-existing detectors / aggregators into a single
operator-facing payload.  Does NOT re-run sync.  Does NOT mutate state.
The endpoint is read-only — buttons that ship to Discord/Telegram call
*separate* endpoints whose privacy contract is independently enforced.

Privacy contract for the dashboard:
  • SAFE everywhere except ``fan_opportunities``, which MAY include the
    fan handle (Mode 3 — owner-only dashboard view).  Fan handles must
    NEVER appear in any other section, and must NEVER reach Discord or
    Telegram (those publishers ignore this payload entirely).
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
    OfIntelligenceChat,
    OfIntelligenceChatter,
    OfIntelligenceFan,
    OfIntelligenceMessage,
    OfIntelligenceRevenue,
    OfIntelligenceSyncLog,
)
from app.models.of_qc_finding import OfIntelligenceQcFinding
from app.services.of_intelligence.qc.daily_summary import build_daily_summary
from app.services.of_intelligence.qc.revenue import detect_revenue_drops

logger = get_logger(__name__)

# Layer 2 codes (Business QC).  Anything else from open alerts ends up in
# layer1.
_LAYER2_CODES = {
    "refund_risk",
    "banned_content_risk",
    "rude_reply",
    "serious_escalation_risk",
    "missed_buying_signal",
    "weak_sales_handling",
    "chatter_qc_rollup",
    "account_revenue_drop",
}


# ── Sub-payload dataclasses ─────────────────────────────────────────────────


@dataclass
class AccountStatus:
    account_id: str
    username: str | None
    health_status: str  # "ok" | "stale" | "blocked" | "expired" | "lost"
    last_synced_at: datetime | None
    hours_since_sync: int | None
    revenue_24h_cents: int
    revenue_7d_avg_cents: int
    open_layer1_codes: list[str]
    open_layer2_codes: list[str]


@dataclass
class RevenueWarning:
    account_id: str
    username: str | None
    revenue_24h_cents: int
    revenue_7d_avg_cents: int
    severity: str
    reason: str
    dashboard_ref: str  # qc/account/{source_id}


@dataclass
class AccountChattingQuality:
    account_id: str
    username: str | None
    total_findings: int
    critical_count: int
    high_count: int
    top_codes: list[tuple[str, int]]
    worst_chatter: str | None  # display name only


@dataclass
class ChatterMistake:
    chatter_name: str
    code: str
    count: int
    accounts_affected: int
    dashboard_ref: str  # qc/chatter/{source_id}


@dataclass
class FanOpportunity:
    finding_id: str  # uuid
    code: str
    severity: str
    account_username: str | None
    chatter_name: str | None
    fan_handle: str | None  # ALLOWED here, dashboard-only
    age_minutes: int
    dashboard_ref: str  # qc/finding/{uuid}


@dataclass
class SyncHealth:
    last_success_per_entity: dict[str, datetime | None]
    error_count_24h: int
    stale_account_count: int
    api_disconnected: bool


@dataclass
class DashboardPayload:
    generated_at: datetime
    account_status: list[AccountStatus] = field(default_factory=list)
    revenue_warnings: list[RevenueWarning] = field(default_factory=list)
    chatting_quality: list[AccountChattingQuality] = field(default_factory=list)
    chatter_mistakes: list[ChatterMistake] = field(default_factory=list)
    fan_opportunities: list[FanOpportunity] = field(default_factory=list)
    sync_health: SyncHealth | None = None
    action_list: list[str] = field(default_factory=list)


# ── Builder ─────────────────────────────────────────────────────────────────


_OPPORTUNITY_CODES = ("missed_buying_signal", "weak_sales_handling", "missed_follow_up")


async def build_dashboard(session: AsyncSession) -> DashboardPayload:
    now = utcnow()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    # ── Reuse detectors ─────────────────────────────────────────────────
    revenue_drops = await detect_revenue_drops(session)
    daily = await build_daily_summary(session)

    # ── Source rows ─────────────────────────────────────────────────────
    accounts = (await session.exec(select(OfIntelligenceAccount))).all()
    findings = (
        await session.exec(
            select(OfIntelligenceQcFinding).where(
                OfIntelligenceQcFinding.created_at >= cutoff_24h
            )
        )
    ).all()
    open_alerts = (
        await session.exec(
            select(OfIntelligenceAlert).where(OfIntelligenceAlert.status == "open")
        )
    ).all()
    revenue_rows = (
        await session.exec(
            select(OfIntelligenceRevenue).where(
                OfIntelligenceRevenue.period_start >= cutoff_7d
            )
        )
    ).all()

    # Resolve display names once.
    chatter_ids = {f.chatter_source_id for f in findings if f.chatter_source_id}
    chatters = (
        await session.exec(
            select(OfIntelligenceChatter).where(
                col(OfIntelligenceChatter.source_id).in_(chatter_ids)
            )
        )
    ).all() if chatter_ids else []
    chatter_name_by_id = {c.source_id: c.name for c in chatters}

    # ── account_status ──────────────────────────────────────────────────
    open_alerts_by_account: dict[str | None, list[str]] = {}
    for a in open_alerts:
        open_alerts_by_account.setdefault(a.account_source_id, []).append(a.code)

    rev_24h_by_acct: Counter[str] = Counter()
    rev_prior_by_acct: Counter[str] = Counter()
    for r in revenue_rows:
        if r.account_source_id is None or r.period_start is None:
            continue
        if r.period_start >= cutoff_24h:
            rev_24h_by_acct[r.account_source_id] += r.revenue_cents
        else:
            rev_prior_by_acct[r.account_source_id] += r.revenue_cents

    account_status: list[AccountStatus] = []
    for a in accounts:
        codes = open_alerts_by_account.get(a.source_id, [])
        layer1 = [c for c in codes if c not in _LAYER2_CODES]
        layer2 = [c for c in codes if c in _LAYER2_CODES]

        hours = None
        if a.last_synced_at is not None:
            hours = max(0, int((now - a.last_synced_at).total_seconds() // 3600))
        access = (a.access_status or "active").lower()
        if access in ("blocked", "expired", "lost"):
            health = access
        elif hours is not None and hours >= 6:
            health = "stale"
        else:
            health = "ok"

        avg7 = int(rev_prior_by_acct.get(a.source_id, 0) / 6.0)
        account_status.append(
            AccountStatus(
                account_id=a.source_id,
                username=a.username,
                health_status=health,
                last_synced_at=a.last_synced_at,
                hours_since_sync=hours,
                revenue_24h_cents=rev_24h_by_acct.get(a.source_id, 0),
                revenue_7d_avg_cents=avg7,
                open_layer1_codes=sorted(layer1),
                open_layer2_codes=sorted(layer2),
            )
        )

    # ── revenue_warnings ────────────────────────────────────────────────
    revenue_warnings = [
        RevenueWarning(
            account_id=w.account_source_id,
            username=w.username,
            revenue_24h_cents=w.revenue_24h_cents,
            revenue_7d_avg_cents=w.revenue_7d_avg_cents,
            severity=w.severity,
            reason=w.reason,
            dashboard_ref=f"qc/account/{w.account_source_id}",
        )
        for w in revenue_drops
    ]

    # ── chatting_quality ────────────────────────────────────────────────
    findings_by_account: dict[str, list[OfIntelligenceQcFinding]] = {}
    for f in findings:
        if f.account_source_id:
            findings_by_account.setdefault(f.account_source_id, []).append(f)

    account_name_by_id = {a.source_id: a.username for a in accounts}
    chatting_quality: list[AccountChattingQuality] = []
    for acct_id, account_findings in findings_by_account.items():
        code_counter: Counter[str] = Counter(f.code for f in account_findings)
        crit = sum(1 for f in account_findings if f.severity == "critical")
        high = sum(1 for f in account_findings if f.severity == "high")
        chatter_counter: Counter[str | None] = Counter(
            f.chatter_source_id for f in account_findings if f.chatter_source_id
        )
        worst_chatter_id = chatter_counter.most_common(1)[0][0] if chatter_counter else None
        chatting_quality.append(
            AccountChattingQuality(
                account_id=acct_id,
                username=account_name_by_id.get(acct_id),
                total_findings=len(account_findings),
                critical_count=crit,
                high_count=high,
                top_codes=code_counter.most_common(5),
                worst_chatter=chatter_name_by_id.get(worst_chatter_id) if worst_chatter_id else None,
            )
        )
    chatting_quality.sort(key=lambda x: x.total_findings, reverse=True)

    # ── chatter_mistakes ────────────────────────────────────────────────
    pair_counts: Counter[tuple[str | None, str]] = Counter()
    pair_accounts: dict[tuple[str | None, str], set[str]] = {}
    for f in findings:
        key = (f.chatter_source_id, f.code)
        pair_counts[key] += 1
        if f.account_source_id:
            pair_accounts.setdefault(key, set()).add(f.account_source_id)
    chatter_mistakes: list[ChatterMistake] = []
    for (chatter_id, code), count in pair_counts.most_common(10):
        chatter_mistakes.append(
            ChatterMistake(
                chatter_name=chatter_name_by_id.get(chatter_id) or "<chatter>",
                code=code,
                count=count,
                accounts_affected=len(pair_accounts.get((chatter_id, code), set())),
                dashboard_ref=f"qc/chatter/{chatter_id}" if chatter_id else "qc/chatter/unknown",
            )
        )

    # ── fan_opportunities ───────────────────────────────────────────────
    opp_findings = [f for f in findings if f.code in _OPPORTUNITY_CODES and f.rolled_up_at is None]

    # Resolve fan handles via OfIntelligenceMessage.fan_source_id → OfIntelligenceFan
    msg_ids = {f.message_source_id for f in opp_findings if f.message_source_id}
    msg_rows = (
        await session.exec(
            select(OfIntelligenceMessage).where(
                col(OfIntelligenceMessage.source_id).in_(msg_ids)
            )
        )
    ).all() if msg_ids else []
    fan_id_by_msg = {m.source_id: m.fan_source_id for m in msg_rows}

    fan_ids = {fid for fid in fan_id_by_msg.values() if fid}
    fan_rows = (
        await session.exec(
            select(OfIntelligenceFan).where(col(OfIntelligenceFan.source_id).in_(fan_ids))
        )
    ).all() if fan_ids else []
    handle_by_fan = {f.source_id: getattr(f, "username", None) for f in fan_rows}

    fan_opportunities: list[FanOpportunity] = []
    for f in opp_findings[:20]:  # cap so the dashboard doesn't bloat
        fan_id = fan_id_by_msg.get(f.message_source_id) if f.message_source_id else None
        fan_handle = handle_by_fan.get(fan_id) if fan_id else None
        age = max(0, int((now - f.created_at).total_seconds() // 60))
        fan_opportunities.append(
            FanOpportunity(
                finding_id=str(f.id),
                code=f.code,
                severity=f.severity,
                account_username=account_name_by_id.get(f.account_source_id) if f.account_source_id else None,
                chatter_name=chatter_name_by_id.get(f.chatter_source_id) if f.chatter_source_id else None,
                fan_handle=fan_handle,
                age_minutes=age,
                dashboard_ref=f"qc/finding/{f.id}",
            )
        )

    # ── sync_health ─────────────────────────────────────────────────────
    sync_logs = (
        await session.exec(
            select(OfIntelligenceSyncLog).where(
                OfIntelligenceSyncLog.started_at >= cutoff_24h
            )
        )
    ).all()
    last_success_per_entity: dict[str, datetime | None] = {}
    error_count_24h = 0
    for log in sync_logs:
        if log.status == "error":
            error_count_24h += 1
            continue
        if log.status == "success":
            existing = last_success_per_entity.get(log.entity)
            if existing is None or (log.started_at and log.started_at > existing):
                last_success_per_entity[log.entity] = log.started_at
    stale_count = sum(1 for s in account_status if s.health_status == "stale")
    api_disconnected = "api_disconnected" in {a.code for a in open_alerts}

    sync_health = SyncHealth(
        last_success_per_entity=last_success_per_entity,
        error_count_24h=error_count_24h,
        stale_account_count=stale_count,
        api_disconnected=api_disconnected,
    )

    # ── action_list (reuse Layer 3) ─────────────────────────────────────
    actions = list(daily.actions)

    # silence unused-import warnings in static analysis if Chats import isn't reached
    _ = OfIntelligenceChat

    return DashboardPayload(
        generated_at=now,
        account_status=account_status,
        revenue_warnings=revenue_warnings,
        chatting_quality=chatting_quality,
        chatter_mistakes=chatter_mistakes,
        fan_opportunities=fan_opportunities,
        sync_health=sync_health,
        action_list=actions,
    )


# ── Mock fixture for ?mock=1 ────────────────────────────────────────────────


def build_mock_payload() -> DashboardPayload:
    """Deterministic fixture — never reads the DB.

    Used by ``GET /qc/dashboard?mock=1`` for local frontend dev and CI.
    """
    now = utcnow()
    return DashboardPayload(
        generated_at=now,
        account_status=[
            AccountStatus(
                account_id="mock-acct-1",
                username="luna_demo",
                health_status="ok",
                last_synced_at=now - timedelta(minutes=20),
                hours_since_sync=0,
                revenue_24h_cents=12000,
                revenue_7d_avg_cents=15000,
                open_layer1_codes=[],
                open_layer2_codes=[],
            ),
            AccountStatus(
                account_id="mock-acct-2",
                username="indigo_demo",
                health_status="stale",
                last_synced_at=now - timedelta(hours=8),
                hours_since_sync=8,
                revenue_24h_cents=0,
                revenue_7d_avg_cents=22000,
                open_layer1_codes=["account_stale"],
                open_layer2_codes=["account_revenue_drop"],
            ),
        ],
        revenue_warnings=[
            RevenueWarning(
                account_id="mock-acct-2",
                username="indigo_demo",
                revenue_24h_cents=0,
                revenue_7d_avg_cents=22000,
                severity="medium",
                reason="zero 24h revenue with prior history",
                dashboard_ref="qc/account/mock-acct-2",
            ),
        ],
        chatting_quality=[
            AccountChattingQuality(
                account_id="mock-acct-1",
                username="luna_demo",
                total_findings=4,
                critical_count=0,
                high_count=1,
                top_codes=[("lazy_reply", 3), ("missed_buying_signal", 1)],
                worst_chatter="Mia",
            ),
        ],
        chatter_mistakes=[
            ChatterMistake(
                chatter_name="Mia",
                code="lazy_reply",
                count=3,
                accounts_affected=1,
                dashboard_ref="qc/chatter/mock-ch-1",
            ),
        ],
        fan_opportunities=[
            FanOpportunity(
                finding_id="00000000-0000-0000-0000-000000000001",
                code="missed_buying_signal",
                severity="high",
                account_username="luna_demo",
                chatter_name="Mia",
                fan_handle="@demo_fan",
                age_minutes=42,
                dashboard_ref="qc/finding/00000000-0000-0000-0000-000000000001",
            ),
        ],
        sync_health=SyncHealth(
            last_success_per_entity={"messages": now - timedelta(minutes=20)},
            error_count_24h=1,
            stale_account_count=1,
            api_disconnected=False,
        ),
        action_list=[
            "Restore lost account access first.",
            "Review missed buying-signal conversations in dashboard.",
        ],
    )
