# ruff: noqa: INP001
"""Critical-QC detector tests.

Pins the keyword-match ↔ direction contract and verifies the candidate
output never carries the matched keyword or message body.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Iterable
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.of_intelligence import (
    OfIntelligenceAccount,
    OfIntelligenceChatter,
    OfIntelligenceMessage,
)
from app.services.of_intelligence.qc.detectors import (
    CriticalQcCandidate,
    scan_critical_qc,
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


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _seed_account(session: AsyncSession, *, username: str) -> str:
    sid = f"acct-{uuid4().hex[:8]}"
    session.add(
        OfIntelligenceAccount(
            source="onlymonster",
            source_id=sid,
            username=username,
            access_status="active",
        )
    )
    await session.commit()
    return sid


async def _seed_chatter(session: AsyncSession, *, name: str) -> str:
    sid = f"ch-{uuid4().hex[:8]}"
    session.add(
        OfIntelligenceChatter(
            source="onlymonster",
            source_id=sid,
            name=name,
            active=True,
        )
    )
    await session.commit()
    return sid


async def _seed_message(
    session: AsyncSession,
    *,
    body: str,
    direction: str,
    account_source_id: str | None = None,
    chatter_source_id: str | None = None,
    minutes_ago: int = 5,
) -> None:
    session.add(
        OfIntelligenceMessage(
            source="onlymonster",
            source_id=f"msg-{uuid4().hex[:10]}",
            account_source_id=account_source_id,
            chatter_source_id=chatter_source_id,
            direction=direction,
            sent_at=utcnow() - timedelta(minutes=minutes_ago),
            body=body,
        )
    )
    await session.commit()


def _codes(candidates: Iterable[CriticalQcCandidate]) -> list[str]:
    return sorted(c.code for c in candidates)


# ── refund_risk (inbound only) ─────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        "I want a refund right now",
        "I'm gonna chargeback this",
        "filing a charge-back",
        "I dispute this charge",
        "cancelling my subscription",
        "I'll report you to OF",
        "this is a scam",
        "fraud!",
        "I'll get a lawyer",
        "legal action incoming",
    ],
)
async def test_refund_risk_fires_on_inbound_match(body: str) -> None:
    async with _make_session() as session:
        acct = await _seed_account(session, username="luna_main")
        await _seed_message(session, body=body, direction="in", account_source_id=acct)

        cands = await scan_critical_qc(session)
        assert "refund_risk" in _codes(cands)


@pytest.mark.asyncio
async def test_refund_risk_does_not_fire_on_outbound() -> None:
    """Even if the outbound contains the keyword, refund_risk should not
    fire — it's an inbound-only category."""
    async with _make_session() as session:
        acct = await _seed_account(session, username="luna_main")
        await _seed_message(
            session,
            body="If you want a refund, please open a support ticket",
            direction="out",
            account_source_id=acct,
        )
        cands = await scan_critical_qc(session)
        assert "refund_risk" not in _codes(cands)


# ── banned_content_risk (outbound only) ────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    ["minor in scope", "underage post", "talking under 18", "carrying a weapon"],
)
async def test_banned_content_fires_on_outbound_match(body: str) -> None:
    async with _make_session() as session:
        acct = await _seed_account(session, username="luna_main")
        ch = await _seed_chatter(session, name="Mia")
        await _seed_message(
            session,
            body=body,
            direction="out",
            account_source_id=acct,
            chatter_source_id=ch,
        )
        cands = await scan_critical_qc(session)
        assert "banned_content_risk" in _codes(cands)


@pytest.mark.asyncio
async def test_banned_content_does_not_fire_on_inbound() -> None:
    """A fan saying a banned term doesn't flag the chatter — direction-checked."""
    async with _make_session() as session:
        acct = await _seed_account(session, username="luna_main")
        await _seed_message(
            session, body="minor", direction="in", account_source_id=acct
        )
        cands = await scan_critical_qc(session)
        assert "banned_content_risk" not in _codes(cands)


# ── rude_reply (outbound only) ─────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        "shut up already",
        "shutup",
        "fuck off",
        "f u c k off",
        "stfu",
        "you're an idiot",
        "stupid loser",
        "go away",
    ],
)
async def test_rude_reply_fires_on_outbound_match(body: str) -> None:
    async with _make_session() as session:
        acct = await _seed_account(session, username="luna_main")
        ch = await _seed_chatter(session, name="Sam")
        await _seed_message(
            session,
            body=body,
            direction="out",
            account_source_id=acct,
            chatter_source_id=ch,
        )
        cands = await scan_critical_qc(session)
        assert "rude_reply" in _codes(cands)


@pytest.mark.asyncio
async def test_rude_reply_does_not_fire_on_inbound() -> None:
    """If the fan is rude, that's not a chatter QC issue; direction enforced."""
    async with _make_session() as session:
        acct = await _seed_account(session, username="luna_main")
        await _seed_message(
            session, body="you're an idiot", direction="in", account_source_id=acct
        )
        cands = await scan_critical_qc(session)
        assert "rude_reply" not in _codes(cands)


# ── serious_escalation_risk (inbound only) ─────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        "I'm calling the police",
        "I'll report you to the FBI",
        "I want to kill myself",
        "thinking about suicide",
        "this is trafficking",
        "abuse allegations",
    ],
)
async def test_escalation_fires_on_inbound_match(body: str) -> None:
    async with _make_session() as session:
        acct = await _seed_account(session, username="luna_main")
        await _seed_message(session, body=body, direction="in", account_source_id=acct)
        cands = await scan_critical_qc(session)
        assert "serious_escalation_risk" in _codes(cands)


# ── Negative cases ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clean_messages_produce_no_candidates() -> None:
    async with _make_session() as session:
        acct = await _seed_account(session, username="luna_main")
        await _seed_message(
            session, body="hey thanks for subscribing!", direction="out",
            account_source_id=acct,
        )
        await _seed_message(
            session, body="love you", direction="in", account_source_id=acct,
        )
        cands = await scan_critical_qc(session)
        assert cands == []


@pytest.mark.asyncio
async def test_messages_outside_lookback_window_are_skipped() -> None:
    async with _make_session() as session:
        acct = await _seed_account(session, username="luna_main")
        await _seed_message(
            session,
            body="refund please",
            direction="in",
            account_source_id=acct,
            minutes_ago=120,  # 2 hours ago — outside default 1h window
        )
        cands = await scan_critical_qc(session)
        assert cands == []


# ── Privacy: candidate output never carries matched keyword or body ────────


@pytest.mark.asyncio
async def test_candidate_does_not_include_matched_keyword_or_body() -> None:
    async with _make_session() as session:
        acct = await _seed_account(session, username="luna_main")
        ch = await _seed_chatter(session, name="Mia")
        body_with_keyword = (
            "Sure babe, I'll give you a REFUND if you want — also @somefan said hi"
        )
        await _seed_message(
            session,
            body=body_with_keyword,
            direction="in",
            account_source_id=acct,
            chatter_source_id=ch,
        )
        cands = await scan_critical_qc(session)
        assert len(cands) == 1
        c = cands[0]
        # Title is allowed to use the account display name only.
        assert c.account_username == "luna_main"
        assert c.chatter_name == "Mia"
        # detection_phrase is the generic category name; the matched
        # keyword's casing from the body and any contextual clutter are
        # what matter for privacy.
        assert c.detection_phrase == "refund-language detected"
        # The body's exact casing of the keyword + the fan handle + the
        # full body must never appear in any candidate field.
        forbidden = ["REFUND", "@somefan", body_with_keyword, "Sure babe"]
        for field in (
            c.title,
            c.detection_phrase,
            c.account_username or "",
            c.chatter_name or "",
        ):
            for needle in forbidden:
                assert needle not in field


# ── Per-(code, account) dedup within a single scan ─────────────────────────


@pytest.mark.asyncio
async def test_multiple_matches_same_account_collapse_to_one_candidate_per_code() -> None:
    async with _make_session() as session:
        acct = await _seed_account(session, username="luna_main")
        for body in ["refund please", "I want my refund", "filing a chargeback"]:
            await _seed_message(
                session, body=body, direction="in", account_source_id=acct
            )
        cands = await scan_critical_qc(session)
        refund_cands = [c for c in cands if c.code == "refund_risk"]
        assert len(refund_cands) == 1
