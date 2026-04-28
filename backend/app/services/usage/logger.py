"""Internal usage event logger — the single shared write path for AI calls.

Future agent / synthesizer / model-call code should call
``record_usage_event(...)`` after each AI call so the Usage Tracker can
account for it.  Phase 1 ships the function and schema; no callers wired yet.

Design intent:
* One function — easy to find with grep, easy to wrap.
* Best-effort: failures inside the logger never propagate to the caller.
  An AI call must not fail because we couldn't log it.
* Cost is auto-estimated from the local pricing table when not supplied.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.time import utcnow
from app.models.usage import UsageEvent
from app.services.usage.pricing import estimate_cost

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)


async def record_usage_event(
    session: AsyncSession,
    *,
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    estimated_cost_usd: float | None = None,
    organization_id: UUID | None = None,
    project: str | None = None,
    feature: str | None = None,
    agent_id: UUID | None = None,
    agent_name: str | None = None,
    status: str = "ok",
    error: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    trigger_source: str | None = None,
    environment: str | None = None,
    request_id: str | None = None,
) -> UsageEvent | None:
    """Persist one ``UsageEvent``.  Returns ``None`` on internal failure.

    Caller owns the session lifecycle.  We ``commit()`` here because callers
    typically want the event durable even if their own transaction rolls back
    afterwards (an inference call already happened — its cost shouldn't be
    forgotten).
    """
    try:
        start = started_at or utcnow()
        end = ended_at
        duration_ms: int | None = None
        if end is not None:
            duration_ms = int((end - start).total_seconds() * 1000)

        total = input_tokens + output_tokens
        cost = estimated_cost_usd
        if cost is None:
            cost = estimate_cost(
                model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

        event = UsageEvent(
            organization_id=organization_id,
            project=project,
            feature=feature,
            agent_id=agent_id,
            agent_name=agent_name,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
            estimated_cost_usd=cost,
            status=status,
            error=error,
            started_at=start,
            ended_at=end,
            duration_ms=duration_ms,
            trigger_source=trigger_source,
            environment=environment,
            request_id=request_id,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event
    except Exception as exc:  # noqa: BLE001 — best-effort logger
        logger.warning(
            "usage.record_event_failed provider=%s model=%s error=%s",
            provider,
            model,
            exc,
        )
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            pass
        return None
