# ruff: noqa: INP001
"""Daily QC read-only ingestion tests — synthetic + local_ofi + privacy."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.of_intelligence import (
    OfIntelligenceAccount,
    OfIntelligenceMessage,
    OfIntelligenceRevenue,
)
from app.models.of_qc_discord_status import OfQcDiscordStatus
from app.services.of_intelligence.qc.ingestion import (
    SourceMode,
    ingest_for_status,
    ingest_local_ofi,
    ingest_synthetic,
)
from app.services.of_intelligence.qc.ingestion_evaluator import evaluate_ingestion


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


# ── Synthetic source ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_synthetic_source_returns_two_demo_accounts() -> None:
    async with _make_session() as session:
        result = await ingest_synthetic(session)
        assert result.source_mode is SourceMode.SYNTHETIC
        assert result.safe_mode is True
        assert result.skipped_reason is None
        assert len(result.accounts) == 2
        labels = {a.account_label for a in result.accounts}
        assert labels == {"luna_demo", "indigo_demo"}


@pytest.mark.asyncio
async def test_synthetic_source_does_not_query_db(monkeypatch: pytest.MonkeyPatch) -> None:
    """Synthetic source must never touch the session — fail loud if it does."""

    async def _explode(*_a: Any, **_kw: Any) -> object:
        raise AssertionError("synthetic source must not call session.exec()")

    async with _make_session() as session:
        monkeypatch.setattr(session, "exec", _explode)
        result = await ingest_synthetic(session)
        assert len(result.accounts) == 2


# ── Local OFI source ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_local_ofi_source_returns_skipped_when_no_accounts() -> None:
    async with _make_session() as session:
        result = await ingest_local_ofi(session)
        assert result.source_mode is SourceMode.LOCAL_OFI
        assert result.skipped_reason == "no_local_ofi_data"
        assert result.accounts == []


@pytest.mark.asyncio
async def test_local_ofi_source_aggregates_real_rows() -> None:
    async with _make_session() as session:
        now = utcnow()
        session.add(
            OfIntelligenceAccount(
                source="onlymonster",
                source_id="acct-1",
                username="luna_real",
                last_synced_at=now - timedelta(minutes=10),
            )
        )
        for i in range(7):
            session.add(
                OfIntelligenceRevenue(
                    source="onlymonster",
                    source_external_id=f"rv-{uuid4().hex[:6]}",
                    account_source_id="acct-1",
                    period_start=now - timedelta(days=i, hours=12),
                    period_end=now - timedelta(days=i, hours=11),
                    revenue_cents=10_000,
                )
            )
        # A few inbound + outbound messages for reply-time computation.
        session.add(
            OfIntelligenceMessage(
                source="onlymonster",
                source_id=f"m-{uuid4().hex[:6]}",
                account_source_id="acct-1",
                chat_source_id="chat-1",
                direction="in",
                sent_at=now - timedelta(hours=2),
                body="ignored",  # body must NOT leak to AccountMetrics
            )
        )
        session.add(
            OfIntelligenceMessage(
                source="onlymonster",
                source_id=f"m-{uuid4().hex[:6]}",
                account_source_id="acct-1",
                chat_source_id="chat-1",
                chatter_source_id="ch-mia",
                direction="out",
                sent_at=now - timedelta(hours=2) + timedelta(minutes=8),
                body="ignored",
                revenue_cents=500,
            )
        )
        await session.commit()

        result = await ingest_local_ofi(session)
        assert result.source_mode is SourceMode.LOCAL_OFI
        assert result.skipped_reason is None
        assert len(result.accounts) == 1
        m = result.accounts[0]
        assert m.account_label == "luna_real"
        assert m.message_count == 2
        assert m.paid_message_count == 1
        assert m.median_reply_minutes == 8
        assert m.operator_id == "ch-mia"


@pytest.mark.asyncio
async def test_local_ofi_does_not_carry_message_bodies_or_fan_handles() -> None:
    """AccountMetrics dataclass has no body / fan fields — pin the contract."""
    async with _make_session() as session:
        now = utcnow()
        session.add(
            OfIntelligenceAccount(
                source="onlymonster",
                source_id="acct-1",
                username="luna_real",
                last_synced_at=now,
            )
        )
        session.add(
            OfIntelligenceMessage(
                source="onlymonster",
                source_id="m-1",
                account_source_id="acct-1",
                fan_source_id="fan-private-001",
                chat_source_id="chat-1",
                direction="in",
                sent_at=now,
                body="this body must never leak",
            )
        )
        await session.commit()

        result = await ingest_local_ofi(session)
        for m in result.accounts:
            payload = repr(m)
            for forbidden in (
                "this body must never leak",
                "fan-private-001",
                "ignored",
            ):
                assert forbidden not in payload


# ── Factory + defaults ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_factory_defaults_to_synthetic_when_no_status_row() -> None:
    async with _make_session() as session:
        result = await ingest_for_status(session)
        assert result.source_mode is SourceMode.SYNTHETIC
        assert result.skipped_reason is None


@pytest.mark.asyncio
async def test_factory_uses_local_ofi_when_status_row_says_so() -> None:
    async with _make_session() as session:
        session.add(
            OfQcDiscordStatus(
                id=1,
                daily_qc_source_mode="local_ofi",
            )
        )
        await session.commit()
        result = await ingest_for_status(session)
        assert result.source_mode is SourceMode.LOCAL_OFI
        assert result.skipped_reason == "no_local_ofi_data"  # empty DB


@pytest.mark.asyncio
async def test_factory_skips_onlymonster_readonly_when_flag_off() -> None:
    async with _make_session() as session:
        session.add(
            OfQcDiscordStatus(
                id=1,
                daily_qc_source_mode="onlymonster_readonly",
                onlymonster_readonly_enabled=False,
            )
        )
        await session.commit()
        result = await ingest_for_status(session)
        assert result.source_mode is SourceMode.ONLYMONSTER_READONLY
        assert result.skipped_reason == "onlymonster_readonly_disabled"
        assert result.accounts == []


@pytest.mark.asyncio
async def test_factory_skips_onlymonster_readonly_even_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V1: even with the flag on, no live wiring exists; factory returns
    a clear ``data_source_disconnected`` skip."""
    # Network calls would blow up the test if any source actually
    # tried to reach OnlyMonster.  We wire a sentinel that fails loud.
    import httpx

    class _ShouldNotBeUsed:
        async def __aenter__(self) -> "_ShouldNotBeUsed":
            raise AssertionError("OnlyMonster network call attempted in v1")

        async def __aexit__(self, *_a: object) -> None:
            return None

    monkeypatch.setattr(httpx, "AsyncClient", lambda *_a, **_kw: _ShouldNotBeUsed())

    async with _make_session() as session:
        session.add(
            OfQcDiscordStatus(
                id=1,
                daily_qc_source_mode="onlymonster_readonly",
                onlymonster_readonly_enabled=True,
            )
        )
        await session.commit()
        result = await ingest_for_status(session)
        assert result.skipped_reason == "data_source_disconnected"


# ── Evaluator ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluator_emits_zero_revenue_finding_for_indigo() -> None:
    """Synthetic 'indigo' has 0 revenue + prior $220/day → must produce
    zero_revenue_24h."""
    async with _make_session() as session:
        result = await ingest_synthetic(session)
        out = evaluate_ingestion(result)
        codes = {f.code for f in out.findings}
        assert "zero_revenue_24h" in codes
        assert out.accounts_checked == 2
        assert out.safe_mode is True


@pytest.mark.asyncio
async def test_evaluator_emits_data_source_disconnected_when_skipped() -> None:
    async with _make_session() as session:
        session.add(
            OfQcDiscordStatus(
                id=1,
                daily_qc_source_mode="onlymonster_readonly",
                onlymonster_readonly_enabled=False,
            )
        )
        await session.commit()
        result = await ingest_for_status(session)
        out = evaluate_ingestion(result)
        codes = {f.code for f in out.findings}
        assert "data_source_disconnected" in codes


@pytest.mark.asyncio
async def test_evaluator_findings_carry_no_pii() -> None:
    """No finding's signal/account_label may include fan handles / bodies /
    raw API content."""
    async with _make_session() as session:
        result = await ingest_synthetic(session)
        out = evaluate_ingestion(result)
        for f in out.findings:
            payload = " ".join(
                str(x)
                for x in (
                    f.code,
                    f.signal,
                    f.account_id,
                    f.account_label,
                    f.operator_id,
                    f.source,
                )
                if x is not None
            )
            for forbidden in (
                "@somefan",
                "fan_handle",
                "body=",
                "https://api",
                "Bearer ",
            ):
                assert forbidden not in payload
