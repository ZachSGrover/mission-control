"""Anthropic usage collector — Admin API based, read-only.

Reads aggregated message usage from the Anthropic Admin API
(``GET /v1/organizations/usage_report/messages``) using an admin key
(``sk-ant-admin01-...``) — distinct from the regular ``ANTHROPIC_API_KEY``
used for inference.

Never makes an inference call.  Returns ``not_configured`` when admin
credentials are missing.

Phase 1 ships the wiring; the live HTTP call stays gated until Phase 2.
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


PROVIDER = "anthropic"


async def collect(
    session: AsyncSession,
    *,
    window_hours: int = 24,
) -> CollectorResult:
    from app.core.config import settings
    from app.core.secrets_store import get_secret_with_source

    admin_key, _src = await get_secret_with_source(
        session,
        "admin_key.anthropic",
        fallback=settings.anthropic_admin_key,
    )
    org_id = settings.anthropic_org_id.strip()

    end = utcnow()
    start = end - timedelta(hours=window_hours)

    if not admin_key.strip() or not org_id:
        missing = []
        if not admin_key.strip():
            missing.append("ANTHROPIC_ADMIN_KEY")
        if not org_id:
            missing.append("ANTHROPIC_ORG_ID")
        return CollectorResult(
            provider=PROVIDER,
            status="not_configured",
            source="placeholder",
            period_start=start,
            period_end=end,
            notes=[
                "Set " + " and ".join(missing) + " to enable live billing snapshots.",
                "Anthropic admin keys are issued separately from regular API keys "
                "and require Console > Settings > Admin keys.",
            ],
        )

    logger.info("usage.anthropic.skeleton org_id_set=true admin_key_set=true")
    return CollectorResult(
        provider=PROVIDER,
        status="not_configured",
        source="placeholder",
        period_start=start,
        period_end=end,
        notes=[
            "Anthropic admin credentials present, but live collection is "
            "disabled in Phase 1.  Will be enabled after Phase 2 review.",
        ],
    )
