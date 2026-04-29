# ruff: noqa: INP001
"""Integration tests for ``evaluate_alerts``.

Pins the post-commit Discord shipping behavior:
  • Each new alert (account_blocked / expired / disconnected / stale /
    sync_failure / api_disconnected) results in exactly one ship call.
  • Re-running evaluation against the same DB state ships nothing
    (dedup gate prevents duplicate Discord messages).
  • The dispatcher receives the resolved ``account_username`` (not the
    internal ``source_id``).
  • A failing dispatcher does not roll back the DB or block other alerts.
"""

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
    OfIntelligenceSyncLog,
)
from app.services.of_intelligence import alerts as alerts_module
from app.services.of_intelligence.alerts import evaluate_alerts


@contextlib.asynccontextmanager
async def _make_env(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncSession, list[dict[str, Any]]]]:
    """SQLite in-memory + capture of dispatcher calls."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    captured: list[dict[str, Any]] = []

    async def _fake_ship(
        *,
        code: str,
        title: str,
        account_username: str | None,
        alert_id: object,
        context: dict[str, Any] | None = None,
        chatter_name: str | None = None,
    ) -> None:
        captured.append(
            {
                "code": code,
                "title": title,
                "account_username": account_username,
                "chatter_name": chatter_name,
                "alert_id": alert_id,
                "context": context,
            }
        )
        return None

    monkeypatch.setattr(alerts_module, "ship_account_or_sync_alert", _fake_ship)

    try:
        async with maker() as session:
            yield session, captured
    finally:
        await engine.dispose()


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _seed_account(
    session: AsyncSession,
    *,
    username: str,
    access_status: str | None,
    last_synced_hours_ago: int = 1,
) -> str:
    source_id = f"acct-{uuid4().hex[:8]}"
    session.add(
        OfIntelligenceAccount(
            source="onlymonster",
            source_id=source_id,
            username=username,
            access_status=access_status,
            last_synced_at=utcnow() - timedelta(hours=last_synced_hours_ago),
        )
    )
    await session.commit()
    return source_id


async def _seed_sync_log(
    session: AsyncSession,
    *,
    entity: str,
    status: str,
    started_at_hours_ago: int = 1,
    error: str | None = None,
) -> None:
    session.add(
        OfIntelligenceSyncLog(
            entity=entity,
            status=status,
            run_id=uuid4(),
            started_at=utcnow() - timedelta(hours=started_at_hours_ago),
            error=error,
        )
    )
    await session.commit()


# ── Per-rule shipping ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_account_blocked_ships_once_with_username(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_env(monkeypatch) as (session, captured):
        await _seed_account(session, username="luna_main", access_status="blocked")
        summary = await evaluate_alerts(session)

        assert summary.alerts_created == 1
        assert len(captured) == 1
        call = captured[0]
        assert call["code"] == "account_blocked"
        assert call["account_username"] == "luna_main"
        assert call["context"] == {"access_status": "blocked"}


@pytest.mark.asyncio
async def test_account_expired_ships(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_env(monkeypatch) as (session, captured):
        await _seed_account(session, username="indigo", access_status="expired")
        await evaluate_alerts(session)
        assert [c["code"] for c in captured] == ["account_expired"]
        assert captured[0]["account_username"] == "indigo"


@pytest.mark.asyncio
async def test_account_disconnected_ships(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_env(monkeypatch) as (session, captured):
        await _seed_account(session, username="rose", access_status="lost")
        await evaluate_alerts(session)
        assert "account_disconnected" in [c["code"] for c in captured]


@pytest.mark.asyncio
async def test_account_stale_ships(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_env(monkeypatch) as (session, captured):
        await _seed_account(
            session,
            username="violet",
            access_status="active",
            last_synced_hours_ago=10,
        )
        await evaluate_alerts(session)
        stale = [c for c in captured if c["code"] == "account_stale"]
        assert len(stale) == 1
        assert stale[0]["context"] == {"hours_since_sync": 6}
        assert stale[0]["account_username"] == "violet"


@pytest.mark.asyncio
async def test_sync_failure_ships_per_entity(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_env(monkeypatch) as (session, captured):
        await _seed_sync_log(
            session,
            entity="messages",
            status="error",
            error="OnlyMonster 401: token bad",
        )
        await _seed_sync_log(session, entity="accounts", status="error")
        await evaluate_alerts(session)
        sync_codes = sorted(c["code"] for c in captured if c["code"].startswith("sync_failure:"))
        assert sync_codes == ["sync_failure:accounts", "sync_failure:messages"]


@pytest.mark.asyncio
async def test_api_disconnected_ships_when_no_recent_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_env(monkeypatch) as (session, captured):
        # Some old sync activity exists but no successful one in last 24h.
        await _seed_sync_log(
            session,
            entity="messages",
            status="success",
            started_at_hours_ago=48,
        )
        await evaluate_alerts(session)
        assert "api_disconnected" in [c["code"] for c in captured]


@pytest.mark.asyncio
async def test_api_disconnected_does_not_fire_for_brand_new_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_env(monkeypatch) as (session, captured):
        await evaluate_alerts(session)
        assert [c["code"] for c in captured if c["code"] == "api_disconnected"] == []


# ── Dedup: re-evaluation does not re-ship ───────────────────────────────────


@pytest.mark.asyncio
async def test_second_evaluation_does_not_reship_open_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_env(monkeypatch) as (session, captured):
        await _seed_account(session, username="luna_main", access_status="blocked")
        await evaluate_alerts(session)
        assert len(captured) == 1
        captured.clear()
        await evaluate_alerts(session)
        assert captured == []


# ── Resilience: a failing dispatcher must not block other ships ─────────────


@pytest.mark.asyncio
async def test_dispatcher_exception_does_not_block_other_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_env(monkeypatch) as (session, _ignored):
        await _seed_account(session, username="alpha", access_status="blocked")
        await _seed_account(session, username="bravo", access_status="expired")

        seen: list[str] = []

        async def _flaky_ship(
            *,
            code: str,
            title: str,
            account_username: str | None,
            alert_id: object,
            context: dict[str, Any] | None = None,
            chatter_name: str | None = None,
        ) -> None:
            _ = title, account_username, alert_id, context, chatter_name
            seen.append(code)
            if code == "account_blocked":
                raise RuntimeError("simulated dispatcher crash")
            return None

        monkeypatch.setattr(alerts_module, "ship_account_or_sync_alert", _flaky_ship)

        summary = await evaluate_alerts(session)

        assert summary.alerts_created == 2
        assert sorted(seen) == ["account_blocked", "account_expired"]

        rows = (await session.exec(select(OfIntelligenceAlert))).all()
        assert {r.code for r in rows} == {"account_blocked", "account_expired"}


# ── Severity values reaching the row ────────────────────────────────────────


@pytest.mark.asyncio
async def test_alert_row_records_correct_severity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_env(monkeypatch) as (session, _captured):
        await _seed_account(session, username="luna_main", access_status="blocked")
        await _seed_account(
            session,
            username="violet",
            access_status="active",
            last_synced_hours_ago=10,
        )

        await evaluate_alerts(session)

        rows = (await session.exec(select(OfIntelligenceAlert))).all()
        by_code = {r.code: r.severity for r in rows}
        assert by_code["account_blocked"] == "critical"
        assert by_code["account_stale"] == "high"
