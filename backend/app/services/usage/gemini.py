"""Gemini usage collector — placeholder.

Google does not (as of 2026-04-28) expose a public per-organization usage /
billing API for Gemini equivalent to OpenAI's Admin API or Anthropic's Usage
Report API.  Spend visibility for Gemini comes from the Google Cloud Billing
console.

For now the only route to track Gemini usage inside Mission Control is
recording each internal call via ``record_usage_event(...)``.  This collector
returns a clear ``not_configured`` placeholder so the UI can surface that
caveat.

When/if a public usage endpoint ships, this is the file to wire it into.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from app.core.time import utcnow
from app.services.usage.base import CollectorResult

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)


PROVIDER = "gemini"


async def collect(
    session: AsyncSession,
    *,
    window_hours: int = 24,
) -> CollectorResult:
    end = utcnow()
    start = end - timedelta(hours=window_hours)
    logger.debug("usage.gemini.placeholder")
    return CollectorResult(
        provider=PROVIDER,
        status="not_configured",
        source="placeholder",
        period_start=start,
        period_end=end,
        notes=[
            "Google does not yet expose a public Gemini usage/billing API. "
            "Track Gemini spend via internal usage events instead.",
        ],
    )
