"""Collector orchestrator — runs all provider collectors and persists results.

Single entry point ``run_collectors(session)`` is invoked by:
* The manual ``POST /api/v1/usage/refresh`` endpoint (Phase 1).
* A future scheduled job (Phase 3 — not wired yet).

Each collector is independent: a failure or ``not_configured`` from one
provider does not block the others.  Every result becomes a row in
``usage_snapshots`` so the UI can show ``last_status`` and ``last_error`` per
provider.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from app.core.time import utcnow
from app.models.usage import UsageSnapshot
from app.services.usage import anthropic as anthropic_collector
from app.services.usage import gemini as gemini_collector
from app.services.usage import internal as internal_collector
from app.services.usage import openai as openai_collector
from app.services.usage.base import CollectorResult

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

PROVIDERS = ("openai", "anthropic", "gemini", "internal")


async def _run_one(
    name: str,
    session: AsyncSession,
    *,
    organization_id: UUID | None,
    window_hours: int,
) -> CollectorResult:
    try:
        if name == "openai":
            return await openai_collector.collect(session, window_hours=window_hours)
        if name == "anthropic":
            return await anthropic_collector.collect(session, window_hours=window_hours)
        if name == "gemini":
            return await gemini_collector.collect(session, window_hours=window_hours)
        if name == "internal":
            return await internal_collector.collect(
                session,
                window_hours=window_hours,
                organization_id=organization_id,
            )
    except Exception as exc:  # noqa: BLE001 — collectors should not raise
        logger.exception("usage.collector_unhandled provider=%s", name)
        return CollectorResult(
            provider=name,
            status="error",
            source="placeholder",
            error=f"unhandled: {exc!r}",
        )
    return CollectorResult(
        provider=name, status="error", source="placeholder", error="unknown collector"
    )


async def run_collectors(
    session: AsyncSession,
    *,
    organization_id: UUID | None = None,
    persist: bool = True,
    window_hours: int = 24,
) -> list[tuple[CollectorResult, UsageSnapshot | None]]:
    """Run every provider collector and (optionally) persist a snapshot row.

    ``window_hours`` controls how far back each collector reaches.  The route
    layer is responsible for validating the value against an allowlist before
    invoking this function — collectors trust the value.

    Returns a list of ``(result, snapshot_or_none)`` pairs in ``PROVIDERS``
    order.  ``snapshot_or_none`` is ``None`` only when ``persist=False``.
    """
    output: list[tuple[CollectorResult, UsageSnapshot | None]] = []
    for name in PROVIDERS:
        result = await _run_one(
            name,
            session,
            organization_id=organization_id,
            window_hours=window_hours,
        )
        snapshot: UsageSnapshot | None = None
        if persist:
            snapshot = UsageSnapshot(
                organization_id=organization_id,
                provider=result.provider,
                captured_at=utcnow(),
                period_start=result.period_start or utcnow(),
                period_end=result.period_end or utcnow(),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.total_tokens
                or (result.input_tokens + result.output_tokens),
                requests=result.requests,
                cost_usd=result.cost_usd,
                source=result.source,
                status=result.status,
                # Notes are sentence-cased and end in periods, so a plain
                # space joins them into readable prose for the UI's
                # last_error / placeholder-hint slot.
                error=result.error or (" ".join(result.notes) if result.notes else None),
                raw=result.raw,
            )
            session.add(snapshot)
        output.append((result, snapshot))

    if persist:
        try:
            await session.commit()
            for _, snap in output:
                if snap is not None:
                    await session.refresh(snap)
        except Exception:
            await session.rollback()
            raise

    return output
