"""Usage / spend tracking service package.

Public surface:

* ``record_usage_event(...)`` — log one internal AI call (Phase 1 foundation;
  no agents wired yet).
* ``run_collectors(...)`` — refresh provider snapshots from external usage APIs.
* ``estimate_cost(...)`` — best-effort $ from token counts and a model name.

Per-provider collectors live in sibling modules and intentionally return a
``not_configured`` status when their admin credentials are absent — they must
never make billable inference calls.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from app.services.usage.logger import record_usage_event
from app.services.usage.pricing import estimate_cost

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.models.usage import UsageSnapshot
    from app.services.usage.base import CollectorResult

__all__ = ["estimate_cost", "record_usage_event", "run_collectors"]


async def run_collectors(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    persist: bool = True,
    window_hours: int = 24,
    only_provider: str | None = None,
) -> list[tuple[CollectorResult, UsageSnapshot | None]]:
    """Lazy-import wrapper around the real ``collector.run_collectors``.

    The package-level lazy import avoids a circular reference at startup
    (sibling submodules import via the parent package).  This wrapper's
    signature mirrors the real one in ``collector.py`` so callers get
    full type information at the import site.
    """
    from app.services.usage.collector import run_collectors as _impl

    return await _impl(
        session,
        organization_id=organization_id,
        persist=persist,
        window_hours=window_hours,
        only_provider=only_provider,
    )
