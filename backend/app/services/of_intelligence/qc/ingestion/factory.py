"""Source-mode factory for the Daily QC ingestion layer.

Reads ``OfQcDiscordStatus.daily_qc_source_mode`` and the per-source
read-only enable flags, returns an ``IngestionResult``.

Defaults:
  • ``daily_qc_source_mode`` = ``synthetic``
  • ``onlymonster_readonly_enabled`` = ``False``  (off; v1 always returns
    a ``data_source_disconnected`` skip when the operator selects this
    mode without enabling the flag — and even when the flag is on, v1
    refuses because no read-only mock client wiring has been merged
    yet.  The skip ensures the scheduler still records audit rows.)
  • ``onlyfans_readonly_enabled``   = ``False``  (off; never enabled in v1)
  • ``platform_write_enabled``      = ``False``  (off; never enabled at all)
"""

from __future__ import annotations

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.models.of_qc_discord_status import OfQcDiscordStatus
from app.services.of_intelligence.qc.ingestion.base import (
    IngestionResult,
    SourceMode,
)
from app.services.of_intelligence.qc.ingestion.local_ofi import ingest_local_ofi
from app.services.of_intelligence.qc.ingestion.synthetic import ingest_synthetic

logger = get_logger(__name__)

_STATUS_ROW_ID = 1


async def ingest_for_status(session: AsyncSession) -> IngestionResult:
    """Pick the correct ingestion source for the current operator config."""
    row = await session.get(OfQcDiscordStatus, _STATUS_ROW_ID)
    raw_mode = getattr(row, "daily_qc_source_mode", None) if row is not None else None
    mode = SourceMode.coerce(raw_mode)

    if mode is SourceMode.SYNTHETIC:
        return await ingest_synthetic(session)

    if mode is SourceMode.LOCAL_OFI:
        return await ingest_local_ofi(session)

    if mode is SourceMode.ONLYMONSTER_READONLY:
        # Hard rule: even with onlymonster_readonly_enabled flipped on,
        # v1 returns a clear skip because no read-only client wiring is
        # merged yet.  This keeps the scheduler honest and the audit
        # trail informative.
        readonly = bool(row and getattr(row, "onlymonster_readonly_enabled", False))
        skipped = "data_source_disconnected" if readonly else "onlymonster_readonly_disabled"
        logger.info(
            "of_qc.ingestion.factory.skipped reason=%s mode=%s readonly_flag=%s",
            skipped,
            mode.value,
            readonly,
        )
        return IngestionResult(
            source_mode=mode,
            source_confidence="unknown",
            safe_mode=True,
            accounts=[],
            skipped_reason=skipped,
            notes=[
                "OnlyMonster read-only ingestion is off-by-default and "
                "no live wiring is merged in v1",
            ],
        )

    # Unknown mode — fall back to synthetic safely.
    logger.warning("of_qc.ingestion.factory.unknown_mode mode=%s", raw_mode)
    return await ingest_synthetic(session)
