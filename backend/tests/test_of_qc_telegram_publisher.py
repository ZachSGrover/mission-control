# ruff: noqa: INP001
"""Telegram publisher tests — privacy-safe, graceful skip rules."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.secrets_store import set_secret
from app.models.of_qc_discord_status import OfQcDiscordStatus
from app.services.of_intelligence.qc import telegram_publisher as tp
from app.services.of_intelligence.qc.telegram_publisher import (
    TELEGRAM_QC_CHAT_DB_KEY,
    ship_daily_summary_telegram,
)

VALID_BOT_TOKEN = "1234567890:" + "A" * 35


@contextlib.asynccontextmanager
async def _make_session(
    monkeypatch: pytest.MonkeyPatch,
    *,
    bot_token: str | None = VALID_BOT_TOKEN,
    chat_id: str | None = "-1001234567890",
    enabled: bool = True,
    telegram_enabled: bool = True,
    live_send_enabled: bool = True,
    next_status: int = 200,
) -> AsyncIterator[tuple[AsyncSession, list[dict[str, Any]]]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    captured: list[dict[str, Any]] = []

    class _FakeResp:
        def __init__(self) -> None:
            self.status_code = next_status

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *_a: object) -> None:
            return None

        async def post(self, url: str, *, json: dict[str, Any] | None = None) -> _FakeResp:
            captured.append({"url": url, "json": json or {}})
            return _FakeResp()

    monkeypatch.setattr(tp.httpx, "AsyncClient", lambda *a, **kw: _FakeClient())

    async def _fake_get_token(_session: AsyncSession) -> str:
        return bot_token or ""

    monkeypatch.setattr(tp, "_get_bot_token", _fake_get_token)

    try:
        async with maker() as session:
            session.add(
                OfQcDiscordStatus(
                    id=1,
                    enabled=enabled,
                    telegram_enabled=telegram_enabled,
                    live_send_enabled=live_send_enabled,
                )
            )
            if chat_id:
                await set_secret(session, TELEGRAM_QC_CHAT_DB_KEY, chat_id)
            await session.commit()
            yield session, captured
    finally:
        await engine.dispose()


# ── Happy path ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ships_when_enabled_and_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_session(monkeypatch) as (session, captured):
        _summary, result = await ship_daily_summary_telegram(session)
        assert result.ok is True
        assert result.status == 200
        assert result.reason == "ok"
        assert len(captured) == 1
        # Bot token must be in the URL but NEVER in the body.
        assert VALID_BOT_TOKEN in captured[0]["url"]
        assert VALID_BOT_TOKEN not in captured[0]["json"].get("text", "")


# ── Skip rules ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skips_when_master_toggle_off(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_session(monkeypatch, enabled=False) as (session, captured):
        _summary, result = await ship_daily_summary_telegram(session)
        assert result.ok is False
        assert result.reason == "disabled"
        assert captured == []


@pytest.mark.asyncio
async def test_skips_when_telegram_toggle_off(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_session(monkeypatch, telegram_enabled=False) as (session, captured):
        _summary, result = await ship_daily_summary_telegram(session)
        assert result.ok is False
        assert result.reason == "telegram_disabled"
        assert captured == []


@pytest.mark.asyncio
async def test_skips_when_no_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_session(monkeypatch, bot_token=None) as (session, captured):
        _summary, result = await ship_daily_summary_telegram(session)
        assert result.ok is False
        assert result.reason == "no_telegram"
        assert captured == []


@pytest.mark.asyncio
async def test_skips_when_no_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_session(monkeypatch, chat_id=None) as (session, captured):
        _summary, result = await ship_daily_summary_telegram(session)
        assert result.ok is False
        assert result.reason == "no_telegram_chat"
        assert captured == []


# ── HTTP failures graceful ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_http_4xx_returns_reason_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_session(monkeypatch, next_status=404) as (session, _captured):
        _summary, result = await ship_daily_summary_telegram(session)
        assert result.ok is False
        assert result.reason == "http_404"
        assert result.status == 404


@pytest.mark.asyncio
async def test_network_error_returns_reason_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_session(monkeypatch) as (session, _):

        async def _boom_post(*_a: Any, **_kw: Any) -> Any:
            raise httpx.ConnectError("boom")

        class _BrokenClient:
            async def __aenter__(self) -> "_BrokenClient":
                return self

            async def __aexit__(self, *_a: object) -> None:
                return None

            post = _boom_post

        monkeypatch.setattr(tp.httpx, "AsyncClient", lambda *a, **kw: _BrokenClient())
        _summary, result = await ship_daily_summary_telegram(session)
        assert result.ok is False
        assert result.reason == "network_error"


# ── Bypass kill switch (operator-initiated send) ──────────────────────────


@pytest.mark.asyncio
async def test_bypass_kill_switch_sends_when_master_off(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_session(monkeypatch, enabled=False) as (session, captured):
        _summary, result = await ship_daily_summary_telegram(session, bypass_kill_switch=True)
        # bypass overrides master toggle; telegram_enabled must still be true,
        # which it is in the default fixture.
        assert result.ok is True
        assert len(captured) == 1


# ── Privacy: no fan handles, no bodies in the rendered text ───────────────


@pytest.mark.asyncio
async def test_rendered_text_has_no_fan_handle_or_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even after seeding fan handles + message bodies, the Telegram render
    must contain neither.  Telegram payload is re-derived from
    ``build_daily_summary``, which uses only safe fields."""
    from datetime import timedelta
    from uuid import uuid4

    from app.core.time import utcnow
    from app.models.of_intelligence import OfIntelligenceFan, OfIntelligenceMessage

    async with _make_session(monkeypatch) as (session, captured):
        session.add(
            OfIntelligenceFan(
                source="onlymonster",
                source_id="fan-1",
                account_source_id="acct-1",
                username="@somefan",
            )
        )
        session.add(
            OfIntelligenceMessage(
                source="onlymonster",
                source_id=f"m-{uuid4().hex[:6]}",
                account_source_id="acct-1",
                fan_source_id="fan-1",
                direction="in",
                sent_at=utcnow() - timedelta(minutes=10),
                body="please refund @somefan was here",
            )
        )
        await session.commit()

        _summary, result = await ship_daily_summary_telegram(session)
        assert result.ok is True
        sent_text = captured[0]["json"]["text"]
        for forbidden in ("@somefan", "please refund", "fan-1"):
            assert forbidden not in sent_text


# ── Bot token never in body or in any captured value ──────────────────────


@pytest.mark.asyncio
async def test_bot_token_never_appears_in_body(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_session(monkeypatch) as (session, captured):
        await ship_daily_summary_telegram(session)
        for call in captured:
            assert VALID_BOT_TOKEN not in call["json"].get("text", "")
            assert VALID_BOT_TOKEN not in str(call["json"])
