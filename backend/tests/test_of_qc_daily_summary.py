# ruff: noqa: INP001
"""Phase 3: daily QC summary generator + render."""

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
    OfIntelligenceAlert,
    OfIntelligenceChatter,
)
from app.models.of_qc_finding import OfIntelligenceQcFinding
from app.services.of_intelligence.qc import daily_summary as ds


@contextlib.asynccontextmanager
async def _make_session(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncSession, list[dict[str, Any]]]]:
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

    monkeypatch.setattr(ds, "publish", _fake_publish)

    try:
        async with maker() as session:
            yield session, captured
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_summary_clean_state(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_session(monkeypatch) as (session, _):
        summary = await ds.build_daily_summary(session)
        assert summary.accounts_reviewed == 0
        assert summary.total_findings == 0
        assert summary.critical_alert_count == 0
        assert summary.actions == ["All clear — no QC issues in the last 24h."]


@pytest.mark.asyncio
async def test_summary_includes_slow_response_and_follow_up_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_session(monkeypatch) as (session, _):
        for code in ("slow_response", "slow_response", "missed_follow_up"):
            session.add(
                OfIntelligenceQcFinding(
                    code=code,
                    severity="medium",
                    account_source_id="acct-1",
                    chatter_source_id="ch-1",
                    message_source_id=f"m-{uuid4().hex[:6]}",
                    detection_phrase=f"{code} detected",
                )
            )
        await session.commit()
        summary = await ds.build_daily_summary(session)
        assert summary.slow_responses == 2
        assert summary.follow_ups_needed == 1
        rendered = ds.render_daily_summary(summary)
        assert "Slow responses: 2" in rendered
        assert "Follow-ups needed: 1" in rendered


@pytest.mark.asyncio
async def test_summary_aggregates_findings_and_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_session(monkeypatch) as (session, _):
        # 1 active account + 1 chatter
        session.add(
            OfIntelligenceAccount(
                source="onlymonster",
                source_id="acct-1",
                username="luna_main",
                access_status="active",
            )
        )
        session.add(
            OfIntelligenceChatter(
                source="onlymonster", source_id="ch-1", name="Mia", active=True
            )
        )
        # 4 findings on (ch-1, acct-1, lazy_reply) → repeat offender
        for _ in range(4):
            session.add(
                OfIntelligenceQcFinding(
                    code="lazy_reply",
                    severity="medium",
                    account_source_id="acct-1",
                    chatter_source_id="ch-1",
                    message_source_id=f"m-{uuid4().hex[:6]}",
                    detection_phrase="lazy_reply detected",
                )
            )
        # 2 missed_buying_signal findings
        for _ in range(2):
            session.add(
                OfIntelligenceQcFinding(
                    code="missed_buying_signal",
                    severity="high",
                    account_source_id="acct-1",
                    chatter_source_id="ch-1",
                    message_source_id=f"m-{uuid4().hex[:6]}",
                    detection_phrase="buying-signal detected",
                )
            )
        # 1 critical open Layer 1 alert
        session.add(
            OfIntelligenceAlert(
                code="account_blocked",
                severity="critical",
                status="open",
                title="account_blocked",
                message="x",
                account_source_id="acct-1",
            )
        )
        # 1 critical open Layer 2 alert
        session.add(
            OfIntelligenceAlert(
                code="refund_risk",
                severity="critical",
                status="open",
                title="refund_risk",
                message="x",
                account_source_id="acct-1",
            )
        )
        await session.commit()

        summary = await ds.build_daily_summary(session)
        assert summary.accounts_reviewed == 1
        assert summary.total_findings == 6
        assert summary.critical_alert_count == 2
        assert summary.worst_accounts[0] == ("luna_main", 6)
        assert summary.worst_chatters[0] == ("Mia", 6)
        assert "Mia" in summary.repeat_offenders
        assert summary.missed_sales_signals == 2
        assert "account_blocked" in summary.layer1_open_alerts
        assert "refund_risk" in summary.layer2_open_alerts
        assert any("Coach repeat offenders" in a for a in summary.actions)
        assert any("missed buying-signal" in a.lower() for a in summary.actions)


@pytest.mark.asyncio
async def test_render_does_not_leak_source_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_session(monkeypatch) as (session, _):
        session.add(
            OfIntelligenceAccount(
                source="onlymonster",
                source_id="acct-secret",
                username="luna_main",
                access_status="active",
            )
        )
        session.add(
            OfIntelligenceChatter(
                source="onlymonster", source_id="ch-secret", name="Mia", active=True
            )
        )
        for _ in range(2):
            session.add(
                OfIntelligenceQcFinding(
                    code="lazy_reply",
                    severity="medium",
                    account_source_id="acct-secret",
                    chatter_source_id="ch-secret",
                    message_source_id="m-secret",
                    detection_phrase="lazy_reply detected",
                )
            )
        await session.commit()
        summary = await ds.build_daily_summary(session)
        rendered = ds.render_daily_summary(summary)
        for forbidden in ("acct-secret", "ch-secret", "m-secret"):
            assert forbidden not in rendered


@pytest.mark.asyncio
async def test_ship_daily_summary_calls_publisher_with_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_session(monkeypatch) as (session, captured):
        summary, result = await ds.ship_daily_summary(session, bypass_kill_switch=True)
        assert result.ok is True
        assert summary.total_findings == 0
        assert len(captured) == 1
        assert captured[0]["bypass_kill_switch"] is True
        assert captured[0]["code"] == ds.DAILY_SUMMARY_CODE
