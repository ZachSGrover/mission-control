"""OnlyFans Intelligence — backend API surface.

All routes are scoped to authenticated Mission Control users; mutating /
sensitive routes additionally require owner role.  The OnlyMonster API key
never leaves the backend — only `has_token` / source flags are returned to
the frontend.

Surface:
  GET    /api/v1/of-intelligence/status            — connection + sync status
  GET    /api/v1/of-intelligence/credentials       — current credential status
  POST   /api/v1/of-intelligence/credentials       — save API key (owner)
  DELETE /api/v1/of-intelligence/credentials       — clear API key (owner)
  POST   /api/v1/of-intelligence/test              — connection ping (owner)
  POST   /api/v1/of-intelligence/sync              — kick off manual sync (owner)
  GET    /api/v1/of-intelligence/sync-logs         — recent sync log rows
  GET    /api/v1/of-intelligence/overview          — overview-page metrics
  GET    /api/v1/of-intelligence/accounts          — list accounts
  GET    /api/v1/of-intelligence/fans              — list fans
  GET    /api/v1/of-intelligence/messages          — list messages
  GET    /api/v1/of-intelligence/chatters          — list chatters
  GET    /api/v1/of-intelligence/mass-messages     — list mass messages
  GET    /api/v1/of-intelligence/posts             — list posts
  GET    /api/v1/of-intelligence/revenue           — revenue snapshots
  GET    /api/v1/of-intelligence/qc-reports        — list / fetch QC reports
  POST   /api/v1/of-intelligence/qc-reports        — generate a new QC report (owner)
  GET    /api/v1/of-intelligence/alerts            — list alerts
  POST   /api/v1/of-intelligence/alerts/evaluate   — run alert engine (owner)
  POST   /api/v1/of-intelligence/alerts/{id}/ack   — acknowledge alert
  POST   /api/v1/of-intelligence/alerts/{id}/resolve — resolve alert
  GET    /api/v1/of-intelligence/memory            — list memory bank entries
  POST   /api/v1/of-intelligence/memory/export     — generate Obsidian export (owner)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.mc_roles import require_owner
from app.core.auth import AuthContext, get_auth_context
from app.core.logging import get_logger
from app.core.secrets_store import (
    delete_secret,
    mask_key,
    set_secret,
)
from app.core.time import utcnow
from app.db.session import get_session
from app.integrations.onlymonster.client import (
    ONLYMONSTER_API_KEY_DB_KEY,
    ONLYMONSTER_BASE_URL_DB_KEY,
    OnlyMonsterClient,
    resolve_credentials,
    supported_entities,
)
from app.models.of_intelligence import (
    BusinessMemoryEntry,
    OfIntelligenceAccount,
    OfIntelligenceAlert,
    OfIntelligenceChat,
    OfIntelligenceChatter,
    OfIntelligenceFan,
    OfIntelligenceMassMessage,
    OfIntelligenceMessage,
    OfIntelligencePost,
    OfIntelligenceQcReport,
    OfIntelligenceRevenue,
    OfIntelligenceSyncLog,
)
from app.services.of_intelligence.alerts import (
    acknowledge_alert,
    evaluate_alerts,
    resolve_alert,
)
from app.services.of_intelligence.obsidian_export import (
    OBSIDIAN_ROOT,
    export_memory,
    mirror_export_to_memory,
)
from app.services.onlymonster.qc_bot import generate_qc_report
from app.services.onlymonster.sync import (
    fetch_latest_sync_state,
    run_sync_in_background,
)

router = APIRouter(prefix="/of-intelligence", tags=["of-intelligence"])
logger = get_logger(__name__)

AUTH_DEP = Depends(get_auth_context)
OWNER_DEP = Depends(require_owner)
SESSION_DEP = Depends(get_session)


# ── Schemas ──────────────────────────────────────────────────────────────────


class CredentialStatus(BaseModel):
    has_token: bool
    api_key_source: str = "none"
    api_key_preview: str | None = None
    base_url: str = ""
    base_url_source: str = "none"
    supported_entities: list[str] = []


class SaveCredentialsRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None


class PingResponse(BaseModel):
    ok: bool
    status_code: int | None = None
    latency_ms: float | None = None
    base_url: str = ""
    api_key_source: str = "none"
    error: str | None = None
    # Self-diagnosing fields (added 2026-04-28).  The frontend renders these
    # so the operator can tell whether a failure originated in their config,
    # the network, or OnlyMonster itself.
    tested_url: str = ""
    error_source: str = "unknown"
    message: str | None = None


class SyncTriggerResponse(BaseModel):
    ok: bool
    started_at: datetime
    triggered_by: str
    detail: str


class SyncLogRow(BaseModel):
    id: UUID
    run_id: UUID
    source: str
    entity: str
    status: str
    items_synced: int
    created_count: int = 0
    updated_count: int = 0
    skipped_duplicate_count: int = 0
    error_count: int = 0
    pages_fetched: int
    reason: str | None
    error: str | None
    source_endpoint: str | None = None
    started_at: datetime
    finished_at: datetime | None
    triggered_by: str | None


class StatusResponse(BaseModel):
    connection: PingResponse
    last_run_id: str | None
    last_run_started_at: datetime | None
    entities: dict[str, dict[str, Any]]
    supported_entities: list[str]


class OverviewMetrics(BaseModel):
    api_connected: bool
    api_key_source: str
    last_sync_started_at: datetime | None
    last_sync_status: str | None
    accounts_synced: int
    fans_synced: int
    messages_synced: int
    revenue_today_cents: int
    revenue_7d_cents: int
    revenue_30d_cents: int
    accounts_needing_attention: int
    chatters_to_review: int
    critical_alerts: int
    latest_qc_report_id: str | None
    latest_qc_report_date: datetime | None


class AccountRow(BaseModel):
    id: UUID
    source: str
    source_id: str
    username: str | None
    display_name: str | None
    status: str | None
    access_status: str | None
    last_synced_at: datetime


class FanRow(BaseModel):
    id: UUID
    source_id: str
    account_source_id: str | None
    username: str | None
    lifetime_value_cents: int | None
    last_message_at: datetime | None
    is_subscribed: bool | None
    last_synced_at: datetime


class ChatterRow(BaseModel):
    id: UUID
    source_id: str
    name: str | None
    email: str | None
    role: str | None
    active: bool | None
    last_synced_at: datetime


class MessageRow(BaseModel):
    id: UUID
    source_id: str
    chat_source_id: str | None
    account_source_id: str | None
    fan_source_id: str | None
    chatter_source_id: str | None
    direction: str | None
    sent_at: datetime | None
    body: str | None
    revenue_cents: int | None


class MassMessageRow(BaseModel):
    id: UUID
    source_id: str
    account_source_id: str | None
    sent_at: datetime | None
    recipients_count: int | None
    purchases_count: int | None
    revenue_cents: int | None
    body_preview: str | None
    snapshot_at: datetime


class PostRow(BaseModel):
    id: UUID
    source_id: str
    account_source_id: str | None
    published_at: datetime | None
    likes_count: int | None
    comments_count: int | None
    revenue_cents: int | None
    snapshot_at: datetime


class RevenueRow(BaseModel):
    id: UUID
    account_source_id: str | None
    period_start: datetime | None
    period_end: datetime | None
    revenue_cents: int
    transactions_count: int | None
    captured_at: datetime


class QcReportRow(BaseModel):
    id: UUID
    report_date: datetime
    summary: str | None
    critical_alerts_count: int
    accounts_reviewed: int
    chatters_reviewed: int
    generated_at: datetime


class QcReportDetail(QcReportRow):
    payload: dict[str, Any]
    markdown: str | None


class AlertRow(BaseModel):
    id: UUID
    code: str
    severity: str
    status: str
    title: str
    message: str | None
    account_source_id: str | None
    chatter_source_id: str | None
    fan_source_id: str | None
    created_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None


class AlertEvaluationResponse(BaseModel):
    evaluated_at: datetime
    rules_run: int
    alerts_created: int
    alerts_skipped_existing: int
    chatter_findings_persisted: int = 0
    rollup_findings: int = 0
    rollup_alert_id: str | None = None


class DailySummaryResponse(BaseModel):
    generated_at: datetime
    accounts_reviewed: int
    chats_reviewed: int
    total_findings: int
    critical_alert_count: int
    worst_accounts: list[tuple[str, int]] = []
    worst_chatters: list[tuple[str, int]] = []
    repeat_offenders: list[str] = []
    missed_sales_signals: int = 0
    slow_responses: int = 0
    follow_ups_needed: int = 0
    layer1_open_alerts: list[str] = []
    layer2_open_alerts: list[str] = []
    actions: list[str] = []
    publish_ok: bool
    publish_reason: str
    publish_status: int | None = None
    channel: str = "discord"


# ── Dashboard payload schemas ────────────────────────────────────────────────


class DashboardAccountStatus(BaseModel):
    account_id: str
    username: str | None
    health_status: str
    last_synced_at: datetime | None
    hours_since_sync: int | None
    revenue_24h_cents: int
    revenue_7d_avg_cents: int
    open_layer1_codes: list[str]
    open_layer2_codes: list[str]


class DashboardRevenueWarning(BaseModel):
    account_id: str
    username: str | None
    revenue_24h_cents: int
    revenue_7d_avg_cents: int
    severity: str
    reason: str
    dashboard_ref: str


class DashboardChattingQuality(BaseModel):
    account_id: str
    username: str | None
    total_findings: int
    critical_count: int
    high_count: int
    top_codes: list[tuple[str, int]]
    worst_chatter: str | None


class DashboardChatterMistake(BaseModel):
    chatter_name: str
    code: str
    count: int
    accounts_affected: int
    dashboard_ref: str


class DashboardFanOpportunity(BaseModel):
    finding_id: str
    code: str
    severity: str
    account_username: str | None
    chatter_name: str | None
    fan_handle: str | None  # dashboard-only; never reaches Discord/Telegram
    age_minutes: int
    dashboard_ref: str


class DashboardSyncHealth(BaseModel):
    last_success_per_entity: dict[str, datetime | None]
    error_count_24h: int
    stale_account_count: int
    api_disconnected: bool


class DashboardResponse(BaseModel):
    generated_at: datetime
    account_status: list[DashboardAccountStatus]
    revenue_warnings: list[DashboardRevenueWarning]
    chatting_quality: list[DashboardChattingQuality]
    chatter_mistakes: list[DashboardChatterMistake]
    fan_opportunities: list[DashboardFanOpportunity]
    sync_health: DashboardSyncHealth
    action_list: list[str]
    mock: bool = False


class MemoryEntryRow(BaseModel):
    id: UUID
    product: str
    kind: str
    title: str
    obsidian_path: str | None
    account_source_id: str | None
    period_start: datetime | None
    created_at: datetime


class ExportRequest(BaseModel):
    target_date: datetime | None = None
    export_path: str | None = Field(
        default=None,
        description=(
            "Optional absolute filesystem path to write files into.  When set, "
            "files are written to disk under this root using the Obsidian-style "
            "subfolder layout (Daily/, Accounts/, etc.)."
        ),
    )
    mirror_to_memory: bool = True


class ExportResponse(BaseModel):
    generated_at: datetime
    file_count: int
    written_to_disk: list[str]
    skipped: list[str]
    obsidian_root: str


# ── Credentials ──────────────────────────────────────────────────────────────


@router.get("/credentials", response_model=CredentialStatus)
async def get_credentials(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> CredentialStatus:
    creds = await resolve_credentials(session)
    return CredentialStatus(
        has_token=bool(creds.api_key),
        api_key_source=creds.api_key_source,
        api_key_preview=mask_key(creds.api_key) if creds.api_key else None,
        base_url=creds.base_url,
        base_url_source=creds.base_url_source,
        supported_entities=supported_entities(),
    )


@router.post("/credentials", response_model=CredentialStatus)
async def save_credentials(
    body: SaveCredentialsRequest,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> CredentialStatus:
    if body.api_key is not None:
        cleaned = body.api_key.strip()
        if not cleaned:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="api_key must not be empty (use DELETE to clear).",
            )
        await set_secret(session, ONLYMONSTER_API_KEY_DB_KEY, cleaned)
        logger.info("of_intelligence.credentials.api_key.saved")
    if body.base_url is not None:
        cleaned_url = body.base_url.strip().rstrip("/")
        if cleaned_url and not (
            cleaned_url.startswith("http://") or cleaned_url.startswith("https://")
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="base_url must be an absolute http(s) URL.",
            )
        if cleaned_url:
            await set_secret(session, ONLYMONSTER_BASE_URL_DB_KEY, cleaned_url)
        else:
            await delete_secret(session, ONLYMONSTER_BASE_URL_DB_KEY)
        logger.info("of_intelligence.credentials.base_url.updated")
    return await get_credentials(session=session)


@router.delete("/credentials", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credentials(
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> None:
    await delete_secret(session, ONLYMONSTER_API_KEY_DB_KEY)
    logger.info("of_intelligence.credentials.api_key.cleared")


# ── Connection test ──────────────────────────────────────────────────────────


@router.post("/test", response_model=PingResponse)
async def test_connection(
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> PingResponse:
    creds = await resolve_credentials(session)
    client = OnlyMonsterClient(creds)
    result = await client.ping()
    logger.info(
        "of_intelligence.test ok=%s status=%s tested_url=%s source=%s latency_ms=%s",
        result.ok,
        result.status_code,
        result.tested_url,
        result.error_source,
        result.latency_ms,
    )
    return PingResponse(
        ok=result.ok,
        status_code=result.status_code,
        latency_ms=result.latency_ms,
        base_url=result.base_url,
        api_key_source=result.api_key_source,
        error=result.error,
        tested_url=result.tested_url,
        error_source=result.error_source,
        message=result.message,
    )


# ── Status & sync ────────────────────────────────────────────────────────────


@router.get("/status", response_model=StatusResponse)
async def get_status(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> StatusResponse:
    creds = await resolve_credentials(session)
    client = OnlyMonsterClient(creds)
    ping = await client.ping()
    sync_state = await fetch_latest_sync_state(session)
    return StatusResponse(
        connection=PingResponse(
            ok=ping.ok,
            status_code=ping.status_code,
            latency_ms=ping.latency_ms,
            base_url=ping.base_url,
            api_key_source=ping.api_key_source,
            error=ping.error,
        ),
        last_run_id=sync_state["last_run_id"],
        last_run_started_at=(
            datetime.fromisoformat(sync_state["last_run_started_at"])
            if sync_state["last_run_started_at"]
            else None
        ),
        entities=sync_state["entities"],
        supported_entities=supported_entities(),
    )


@router.post("/sync", response_model=SyncTriggerResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_sync(
    background: BackgroundTasks,
    _role: str = OWNER_DEP,
) -> SyncTriggerResponse:
    """Manual sync — fire-and-forget; UI polls /status and /sync-logs."""
    started_at = utcnow()
    background.add_task(_run_sync_safe)
    logger.info("of_intelligence.sync.triggered triggered_by=manual at=%s", started_at.isoformat())
    return SyncTriggerResponse(
        ok=True,
        started_at=started_at,
        triggered_by="manual",
        detail="Sync started in the background. Poll /status for progress.",
    )


async def _run_sync_safe() -> None:
    try:
        await run_sync_in_background(triggered_by="manual")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("of_intelligence.sync.background.unhandled")


@router.get("/sync-logs", response_model=list[SyncLogRow])
async def list_sync_logs(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[SyncLogRow]:
    rows = (
        await session.exec(
            select(OfIntelligenceSyncLog)
            .order_by(col(OfIntelligenceSyncLog.started_at).desc())
            .limit(limit)
        )
    ).all()
    return [SyncLogRow.model_validate(r, from_attributes=True) for r in rows]


# ── Overview ─────────────────────────────────────────────────────────────────


@router.get("/overview", response_model=OverviewMetrics)
async def overview_metrics(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> OverviewMetrics:
    creds = await resolve_credentials(session)

    accounts_synced = (await session.exec(select(OfIntelligenceAccount))).all()
    fans_count = len((await session.exec(select(OfIntelligenceFan))).all())
    messages_count = len((await session.exec(select(OfIntelligenceMessage))).all())
    chatters = (await session.exec(select(OfIntelligenceChatter))).all()
    open_critical_alerts = (
        await session.exec(
            select(OfIntelligenceAlert)
            .where(OfIntelligenceAlert.status == "open")
            .where(OfIntelligenceAlert.severity == "critical")
        )
    ).all()

    # Bucket revenue by *transaction time* (period_start), not by when we
    # synced it — otherwise "Revenue Today" reports the full 30-day backfill
    # on the day of first sync.  Falls back to captured_at when period_start
    # is missing (legacy rows pre-source_external_id).
    revenue_rows = (
        await session.exec(
            select(OfIntelligenceRevenue)
            .order_by(col(OfIntelligenceRevenue.captured_at).desc())
            .limit(10_000)
        )
    ).all()
    now = utcnow()

    def _txn_time(row: OfIntelligenceRevenue) -> datetime:
        return row.period_start or row.captured_at

    revenue_today = sum(r.revenue_cents for r in revenue_rows if (now - _txn_time(r)).days < 1)
    revenue_7d = sum(r.revenue_cents for r in revenue_rows if (now - _txn_time(r)).days < 7)
    revenue_30d = sum(r.revenue_cents for r in revenue_rows if (now - _txn_time(r)).days < 30)

    last_log = (
        await session.exec(
            select(OfIntelligenceSyncLog)
            .order_by(col(OfIntelligenceSyncLog.started_at).desc())
            .limit(1)
        )
    ).first()
    latest_qc = (
        await session.exec(
            select(OfIntelligenceQcReport)
            .order_by(col(OfIntelligenceQcReport.generated_at).desc())
            .limit(1)
        )
    ).first()

    accounts_needing_attention = sum(
        1
        for a in accounts_synced
        if (a.access_status or "").lower() in {"lost", "blocked", "expired"}
        or (now - a.last_synced_at).total_seconds() > 6 * 3600
    )

    return OverviewMetrics(
        api_connected=bool(creds.api_key),
        api_key_source=creds.api_key_source,
        last_sync_started_at=last_log.started_at if last_log else None,
        last_sync_status=last_log.status if last_log else None,
        accounts_synced=len(accounts_synced),
        fans_synced=fans_count,
        messages_synced=messages_count,
        revenue_today_cents=revenue_today,
        revenue_7d_cents=revenue_7d,
        revenue_30d_cents=revenue_30d,
        accounts_needing_attention=accounts_needing_attention,
        chatters_to_review=sum(1 for c in chatters if c.active),
        critical_alerts=len(open_critical_alerts),
        latest_qc_report_id=str(latest_qc.id) if latest_qc else None,
        latest_qc_report_date=latest_qc.report_date if latest_qc else None,
    )


# ── Entity listing endpoints ─────────────────────────────────────────────────


@router.get("/accounts", response_model=list[AccountRow])
async def list_accounts(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> list[AccountRow]:
    rows = (
        await session.exec(
            select(OfIntelligenceAccount)
            .order_by(col(OfIntelligenceAccount.last_synced_at).desc())
            .limit(500)
        )
    ).all()
    return [AccountRow.model_validate(r, from_attributes=True) for r in rows]


@router.get("/fans", response_model=list[FanRow])
async def list_fans(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[FanRow]:
    rows = (
        await session.exec(
            select(OfIntelligenceFan).order_by(OfIntelligenceFan.lifetime_value_cents.desc()).limit(limit)  # type: ignore[union-attr]
        )
    ).all()
    return [FanRow.model_validate(r, from_attributes=True) for r in rows]


@router.get("/messages", response_model=list[MessageRow])
async def list_messages(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[MessageRow]:
    rows = (
        await session.exec(
            select(OfIntelligenceMessage).order_by(OfIntelligenceMessage.sent_at.desc()).limit(limit)  # type: ignore[union-attr]
        )
    ).all()
    return [MessageRow.model_validate(r, from_attributes=True) for r in rows]


@router.get("/chatters", response_model=list[ChatterRow])
async def list_chatters(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> list[ChatterRow]:
    rows = (
        await session.exec(
            select(OfIntelligenceChatter)
            .order_by(col(OfIntelligenceChatter.last_synced_at).desc())
            .limit(500)
        )
    ).all()
    return [ChatterRow.model_validate(r, from_attributes=True) for r in rows]


@router.get("/mass-messages", response_model=list[MassMessageRow])
async def list_mass_messages(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[MassMessageRow]:
    rows = (
        await session.exec(
            select(OfIntelligenceMassMessage)
            .order_by(col(OfIntelligenceMassMessage.snapshot_at).desc())
            .limit(limit)
        )
    ).all()
    return [MassMessageRow.model_validate(r, from_attributes=True) for r in rows]


@router.get("/posts", response_model=list[PostRow])
async def list_posts(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[PostRow]:
    rows = (
        await session.exec(
            select(OfIntelligencePost)
            .order_by(col(OfIntelligencePost.snapshot_at).desc())
            .limit(limit)
        )
    ).all()
    return [PostRow.model_validate(r, from_attributes=True) for r in rows]


@router.get("/revenue", response_model=list[RevenueRow])
async def list_revenue(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[RevenueRow]:
    rows = (
        await session.exec(
            select(OfIntelligenceRevenue)
            .order_by(col(OfIntelligenceRevenue.captured_at).desc())
            .limit(limit)
        )
    ).all()
    return [RevenueRow.model_validate(r, from_attributes=True) for r in rows]


# ── QC reports ───────────────────────────────────────────────────────────────


@router.get("/qc-reports", response_model=list[QcReportRow])
async def list_qc_reports(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
    limit: int = Query(default=30, ge=1, le=200),
) -> list[QcReportRow]:
    rows = (
        await session.exec(
            select(OfIntelligenceQcReport)
            .order_by(col(OfIntelligenceQcReport.generated_at).desc())
            .limit(limit)
        )
    ).all()
    return [QcReportRow.model_validate(r, from_attributes=True) for r in rows]


@router.get("/qc-reports/{report_id}", response_model=QcReportDetail)
async def get_qc_report(
    report_id: UUID,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> QcReportDetail:
    row = (
        await session.exec(
            select(OfIntelligenceQcReport).where(OfIntelligenceQcReport.id == report_id)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="QC report not found.")
    return QcReportDetail.model_validate(row, from_attributes=True)


@router.post("/qc-reports", response_model=QcReportDetail, status_code=status.HTTP_201_CREATED)
async def create_qc_report(
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> QcReportDetail:
    report = await generate_qc_report(session)
    return QcReportDetail.model_validate(report, from_attributes=True)


# ── Alerts ───────────────────────────────────────────────────────────────────


@router.get("/alerts", response_model=list[AlertRow])
async def list_alerts(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
    only_open: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AlertRow]:
    stmt = (
        select(OfIntelligenceAlert)
        .order_by(col(OfIntelligenceAlert.created_at).desc())
        .limit(limit)
    )
    if only_open:
        stmt = stmt.where(OfIntelligenceAlert.status == "open")
    rows = (await session.exec(stmt)).all()
    return [AlertRow.model_validate(r, from_attributes=True) for r in rows]


@router.post("/alerts/evaluate", response_model=AlertEvaluationResponse)
async def trigger_alert_evaluation(
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AlertEvaluationResponse:
    summary = await evaluate_alerts(session)
    return AlertEvaluationResponse(
        evaluated_at=summary.evaluated_at,
        rules_run=summary.rules_run,
        alerts_created=summary.alerts_created,
        alerts_skipped_existing=summary.alerts_skipped_existing,
        chatter_findings_persisted=summary.chatter_findings_persisted,
        rollup_findings=summary.rollup_findings,
        rollup_alert_id=summary.rollup_alert_id,
    )


@router.post("/qc/daily-summary", response_model=DailySummaryResponse)
async def trigger_daily_summary(
    channel: str = "discord",
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> DailySummaryResponse:
    """Build + ship the daily QC scorecard.

    Owner-only.  Bypasses the kill switch (operator-initiated, must surface
    even if real-alert toggle is off) but still requires a saved webhook
    (Discord) or token + chat id (Telegram).

    ``channel=discord`` (default) ships via the existing webhook publisher.
    ``channel=telegram`` ships via the safe-summary Telegram publisher and
    returns ``publish_reason="no_telegram"`` if Telegram isn't configured.
    """
    selected = (channel or "discord").strip().lower()
    if selected not in ("discord", "telegram"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="channel must be 'discord' or 'telegram'.",
        )

    if selected == "telegram":
        from app.services.of_intelligence.qc.telegram_publisher import (
            ship_daily_summary_telegram,
        )
        summary, tg_result = await ship_daily_summary_telegram(
            session, bypass_kill_switch=True
        )
        return DailySummaryResponse(
            generated_at=summary.generated_at,
            accounts_reviewed=summary.accounts_reviewed,
            chats_reviewed=summary.chats_reviewed,
            total_findings=summary.total_findings,
            critical_alert_count=summary.critical_alert_count,
            worst_accounts=list(summary.worst_accounts),
            worst_chatters=list(summary.worst_chatters),
            repeat_offenders=list(summary.repeat_offenders),
            missed_sales_signals=summary.missed_sales_signals,
            slow_responses=summary.slow_responses,
            follow_ups_needed=summary.follow_ups_needed,
            layer1_open_alerts=list(summary.layer1_open_alerts),
            layer2_open_alerts=list(summary.layer2_open_alerts),
            actions=list(summary.actions),
            publish_ok=tg_result.ok,
            publish_reason=tg_result.reason,
            publish_status=tg_result.status,
            channel="telegram",
        )

    from app.services.of_intelligence.qc.daily_summary import ship_daily_summary

    summary, result = await ship_daily_summary(session, bypass_kill_switch=True)
    return DailySummaryResponse(
        generated_at=summary.generated_at,
        accounts_reviewed=summary.accounts_reviewed,
        chats_reviewed=summary.chats_reviewed,
        total_findings=summary.total_findings,
        critical_alert_count=summary.critical_alert_count,
        worst_accounts=list(summary.worst_accounts),
        worst_chatters=list(summary.worst_chatters),
        repeat_offenders=list(summary.repeat_offenders),
        missed_sales_signals=summary.missed_sales_signals,
        slow_responses=summary.slow_responses,
        follow_ups_needed=summary.follow_ups_needed,
        layer1_open_alerts=list(summary.layer1_open_alerts),
        layer2_open_alerts=list(summary.layer2_open_alerts),
        actions=list(summary.actions),
        publish_ok=result.ok,
        publish_reason=result.reason,
        publish_status=result.status,
        channel="discord",
    )


@router.get("/qc/dashboard", response_model=DashboardResponse)
async def get_qc_dashboard(
    mock: int = 0,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> DashboardResponse:
    """Read-only Daily QC Dashboard payload (Layer 3 view).

    Owner-only.  Includes per-account status, revenue warnings, chatting
    quality, top chatter mistakes, fan opportunities (the only section
    that may include fan handles), sync health, and the Layer-3 action
    list.

    ``?mock=1`` returns a deterministic fixture without touching the DB —
    used by frontend dev and CI.
    """
    from app.services.of_intelligence.qc.dashboard import (
        build_dashboard,
        build_mock_payload,
    )

    payload = build_mock_payload() if mock else await build_dashboard(session)

    return DashboardResponse(
        generated_at=payload.generated_at,
        account_status=[
            DashboardAccountStatus(
                account_id=a.account_id,
                username=a.username,
                health_status=a.health_status,
                last_synced_at=a.last_synced_at,
                hours_since_sync=a.hours_since_sync,
                revenue_24h_cents=a.revenue_24h_cents,
                revenue_7d_avg_cents=a.revenue_7d_avg_cents,
                open_layer1_codes=a.open_layer1_codes,
                open_layer2_codes=a.open_layer2_codes,
            )
            for a in payload.account_status
        ],
        revenue_warnings=[
            DashboardRevenueWarning(
                account_id=w.account_id,
                username=w.username,
                revenue_24h_cents=w.revenue_24h_cents,
                revenue_7d_avg_cents=w.revenue_7d_avg_cents,
                severity=w.severity,
                reason=w.reason,
                dashboard_ref=w.dashboard_ref,
            )
            for w in payload.revenue_warnings
        ],
        chatting_quality=[
            DashboardChattingQuality(
                account_id=q.account_id,
                username=q.username,
                total_findings=q.total_findings,
                critical_count=q.critical_count,
                high_count=q.high_count,
                top_codes=q.top_codes,
                worst_chatter=q.worst_chatter,
            )
            for q in payload.chatting_quality
        ],
        chatter_mistakes=[
            DashboardChatterMistake(
                chatter_name=m.chatter_name,
                code=m.code,
                count=m.count,
                accounts_affected=m.accounts_affected,
                dashboard_ref=m.dashboard_ref,
            )
            for m in payload.chatter_mistakes
        ],
        fan_opportunities=[
            DashboardFanOpportunity(
                finding_id=o.finding_id,
                code=o.code,
                severity=o.severity,
                account_username=o.account_username,
                chatter_name=o.chatter_name,
                fan_handle=o.fan_handle,
                age_minutes=o.age_minutes,
                dashboard_ref=o.dashboard_ref,
            )
            for o in payload.fan_opportunities
        ],
        sync_health=DashboardSyncHealth(
            last_success_per_entity=payload.sync_health.last_success_per_entity if payload.sync_health else {},
            error_count_24h=payload.sync_health.error_count_24h if payload.sync_health else 0,
            stale_account_count=payload.sync_health.stale_account_count if payload.sync_health else 0,
            api_disconnected=payload.sync_health.api_disconnected if payload.sync_health else False,
        ),
        action_list=list(payload.action_list),
        mock=bool(mock),
    )


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertRow)
async def post_alert_acknowledge(
    alert_id: UUID,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AlertRow:
    alert = await acknowledge_alert(session, str(alert_id))
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found.")
    return AlertRow.model_validate(alert, from_attributes=True)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertRow)
async def post_alert_resolve(
    alert_id: UUID,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AlertRow:
    alert = await resolve_alert(session, str(alert_id))
    if not alert:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found.")
    return AlertRow.model_validate(alert, from_attributes=True)


# ── Memory bank / Obsidian export ────────────────────────────────────────────


@router.get("/memory", response_model=list[MemoryEntryRow])
async def list_memory(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[MemoryEntryRow]:
    rows = (
        await session.exec(
            select(BusinessMemoryEntry)
            .where(BusinessMemoryEntry.product == "of_intelligence")
            .order_by(col(BusinessMemoryEntry.created_at).desc())
            .limit(limit)
        )
    ).all()
    return [MemoryEntryRow.model_validate(r, from_attributes=True) for r in rows]


@router.post("/memory/export", response_model=ExportResponse)
async def export_memory_endpoint(
    body: ExportRequest,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ExportResponse:
    result = await export_memory(
        session,
        target_date=body.target_date,
        export_path=body.export_path,
    )
    if body.mirror_to_memory:
        await mirror_export_to_memory(session, result)
    return ExportResponse(
        generated_at=result.generated_at,
        file_count=len(result.files),
        written_to_disk=result.written_to_disk,
        skipped=result.skipped,
        obsidian_root=OBSIDIAN_ROOT,
    )


# ── Chats listing helper (read-only convenience for UI) ──────────────────────


@router.get("/chats", response_model=list[dict[str, Any]])
async def list_chats(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    rows = (
        await session.exec(
            select(OfIntelligenceChat).order_by(OfIntelligenceChat.last_message_at.desc()).limit(limit)  # type: ignore[union-attr]
        )
    ).all()
    return [
        {
            "id": str(r.id),
            "source_id": r.source_id,
            "account_source_id": r.account_source_id,
            "fan_source_id": r.fan_source_id,
            "last_message_at": r.last_message_at.isoformat() if r.last_message_at else None,
            "unread_count": r.unread_count,
        }
        for r in rows
    ]
