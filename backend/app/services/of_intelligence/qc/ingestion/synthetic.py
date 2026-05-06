"""Synthetic ingestion source — deterministic fixture, always safe.

Used when ``daily_qc_source_mode == "synthetic"`` (default) and by every
sandbox / unit-test path.  Returns a fixed-shape ``IngestionResult`` with
two demo accounts: one healthy, one with a revenue drop.

NEVER reads the database.  NEVER calls external APIs.  NEVER touches
fan or message data.
"""

from __future__ import annotations

from datetime import timedelta

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.services.of_intelligence.qc.ingestion.base import (
    AccountMetrics,
    IngestionResult,
    SourceMode,
)

logger = get_logger(__name__)


async def ingest_synthetic(_session: AsyncSession) -> IngestionResult:
    """Deterministic synthetic snapshot — two demo accounts."""
    now = utcnow()
    period_end = now
    period_start = now - timedelta(hours=24)

    accounts = [
        AccountMetrics(
            account_id="synthetic-luna",
            account_label="luna_demo",
            period_start=period_start,
            period_end=period_end,
            revenue_cents=12_000,
            previous_revenue_cents=15_000,
            message_count=42,
            paid_message_count=6,
            purchase_count=3,
            median_reply_minutes=4,
            operator_id="synthetic-mia",
            source=SourceMode.SYNTHETIC.value,
            source_confidence="high",
            last_synced_at=now - timedelta(minutes=20),
            has_recent_sync_failure=False,
        ),
        AccountMetrics(
            account_id="synthetic-indigo",
            account_label="indigo_demo",
            period_start=period_start,
            period_end=period_end,
            revenue_cents=0,  # ← drop scenario
            previous_revenue_cents=22_000,
            message_count=8,
            paid_message_count=0,
            purchase_count=0,
            median_reply_minutes=18,
            operator_id="synthetic-sam",
            source=SourceMode.SYNTHETIC.value,
            source_confidence="high",
            last_synced_at=now - timedelta(hours=8),
            has_recent_sync_failure=False,
        ),
    ]
    logger.info("of_qc.ingestion.synthetic accounts=%s", len(accounts))
    return IngestionResult(
        source_mode=SourceMode.SYNTHETIC,
        source_confidence="high",
        safe_mode=True,
        accounts=accounts,
        skipped_reason=None,
        notes=["synthetic seeded fixture; no real data"],
    )
