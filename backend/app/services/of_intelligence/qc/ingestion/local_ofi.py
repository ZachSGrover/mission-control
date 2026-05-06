"""Local-OFI ingestion source — reads existing OFI tables only.

Activated when ``daily_qc_source_mode == "local_ofi"``.  Pulls account-
level aggregates from the rows already synced into ``of_intelligence_*``
tables (no external network calls).

Privacy:
  • Reads message rows only to count + compute median reply time.
    Message *bodies* are never read into Python and never persisted
    into the ``AccountMetrics`` we return.
  • Fan rows are NOT joined.  Fan handles never reach the QC layer.
  • Chatter (``operator_id``) is the internal ``OfIntelligenceChatter
    .source_id`` — used only for grouping findings; never rendered to
    Discord/Telegram.

Skipped reasons returned in ``IngestionResult.skipped_reason``:
  • ``no_local_ofi_data`` — no account rows present
  • ``ofi_table_missing`` — schema mismatch (caught defensively)
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.of_intelligence import (
    OfIntelligenceAccount,
    OfIntelligenceMessage,
    OfIntelligenceRevenue,
    OfIntelligenceSyncLog,
)
from app.services.of_intelligence.qc.ingestion.base import (
    AccountMetrics,
    IngestionResult,
    SourceMode,
)

logger = get_logger(__name__)

DEFAULT_WINDOW_HOURS = 24
DEFAULT_PRIOR_DAYS = 7


async def ingest_local_ofi(session: AsyncSession) -> IngestionResult:
    """Aggregate stored OFI rows into ``AccountMetrics`` snapshots.

    Returns an empty-account ``IngestionResult`` (with a clear skipped
    reason) when no OFI rows have been synced yet — the scheduler treats
    that as a graceful skip rather than a failure.
    """
    now = utcnow()
    period_end = now
    period_start = now - timedelta(hours=DEFAULT_WINDOW_HOURS)
    prior_cutoff = now - timedelta(days=DEFAULT_PRIOR_DAYS)

    try:
        accounts = list((await session.exec(select(OfIntelligenceAccount))).all())
    except Exception:
        logger.exception("of_qc.ingestion.local_ofi.account_query_failed")
        return IngestionResult(
            source_mode=SourceMode.LOCAL_OFI,
            source_confidence="unknown",
            safe_mode=True,
            accounts=[],
            skipped_reason="ofi_table_missing",
            notes=["OFI tables not reachable; skipping ingestion"],
        )

    if not accounts:
        return IngestionResult(
            source_mode=SourceMode.LOCAL_OFI,
            source_confidence="medium",
            safe_mode=True,
            accounts=[],
            skipped_reason="no_local_ofi_data",
            notes=["no OFI accounts synced yet"],
        )

    revenue_24h: defaultdict[str, int] = defaultdict(int)
    revenue_prior: defaultdict[str, int] = defaultdict(int)
    revenue_rows = (
        await session.exec(
            select(OfIntelligenceRevenue)
            .where(col(OfIntelligenceRevenue.period_start).is_not(None))
            .where(col(OfIntelligenceRevenue.period_start) >= prior_cutoff)
        )
    ).all()
    for r in revenue_rows:
        if r.account_source_id is None or r.period_start is None:
            continue
        if r.period_start >= period_start:
            revenue_24h[r.account_source_id] += r.revenue_cents
        else:
            revenue_prior[r.account_source_id] += r.revenue_cents

    msg_count: defaultdict[str, int] = defaultdict(int)
    paid_msg_count: defaultdict[str, int] = defaultdict(int)
    reply_minutes_by_chat: defaultdict[tuple[str, str], list[int]] = defaultdict(list)
    last_inbound_per_chat: dict[str, datetime] = {}
    operator_by_account: dict[str, str | None] = {}

    msg_rows = (
        await session.exec(
            select(OfIntelligenceMessage)
            .where(col(OfIntelligenceMessage.sent_at).is_not(None))
            .where(col(OfIntelligenceMessage.sent_at) >= period_start)
        )
    ).all()

    # Walk messages in chronological order so we can compute reply gaps
    # without ever loading the body into a Python string we could log.
    msg_rows_sorted = sorted(
        msg_rows, key=lambda m: m.sent_at  # type: ignore[arg-type, return-value]
    )
    for m in msg_rows_sorted:
        if m.account_source_id is None or m.sent_at is None:
            continue
        msg_count[m.account_source_id] += 1
        if (m.revenue_cents or 0) > 0:
            paid_msg_count[m.account_source_id] += 1
        if m.chatter_source_id and m.account_source_id not in operator_by_account:
            operator_by_account[m.account_source_id] = m.chatter_source_id

        # Reply-time tracking — fan inbound, then first outbound.
        chat_id = m.chat_source_id
        if chat_id is None:
            continue
        if m.direction == "in":
            last_inbound_per_chat[chat_id] = m.sent_at
        elif m.direction == "out" and chat_id in last_inbound_per_chat:
            gap_min = max(
                0,
                int((m.sent_at - last_inbound_per_chat[chat_id]).total_seconds() // 60),
            )
            reply_minutes_by_chat[(m.account_source_id, chat_id)].append(gap_min)
            del last_inbound_per_chat[chat_id]

    # Summarize reply medians per account.
    median_reply_by_account: dict[str, int | None] = {}
    grouped_per_account: defaultdict[str, list[int]] = defaultdict(list)
    for (acct_id, _chat_id), gaps in reply_minutes_by_chat.items():
        grouped_per_account[acct_id].extend(gaps)
    for acct_id, gaps in grouped_per_account.items():
        median_reply_by_account[acct_id] = int(statistics.median(gaps)) if gaps else None

    # Recent sync failures per account (any failed sync_log row in 24h).
    sync_log_rows = (
        await session.exec(
            select(OfIntelligenceSyncLog)
            .where(col(OfIntelligenceSyncLog.started_at).is_not(None))
            .where(col(OfIntelligenceSyncLog.started_at) >= period_start)
            .where(OfIntelligenceSyncLog.status == "error")
        )
    ).all()
    has_recent_sync_failure = bool(sync_log_rows)

    out: list[AccountMetrics] = []
    for a in accounts:
        prior_total = revenue_prior.get(a.source_id, 0)
        previous_avg = int(prior_total / max(DEFAULT_PRIOR_DAYS - 1, 1))
        out.append(
            AccountMetrics(
                account_id=a.source_id,
                account_label=a.username,
                period_start=period_start,
                period_end=period_end,
                revenue_cents=revenue_24h.get(a.source_id, 0),
                previous_revenue_cents=previous_avg,
                message_count=msg_count.get(a.source_id),
                paid_message_count=paid_msg_count.get(a.source_id),
                purchase_count=None,  # mass-message purchases not joined in v1
                median_reply_minutes=median_reply_by_account.get(a.source_id),
                operator_id=operator_by_account.get(a.source_id),
                source=SourceMode.LOCAL_OFI.value,
                source_confidence="medium" if msg_rows else "low",
                last_synced_at=a.last_synced_at,
                has_recent_sync_failure=has_recent_sync_failure,
            )
        )

    logger.info("of_qc.ingestion.local_ofi accounts=%s msg_rows=%s", len(out), len(msg_rows))
    return IngestionResult(
        source_mode=SourceMode.LOCAL_OFI,
        source_confidence="medium" if msg_rows else "low",
        safe_mode=True,
        accounts=out,
        skipped_reason=None,
        notes=[],
    )
