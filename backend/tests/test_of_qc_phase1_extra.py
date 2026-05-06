# ruff: noqa: INP001
"""Phase 1 follow-up: missed_buying_signal + weak_sales_handling detectors."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.of_intelligence import OfIntelligenceAccount, OfIntelligenceMessage
from app.services.of_intelligence.qc.detectors import scan_critical_qc


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


async def _seed(session: AsyncSession, body: str, direction: str) -> str:
    sid = f"acct-{uuid4().hex[:8]}"
    session.add(
        OfIntelligenceAccount(
            source="onlymonster", source_id=sid, username="luna_main", access_status="active"
        )
    )
    session.add(
        OfIntelligenceMessage(
            source="onlymonster",
            source_id=f"m-{uuid4().hex[:8]}",
            account_source_id=sid,
            direction=direction,
            sent_at=utcnow() - timedelta(minutes=5),
            body=body,
        )
    )
    await session.commit()
    return sid


# ── missed_buying_signal ────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        "how much for the menu?",
        "what does it cost",
        "can I buy that video",
        "send me more pics please",
        "any specials right now",
        "do you have a menu",
        "what's the price",
        "any deals going on",
    ],
)
async def test_missed_buying_signal_fires_inbound(body: str) -> None:
    async with _make_session() as session:
        await _seed(session, body, "in")
        cands = await scan_critical_qc(session)
        assert any(c.code == "missed_buying_signal" for c in cands)


@pytest.mark.asyncio
async def test_missed_buying_signal_does_not_fire_outbound() -> None:
    async with _make_session() as session:
        await _seed(session, "the price is $20", "out")
        cands = await scan_critical_qc(session)
        assert not any(c.code == "missed_buying_signal" for c in cands)


# ── weak_sales_handling ─────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        "too expensive",
        "i can't afford that",
        "i don't have money",
        "not right now",
        "maybe later",
        "i'll think about it",
        "no thanks",
        "out of my budget",
    ],
)
async def test_weak_sales_handling_fires_inbound(body: str) -> None:
    async with _make_session() as session:
        await _seed(session, body, "in")
        cands = await scan_critical_qc(session)
        assert any(c.code == "weak_sales_handling" for c in cands)


@pytest.mark.asyncio
async def test_weak_sales_handling_privacy_no_keyword_in_phrase() -> None:
    async with _make_session() as session:
        await _seed(session, "TOO EXPENSIVE for me", "in")
        cands = await scan_critical_qc(session)
        cand = next(c for c in cands if c.code == "weak_sales_handling")
        assert "TOO EXPENSIVE" not in cand.detection_phrase
        assert "TOO EXPENSIVE" not in cand.title
        assert cand.detection_phrase == "fan voiced an objection"
