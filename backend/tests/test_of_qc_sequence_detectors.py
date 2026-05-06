# ruff: noqa: INP001
"""Phase 2 sequence detectors — slow_response + missed_follow_up."""

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
from app.models.of_intelligence import OfIntelligenceMessage
from app.services.of_intelligence.qc.sequence_detectors import (
    DEFAULT_MISSED_FOLLOW_UP_WINDOW_MINUTES,
    DEFAULT_SLOW_RESPONSE_WINDOW_MINUTES,
    scan_missed_follow_up,
    scan_slow_response,
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


async def _seed(
    session: AsyncSession,
    *,
    direction: str,
    minutes_ago: int,
    chat: str = "chat-1",
    account: str = "acct-luna",
    chatter: str | None = "ch-mia",
    body: str | None = "hi",
) -> str:
    sid = f"m-{uuid4().hex[:8]}"
    session.add(
        OfIntelligenceMessage(
            source="onlymonster",
            source_id=sid,
            account_source_id=account,
            chat_source_id=chat,
            chatter_source_id=chatter,
            direction=direction,
            sent_at=utcnow() - timedelta(minutes=minutes_ago),
            body=body,
        )
    )
    await session.commit()
    return sid


# ── slow_response ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slow_response_fires_when_no_outbound_within_window() -> None:
    async with _make_session() as session:
        # Inbound 60 min ago, no outbound after.  Window default = 30 min.
        await _seed(session, direction="in", minutes_ago=60)
        cands = await scan_slow_response(session)
        assert any(c.code == "slow_response" for c in cands)


@pytest.mark.asyncio
async def test_slow_response_does_not_fire_when_outbound_within_window() -> None:
    async with _make_session() as session:
        await _seed(session, direction="in", minutes_ago=60, body="hey")
        await _seed(session, direction="out", minutes_ago=50, body="thanks!")
        cands = await scan_slow_response(session)
        assert not any(c.code == "slow_response" for c in cands)


@pytest.mark.asyncio
async def test_slow_response_does_not_fire_when_window_still_open() -> None:
    """An inbound 5 min ago must NOT trigger slow_response yet — the chatter
    still has time to reply within the 30-min window."""
    async with _make_session() as session:
        await _seed(session, direction="in", minutes_ago=5)
        cands = await scan_slow_response(session)
        assert not any(c.code == "slow_response" for c in cands)


@pytest.mark.asyncio
async def test_slow_response_resolves_prior_chatter_for_rollup() -> None:
    async with _make_session() as session:
        # A prior outbound on this chat carries the chatter id.
        await _seed(session, direction="out", minutes_ago=120, chatter="ch-mia")
        await _seed(session, direction="in", minutes_ago=60, chatter=None)
        cands = await scan_slow_response(session)
        slow = next(c for c in cands if c.code == "slow_response")
        assert slow.chatter_source_id == "ch-mia"


@pytest.mark.asyncio
async def test_slow_response_skips_already_seen_message_ids() -> None:
    async with _make_session() as session:
        msg_id = await _seed(session, direction="in", minutes_ago=60)
        cands = await scan_slow_response(session, seen_message_ids={msg_id})
        assert not any(c.code == "slow_response" for c in cands)


# ── missed_follow_up ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missed_follow_up_fires_on_buying_signal_with_no_response() -> None:
    async with _make_session() as session:
        await _seed(
            session,
            direction="in",
            minutes_ago=DEFAULT_MISSED_FOLLOW_UP_WINDOW_MINUTES + 30,
            body="how much for the menu?",
        )
        cands = await scan_missed_follow_up(session)
        assert any(c.code == "missed_follow_up" for c in cands)


@pytest.mark.asyncio
async def test_missed_follow_up_fires_on_objection_with_no_response() -> None:
    async with _make_session() as session:
        await _seed(
            session,
            direction="in",
            minutes_ago=DEFAULT_MISSED_FOLLOW_UP_WINDOW_MINUTES + 30,
            body="too expensive for me",
        )
        cands = await scan_missed_follow_up(session)
        assert any(c.code == "missed_follow_up" for c in cands)


@pytest.mark.asyncio
async def test_missed_follow_up_does_not_fire_on_low_intent_inbound() -> None:
    """A friendly hello with no buying-signal pattern should NOT trigger
    missed_follow_up — slow_response will catch it if needed, but
    missed_follow_up is reserved for high-intent moments."""
    async with _make_session() as session:
        await _seed(
            session,
            direction="in",
            minutes_ago=DEFAULT_MISSED_FOLLOW_UP_WINDOW_MINUTES + 30,
            body="hi babe how are you",
        )
        cands = await scan_missed_follow_up(session)
        assert not any(c.code == "missed_follow_up" for c in cands)


@pytest.mark.asyncio
async def test_missed_follow_up_does_not_fire_when_chatter_responded() -> None:
    async with _make_session() as session:
        await _seed(
            session,
            direction="in",
            minutes_ago=DEFAULT_MISSED_FOLLOW_UP_WINDOW_MINUTES + 30,
            body="how much",
        )
        await _seed(
            session,
            direction="out",
            minutes_ago=DEFAULT_MISSED_FOLLOW_UP_WINDOW_MINUTES + 10,
            body="my menu is $20",
        )
        cands = await scan_missed_follow_up(session)
        assert not any(c.code == "missed_follow_up" for c in cands)


@pytest.mark.asyncio
async def test_missed_follow_up_does_not_fire_when_window_still_open() -> None:
    async with _make_session() as session:
        # Inbound 10 min ago — still well inside the 60-min follow-up window.
        await _seed(session, direction="in", minutes_ago=10, body="how much")
        cands = await scan_missed_follow_up(session)
        assert not any(c.code == "missed_follow_up" for c in cands)


@pytest.mark.asyncio
async def test_sequence_candidates_do_not_carry_body_or_fan_handle() -> None:
    """Privacy: detector reads the body to match patterns but the candidate
    must contain only generic detection_phrase + safe ids."""
    body = "how much babe? @somefan said yes"
    async with _make_session() as session:
        await _seed(
            session,
            direction="in",
            minutes_ago=DEFAULT_SLOW_RESPONSE_WINDOW_MINUTES + 30,
            body=body,
        )
        slow_cands = await scan_slow_response(session)
        miss_cands = await scan_missed_follow_up(session)
        for c in (*slow_cands, *miss_cands):
            for forbidden in ("@somefan", body, "babe?"):
                assert forbidden not in c.detection_phrase
                assert forbidden not in c.code
                assert forbidden not in (c.chatter_source_id or "")
                assert forbidden not in (c.account_source_id or "")
