"""Internal usage collector — aggregates ``UsageEvent`` rows into a snapshot.

Unlike the external provider collectors, this one never talks to a third
party.  It rolls up rows already written to ``usage_events`` (by future
agent code calling ``record_usage_event``) into a single snapshot for the
recent window so the UI can show "internal calls" alongside provider totals.

Reading from the events log is always safe: it's a local DB query.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func
from sqlmodel import col, select

from app.core.time import utcnow
from app.models.usage import UsageEvent
from app.services.usage.base import CollectorResult

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)


PROVIDER = "internal"


async def collect(
    session: AsyncSession,
    *,
    window_hours: int = 24,
    organization_id: UUID | None = None,
) -> CollectorResult:
    end = utcnow()
    start = end - timedelta(hours=window_hours)

    # mypy can't pick a select() overload for a 5-aggregate projection.
    # ``col(UsageEvent.id)`` fixes the count argument type; the remaining
    # heterogeneous-tuple overload-resolution gap is a known SQLAlchemy
    # / sqlmodel typing limitation we narrowly suppress here.
    stmt = select(  # type: ignore[call-overload]
        func.coalesce(func.sum(UsageEvent.input_tokens), 0),
        func.coalesce(func.sum(UsageEvent.output_tokens), 0),
        func.coalesce(func.sum(UsageEvent.total_tokens), 0),
        func.coalesce(func.sum(UsageEvent.estimated_cost_usd), 0.0),
        func.count(col(UsageEvent.id)),
    ).where(UsageEvent.started_at >= start, UsageEvent.started_at < end)
    if organization_id is not None:
        stmt = stmt.where(UsageEvent.organization_id == organization_id)

    result = (await session.exec(stmt)).first()
    if result is None:
        in_tok = out_tok = total_tok = req = 0
        cost = 0.0
    else:
        in_tok, out_tok, total_tok, cost, req = result

    return CollectorResult(
        provider=PROVIDER,
        status="ok",
        source="live",
        period_start=start,
        period_end=end,
        input_tokens=int(in_tok or 0),
        output_tokens=int(out_tok or 0),
        total_tokens=int(total_tok or 0),
        requests=int(req or 0),
        cost_usd=float(cost or 0.0),
        notes=[
            "Aggregated from internal usage_events.  Will be empty until "
            "agent / synthesizer code starts calling record_usage_event().",
        ],
    )
