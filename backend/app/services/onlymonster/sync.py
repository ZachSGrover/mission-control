"""OnlyMonster sync orchestrator.

Wired to the live om-api-service v0.30.0 catalog (see
`app.integrations.onlymonster.endpoints`).  Sync is strictly read-only:
the client refuses to fire any endpoint flagged `write=True`, and the
orchestrator never asks for one.

Flow:
  1. Walk `ENDPOINT_CATALOG` in declaration order.
  2. For `flat` entities, call once and persist.
  3. For `per_account` entities, iterate over the accounts captured during
     this run (collected from step 1's `accounts` call) and call once per
     account.  If `accounts` produced nothing, the per-account entities
     short-circuit with a clear sync_log row.
  4. For `per_platform_account` entities, iterate over the same accounts but
     pass `platform` and `platform_account_id` from each account record.
  5. Disabled / write / dynamic-discovery entities never make a network
     call; they get a sync_log row stamped with the reason.

Every entity, regardless of outcome, produces exactly one row in
`of_intelligence_sync_logs` for the run.  The UI uses those rows verbatim.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select as sa_select
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.db.session import async_session_maker
from app.integrations.onlymonster.client import (
    EndpointResult,
    OnlyMonsterClient,
    resolve_credentials,
)
from app.integrations.onlymonster.endpoints import ENDPOINT_CATALOG, EndpointSpec
from app.integrations.onlymonster.rate_limiter import OnlyMonsterRateLimiter
from app.models.of_intelligence import (
    SOURCE_ONLYMONSTER,
    OfIntelligenceAccount,
    OfIntelligenceChatter,
    OfIntelligenceFan,
    OfIntelligenceRevenue,
    OfIntelligenceSyncLog,
    OfIntelligenceTrackingLink,
)

logger = logging.getLogger(__name__)


@dataclass
class SyncRunContext:
    """In-memory state shared across a single sync run."""

    run_id: UUID
    accounts: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SyncRunSummary:
    run_id: UUID
    started_at: datetime
    finished_at: datetime
    total_entities: int
    succeeded: int
    not_available: int
    failed: int
    skipped: int


# ── Entrypoints ──────────────────────────────────────────────────────────────


async def run_sync(
    session: AsyncSession,
    *,
    triggered_by: str = "manual",
    only: list[str] | None = None,
) -> SyncRunSummary:
    run_id = uuid4()
    started_at = utcnow()
    logger.info("of_intelligence.sync.start run_id=%s triggered_by=%s", run_id, triggered_by)

    credentials = await resolve_credentials(session)
    client = OnlyMonsterClient(credentials, rate_limiter=OnlyMonsterRateLimiter())
    ctx = SyncRunContext(run_id=run_id)

    selected: tuple[EndpointSpec, ...] = (
        ENDPOINT_CATALOG
        if not only
        else tuple(spec for spec in ENDPOINT_CATALOG if spec.entity in set(only))
    )

    succeeded = not_available = failed = skipped = 0

    for spec in selected:
        # ── Reasons to never make a network call ──────────────────────────
        if spec.write:
            await _record_skip(session, run_id, spec, triggered_by, "write_disabled",
                               "Write endpoint — disabled by policy.")
            skipped += 1
            continue
        if not spec.available:
            reason = "dynamic_discovery_required" if spec.requires_dynamic_discovery else "not_available_from_api"
            await _record_skip(session, run_id, spec, triggered_by, reason, spec.description)
            not_available += 1
            continue

        # ── Fan-out planning ──────────────────────────────────────────────
        if spec.fan_out == "flat":
            outcome = await _run_one(session, client, spec, ctx, run_id, triggered_by, path_params={})
            _tally(outcome, succeeded_l := [succeeded], failed_l := [failed],
                   not_available_l := [not_available], skipped_l := [skipped])
            succeeded, failed, not_available, skipped = succeeded_l[0], failed_l[0], not_available_l[0], skipped_l[0]
        elif spec.fan_out == "per_account":
            if not ctx.accounts:
                await _record_skip(session, run_id, spec, triggered_by, "no_accounts_in_run",
                                   "Skipped — accounts sync produced no results in this run.")
                skipped += 1
                continue
            for account in ctx.accounts:
                aid = account.get("id")
                if aid in (None, ""):
                    continue
                outcome = await _run_one(
                    session, client, spec, ctx, run_id, triggered_by,
                    path_params={"account_id": aid},
                )
                _tally(outcome, succeeded_l := [succeeded], failed_l := [failed],
                       not_available_l := [not_available], skipped_l := [skipped])
                succeeded, failed, not_available, skipped = (
                    succeeded_l[0], failed_l[0], not_available_l[0], skipped_l[0]
                )
        elif spec.fan_out == "per_platform_account":
            if not ctx.accounts:
                await _record_skip(session, run_id, spec, triggered_by, "no_accounts_in_run",
                                   "Skipped — accounts sync produced no results in this run.")
                skipped += 1
                continue
            for account in ctx.accounts:
                platform = account.get("platform")
                platform_account_id = account.get("platform_account_id")
                if not platform or not platform_account_id:
                    continue
                outcome = await _run_one(
                    session, client, spec, ctx, run_id, triggered_by,
                    path_params={"platform": platform, "platform_account_id": platform_account_id},
                )
                _tally(outcome, succeeded_l := [succeeded], failed_l := [failed],
                       not_available_l := [not_available], skipped_l := [skipped])
                succeeded, failed, not_available, skipped = (
                    succeeded_l[0], failed_l[0], not_available_l[0], skipped_l[0]
                )
        else:
            await _record_skip(session, run_id, spec, triggered_by, "unsupported_fan_out",
                               f"Unsupported fan_out={spec.fan_out}")
            skipped += 1

    finished_at = utcnow()
    summary = SyncRunSummary(
        run_id=run_id, started_at=started_at, finished_at=finished_at,
        total_entities=len(selected),
        succeeded=succeeded, not_available=not_available, failed=failed, skipped=skipped,
    )
    logger.info(
        "of_intelligence.sync.finish run_id=%s ok=%s na=%s fail=%s skip=%s elapsed=%.1fs",
        run_id, succeeded, not_available, failed, skipped,
        (finished_at - started_at).total_seconds(),
    )
    return summary


async def run_sync_in_background(*, triggered_by: str = "manual") -> None:
    async with async_session_maker() as session:
        try:
            await run_sync(session, triggered_by=triggered_by)
        except Exception:
            logger.exception("of_intelligence.sync.background.crash")


# ── Single-entity execution ──────────────────────────────────────────────────


async def _run_one(
    session: AsyncSession,
    client: OnlyMonsterClient,
    spec: EndpointSpec,
    ctx: SyncRunContext,
    run_id: UUID,
    triggered_by: str,
    path_params: dict[str, Any],
) -> str:
    """Fetch + persist a single (entity, path_params) pair.  Returns status."""
    log = OfIntelligenceSyncLog(
        run_id=run_id, source=SOURCE_ONLYMONSTER, entity=spec.entity, status="running",
        triggered_by=triggered_by, started_at=utcnow(),
    )
    session.add(log)
    await session.commit()
    await session.refresh(log)

    try:
        result = await client.fetch_entity(spec.entity, path_params=path_params)
    except Exception as exc:
        logger.exception("of_intelligence.sync.entity.crash entity=%s", spec.entity)
        log.status = "error"
        log.error = f"unhandled: {exc!r}"
        log.finished_at = utcnow()
        session.add(log)
        await session.commit()
        return "error"

    items_written = 0
    if not result.available:
        log.status = result.reason or "not_available_from_api"
        log.reason = result.reason
        log.error = result.error
        log.finished_at = utcnow()
        session.add(log)
        await session.commit()
        return "not_available"

    if result.error and not result.items:
        log.status = "error"
        log.reason = result.reason
        log.error = result.error
        log.finished_at = utcnow()
        session.add(log)
        await session.commit()
        return "error"

    try:
        items_written = await _persist_entity(session, spec.entity, result, ctx)
        log.items_synced = items_written
        log.pages_fetched = result.page_count
        log.reason = result.reason
        log.error = result.error
        log.status = "partial" if result.error else "success"
    except Exception as exc:
        logger.exception("of_intelligence.sync.persist.crash entity=%s", spec.entity)
        log.status = "error"
        log.reason = "persist_error"
        log.error = f"{exc!r}"
    log.finished_at = utcnow()
    session.add(log)
    await session.commit()
    logger.info(
        "of_intelligence.sync.entity.done entity=%s status=%s items=%s pages=%s pp=%s",
        spec.entity, log.status, items_written, result.page_count, path_params,
    )
    return "success" if log.status == "success" else log.status or "error"


async def _record_skip(
    session: AsyncSession,
    run_id: UUID,
    spec: EndpointSpec,
    triggered_by: str,
    reason: str,
    detail: str | None,
) -> None:
    session.add(OfIntelligenceSyncLog(
        run_id=run_id, source=SOURCE_ONLYMONSTER, entity=spec.entity,
        status=reason, reason=reason, error=detail,
        triggered_by=triggered_by, started_at=utcnow(), finished_at=utcnow(),
    ))
    await session.commit()


def _tally(outcome: str, succeeded: list[int], failed: list[int],
           not_available: list[int], skipped: list[int]) -> None:
    if outcome == "success":
        succeeded[0] += 1
    elif outcome == "not_available":
        not_available[0] += 1
    elif outcome in ("partial", "error"):
        failed[0] += 1
    else:
        skipped[0] += 1


# ── Persistence ──────────────────────────────────────────────────────────────


async def _persist_entity(
    session: AsyncSession,
    entity: str,
    result: EndpointResult,
    ctx: SyncRunContext,
) -> int:
    if not result.items:
        return 0
    handler = _PERSISTERS.get(entity)
    if handler is None:
        # Honest no-op — the data was fetched and counted in sync_logs, but
        # we don't persist it yet.  Adding a persister later is purely
        # additive (no migration).
        logger.info("of_intelligence.sync.no_persister entity=%s items=%s",
                    entity, len(result.items))
        return 0
    return await handler(session, result.items, result, ctx)


async def _persist_accounts(
    session: AsyncSession,
    items: list[dict[str, Any]],
    result: EndpointResult,
    ctx: SyncRunContext,
) -> int:
    """Upsert accounts and capture them in the run context for fan-out."""
    written = 0
    now = utcnow()
    for item in items:
        ctx.accounts.append(item)  # Always feed the run context, even if persist fails.
        source_id = _coerce_str(item.get("id"))
        if not source_id:
            continue
        existing = (await session.exec(
            select(OfIntelligenceAccount).where(
                OfIntelligenceAccount.source == SOURCE_ONLYMONSTER,
                OfIntelligenceAccount.source_id == source_id,
            )
        )).first()
        access = "active" if not item.get("subscription_expiration_date") else _account_access_status(item)
        if existing:
            existing.username = _coerce_str(item.get("username")) or existing.username
            existing.display_name = _coerce_str(item.get("name")) or existing.display_name
            existing.status = _coerce_str(item.get("platform")) or existing.status
            existing.access_status = access or existing.access_status
            existing.raw = item
            existing.last_synced_at = now
            session.add(existing)
        else:
            session.add(OfIntelligenceAccount(
                source=SOURCE_ONLYMONSTER,
                source_id=source_id,
                username=_coerce_str(item.get("username")),
                display_name=_coerce_str(item.get("name")),
                status=_coerce_str(item.get("platform")),
                access_status=access,
                raw=item,
                first_seen_at=now,
                last_synced_at=now,
            ))
        written += 1
    await session.commit()
    return written


async def _persist_account_details(
    session: AsyncSession,
    items: list[dict[str, Any]],
    result: EndpointResult,
    ctx: SyncRunContext,
) -> int:
    """Refresh the existing accounts row with the per-account detail payload."""
    written = 0
    now = utcnow()
    for item in items:
        source_id = _coerce_str(item.get("id"))
        if not source_id:
            continue
        existing = (await session.exec(
            select(OfIntelligenceAccount).where(
                OfIntelligenceAccount.source == SOURCE_ONLYMONSTER,
                OfIntelligenceAccount.source_id == source_id,
            )
        )).first()
        if existing:
            existing.raw = {**(existing.raw or {}), **item}
            existing.last_synced_at = now
            session.add(existing)
            written += 1
    await session.commit()
    return written


async def _persist_fans(
    session: AsyncSession,
    items: list[dict[str, Any]],
    result: EndpointResult,
    ctx: SyncRunContext,
) -> int:
    """Insert/refresh fan IDs.  Each item is `{"fan_id": "..."}` from the
    client's special-case unwrapping of `{fan_ids: [...]}`."""
    written = 0
    now = utcnow()
    account_id = _coerce_str(result.path_params.get("account_id"))
    for item in items:
        source_id = _coerce_str(item.get("fan_id"))
        if not source_id:
            continue
        existing = (await session.exec(
            select(OfIntelligenceFan).where(
                OfIntelligenceFan.source == SOURCE_ONLYMONSTER,
                OfIntelligenceFan.source_id == source_id,
            )
        )).first()
        if existing:
            existing.account_source_id = account_id or existing.account_source_id
            existing.raw = item
            existing.last_synced_at = now
            session.add(existing)
        else:
            session.add(OfIntelligenceFan(
                source=SOURCE_ONLYMONSTER,
                source_id=source_id,
                account_source_id=account_id,
                raw=item,
                first_seen_at=now,
                last_synced_at=now,
            ))
        written += 1
    await session.commit()
    return written


async def _persist_members(
    session: AsyncSession,
    items: list[dict[str, Any]],
    result: EndpointResult,
    ctx: SyncRunContext,
) -> int:
    """Map OnlyMonster organisation members → OFI chatters."""
    written = 0
    now = utcnow()
    for item in items:
        source_id = _coerce_str(item.get("id"))
        if not source_id:
            continue
        existing = (await session.exec(
            select(OfIntelligenceChatter).where(
                OfIntelligenceChatter.source == SOURCE_ONLYMONSTER,
                OfIntelligenceChatter.source_id == source_id,
            )
        )).first()
        if existing:
            existing.name = _coerce_str(item.get("name")) or existing.name
            existing.email = _coerce_str(item.get("email")) or existing.email
            existing.raw = item
            existing.last_synced_at = now
            session.add(existing)
        else:
            session.add(OfIntelligenceChatter(
                source=SOURCE_ONLYMONSTER,
                source_id=source_id,
                name=_coerce_str(item.get("name")),
                email=_coerce_str(item.get("email")),
                raw=item,
                first_seen_at=now,
                last_synced_at=now,
            ))
        written += 1
    await session.commit()
    return written


async def _persist_transactions(
    session: AsyncSession,
    items: list[dict[str, Any]],
    result: EndpointResult,
    ctx: SyncRunContext,
) -> int:
    """Append each transaction to of_intelligence_revenue (1 row per txn)."""
    written = 0
    now = utcnow()
    platform_account_id = _coerce_str(result.path_params.get("platform_account_id"))
    account_internal_id = _resolve_account_internal_id(ctx, platform_account_id)
    for item in items:
        amount = item.get("amount")
        try:
            cents = int(round(float(amount) * 100))
        except (TypeError, ValueError):
            cents = 0
        ts = _coerce_dt(item.get("timestamp"))
        session.add(OfIntelligenceRevenue(
            source=SOURCE_ONLYMONSTER,
            account_source_id=account_internal_id or platform_account_id,
            period_start=ts,
            period_end=ts,
            revenue_cents=cents,
            transactions_count=1,
            tips_cents=cents if (item.get("type") or "").lower().startswith("tip") else None,
            ppv_cents=cents if "post" in (item.get("type") or "").lower() else None,
            breakdown={"type": item.get("type"), "status": item.get("status")},
            raw=item,
            captured_at=now,
        ))
        written += 1
    await session.commit()
    return written


async def _persist_chargebacks(
    session: AsyncSession,
    items: list[dict[str, Any]],
    result: EndpointResult,
    ctx: SyncRunContext,
) -> int:
    """Chargebacks land in revenue with a negative sign + chargeback marker."""
    written = 0
    now = utcnow()
    platform_account_id = _coerce_str(result.path_params.get("platform_account_id"))
    account_internal_id = _resolve_account_internal_id(ctx, platform_account_id)
    for item in items:
        amount = item.get("amount")
        try:
            cents = -abs(int(round(float(amount) * 100)))
        except (TypeError, ValueError):
            cents = 0
        ts = _coerce_dt(item.get("chargeback_timestamp")) or _coerce_dt(item.get("transaction_timestamp"))
        session.add(OfIntelligenceRevenue(
            source=SOURCE_ONLYMONSTER,
            account_source_id=account_internal_id or platform_account_id,
            period_start=ts,
            period_end=ts,
            revenue_cents=cents,
            transactions_count=1,
            breakdown={"kind": "chargeback", "type": item.get("type"), "status": item.get("status")},
            raw=item,
            captured_at=now,
        ))
        written += 1
    await session.commit()
    return written


async def _persist_links(
    session: AsyncSession,
    items: list[dict[str, Any]],
    result: EndpointResult,
    ctx: SyncRunContext,
) -> int:
    """Trial + tracking links share a row format in of_intelligence_tracking_links."""
    written = 0
    now = utcnow()
    kind = "trial" if result.entity == "trial_links" else "tracking"
    platform_account_id = _coerce_str(result.path_params.get("platform_account_id"))
    account_internal_id = _resolve_account_internal_id(ctx, platform_account_id)
    for item in items:
        source_id = _coerce_str(item.get("id"))
        if not source_id:
            continue
        session.add(OfIntelligenceTrackingLink(
            source=SOURCE_ONLYMONSTER,
            source_id=f"{kind}:{source_id}",
            account_source_id=account_internal_id or platform_account_id,
            name=_coerce_str(item.get("name")),
            url=_coerce_str(item.get("url")),
            clicks=_coerce_int(item.get("clicks")),
            conversions=_coerce_int(item.get("subscribers") or item.get("claims")),
            revenue_cents=None,
            raw={**item, "kind": kind},
            snapshot_at=now,
        ))
        written += 1
    await session.commit()
    return written


_PERSISTERS = {
    "accounts":         _persist_accounts,
    "account_details":  _persist_account_details,
    "fans":             _persist_fans,
    "members":          _persist_members,
    "transactions":     _persist_transactions,
    "chargebacks":      _persist_chargebacks,
    "trial_links":      _persist_links,
    "tracking_links":   _persist_links,
    # vault_folders, vault_uploads, trial_link_users, tracking_link_users,
    # user_metrics — fetched + counted in sync_logs but not yet persisted to
    # bespoke tables.  Add a dedicated persister + table when needed.
}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _resolve_account_internal_id(ctx: SyncRunContext, platform_account_id: str | None) -> str | None:
    """Find the internal numeric account id for a given platform_account_id."""
    if not platform_account_id:
        return None
    for account in ctx.accounts:
        if str(account.get("platform_account_id")) == platform_account_id:
            return _coerce_str(account.get("id"))
    return None


def _account_access_status(account: dict[str, Any]) -> str:
    expiry = _coerce_dt(account.get("subscription_expiration_date"))
    if expiry is None:
        return "unknown"
    return "active" if expiry > utcnow() else "expired"


# ── Latest-status helper for the API status endpoint ─────────────────────────


async def fetch_latest_sync_state(session: AsyncSession) -> dict[str, Any]:
    stmt = (
        sa_select(OfIntelligenceSyncLog)
        .order_by(OfIntelligenceSyncLog.started_at.desc())
        .limit(500)
    )
    rows = (await session.exec(stmt)).scalars().all()  # type: ignore[attr-defined]

    latest_per_entity: dict[str, OfIntelligenceSyncLog] = {}
    last_run_id: UUID | None = None
    last_run_started: datetime | None = None
    for row in rows:
        if last_run_id is None:
            last_run_id = row.run_id
            last_run_started = row.started_at
        if row.entity not in latest_per_entity:
            latest_per_entity[row.entity] = row

    return {
        "last_run_id": str(last_run_id) if last_run_id else None,
        "last_run_started_at": last_run_started.isoformat() if last_run_started else None,
        "entities": {
            entity: {
                "status": log.status,
                "items_synced": log.items_synced,
                "pages_fetched": log.pages_fetched,
                "started_at": log.started_at.isoformat() if log.started_at else None,
                "finished_at": log.finished_at.isoformat() if log.finished_at else None,
                "reason": log.reason,
                "error": log.error,
            }
            for entity, log in latest_per_entity.items()
        },
    }


# ── Coercion helpers ─────────────────────────────────────────────────────────


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.utcfromtimestamp(float(value))
        except (OverflowError, ValueError, OSError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
