# ruff: noqa: INP001
"""Phase 2: chatter findings detectors + persistence."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.of_intelligence import OfIntelligenceMessage
from app.models.of_qc_finding import OfIntelligenceQcFinding
from app.services.of_intelligence.qc.chatter_findings import (
    persist_findings,
    scan_chatter_findings,
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


async def _seed_outbound(
    session: AsyncSession,
    body: str,
    *,
    chatter: str | None = "ch-mia",
    account: str | None = "acct-luna",
) -> str:
    msg_id = f"m-{uuid4().hex[:10]}"
    session.add(
        OfIntelligenceMessage(
            source="onlymonster",
            source_id=msg_id,
            account_source_id=account,
            chatter_source_id=chatter,
            direction="out",
            sent_at=utcnow() - timedelta(minutes=3),
            body=body,
        )
    )
    await session.commit()
    return msg_id


# ── lazy_reply ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["k", "ok", "lol", "ya", "haha"])
async def test_lazy_reply_fires_on_short_outbound(body: str) -> None:
    async with _make_session() as session:
        await _seed_outbound(session, body)
        cands = await scan_chatter_findings(session)
        assert any(c.code == "lazy_reply" for c in cands)


@pytest.mark.asyncio
async def test_lazy_reply_does_not_fire_for_real_reply() -> None:
    async with _make_session() as session:
        await _seed_outbound(
            session, "hey babe! how was your day? i was thinking of you", chatter="ch-x"
        )
        cands = await scan_chatter_findings(session)
        assert not any(c.code == "lazy_reply" for c in cands)


# ── low_effort_chatting ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_low_effort_chatting_fires_for_short_no_question() -> None:
    async with _make_session() as session:
        await _seed_outbound(session, "thanks babe really sweet")
        cands = await scan_chatter_findings(session)
        assert any(c.code == "low_effort_chatting" for c in cands)


@pytest.mark.asyncio
async def test_low_effort_does_not_fire_when_question_present() -> None:
    async with _make_session() as session:
        await _seed_outbound(session, "thanks babe how was your day?")
        cands = await scan_chatter_findings(session)
        assert not any(c.code == "low_effort_chatting" for c in cands)


# ── bad_english ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        "i recieve your gift thanks alot",
        "i would of definately came",
        "u r so cute u r amazing u r the best",  # 3+ shorthand tokens
    ],
)
async def test_bad_english_fires_on_typos(body: str) -> None:
    async with _make_session() as session:
        await _seed_outbound(session, body)
        cands = await scan_chatter_findings(session)
        assert any(c.code == "bad_english" for c in cands)


@pytest.mark.asyncio
async def test_bad_english_does_not_fire_on_clean_text() -> None:
    async with _make_session() as session:
        await _seed_outbound(session, "thanks for subscribing, hope you enjoy the content")
        cands = await scan_chatter_findings(session)
        assert not any(c.code == "bad_english" for c in cands)


# ── inbound never produces chatter findings ────────────────────────────────


@pytest.mark.asyncio
async def test_inbound_messages_do_not_produce_chatter_findings() -> None:
    async with _make_session() as session:
        msg_id = f"m-{uuid4().hex[:10]}"
        session.add(
            OfIntelligenceMessage(
                source="onlymonster",
                source_id=msg_id,
                account_source_id="acct-luna",
                chatter_source_id=None,
                direction="in",
                sent_at=utcnow(),
                body="k",  # would trigger lazy_reply if outbound
            )
        )
        await session.commit()
        cands = await scan_chatter_findings(session)
        assert cands == []


# ── persistence + idempotency ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_persist_findings_writes_rows() -> None:
    async with _make_session() as session:
        await _seed_outbound(session, "k")
        cands = await scan_chatter_findings(session)
        n = await persist_findings(session, cands)
        assert n >= 1
        rows = (await session.exec(select(OfIntelligenceQcFinding))).all()
        assert len(rows) == n


@pytest.mark.asyncio
async def test_scan_skips_messages_already_having_findings() -> None:
    async with _make_session() as session:
        msg_id = await _seed_outbound(session, "k")
        cands = await scan_chatter_findings(session)
        await persist_findings(session, cands)

        # Re-scan should not re-emit candidates for the same message_source_id.
        cands2 = await scan_chatter_findings(session)
        assert all(c.message_source_id != msg_id for c in cands2)


# ── privacy: no body / fan handle on the persisted row ─────────────────────


@pytest.mark.asyncio
async def test_finding_row_does_not_carry_message_body_or_fan_handle() -> None:
    async with _make_session() as session:
        body = "k @somefan"
        await _seed_outbound(session, body)
        cands = await scan_chatter_findings(session)
        await persist_findings(session, cands)
        rows = (await session.exec(select(OfIntelligenceQcFinding))).all()
        assert rows
        for r in rows:
            for field in (r.detection_phrase, r.code, r.severity):
                assert "@somefan" not in field
                assert body not in field
