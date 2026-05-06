# ruff: noqa: INP001
"""``live_send_enabled`` gate tests for Discord + Telegram publishers."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.secrets_store import set_secret
from app.models.of_qc_discord_status import OfQcDiscordStatus
from app.services.of_intelligence.qc import publisher as discord_publisher
from app.services.of_intelligence.qc import telegram_publisher as tg_publisher
from app.services.of_intelligence.qc.publisher import publish
from app.services.of_intelligence.qc.telegram_publisher import (
    TELEGRAM_QC_CHAT_DB_KEY,
    ship_daily_summary_telegram,
)

VALID_WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/abcDEF_ghi-jkl"
SAFE_RENDERED = "🟦 [QC] Test message\nAccount: example_account"


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


# ── Discord publisher gate ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_discord_publish_blocked_when_live_send_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``enabled=True`` alone is not enough — ``live_send_enabled=False``
    must additionally block the send."""

    async def _fake_read_db_enabled() -> bool | None:
        return True  # discord channel ON

    async def _fake_read_db_live_send_enabled() -> bool | None:
        return False  # live send OFF

    async def _fake_resolve_webhook() -> str:
        return VALID_WEBHOOK

    monkeypatch.setattr(discord_publisher, "_read_db_enabled", _fake_read_db_enabled)
    monkeypatch.setattr(
        discord_publisher, "_read_db_live_send_enabled", _fake_read_db_live_send_enabled
    )
    monkeypatch.setattr(discord_publisher, "_resolve_webhook_url", _fake_resolve_webhook)

    # If httpx.AsyncClient is touched, the test fails — gate must short-circuit.
    class _ShouldNotBeCalled:
        async def __aenter__(self) -> "_ShouldNotBeCalled":
            return self

        async def __aexit__(self, *_a: object) -> None:
            return None

        async def post(self, *_a: object, **_kw: object) -> object:
            raise AssertionError("publisher must NOT POST when live_send_enabled is False")

    monkeypatch.setattr(
        discord_publisher.httpx, "AsyncClient", lambda *_a, **_kw: _ShouldNotBeCalled()
    )

    result = await publish(SAFE_RENDERED, code="x", severity="info")
    assert result.ok is False
    assert result.reason == "live_send_disabled"


@pytest.mark.asyncio
async def test_discord_publish_bypass_kill_switch_ignores_live_send_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator-initiated test alerts (Settings → Send Test Alert) bypass
    every gate including ``live_send_enabled`` so the operator can verify
    the webhook before flipping live sending on."""

    async def _fake_read_db_enabled() -> bool | None:
        return False

    async def _fake_read_db_live_send_enabled() -> bool | None:
        return False

    async def _fake_resolve_webhook() -> str:
        return VALID_WEBHOOK

    monkeypatch.setattr(discord_publisher, "_read_db_enabled", _fake_read_db_enabled)
    monkeypatch.setattr(
        discord_publisher, "_read_db_live_send_enabled", _fake_read_db_live_send_enabled
    )
    monkeypatch.setattr(discord_publisher, "_resolve_webhook_url", _fake_resolve_webhook)

    class _OkResp:
        status_code = 204
        headers: dict[str, str] = {}

        def json(self) -> Any:
            return {}

    class _OkClient:
        async def __aenter__(self) -> "_OkClient":
            return self

        async def __aexit__(self, *_a: object) -> None:
            return None

        async def post(self, *_a: object, **_kw: object) -> _OkResp:
            return _OkResp()

    monkeypatch.setattr(discord_publisher.httpx, "AsyncClient", lambda *_a, **_kw: _OkClient())

    async def _no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(discord_publisher.asyncio, "sleep", _no_sleep)

    result = await publish(SAFE_RENDERED, code="x", severity="info", bypass_kill_switch=True)
    assert result.ok is True
    assert result.reason == "ok"


# ── Telegram publisher gate ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_telegram_publisher_blocked_when_live_send_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_session() as session:
        # All channel toggles ON, but live_send_enabled is OFF.
        session.add(
            OfQcDiscordStatus(
                id=1,
                enabled=True,
                telegram_enabled=True,
                live_send_enabled=False,
            )
        )
        await set_secret(session, TELEGRAM_QC_CHAT_DB_KEY, "-100123")
        await session.commit()

        class _ShouldNotBeCalled:
            async def __aenter__(self) -> "_ShouldNotBeCalled":
                return self

            async def __aexit__(self, *_a: object) -> None:
                return None

            async def post(self, *_a: object, **_kw: object) -> object:
                raise AssertionError("telegram must NOT POST when live_send_enabled is False")

        monkeypatch.setattr(
            tg_publisher.httpx, "AsyncClient", lambda *_a, **_kw: _ShouldNotBeCalled()
        )

        async def _fake_token(_session: AsyncSession) -> str:
            return "1234567890:" + "A" * 35

        monkeypatch.setattr(tg_publisher, "_get_bot_token", _fake_token)

        _summary, result = await ship_daily_summary_telegram(session)
        assert result.ok is False
        assert result.reason == "live_send_disabled"
