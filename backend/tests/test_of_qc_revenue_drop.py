# ruff: noqa: INP001
"""Revenue-drop detector tests."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.of_intelligence import OfIntelligenceAccount, OfIntelligenceRevenue
from app.services.of_intelligence.qc.revenue import (
    ACCOUNT_REVENUE_DROP_CODE,
    detect_revenue_drops,
)


@contextlib.asynccontextmanager
async def _make_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with maker() as session:
            yield session
    finally:
        await engine.dispose()


async def _seed_account(session: AsyncSession, *, source_id: str, username: str) -> None:
    session.add(
        OfIntelligenceAccount(
            source="onlymonster",
            source_id=source_id,
            username=username,
            access_status="active",
        )
    )
    await session.commit()


async def _seed_revenue(
    session: AsyncSession,
    *,
    account_source_id: str,
    cents: int,
    period_start: datetime,
) -> None:
    session.add(
        OfIntelligenceRevenue(
            source="onlymonster",
            source_external_id=f"rv-{uuid4().hex[:8]}",
            account_source_id=account_source_id,
            period_start=period_start,
            period_end=period_start + timedelta(hours=1),
            revenue_cents=cents,
        )
    )
    await session.commit()


# ── 60% threshold ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_high_severity_when_24h_below_60_percent_of_avg() -> None:
    async with _make_session() as session:
        await _seed_account(session, source_id="acct-1", username="luna")
        # 6 prior days, $100/day = 60000 cents/day total = 60000 / 6 = 10000 avg.
        for i in range(1, 7):
            await _seed_revenue(
                session,
                account_source_id="acct-1",
                cents=10000,
                period_start=utcnow() - timedelta(days=i, hours=12),
            )
        # 24h = 5000 (50% of avg) → fires high.
        await _seed_revenue(
            session,
            account_source_id="acct-1",
            cents=5000,
            period_start=utcnow() - timedelta(hours=12),
        )
        warnings = await detect_revenue_drops(session)
        assert len(warnings) == 1
        assert warnings[0].severity == "high"
        assert warnings[0].account_source_id == "acct-1"


@pytest.mark.asyncio
async def test_does_not_fire_when_24h_above_threshold() -> None:
    async with _make_session() as session:
        await _seed_account(session, source_id="acct-1", username="luna")
        for i in range(1, 7):
            await _seed_revenue(
                session,
                account_source_id="acct-1",
                cents=10000,
                period_start=utcnow() - timedelta(days=i, hours=12),
            )
        # 24h = 9000 (90% of avg) → no fire.
        await _seed_revenue(
            session,
            account_source_id="acct-1",
            cents=9000,
            period_start=utcnow() - timedelta(hours=12),
        )
        warnings = await detect_revenue_drops(session)
        assert warnings == []


# ── Zero 24h with prior history → medium ───────────────────────────────────


@pytest.mark.asyncio
async def test_zero_24h_with_prior_history_emits_medium() -> None:
    async with _make_session() as session:
        await _seed_account(session, source_id="acct-1", username="luna")
        for i in range(1, 7):
            await _seed_revenue(
                session,
                account_source_id="acct-1",
                cents=10000,
                period_start=utcnow() - timedelta(days=i),
            )
        warnings = await detect_revenue_drops(session)
        assert len(warnings) == 1
        assert warnings[0].severity == "medium"
        assert warnings[0].revenue_24h_cents == 0
        assert warnings[0].revenue_7d_avg_cents > 0
        assert "zero" in warnings[0].reason.lower()


# ── Brand new accounts skipped ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_brand_new_account_with_no_prior_history_does_not_fire() -> None:
    async with _make_session() as session:
        await _seed_account(session, source_id="acct-new", username="new")
        # Only 24h revenue, zero prior history → cannot judge → skip.
        await _seed_revenue(
            session,
            account_source_id="acct-new",
            cents=0,
            period_start=utcnow() - timedelta(hours=12),
        )
        warnings = await detect_revenue_drops(session)
        assert warnings == []


@pytest.mark.asyncio
async def test_zero_24h_zero_prior_does_not_fire() -> None:
    async with _make_session() as session:
        await _seed_account(session, source_id="acct-empty", username="empty")
        warnings = await detect_revenue_drops(session)
        assert warnings == []


# ── Per-account independence ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_only_unhealthy_accounts_get_warnings() -> None:
    async with _make_session() as session:
        await _seed_account(session, source_id="acct-good", username="good")
        await _seed_account(session, source_id="acct-bad", username="bad")
        for i in range(1, 7):
            await _seed_revenue(
                session, account_source_id="acct-good", cents=10000,
                period_start=utcnow() - timedelta(days=i),
            )
            await _seed_revenue(
                session, account_source_id="acct-bad", cents=10000,
                period_start=utcnow() - timedelta(days=i),
            )
        await _seed_revenue(
            session, account_source_id="acct-good", cents=12000,
            period_start=utcnow() - timedelta(hours=6),
        )
        # bad: zero 24h
        warnings = await detect_revenue_drops(session)
        ids = {w.account_source_id for w in warnings}
        assert ids == {"acct-bad"}


# ── Privacy ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_warning_has_no_raw_breakdown_or_payload() -> None:
    async with _make_session() as session:
        await _seed_account(session, source_id="acct-1", username="luna")
        for i in range(1, 7):
            await _seed_revenue(
                session, account_source_id="acct-1", cents=10000,
                period_start=utcnow() - timedelta(days=i),
            )
        warnings = await detect_revenue_drops(session)
        # The warning is a dataclass — only the privacy-safe fields exist.
        w = warnings[0]
        for forbidden in ("@somefan", "<HTTP", "Bearer ", "https://api"):
            assert forbidden not in w.reason
            assert forbidden not in (w.username or "")
        # Detector does NOT pass raw `breakdown` or `raw` JSON anywhere.
        assert not hasattr(w, "raw")
        assert not hasattr(w, "breakdown")


# ── Code constant pinned (alerts.py + dispatch.py rely on it) ──────────────


def test_account_revenue_drop_code_constant() -> None:
    assert ACCOUNT_REVENUE_DROP_CODE == "account_revenue_drop"
