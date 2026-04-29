# ruff: noqa: INP001
"""API tests for /api/v1/of-qc-discord — Settings card endpoints.

Covers:
  • GET /status returns ``not_configured`` initially
  • PUT /webhook validates host allowlist; rejects non-Discord URLs
  • PUT /webhook stores encrypted; response carries fixed masked preview
  • GET /status never echoes the plaintext URL
  • PUT /enabled toggles the singleton row
  • POST /test sends one canned alert (no real OF data), bypasses kill
    switch, updates last_success / last_failure fields, drives card_state
  • DELETE /webhook clears the secret AND the test history, forces toggle off
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.mc_roles import require_owner
from app.api.of_qc_discord import router as of_qc_discord_router
from app.core.auth import AuthContext, get_auth_context
from app.core.secrets_store import QC_DISCORD_WEBHOOK_DB_KEY, get_secret
from app.db.session import get_session
from app.models.of_qc_discord_status import OfQcDiscordStatus
from app.services.of_intelligence.qc import publisher

VALID_WEBHOOK = "https://discord.com/api/webhooks/123456789012345678/ABCdef-ghi_JKLmno"
ALT_WEBHOOK = "https://canary.discord.com/api/v10/webhooks/987654321098765432/zyxWVU"
MASKED = "https://discord.com/api/webhooks/****"


# ── Test client builder (helper, not fixture — tests are async) ─────────────


@contextlib.asynccontextmanager
async def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    next_status: int = 204,
) -> AsyncIterator[AsyncClient]:
    """Build a fresh in-memory SQLite app + httpx client.

    Stubs publisher network IO with a fake ``httpx.AsyncClient`` that returns
    a configurable status code, and re-routes the publisher's DB lookups to
    the same SQLite session_maker the API writes to.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(of_qc_discord_router)
    app.include_router(api_v1)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    async def _override_auth() -> AuthContext:
        return AuthContext(actor_type="user", user=None)

    async def _override_owner() -> str:
        return "owner"

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_auth_context] = _override_auth
    app.dependency_overrides[require_owner] = _override_owner

    async def _read_webhook_test() -> str:
        async with maker() as session:
            value = await get_secret(session, QC_DISCORD_WEBHOOK_DB_KEY)
            return (value or "").strip()

    async def _read_enabled_test() -> bool | None:
        async with maker() as session:
            row = await session.get(OfQcDiscordStatus, 1)
            return row.enabled if row is not None else None

    monkeypatch.setattr(publisher, "_read_db_webhook", _read_webhook_test)
    monkeypatch.setattr(publisher, "_read_db_enabled", _read_enabled_test)
    monkeypatch.setattr(publisher.httpx, "AsyncClient", _make_fake_httpx(next_status))

    async def _no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(publisher.asyncio, "sleep", _no_sleep)

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await engine.dispose()


def _make_fake_httpx(status_code: int):
    class _FakeResp:
        def __init__(self) -> None:
            self.status_code = status_code
            self.headers: dict[str, str] = {}

        def json(self) -> Any:
            return {}

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *_a: object) -> None:
            return None

        async def post(self, _url: str, *, json: dict[str, Any] | None = None) -> _FakeResp:
            _ = json
            return _FakeResp()

    def _factory(*_a: object, **_kw: object) -> _FakeClient:
        return _FakeClient()

    return _factory


# ── /status (initial) ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_initial_state_is_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_client(monkeypatch) as client:
        res = await client.get("/api/v1/of-qc-discord/status")
        assert res.status_code == 200
        body = res.json()
        assert body["configured"] is False
        assert body["preview"] is None
        assert body["enabled"] is False
        assert body["card_state"] == "not_configured"
        assert body["last_success_at"] is None
        assert body["last_failure_at"] is None


# ── PUT /webhook validation ─────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_url",
    [
        "https://evil.example.com/api/webhooks/1/abc",
        "http://discord.com/api/webhooks/1/abc",  # http not https
        "https://discord.com/webhooks/1/abc",  # missing /api/
        "ftp://discord.com/api/webhooks/1/abc",
        "not a url",
    ],
)
async def test_put_webhook_rejects_non_discord_urls(
    monkeypatch: pytest.MonkeyPatch, bad_url: str
) -> None:
    async with _make_client(monkeypatch) as client:
        res = await client.put("/api/v1/of-qc-discord/webhook", json={"key": bad_url})
        assert res.status_code == 400
        # Error must never echo the submitted value.
        assert bad_url not in res.text


@pytest.mark.asyncio
async def test_put_webhook_accepts_each_documented_discord_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid_hosts = [
        "https://discord.com/api/webhooks/1/abc",
        "https://discordapp.com/api/webhooks/1/abc",
        "https://canary.discord.com/api/v10/webhooks/1/abc",
        "https://ptb.discord.com/api/webhooks/1/abc",
    ]
    async with _make_client(monkeypatch) as client:
        for url in valid_hosts:
            res = await client.put("/api/v1/of-qc-discord/webhook", json={"key": url})
            assert res.status_code == 200, f"failed for {url}"


# ── PUT /webhook storage + masked preview ───────────────────────────────────


@pytest.mark.asyncio
async def test_put_webhook_returns_only_masked_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_client(monkeypatch) as client:
        res = await client.put("/api/v1/of-qc-discord/webhook", json={"key": VALID_WEBHOOK})
        assert res.status_code == 200
        body = res.json()
        assert body["configured"] is True
        assert body["preview"] == MASKED
        assert body["card_state"] == "configured"
        # Full URL never appears in any response.
        assert VALID_WEBHOOK not in res.text


@pytest.mark.asyncio
async def test_get_status_after_save_never_echoes_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_client(monkeypatch) as client:
        await client.put("/api/v1/of-qc-discord/webhook", json={"key": VALID_WEBHOOK})
        res = await client.get("/api/v1/of-qc-discord/status")
        assert res.status_code == 200
        assert VALID_WEBHOOK not in res.text
        assert res.json()["preview"] == MASKED


# ── PUT /enabled ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_enabled_toggles_row_and_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_client(monkeypatch) as client:
        await client.put("/api/v1/of-qc-discord/webhook", json={"key": VALID_WEBHOOK})

        res = await client.put("/api/v1/of-qc-discord/enabled", json={"enabled": True})
        assert res.status_code == 200
        assert res.json()["enabled"] is True

        res = await client.put("/api/v1/of-qc-discord/enabled", json={"enabled": False})
        assert res.json()["enabled"] is False


# ── POST /test ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_test_sends_canned_alert_and_marks_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_client(monkeypatch) as client:
        await client.put("/api/v1/of-qc-discord/webhook", json={"key": VALID_WEBHOOK})

        # Toggle is OFF — the test must still send (bypass).
        res = await client.post("/api/v1/of-qc-discord/test")
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        assert body["status"] == 204
        assert body["reason"] == "ok"
        assert body["card_state"] == "connected"

        status = (await client.get("/api/v1/of-qc-discord/status")).json()
        assert status["card_state"] == "connected"
        assert status["last_success_at"] is not None
        assert status["last_failure_at"] is None


@pytest.mark.asyncio
async def test_post_test_records_failure_and_marks_last_test_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_client(monkeypatch, next_status=500) as client:
        await client.put("/api/v1/of-qc-discord/webhook", json={"key": VALID_WEBHOOK})

        res = await client.post("/api/v1/of-qc-discord/test")
        body = res.json()
        assert body["ok"] is False
        assert body["reason"] == "http_5xx"
        assert body["card_state"] == "last_test_failed"

        status = (await client.get("/api/v1/of-qc-discord/status")).json()
        assert status["last_failure_reason"] == "http_5xx"
        assert status["last_failure_status"] == 500
        assert status["card_state"] == "last_test_failed"


@pytest.mark.asyncio
async def test_post_test_returns_no_webhook_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_client(monkeypatch) as client:
        res = await client.post("/api/v1/of-qc-discord/test")
        body = res.json()
        assert body["ok"] is False
        assert body["reason"] == "no_webhook"
        # Card state stays not_configured because the webhook isn't saved.
        status = (await client.get("/api/v1/of-qc-discord/status")).json()
        assert status["card_state"] == "not_configured"


# ── DELETE /webhook ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_webhook_clears_secret_history_and_toggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_client(monkeypatch) as client:
        await client.put("/api/v1/of-qc-discord/webhook", json={"key": VALID_WEBHOOK})
        await client.put("/api/v1/of-qc-discord/enabled", json={"enabled": True})
        await client.post("/api/v1/of-qc-discord/test")

        pre = (await client.get("/api/v1/of-qc-discord/status")).json()
        assert pre["enabled"] is True
        assert pre["card_state"] == "connected"

        res = await client.delete("/api/v1/of-qc-discord/webhook")
        assert res.status_code == 200
        body = res.json()
        assert body["configured"] is False
        assert body["preview"] is None
        assert body["enabled"] is False
        assert body["last_success_at"] is None
        assert body["last_failure_at"] is None
        assert body["card_state"] == "not_configured"


# ── Webhook rotation via PUT ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_webhook_rotates_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_client(monkeypatch) as client:
        await client.put("/api/v1/of-qc-discord/webhook", json={"key": VALID_WEBHOOK})
        res = await client.put("/api/v1/of-qc-discord/webhook", json={"key": ALT_WEBHOOK})
        assert res.status_code == 200
        assert res.json()["preview"] == MASKED
        # Neither URL appears in any response.
        assert VALID_WEBHOOK not in res.text
        assert ALT_WEBHOOK not in res.text
