"""OnlyMonster sync orchestrator — idempotent end-to-end.

Wired to om-api-service v0.30.0
(https://omapi.onlymonster.ai/docs/json).  Sync is strictly read-only —
the client refuses to fire any endpoint flagged `write=True`, and the
orchestrator never asks for one.

Idempotency contract (post migration `b1f2e3d4c5a6`):
  • Every persister returns a `PersistResult` with explicit
    `created / updated / skipped_duplicate / error` counters.
  • Mutable entity rows (`accounts`, `fans`, `chatters`, `tracking_links`)
    are upserted by their stable `(source, source_external_id)` pair and
    never inserted twice.
  • Revenue rows from transactions and chargebacks dedupe on the upstream
    transaction id — running Sync Now twice does NOT change
    `SUM(revenue_cents)` unless OnlyMonster returned new rows.
  • Sync log rows carry the per-bucket counters and the upstream endpoint
    path so the UI can show exactly what changed.

Flow:
  1. Walk the catalog in declaration order.
  2. `flat` entities → call once.
  3. `per_account` entities → iterate over the accounts captured during
     this run (collected from step 1's `accounts` call).
  4. `per_platform_account` → same accounts, pass `platform` and
     `platform_account_id`.
  5. Disabled / write / dynamic-discovery entities never make a network
     call; they get a sync_log row stamped with the reason.
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


# ── Result containers ────────────────────────────────────────────────────────


@dataclass
class PersistResult:
    """Per-entity persistence outcome."""

    created: int = 0
    updated: int = 0
    skipped_duplicate: int = 0
    errors: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated + self.skipped_duplicate + self.errors


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

        if spec.fan_out == "flat":
            outcome = await _run_one(session, client, spec, ctx, run_id, triggered_by, path_params={})
            succeeded, failed, not_available, skipped = _tally(
                outcome, succeeded, failed, not_available, skipped,
            )
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
                succeeded, failed, not_available, skipped = _tally(
                    outcome, succeeded, failed, not_available, skipped,
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
                succeeded, failed, not_available, skipped = _tally(
                    outcome, succeeded, failed, not_available, skipped,
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
        triggered_by=triggered_by, started_at=utcnow(), source_endpoint=spec.path,
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
        log.error_count = 1
        log.finished_at = utcnow()
        session.add(log)
        await session.commit()
        return "error"

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
        log.error_count = 1
        log.finished_at = utcnow()
        session.add(log)
        await session.commit()
        return "error"

    persisted = PersistResult()
    try:
        persisted = await _persist_entity(session, spec.entity, result, ctx)
        log.items_synced = len(result.items)
        log.created_count = persisted.created
        log.updated_count = persisted.updated
        log.skipped_duplicate_count = persisted.skipped_duplicate
        log.error_count = persisted.errors
        log.pages_fetched = result.page_count
        log.reason = result.reason
        log.error = result.error
        log.status = "partial" if (result.error or persisted.errors) else "success"
    except Exception as exc:
        logger.exception("of_intelligence.sync.persist.crash entity=%s", spec.entity)
        log.status = "error"
        log.reason = "persist_error"
        log.error = f"{exc!r}"
        log.error_count = max(1, persisted.errors)
    log.finished_at = utcnow()
    session.add(log)
    await session.commit()
    logger.info(
        "of_intelligence.sync.entity.done entity=%s status=%s items=%s "
        "created=%s updated=%s skipped_dup=%s errors=%s pages=%s pp=%s",
        spec.entity, log.status, log.items_synced,
        log.created_count, log.updated_count, log.skipped_duplicate_count, log.error_count,
        result.page_count, path_params,
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
        source_endpoint=spec.path,
    ))
    await session.commit()


def _tally(outcome: str, succeeded: int, failed: int,
           not_available: int, skipped: int) -> tuple[int, int, int, int]:
    if outcome == "success":
        succeeded += 1
    elif outcome == "not_available":
        not_available += 1
    elif outcome in ("partial", "error"):
        failed += 1
    else:
        skipped += 1
    return succeeded, failed, not_available, skipped


# ── Persistence ──────────────────────────────────────────────────────────────


async def _persist_entity(
    session: AsyncSession,
    entity: str,
    result: EndpointResult,
    ctx: SyncRunContext,
) -> PersistResult:
    if not result.items:
        return PersistResult()
    handler = _PERSISTERS.get(entity)
    if handler is None:
        # No persister wired for this entity yet — sync_log tracks fetched
        # items in `items_synced` so the audit trail is intact, but we
        # don't accumulate anything in the data tables (so no duplicates).
        logger.info("of_intelligence.sync.no_persister entity=%s items=%s",
                    entity, len(result.items))
        return PersistResult()
    return await handler(session, result.items, result, ctx)


async def _persist_accounts(
    session: AsyncSession,
    items: list[dict[str, Any]],
    result: EndpointResult,
    ctx: SyncRunContext,
) -> PersistResult:
    """Upsert accounts and capture them in the run context for fan-out."""
    out = PersistResult()
    now = utcnow()
    for item in items:
        ctx.accounts.append(item)  # Always feed run context, even if persist fails.
        source_id = _coerce_str(item.get("id"))
        if not source_id:
            out.errors += 1
            continue
        try:
            existing = (await session.exec(
                select(OfIntelligenceAccount).where(
                    OfIntelligenceAccount.source == SOURCE_ONLYMONSTER,
                    OfIntelligenceAccount.source_id == source_id,
                )
            )).first()
            access = _account_access_status(item)
            if existing:
                existing.username = _coerce_str(item.get("username")) or existing.username
                existing.display_name = _coerce_str(item.get("name")) or existing.display_name
                existing.status = _coerce_str(item.get("platform")) or existing.status
                existing.access_status = access or existing.access_status
                existing.raw = item
                existing.last_synced_at = now
                session.add(existing)
                out.updated += 1
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
                out.created += 1
        except Exception as exc:
            logger.warning("of_intelligence.persist.account.error source_id=%s err=%s", source_id, exc)
            out.errors += 1
    await session.commit()
    return out


async def _persist_account_details(
    session: AsyncSession,
    items: list[dict[str, Any]],
    result: EndpointResult,
    ctx: SyncRunContext,
) -> PersistResult:
    """Refresh the existing accounts row with the per-account detail payload.

    Idempotent — only ever updates an existing row; never creates one.
    """
    out = PersistResult()
    now = utcnow()
    for item in items:
        source_id = _coerce_str(item.get("id"))
        if not source_id:
            out.errors += 1
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
            out.updated += 1
        else:
            out.skipped_duplicate += 1  # account row not found; account_details should run after accounts.
    await session.commit()
    return out


async def _persist_fans(
    session: AsyncSession,
    items: list[dict[str, Any]],
    result: EndpointResult,
    ctx: SyncRunContext,
) -> PersistResult:
    """Upsert fan IDs by `(source, source_id)` — idempotent."""
    out = PersistResult()
    now = utcnow()
    account_id = _coerce_str(result.path_params.get("account_id"))
    for item in items:
        source_id = _coerce_str(item.get("fan_id"))
        if not source_id:
            out.errors += 1
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
            out.updated += 1
        else:
            session.add(OfIntelligenceFan(
                source=SOURCE_ONLYMONSTER,
                source_id=source_id,
                account_source_id=account_id,
                raw=item,
                first_seen_at=now,
                last_synced_at=now,
            ))
            out.created += 1
    await session.commit()
    return out


async def _persist_members(
    session: AsyncSession,
    items: list[dict[str, Any]],
    result: EndpointResult,
    ctx: SyncRunContext,
) -> PersistResult:
    """Map OnlyMonster organisation members → OFI chatters (upsert)."""
    out = PersistResult()
    now = utcnow()
    for item in items:
        source_id = _coerce_str(item.get("id"))
        if not source_id:
            out.errors += 1
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
            out.updated += 1
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
            out.created += 1
    await session.commit()
    return out


async def _persist_transactions(
    session: AsyncSession,
    items: list[dict[str, Any]],
    result: EndpointResult,
    ctx: SyncRunContext,
) -> PersistResult:
    """Idempotent insert of transactions into of_intelligence_revenue.

    Stable dedup key: `source_external_id` = upstream transaction id when
    present, else a deterministic hash of (endpoint, account, timestamp,
    amount, fan, type, status).  Already-seen rows are reported as
    `skipped_duplicate`.
    """
    return await _persist_revenue_events(
        session, items, result, ctx, kind=None,
    )


async def _persist_chargebacks(
    session: AsyncSession,
    items: list[dict[str, Any]],
    result: EndpointResult,
    ctx: SyncRunContext,
) -> PersistResult:
    """Chargebacks land in revenue with a negative sign + chargeback marker."""
    return await _persist_revenue_events(
        session, items, result, ctx, kind="chargeback",
    )


async def _persist_revenue_events(
    session: AsyncSession,
    items: list[dict[str, Any]],
    result: EndpointResult,
    ctx: SyncRunContext,
    *,
    kind: str | None,
) -> PersistResult:
    out = PersistResult()
    now = utcnow()
    platform_account_id = _coerce_str(result.path_params.get("platform_account_id"))
    account_internal_id = _resolve_account_internal_id(ctx, platform_account_id) or platform_account_id

    for item in items:
        external_id = _stable_revenue_key(item, result, kind=kind)
        if not external_id:
            out.errors += 1
            continue

        existing = (await session.exec(
            select(OfIntelligenceRevenue).where(
                OfIntelligenceRevenue.source == SOURCE_ONLYMONSTER,
                OfIntelligenceRevenue.source_external_id == external_id,
            )
        )).first()
        if existing:
            out.skipped_duplicate += 1
            continue

        amount = item.get("amount")
        try:
            cents = int(round(float(amount) * 100))
        except (TypeError, ValueError):
            cents = 0
        if kind == "chargeback":
            cents = -abs(cents)
            ts = _coerce_dt(item.get("chargeback_timestamp")) or _coerce_dt(item.get("transaction_timestamp"))
            breakdown = {"kind": "chargeback", "type": item.get("type"), "status": item.get("status")}
            tips_cents = None
            ppv_cents = None
        else:
            ts = _coerce_dt(item.get("timestamp"))
            type_str = (item.get("type") or "").lower()
            tips_cents = cents if type_str.startswith("tip") else None
            ppv_cents = cents if "post" in type_str else None
            breakdown = {"type": item.get("type"), "status": item.get("status")}

        session.add(OfIntelligenceRevenue(
            source=SOURCE_ONLYMONSTER,
            source_external_id=external_id,
            account_source_id=account_internal_id,
            period_start=ts,
            period_end=ts,
            revenue_cents=cents,
            transactions_count=1,
            tips_cents=tips_cents,
            ppv_cents=ppv_cents,
            breakdown=breakdown,
            raw=item,
            captured_at=now,
        ))
        out.created += 1
    await session.commit()
    return out


async def _persist_links(
    session: AsyncSession,
    items: list[dict[str, Any]],
    result: EndpointResult,
    ctx: SyncRunContext,
) -> PersistResult:
    """Trial + tracking links upsert by `(source, source_id)`.

    The schema-level constraint is `(source, source_id, snapshot_at)`, but
    we explicitly look up by `(source, source_id)` first so a re-sync
    UPDATES rather than appending a new snapshot.
    """
    out = PersistResult()
    now = utcnow()
    kind = "trial" if result.entity == "trial_links" else "tracking"
    platform_account_id = _coerce_str(result.path_params.get("platform_account_id"))
    account_internal_id = _resolve_account_internal_id(ctx, platform_account_id) or platform_account_id

    for item in items:
        upstream_id = _coerce_str(item.get("id"))
        if not upstream_id:
            out.errors += 1
            continue
        source_id = f"{kind}:{upstream_id}"

        existing = (await session.exec(
            select(OfIntelligenceTrackingLink).where(
                OfIntelligenceTrackingLink.source == SOURCE_ONLYMONSTER,
                OfIntelligenceTrackingLink.source_id == source_id,
            )
        )).first()
        clicks = _coerce_int(item.get("clicks"))
        conversions = _coerce_int(item.get("subscribers") or item.get("claims"))
        if existing:
            existing.account_source_id = account_internal_id or existing.account_source_id
            existing.name = _coerce_str(item.get("name")) or existing.name
            existing.url = _coerce_str(item.get("url")) or existing.url
            if clicks is not None:
                existing.clicks = clicks
            if conversions is not None:
                existing.conversions = conversions
            existing.raw = {**item, "kind": kind}
            existing.snapshot_at = now
            session.add(existing)
            out.updated += 1
        else:
            session.add(OfIntelligenceTrackingLink(
                source=SOURCE_ONLYMONSTER,
                source_id=source_id,
                account_source_id=account_internal_id,
                name=_coerce_str(item.get("name")),
                url=_coerce_str(item.get("url")),
                clicks=clicks,
                conversions=conversions,
                revenue_cents=None,
                raw={**item, "kind": kind},
                snapshot_at=now,
            ))
            out.created += 1
    await session.commit()
    return out


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
    # bespoke tables.  Adding a persister later is purely additive (no
    # migration needed for sync_log tracking; a new table would need one).
}


# ── Helpers ──────────────────────────────────────────────────────────────────


def _stable_revenue_key(
    item: dict[str, Any],
    result: EndpointResult,
    *,
    kind: str | None,
) -> str | None:
    """Stable dedup key for a revenue row.

    Strategy:
      1. Use upstream `id` when present (transactions + chargebacks both
         expose one in v0.30.0).  Prefix with the entity name so a tx and
         a chargeback that happened to share an id can never collide.
      2. Otherwise, fall back to a SHA-256 over the tuple
         (entity, account, timestamp, amount, fan, type, status) — this
         only changes when OnlyMonster changes the underlying data.
    """
    upstream_id = item.get("id")
    if upstream_id not in (None, ""):
        return f"{result.entity}:{upstream_id}"

    import hashlib
    fields = (
        kind or result.entity,
        result.path_params.get("platform"),
        result.path_params.get("platform_account_id") or result.path_params.get("account_id"),
        item.get("timestamp") or item.get("chargeback_timestamp") or item.get("transaction_timestamp"),
        item.get("amount"),
        (item.get("fan") or {}).get("id") if isinstance(item.get("fan"), dict) else None,
        item.get("type"),
        item.get("status"),
    )
    canonical = "|".join("" if v is None else str(v) for v in fields)
    if not canonical.strip("|"):
        return None
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{result.entity}:hash:{digest[:32]}"


def _resolve_account_internal_id(ctx: SyncRunContext, platform_account_id: str | None) -> str | None:
    """Find the internal numeric account id for a given platform_account_id."""
    if not platform_account_id:
        return None
    for account in ctx.accounts:
        if str(account.get("platform_account_id")) == platform_account_id:
            return _coerce_str(account.get("id"))
    return None


def _account_access_status(account: dict[str, Any]) -> str:
    """Compute access status from subscription_expiration_date.

    `_coerce_dt` returns naive UTC, matching `utcnow()`, so tz-aware
    payloads from OnlyMonster are normalized before comparison.  This was
    the source of the original silent-rollback bug.
    """
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
                "created": log.created_count,
                "updated": log.updated_count,
                "skipped_duplicate": log.skipped_duplicate_count,
                "errors": log.error_count,
                "pages_fetched": log.pages_fetched,
                "started_at": log.started_at.isoformat() if log.started_at else None,
                "finished_at": log.finished_at.isoformat() if log.finished_at else None,
                "reason": log.reason,
                "error": log.error,
                "source_endpoint": log.source_endpoint,
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
    """Parse to **naive** UTC datetime to match `utcnow()`.

    OnlyMonster timestamps are ISO-8601 with a trailing `Z` (UTC).  Strip
    the tz before returning so callers can compare against `utcnow()`
    without raising TypeError.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
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
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed
    return None
