"""Usage / Spend Tracker API.

Routes:
  GET    /api/v1/usage/overview              — totals + per-provider summary
  GET    /api/v1/usage/providers             — per-provider latest snapshot + status
  GET    /api/v1/usage/daily                 — daily buckets over a date range
  GET    /api/v1/usage/projects              — internal-event rollup
  GET    /api/v1/usage/alerts                — current alert state
  GET    /api/v1/usage/settings              — thresholds + admin credential status
  PUT    /api/v1/usage/settings              — update thresholds / alerts_enabled
  PUT    /api/v1/usage/credentials/openai    — save OpenAI admin key / org id
  DELETE /api/v1/usage/credentials/openai    — clear OpenAI admin credentials
  POST   /api/v1/usage/refresh               — manually run all collectors

Mutating routes are owner-gated.  No expensive provider calls are made —
collectors hit Admin / Usage endpoints only and are gated on admin
credentials being present (otherwise they return ``not_configured``).
Credentials are stored encrypted via the existing AppSetting / Fernet
pattern; the raw values never appear in logs or responses.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import select

from app.api.mc_roles import require_owner
from app.core.auth import AuthContext, get_auth_context
from app.core.time import utcnow
from app.db.session import get_session
from app.models.usage import UsageAlertConfig, UsageEvent, UsageSnapshot
from app.schemas.usage import (
    AlertsResponse,
    CredentialsStatus,
    DailyBucket,
    DailyUsageResponse,
    OpenAiCredentialsUpdate,
    ProjectListResponse,
    ProjectTotals,
    ProviderListResponse,
    ProviderRefreshResult,
    ProviderTotals,
    RangeKey,
    RefreshResponse,
    UsageOverviewResponse,
    UsageSettingsResponse,
    UsageSettingsUpdate,
)
from app.services.usage import run_collectors

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/usage", tags=["usage"])
AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)

KNOWN_PROVIDERS = ("openai", "anthropic", "gemini", "internal")

# Process-local refresh throttle: one full refresh every N seconds.  Cheap
# protection against accidental refresh-button mashing — does not need to be
# distributed because all the work is non-billable.
_REFRESH_MIN_INTERVAL_SECONDS = 10.0
_last_refresh_started_at: float = 0.0


# ── Helpers ──────────────────────────────────────────────────────────────────


def _resolve_range(range_key: RangeKey) -> tuple[datetime, datetime]:
    end = utcnow()
    if range_key == "24h":
        return end - timedelta(hours=24), end
    if range_key == "7d":
        return end - timedelta(days=7), end
    if range_key == "30d":
        return end - timedelta(days=30), end
    if range_key == "mtd":
        start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, end
    return end - timedelta(days=7), end


async def _get_alert_config(session: AsyncSession) -> UsageAlertConfig:
    """Return the (single) alert config row, creating it lazily if missing.

    Phase 1: org_id stays NULL — multi-tenant scoping comes in Phase 2.
    """
    row = (
        await session.exec(
            select(UsageAlertConfig).where(UsageAlertConfig.organization_id.is_(None))
        )
    ).first()
    if row is None:
        row = UsageAlertConfig(organization_id=None)
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


async def _latest_snapshot_per_provider(
    session: AsyncSession,
) -> dict[str, UsageSnapshot]:
    """Return the most recent snapshot keyed by provider.  Empty dict if none."""
    snapshots = list(
        await session.exec(
            select(UsageSnapshot).order_by(UsageSnapshot.captured_at.desc())
        )
    )
    latest: dict[str, UsageSnapshot] = {}
    for snap in snapshots:
        latest.setdefault(snap.provider, snap)
    return latest


async def _provider_totals_for_window(
    session: AsyncSession,
    *,
    start: datetime,
    end: datetime,
) -> dict[str, ProviderTotals]:
    """Aggregate snapshots in [start, end) per provider for window totals."""
    rows = list(
        await session.exec(
            select(UsageSnapshot).where(
                UsageSnapshot.captured_at >= start,
                UsageSnapshot.captured_at < end,
            )
        )
    )
    aggregates: dict[str, ProviderTotals] = {}
    for snap in rows:
        agg = aggregates.setdefault(
            snap.provider, ProviderTotals(provider=snap.provider)
        )
        agg.input_tokens += snap.input_tokens
        agg.output_tokens += snap.output_tokens
        agg.total_tokens += snap.total_tokens or (
            snap.input_tokens + snap.output_tokens
        )
        agg.requests += snap.requests
        agg.cost_usd += snap.cost_usd
    return aggregates


def _decorate_with_status(
    totals: dict[str, ProviderTotals],
    latest: dict[str, UsageSnapshot],
) -> list[ProviderTotals]:
    """Combine window totals with per-provider freshness/status info."""
    result: list[ProviderTotals] = []
    for provider in KNOWN_PROVIDERS:
        agg = totals.get(provider) or ProviderTotals(provider=provider)
        snap = latest.get(provider)
        if snap is not None:
            agg.last_captured_at = snap.captured_at
            agg.last_status = snap.status  # type: ignore[assignment]
            agg.last_error = snap.error
            agg.last_source = snap.source  # type: ignore[assignment]
            agg.configured = snap.status != "not_configured"
        result.append(agg)
    return result


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("/overview", response_model=UsageOverviewResponse)
async def get_overview(
    range_key: RangeKey = Query("7d"),
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> UsageOverviewResponse:
    start, end = _resolve_range(range_key)
    totals = await _provider_totals_for_window(session, start=start, end=end)
    latest = await _latest_snapshot_per_provider(session)
    providers = _decorate_with_status(totals, latest)

    total_cost = sum(p.cost_usd for p in providers)
    total_in = sum(p.input_tokens for p in providers)
    total_out = sum(p.output_tokens for p in providers)
    total_req = sum(p.requests for p in providers)

    cfg = await _get_alert_config(session)
    daily_breached = (
        cfg.daily_threshold_usd is not None
        and total_cost >= cfg.daily_threshold_usd
        and range_key == "24h"
    )
    monthly_breached = (
        cfg.monthly_threshold_usd is not None
        and total_cost >= cfg.monthly_threshold_usd
        and range_key in ("30d", "mtd")
    )

    last_refresh = max(
        (s.captured_at for s in latest.values()),
        default=None,
    )

    return UsageOverviewResponse(
        range_key=range_key,
        range_start=start,
        range_end=end,
        total_cost_usd=total_cost,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_requests=total_req,
        providers=providers,
        daily_threshold_usd=cfg.daily_threshold_usd,
        monthly_threshold_usd=cfg.monthly_threshold_usd,
        daily_threshold_breached=daily_breached,
        monthly_threshold_breached=monthly_breached,
        last_refresh_at=last_refresh,
    )


@router.get("/providers", response_model=ProviderListResponse)
async def get_providers(
    range_key: RangeKey = Query("7d"),
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ProviderListResponse:
    start, end = _resolve_range(range_key)
    totals = await _provider_totals_for_window(session, start=start, end=end)
    latest = await _latest_snapshot_per_provider(session)
    return ProviderListResponse(providers=_decorate_with_status(totals, latest))


@router.get("/daily", response_model=DailyUsageResponse)
async def get_daily(
    days: int = Query(14, ge=1, le=90),
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> DailyUsageResponse:
    """Daily spend buckets covering the last *days* days.

    Buckets pull from snapshots (captured_at) when available; otherwise zero-
    fill so the chart always has a row per day.
    """
    end = utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
        days=1
    )
    start = end - timedelta(days=days)

    rows = list(
        await session.exec(
            select(UsageSnapshot).where(
                UsageSnapshot.captured_at >= start,
                UsageSnapshot.captured_at < end,
            )
        )
    )
    by_day: dict[datetime, DailyBucket] = {}
    cursor = start
    while cursor < end:
        by_day[cursor] = DailyBucket(day=cursor)
        cursor += timedelta(days=1)

    for snap in rows:
        day = snap.captured_at.replace(hour=0, minute=0, second=0, microsecond=0)
        bucket = by_day.get(day)
        if bucket is None:
            continue
        bucket.cost_usd += snap.cost_usd
        bucket.input_tokens += snap.input_tokens
        bucket.output_tokens += snap.output_tokens
        bucket.requests += snap.requests

    return DailyUsageResponse(
        start=start, end=end, buckets=sorted(by_day.values(), key=lambda b: b.day)
    )


@router.get("/projects", response_model=ProjectListResponse)
async def get_projects(
    range_key: RangeKey = Query("7d"),
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ProjectListResponse:
    """Per-project / per-feature rollup of internal usage events.

    Empty until ``record_usage_event`` callers are wired in Phase 2+.
    """
    start, end = _resolve_range(range_key)
    rows = list(
        await session.exec(
            select(
                UsageEvent.project,
                UsageEvent.feature,
                func.coalesce(func.sum(UsageEvent.input_tokens), 0),
                func.coalesce(func.sum(UsageEvent.output_tokens), 0),
                func.coalesce(func.sum(UsageEvent.estimated_cost_usd), 0.0),
                func.count(UsageEvent.id),
            )
            .where(UsageEvent.started_at >= start, UsageEvent.started_at < end)
            .group_by(UsageEvent.project, UsageEvent.feature)
            .order_by(func.coalesce(func.sum(UsageEvent.estimated_cost_usd), 0.0).desc())
        )
    )
    out: list[ProjectTotals] = []
    for project, feature, in_tok, out_tok, cost, req in rows:
        out.append(
            ProjectTotals(
                project=project,
                feature=feature,
                input_tokens=int(in_tok or 0),
                output_tokens=int(out_tok or 0),
                cost_usd=float(cost or 0.0),
                requests=int(req or 0),
            )
        )
    return ProjectListResponse(range_key=range_key, rows=out)


@router.get("/alerts", response_model=AlertsResponse)
async def get_alerts(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> AlertsResponse:
    cfg = await _get_alert_config(session)

    end = utcnow()
    day_start = end - timedelta(hours=24)
    month_start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    daily_total = 0.0
    monthly_total = 0.0

    daily_rows = await session.exec(
        select(func.coalesce(func.sum(UsageSnapshot.cost_usd), 0.0)).where(
            UsageSnapshot.captured_at >= day_start,
            UsageSnapshot.captured_at < end,
        )
    )
    daily_total = float(daily_rows.first() or 0.0)

    monthly_rows = await session.exec(
        select(func.coalesce(func.sum(UsageSnapshot.cost_usd), 0.0)).where(
            UsageSnapshot.captured_at >= month_start,
            UsageSnapshot.captured_at < end,
        )
    )
    monthly_total = float(monthly_rows.first() or 0.0)

    last_error_snap = (
        await session.exec(
            select(UsageSnapshot)
            .where(UsageSnapshot.status == "error")
            .order_by(UsageSnapshot.captured_at.desc())
        )
    ).first()

    last_ok_snap = (
        await session.exec(
            select(UsageSnapshot)
            .where(UsageSnapshot.status == "ok")
            .order_by(UsageSnapshot.captured_at.desc())
        )
    ).first()

    return AlertsResponse(
        alerts_enabled=cfg.alerts_enabled,
        daily_threshold_usd=cfg.daily_threshold_usd,
        monthly_threshold_usd=cfg.monthly_threshold_usd,
        daily_spend_usd=daily_total,
        monthly_spend_usd=monthly_total,
        daily_breached=(
            cfg.daily_threshold_usd is not None
            and daily_total >= cfg.daily_threshold_usd
        ),
        monthly_breached=(
            cfg.monthly_threshold_usd is not None
            and monthly_total >= cfg.monthly_threshold_usd
        ),
        last_error=last_error_snap.error if last_error_snap else None,
        last_error_provider=last_error_snap.provider if last_error_snap else None,
        last_error_at=last_error_snap.captured_at if last_error_snap else None,
        last_successful_check_at=last_ok_snap.captured_at if last_ok_snap else None,
    )


# DB keys for OpenAI Admin Usage credentials (encrypted via existing
# AppSetting / Fernet path).  Org id is technically a public identifier
# but goes through the same encrypted store for uniformity.
_OPENAI_ADMIN_KEY_DBKEY = "admin_key.openai"
_OPENAI_ORG_ID_DBKEY = "admin_org_id.openai"


async def _load_openai_credentials_status(session: AsyncSession) -> dict:
    """Read OpenAI admin credential status from DB (with .env fallback)."""
    from app.core.config import settings as app_settings
    from app.core.secrets_store import get_secret_with_source, mask_key

    admin_value, admin_src = await get_secret_with_source(
        session, _OPENAI_ADMIN_KEY_DBKEY, fallback=app_settings.openai_admin_key
    )
    org_value, org_src = await get_secret_with_source(
        session, _OPENAI_ORG_ID_DBKEY, fallback=app_settings.openai_org_id
    )
    admin_configured = bool(admin_value.strip())
    org_set = bool(org_value.strip())
    return {
        "admin_configured": admin_configured,
        "admin_source": admin_src,
        "admin_preview": mask_key(admin_value) if admin_configured else None,
        "org_id_set": org_set,
        "org_id_source": org_src,
        # Org IDs are public identifiers — surface in full so the user can
        # verify which organization is wired up without re-entering it.
        "org_id_value": org_value if org_set else None,
    }


@router.get("/settings", response_model=UsageSettingsResponse)
async def get_settings(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> UsageSettingsResponse:
    from app.core.config import settings as app_settings
    from app.core.secrets_store import get_secret_with_source

    cfg = await _get_alert_config(session)

    openai_status = await _load_openai_credentials_status(session)

    anthropic_admin, anthropic_src = await get_secret_with_source(
        session, "admin_key.anthropic", fallback=app_settings.anthropic_admin_key
    )

    return UsageSettingsResponse(
        daily_threshold_usd=cfg.daily_threshold_usd,
        monthly_threshold_usd=cfg.monthly_threshold_usd,
        alerts_enabled=cfg.alerts_enabled,
        discord_webhook_configured=cfg.discord_webhook_configured,
        openai_admin_configured=openai_status["admin_configured"],
        openai_admin_source=openai_status["admin_source"],
        openai_admin_preview=openai_status["admin_preview"],
        openai_org_id_set=openai_status["org_id_set"],
        openai_org_id_source=openai_status["org_id_source"],
        openai_org_id_value=openai_status["org_id_value"],
        anthropic_admin_configured=bool(anthropic_admin.strip()),
        anthropic_admin_source=anthropic_src,  # type: ignore[arg-type]
        anthropic_org_id_set=bool(app_settings.anthropic_org_id.strip()),
        gemini_supported=False,
    )


@router.put("/settings", response_model=UsageSettingsResponse)
async def update_settings(
    body: UsageSettingsUpdate,
    _: AuthContext = AUTH_DEP,
    _role: str = Depends(require_owner),
    session: AsyncSession = SESSION_DEP,
) -> UsageSettingsResponse:
    cfg = await _get_alert_config(session)
    if body.daily_threshold_usd is not None:
        cfg.daily_threshold_usd = body.daily_threshold_usd or None
    if body.monthly_threshold_usd is not None:
        cfg.monthly_threshold_usd = body.monthly_threshold_usd or None
    if body.alerts_enabled is not None:
        cfg.alerts_enabled = body.alerts_enabled
    cfg.updated_at = utcnow()
    session.add(cfg)
    await session.commit()
    return await get_settings(session=session)  # reuse formatting


# ── OpenAI Admin Usage credentials ──────────────────────────────────────────


def _credentials_status_from_dict(data: dict) -> CredentialsStatus:
    return CredentialsStatus(
        admin_configured=data["admin_configured"],
        admin_source=data["admin_source"],
        admin_preview=data["admin_preview"],
        org_id_set=data["org_id_set"],
        org_id_source=data["org_id_source"],
        org_id_value=data["org_id_value"],
    )


@router.put("/credentials/openai", response_model=CredentialsStatus)
async def upsert_openai_credentials(
    body: OpenAiCredentialsUpdate,
    _: AuthContext = AUTH_DEP,
    _role: str = Depends(require_owner),
    session: AsyncSession = SESSION_DEP,
) -> CredentialsStatus:
    """Save the OpenAI Admin Usage credentials.

    Each field is optional and persisted only when supplied as a non-empty
    string — partial updates leave the other field untouched.  To clear
    credentials, call DELETE on this same path.

    Returns a status payload with masked / public previews.  The raw admin
    key is never echoed back, never logged, never included in error
    messages.
    """
    from app.core.secrets_store import set_secret

    admin_key_in = (body.admin_key or "").strip() if body.admin_key else ""
    org_id_in = (body.org_id or "").strip() if body.org_id else ""

    if not admin_key_in and not org_id_in:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Provide admin_key, org_id, or both. To clear stored "
                "credentials, use DELETE /api/v1/usage/credentials/openai."
            ),
        )

    # Light shape sanity — keep the message generic; do NOT echo the key.
    if admin_key_in and not admin_key_in.startswith(("sk-admin-", "sk-proj-admin-")):
        # We don't reject — formats can change — just warn in the log so a
        # user can debug a misconfiguration.  No part of the key is logged.
        logger.warning(
            "usage.openai.credentials.suspect_admin_key_prefix length=%d",
            len(admin_key_in),
        )

    if admin_key_in:
        await set_secret(session, _OPENAI_ADMIN_KEY_DBKEY, admin_key_in)
        logger.info("usage.openai.credentials.admin_key.saved length=%d", len(admin_key_in))
    if org_id_in:
        await set_secret(session, _OPENAI_ORG_ID_DBKEY, org_id_in)
        # Org id is a public identifier (`org-…`) — safe to log in full.
        logger.info("usage.openai.credentials.org_id.saved value=%s", org_id_in)

    status_data = await _load_openai_credentials_status(session)
    return _credentials_status_from_dict(status_data)


@router.delete("/credentials/openai", response_model=CredentialsStatus)
async def delete_openai_credentials(
    _: AuthContext = AUTH_DEP,
    _role: str = Depends(require_owner),
    session: AsyncSession = SESSION_DEP,
) -> CredentialsStatus:
    """Remove both the admin key and the org id from encrypted storage.

    After clearing, the .env values (if any) become the active fallback;
    otherwise the OpenAI collector returns ``not_configured``.
    """
    from app.core.secrets_store import delete_secret

    await delete_secret(session, _OPENAI_ADMIN_KEY_DBKEY)
    await delete_secret(session, _OPENAI_ORG_ID_DBKEY)
    logger.info("usage.openai.credentials.cleared")
    status_data = await _load_openai_credentials_status(session)
    return _credentials_status_from_dict(status_data)


# ── Refresh ─────────────────────────────────────────────────────────────────


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_usage(
    _: AuthContext = AUTH_DEP,
    _role: str = Depends(require_owner),
    session: AsyncSession = SESSION_DEP,
) -> RefreshResponse:
    """Manually run all provider collectors and persist snapshots."""
    global _last_refresh_started_at
    now_mono = time.monotonic()
    if now_mono - _last_refresh_started_at < _REFRESH_MIN_INTERVAL_SECONDS:
        wait = _REFRESH_MIN_INTERVAL_SECONDS - (now_mono - _last_refresh_started_at)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Refresh throttled — try again in {wait:.0f}s.",
        )
    _last_refresh_started_at = now_mono

    started = utcnow()
    results = await run_collectors(session)
    finished = utcnow()

    return RefreshResponse(
        started_at=started,
        finished_at=finished,
        results=[
            ProviderRefreshResult(
                provider=r.provider,
                status=r.status,
                snapshot_id=snap.id if snap else None,
                captured_at=snap.captured_at if snap else None,
                cost_usd=r.cost_usd,
                total_tokens=r.total_tokens or (r.input_tokens + r.output_tokens),
                error=r.error,
                source=r.source,
            )
            for r, snap in results
        ],
    )
