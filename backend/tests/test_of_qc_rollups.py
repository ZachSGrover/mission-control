# ruff: noqa: INP001
"""Phase 2: rollup engine tests."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.of_intelligence import (
    OfIntelligenceAccount,
    OfIntelligenceAlert,
    OfIntelligenceChatter,
)
from app.models.of_qc_finding import OfIntelligenceQcFinding
from app.services.of_intelligence.qc import publisher, rollups
from app.services.of_intelligence.qc.rollups import (
    ROLLUP_ALERT_CODE,
    fire_rollup_if_due,
)


@contextlib.asynccontextmanager
async def _make_session(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[
    tuple[AsyncSession, list[dict[str, Any]]]
]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    captured: list[dict[str, Any]] = []

    async def _fake_publish(rendered_message: str, **kwargs: Any) -> object:
        captured.append({"rendered": rendered_message, **kwargs})

        class _R:
            ok = True
            status = 204
            attempts = 1
            reason = "ok"
            elapsed_ms = 1

        return _R()

    monkeypatch.setattr(rollups, "publish", _fake_publish)
    # Also stub the underlying publisher so any direct call doesn't hit the
    # network.
    async def _fake_pub2(*_a: Any, **_kw: Any) -> object:
        class _R:
            ok = True
            status = 204
            attempts = 1
            reason = "ok"
            elapsed_ms = 1

        return _R()

    monkeypatch.setattr(publisher, "publish", _fake_pub2)

    try:
        async with maker() as session:
            yield session, captured
    finally:
        await engine.dispose()


async def _seed_chatter(session: AsyncSession, name: str) -> str:
    sid = f"ch-{uuid4().hex[:6]}"
    session.add(
        OfIntelligenceChatter(
            source="onlymonster", source_id=sid, name=name, active=True
        )
    )
    await session.commit()
    return sid


async def _seed_account(session: AsyncSession, username: str) -> str:
    sid = f"acct-{uuid4().hex[:6]}"
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


async def _seed_finding(
    session: AsyncSession,
    *,
    code: str,
    chatter_source_id: str | None,
    account_source_id: str | None,
    minutes_ago: int = 5,
    severity: str = "low",
) -> None:
    session.add(
        OfIntelligenceQcFinding(
            code=code,
            severity=severity,
            account_source_id=account_source_id,
            chatter_source_id=chatter_source_id,
            message_source_id=f"m-{uuid4().hex[:6]}",
            detection_phrase=f"{code} detected",
            created_at=utcnow() - timedelta(minutes=minutes_ago),
        )
    )
    await session.commit()


# ── Threshold ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rollup_does_not_fire_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_session(monkeypatch) as (session, captured):
        ch = await _seed_chatter(session, "Mia")
        ac = await _seed_account(session, "luna_main")
        await _seed_finding(session, code="lazy_reply", chatter_source_id=ch, account_source_id=ac)
        # Only one finding — threshold for digest is >=2.
        result = await fire_rollup_if_due(session)
        assert result.alert_id is None
        assert captured == []


@pytest.mark.asyncio
async def test_rollup_fires_at_threshold_and_marks_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_session(monkeypatch) as (session, captured):
        ch = await _seed_chatter(session, "Mia")
        ac = await _seed_account(session, "luna_main")
        for _ in range(3):
            await _seed_finding(session, code="lazy_reply", chatter_source_id=ch, account_source_id=ac)

        result = await fire_rollup_if_due(session)
        assert result.alert_id is not None
        assert result.findings_rolled == 3
        assert result.chatter_count == 1
        assert result.account_count == 1

        # All findings stamped rolled_up_at.
        findings = (await session.exec(select(OfIntelligenceQcFinding))).all()
        assert all(f.rolled_up_at is not None for f in findings)

        # Rollup alert row created.
        alerts = (
            await session.exec(
                select(OfIntelligenceAlert).where(
                    OfIntelligenceAlert.code == ROLLUP_ALERT_CODE
                )
            )
        ).all()
        assert len(alerts) == 1
        assert alerts[0].severity == "high"  # 3+ → repeat-offender escalation

        # Discord ship captured.
        assert len(captured) == 1
        rendered = captured[0]["rendered"]
        assert "[QC] Chatter QC — last 30 min" in rendered
        assert "luna_main / Mia" in rendered
        assert "3× lazy_reply" in rendered
        assert "repeat offender" in rendered


@pytest.mark.asyncio
async def test_rollup_below_escalation_threshold_uses_medium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_session(monkeypatch) as (session, captured):
        ch = await _seed_chatter(session, "Sam")
        ac = await _seed_account(session, "indigo")
        # 2 findings of same code = at digest threshold but below escalation.
        await _seed_finding(session, code="bad_english", chatter_source_id=ch, account_source_id=ac)
        await _seed_finding(session, code="bad_english", chatter_source_id=ch, account_source_id=ac)
        result = await fire_rollup_if_due(session)
        assert result.alert_id is not None

        alerts = (
            await session.exec(
                select(OfIntelligenceAlert).where(
                    OfIntelligenceAlert.code == ROLLUP_ALERT_CODE
                )
            )
        ).all()
        assert alerts[0].severity == "medium"
        assert "repeat offender" not in captured[0]["rendered"]


# ── Idempotency: re-running does not re-ship the same findings ─────────────


@pytest.mark.asyncio
async def test_rollup_skips_already_rolled_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_session(monkeypatch) as (session, captured):
        ch = await _seed_chatter(session, "Mia")
        ac = await _seed_account(session, "luna_main")
        for _ in range(3):
            await _seed_finding(session, code="lazy_reply", chatter_source_id=ch, account_source_id=ac)

        await fire_rollup_if_due(session)
        assert len(captured) == 1

        captured.clear()
        # Same DB state — nothing un-rolled-up remains.
        result2 = await fire_rollup_if_due(session)
        assert result2.alert_id is None
        assert captured == []


# ── Privacy: no source_id leaks into the rendered digest ───────────────────


@pytest.mark.asyncio
async def test_rollup_does_not_leak_source_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_session(monkeypatch) as (session, captured):
        ch = await _seed_chatter(session, "Mia")
        ac = await _seed_account(session, "luna_main")
        for _ in range(2):
            await _seed_finding(session, code="lazy_reply", chatter_source_id=ch, account_source_id=ac)

        await fire_rollup_if_due(session)
        rendered = captured[0]["rendered"]
        # Display names may render; source_ids must not.
        assert ch not in rendered
        assert ac not in rendered
        # Common forbidden substrings.
        for forbidden in ("@somefan", "Bearer ", "https://discord.com/api/webhooks"):
            assert forbidden not in rendered


# ── Empty pair labels fall back to placeholder, not source_id ──────────────


@pytest.mark.asyncio
async def test_rollup_uses_placeholders_when_display_names_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_session(monkeypatch) as (session, captured):
        # No chatter / account rows seeded — so display lookup misses.
        for _ in range(2):
            await _seed_finding(
                session,
                code="lazy_reply",
                chatter_source_id="ch-orphan",
                account_source_id="acct-orphan",
            )
        await fire_rollup_if_due(session)
        rendered = captured[0]["rendered"]
        assert "ch-orphan" not in rendered
        assert "acct-orphan" not in rendered
        assert "<account>" in rendered or "<chatter>" in rendered
