"""OnlyMonster sync orchestrator.

Phase 1 design: a single foreground async function `run_sync()` that walks the
endpoint catalog, fetches each entity, persists items, and writes one row per
entity into `of_intelligence_sync_logs`.  A background-task wrapper is also
exposed so the API can fire-and-forget while the UI polls sync log status.

Entities marked unavailable in `endpoints.ENDPOINT_CATALOG` record a
placeholder log row (`status="not_available_from_api"`) — this lets the UI
truthfully report which entities are wired up and which are still stubs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
from app.models.of_intelligence import (
    SOURCE_ONLYMONSTER,
    OfIntelligenceAccount,
    OfIntelligenceChat,
    OfIntelligenceChatter,
    OfIntelligenceFan,
    OfIntelligenceMassMessage,
    OfIntelligenceMessage,
    OfIntelligencePost,
    OfIntelligenceRevenue,
    OfIntelligenceSyncLog,
    OfIntelligenceTrackingLink,
)

logger = logging.getLogger(__name__)


@dataclass
class SyncRunSummary:
    run_id: UUID
    started_at: datetime
    finished_at: datetime
    total_entities: int
    succeeded: int
    not_available: int
    failed: int


# ── Entrypoints ──────────────────────────────────────────────────────────────


async def run_sync(
    session: AsyncSession,
    *,
    triggered_by: str = "manual",
    only: list[str] | None = None,
) -> SyncRunSummary:
    """Run a full OnlyMonster sync.  Returns a summary the caller can log."""
    run_id = uuid4()
    started_at = utcnow()
    logger.info("of_intelligence.sync.start run_id=%s triggered_by=%s", run_id, triggered_by)

    credentials = await resolve_credentials(session)
    client = OnlyMonsterClient(credentials)

    succeeded = not_available = failed = 0
    selected: tuple[EndpointSpec, ...] = (
        ENDPOINT_CATALOG
        if not only
        else tuple(spec for spec in ENDPOINT_CATALOG if spec.entity in set(only))
    )

    for spec in selected:
        log = OfIntelligenceSyncLog(
            run_id=run_id,
            source=SOURCE_ONLYMONSTER,
            entity=spec.entity,
            status="running",
            triggered_by=triggered_by,
            started_at=utcnow(),
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)

        try:
            result = await client.fetch_entity(spec.entity)
        except Exception as exc:  # defensive — never let one entity kill the run
            logger.exception("of_intelligence.sync.entity.crash entity=%s", spec.entity)
            log.status = "error"
            log.error = f"unhandled: {exc!r}"
            log.finished_at = utcnow()
            session.add(log)
            await session.commit()
            failed += 1
            continue

        items_written = 0
        if not result.available and result.reason == "not_available_from_api":
            log.status = "not_available_from_api"
            log.reason = "not_available_from_api"
            not_available += 1
        elif not result.available:
            log.status = "error"
            log.reason = result.reason
            log.error = result.error
            failed += 1
        elif result.error and not result.items:
            log.status = "error"
            log.reason = result.reason
            log.error = result.error
            failed += 1
        else:
            try:
                items_written = await _persist_entity(session, spec.entity, result)
                log.status = "success" if not result.error else "partial"
                log.items_synced = items_written
                log.pages_fetched = result.page_count
                log.reason = result.reason
                log.error = result.error
                if log.status == "success":
                    succeeded += 1
                else:
                    failed += 1
            except Exception as exc:
                logger.exception("of_intelligence.sync.persist.crash entity=%s", spec.entity)
                log.status = "error"
                log.reason = "persist_error"
                log.error = f"{exc!r}"
                failed += 1

        log.finished_at = utcnow()
        session.add(log)
        await session.commit()
        logger.info(
            "of_intelligence.sync.entity.done entity=%s status=%s items=%s pages=%s",
            spec.entity, log.status, items_written, result.page_count,
        )

    finished_at = utcnow()
    summary = SyncRunSummary(
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        total_entities=len(selected),
        succeeded=succeeded,
        not_available=not_available,
        failed=failed,
    )
    logger.info(
        "of_intelligence.sync.finish run_id=%s ok=%s na=%s fail=%s elapsed=%.1fs",
        run_id, succeeded, not_available, failed,
        (finished_at - started_at).total_seconds(),
    )
    return summary


async def run_sync_in_background(*, triggered_by: str = "manual") -> None:
    """Fire-and-forget wrapper that opens its own session.

    Used by the manual-sync endpoint so the HTTP request returns immediately
    while the sync continues server-side.  All progress is observable via
    `of_intelligence_sync_logs`.
    """
    async with async_session_maker() as session:
        try:
            await run_sync(session, triggered_by=triggered_by)
        except Exception:
            logger.exception("of_intelligence.sync.background.crash")


# ── Persistence helpers (one branch per entity) ──────────────────────────────


async def _persist_entity(session: AsyncSession, entity: str, result: EndpointResult) -> int:
    """Persist `result.items` into the right table.  Returns rows written."""
    if not result.items:
        return 0

    handler = _PERSISTERS.get(entity)
    if handler is None:
        # No bespoke persister yet — store as a sync_log breadcrumb only.
        logger.warning("of_intelligence.sync.no_persister entity=%s items=%s", entity, len(result.items))
        return 0

    return await handler(session, result.items)


async def _persist_accounts(session: AsyncSession, items: list[dict[str, Any]]) -> int:
    written = 0
    now = utcnow()
    for item in items:
        source_id = _coerce_str(item.get("id") or item.get("account_id"))
        if not source_id:
            continue
        existing = (await session.exec(
            select(OfIntelligenceAccount).where(
                OfIntelligenceAccount.source == SOURCE_ONLYMONSTER,
                OfIntelligenceAccount.source_id == source_id,
            )
        )).first()
        if existing:
            existing.username = _coerce_str(item.get("username")) or existing.username
            existing.display_name = _coerce_str(item.get("display_name") or item.get("name")) or existing.display_name
            existing.status = _coerce_str(item.get("status")) or existing.status
            existing.access_status = _coerce_str(item.get("access_status")) or existing.access_status
            existing.raw = item
            existing.last_synced_at = now
            session.add(existing)
        else:
            session.add(OfIntelligenceAccount(
                source=SOURCE_ONLYMONSTER,
                source_id=source_id,
                username=_coerce_str(item.get("username")),
                display_name=_coerce_str(item.get("display_name") or item.get("name")),
                status=_coerce_str(item.get("status")),
                access_status=_coerce_str(item.get("access_status")),
                raw=item,
                first_seen_at=now,
                last_synced_at=now,
            ))
        written += 1
    await session.commit()
    return written


async def _persist_fans(session: AsyncSession, items: list[dict[str, Any]]) -> int:
    written = 0
    now = utcnow()
    for item in items:
        source_id = _coerce_str(item.get("id") or item.get("fan_id"))
        if not source_id:
            continue
        existing = (await session.exec(
            select(OfIntelligenceFan).where(
                OfIntelligenceFan.source == SOURCE_ONLYMONSTER,
                OfIntelligenceFan.source_id == source_id,
            )
        )).first()
        ltv = _coerce_int(item.get("lifetime_value_cents") or item.get("ltv_cents"))
        last_message_at = _coerce_dt(item.get("last_message_at"))
        is_subscribed = _coerce_bool(item.get("is_subscribed") or item.get("subscribed"))
        if existing:
            existing.account_source_id = _coerce_str(item.get("account_id")) or existing.account_source_id
            existing.username = _coerce_str(item.get("username")) or existing.username
            existing.lifetime_value_cents = ltv if ltv is not None else existing.lifetime_value_cents
            existing.last_message_at = last_message_at or existing.last_message_at
            existing.is_subscribed = is_subscribed if is_subscribed is not None else existing.is_subscribed
            existing.raw = item
            existing.last_synced_at = now
            session.add(existing)
        else:
            session.add(OfIntelligenceFan(
                source=SOURCE_ONLYMONSTER,
                source_id=source_id,
                account_source_id=_coerce_str(item.get("account_id")),
                username=_coerce_str(item.get("username")),
                lifetime_value_cents=ltv,
                last_message_at=last_message_at,
                is_subscribed=is_subscribed,
                raw=item,
                first_seen_at=now,
                last_synced_at=now,
            ))
        written += 1
    await session.commit()
    return written


async def _persist_chats(session: AsyncSession, items: list[dict[str, Any]]) -> int:
    written = 0
    now = utcnow()
    for item in items:
        source_id = _coerce_str(item.get("id") or item.get("chat_id"))
        if not source_id:
            continue
        existing = (await session.exec(
            select(OfIntelligenceChat).where(
                OfIntelligenceChat.source == SOURCE_ONLYMONSTER,
                OfIntelligenceChat.source_id == source_id,
            )
        )).first()
        if existing:
            existing.account_source_id = _coerce_str(item.get("account_id")) or existing.account_source_id
            existing.fan_source_id = _coerce_str(item.get("fan_id")) or existing.fan_source_id
            existing.last_message_at = _coerce_dt(item.get("last_message_at")) or existing.last_message_at
            existing.unread_count = _coerce_int(item.get("unread_count")) or existing.unread_count
            existing.raw = item
            existing.last_synced_at = now
            session.add(existing)
        else:
            session.add(OfIntelligenceChat(
                source=SOURCE_ONLYMONSTER,
                source_id=source_id,
                account_source_id=_coerce_str(item.get("account_id")),
                fan_source_id=_coerce_str(item.get("fan_id")),
                last_message_at=_coerce_dt(item.get("last_message_at")),
                unread_count=_coerce_int(item.get("unread_count")),
                raw=item,
                first_seen_at=now,
                last_synced_at=now,
            ))
        written += 1
    await session.commit()
    return written


async def _persist_messages(session: AsyncSession, items: list[dict[str, Any]]) -> int:
    written = 0
    now = utcnow()
    for item in items:
        source_id = _coerce_str(item.get("id") or item.get("message_id"))
        if not source_id:
            continue
        # Append-only: skip if (source, source_id) already present.
        existing = (await session.exec(
            select(OfIntelligenceMessage).where(
                OfIntelligenceMessage.source == SOURCE_ONLYMONSTER,
                OfIntelligenceMessage.source_id == source_id,
            )
        )).first()
        if existing:
            continue
        session.add(OfIntelligenceMessage(
            source=SOURCE_ONLYMONSTER,
            source_id=source_id,
            chat_source_id=_coerce_str(item.get("chat_id")),
            account_source_id=_coerce_str(item.get("account_id")),
            fan_source_id=_coerce_str(item.get("fan_id")),
            chatter_source_id=_coerce_str(item.get("chatter_id") or item.get("sender_id")),
            direction=_coerce_str(item.get("direction")),
            sent_at=_coerce_dt(item.get("sent_at") or item.get("created_at")),
            body=_coerce_str(item.get("body") or item.get("text")),
            revenue_cents=_coerce_int(item.get("revenue_cents") or item.get("price_cents")),
            raw=item,
            synced_at=now,
        ))
        written += 1
    await session.commit()
    return written


async def _persist_chatters(session: AsyncSession, items: list[dict[str, Any]]) -> int:
    written = 0
    now = utcnow()
    for item in items:
        source_id = _coerce_str(item.get("id") or item.get("chatter_id"))
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
            existing.role = _coerce_str(item.get("role")) or existing.role
            existing.active = _coerce_bool(item.get("active")) if item.get("active") is not None else existing.active
            existing.raw = item
            existing.last_synced_at = now
            session.add(existing)
        else:
            session.add(OfIntelligenceChatter(
                source=SOURCE_ONLYMONSTER,
                source_id=source_id,
                name=_coerce_str(item.get("name")),
                email=_coerce_str(item.get("email")),
                role=_coerce_str(item.get("role")),
                active=_coerce_bool(item.get("active")),
                raw=item,
                first_seen_at=now,
                last_synced_at=now,
            ))
        written += 1
    await session.commit()
    return written


async def _persist_mass_messages(session: AsyncSession, items: list[dict[str, Any]]) -> int:
    written = 0
    now = utcnow()
    for item in items:
        source_id = _coerce_str(item.get("id") or item.get("mass_message_id"))
        if not source_id:
            continue
        session.add(OfIntelligenceMassMessage(
            source=SOURCE_ONLYMONSTER,
            source_id=source_id,
            account_source_id=_coerce_str(item.get("account_id")),
            sent_at=_coerce_dt(item.get("sent_at")),
            recipients_count=_coerce_int(item.get("recipients_count")),
            purchases_count=_coerce_int(item.get("purchases_count")),
            revenue_cents=_coerce_int(item.get("revenue_cents")),
            body_preview=_coerce_str(item.get("body") or item.get("text")),
            raw=item,
            snapshot_at=now,
        ))
        written += 1
    await session.commit()
    return written


async def _persist_posts(session: AsyncSession, items: list[dict[str, Any]]) -> int:
    written = 0
    now = utcnow()
    for item in items:
        source_id = _coerce_str(item.get("id") or item.get("post_id"))
        if not source_id:
            continue
        session.add(OfIntelligencePost(
            source=SOURCE_ONLYMONSTER,
            source_id=source_id,
            account_source_id=_coerce_str(item.get("account_id")),
            published_at=_coerce_dt(item.get("published_at") or item.get("posted_at")),
            likes_count=_coerce_int(item.get("likes_count")),
            comments_count=_coerce_int(item.get("comments_count")),
            revenue_cents=_coerce_int(item.get("revenue_cents")),
            raw=item,
            snapshot_at=now,
        ))
        written += 1
    await session.commit()
    return written


async def _persist_tracking_links(session: AsyncSession, items: list[dict[str, Any]]) -> int:
    written = 0
    now = utcnow()
    for item in items:
        source_id = _coerce_str(item.get("id") or item.get("link_id"))
        if not source_id:
            continue
        session.add(OfIntelligenceTrackingLink(
            source=SOURCE_ONLYMONSTER,
            source_id=source_id,
            account_source_id=_coerce_str(item.get("account_id")),
            name=_coerce_str(item.get("name")),
            url=_coerce_str(item.get("url")),
            clicks=_coerce_int(item.get("clicks")),
            conversions=_coerce_int(item.get("conversions")),
            revenue_cents=_coerce_int(item.get("revenue_cents")),
            raw=item,
            snapshot_at=now,
        ))
        written += 1
    await session.commit()
    return written


async def _persist_revenue(session: AsyncSession, items: list[dict[str, Any]]) -> int:
    """Append-only — every sync writes new rows, never overwrites."""
    written = 0
    now = utcnow()
    for item in items:
        session.add(OfIntelligenceRevenue(
            source=SOURCE_ONLYMONSTER,
            account_source_id=_coerce_str(item.get("account_id")),
            period_start=_coerce_dt(item.get("period_start")),
            period_end=_coerce_dt(item.get("period_end")),
            revenue_cents=_coerce_int(item.get("revenue_cents")) or 0,
            transactions_count=_coerce_int(item.get("transactions_count")),
            tips_cents=_coerce_int(item.get("tips_cents")),
            subscriptions_cents=_coerce_int(item.get("subscriptions_cents")),
            ppv_cents=_coerce_int(item.get("ppv_cents")),
            breakdown=item.get("breakdown") if isinstance(item.get("breakdown"), dict) else None,
            raw=item,
            captured_at=now,
        ))
        written += 1
    await session.commit()
    return written


_PERSISTERS = {
    "accounts": _persist_accounts,
    "fans": _persist_fans,
    "chats": _persist_chats,
    "messages": _persist_messages,
    "chatters": _persist_chatters,
    "mass_messages": _persist_mass_messages,
    "posts": _persist_posts,
    "tracking_links": _persist_tracking_links,
    "trial_links": _persist_tracking_links,
    "revenue": _persist_revenue,
    # Other entities (auto_messages, stories, transactions, etc.) currently
    # write only sync_log breadcrumbs — add a persister here once the upstream
    # shape is known.
}


# ── Latest-status helper for the API status endpoint ─────────────────────────


async def fetch_latest_sync_state(session: AsyncSession) -> dict[str, Any]:
    """Return latest run_id + per-entity status snapshot used by the UI."""
    stmt = (
        sa_select(OfIntelligenceSyncLog)
        .order_by(OfIntelligenceSyncLog.started_at.desc())
        .limit(200)
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


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "yes", "1", "active"):
            return True
        if v in ("false", "no", "0", "inactive"):
            return False
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
        # Best-effort ISO-8601 parse.  Tolerate trailing 'Z'.
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None
