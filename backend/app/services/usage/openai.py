"""OpenAI usage collector — Admin API based, read-only.

Reads aggregated usage and cost from the OpenAI Admin API
(``GET /v1/organization/usage/completions`` and ``/v1/organization/costs``).

Never makes a chat or completion call — those would create spend.  If the
admin key (``OPENAI_ADMIN_KEY``) or org id (``OPENAI_ORG_ID``) is not
configured, returns a ``not_configured`` placeholder result.

Phase 1 stub: this module knows *how* to talk to the API but ships in
"skeleton" mode — the live HTTP call is intentionally gated on a real admin
key being present, and we ship without exercising it.  The collector
framework is what's being delivered here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.core.time import utcnow
from app.services.usage.base import CollectorResult

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)


PROVIDER = "openai"


async def collect(
    session: AsyncSession,
    *,
    window_hours: int = 24,
) -> CollectorResult:
    """Pull a recent-window snapshot from the OpenAI Admin API.

    Returns ``CollectorResult(status="not_configured")`` when admin
    credentials are missing — never raises, never makes an inference call.
    """
    from app.core.config import settings
    from app.core.secrets_store import get_secret_with_source

    admin_key, _src = await get_secret_with_source(
        session,
        "admin_key.openai",
        fallback=settings.openai_admin_key,
    )
    org_id = settings.openai_org_id.strip()

    end = utcnow()
    start = end - timedelta(hours=window_hours)

    if not admin_key.strip() or not org_id:
        missing = []
        if not admin_key.strip():
            missing.append("OPENAI_ADMIN_KEY")
        if not org_id:
            missing.append("OPENAI_ORG_ID")
        return CollectorResult(
            provider=PROVIDER,
            status="not_configured",
            source="placeholder",
            period_start=start,
            period_end=end,
            notes=[
                "Set " + " and ".join(missing) + " to enable live billing snapshots.",
                "OpenAI requires an Admin key (sk-admin-...) — this is different "
                "from the regular API key used for chat completions.",
            ],
        )

    # Phase 1: skeleton only.  Do not perform live HTTP calls until Phase 2
    # has been reviewed.  Returning a placeholder keeps refresh idempotent
    # and avoids any risk of making a billable call from this code path.
    logger.info("usage.openai.skeleton org_id_set=%s admin_key_set=true", bool(org_id))
    return CollectorResult(
        provider=PROVIDER,
        status="not_configured",
        source="placeholder",
        period_start=start,
        period_end=end,
        notes=[
            "OpenAI admin credentials present, but live collection is disabled "
            "in Phase 1.  Will be enabled after Phase 2 review.",
        ],
    )
