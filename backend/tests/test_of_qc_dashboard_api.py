# ruff: noqa: INP001
"""Daily QC Dashboard API tests + privacy regression."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.mc_roles import require_owner
from app.api.of_intelligence import router as ofi_router
from app.core.auth import AuthContext, get_auth_context
from app.core.time import utcnow
from app.db.session import get_session
from app.models.of_intelligence import (
    OfIntelligenceAccount,
    OfIntelligenceAlert,
    OfIntelligenceChatter,
    OfIntelligenceFan,
    OfIntelligenceMessage,
    OfIntelligenceRevenue,
)
from app.models.of_qc_finding import OfIntelligenceQcFinding


@contextlib.asynccontextmanager
async def _make_client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(ofi_router)
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

    # Stub Discord publish so /qc/daily-summary doesn't hit the network.
    from app.services.of_intelligence.qc import publisher as discord_pub
    from app.services.of_intelligence.qc import telegram_publisher as tg_pub

    class _StubResp:
        ok = False
        status = None
        reason = "no_webhook"
        attempts = 0
        elapsed_ms = 0

    async def _stub_pub(*_a: Any, **_kw: Any) -> _StubResp:
        return _StubResp()

    monkeypatch.setattr(discord_pub, "publish", _stub_pub)

    async def _stub_tg(*_a: Any, **_kw: Any) -> tuple[Any, Any]:
        from app.services.of_intelligence.qc.daily_summary import build_daily_summary

        summary = await build_daily_summary(_a[0])

        class _R:
            ok = False
            status = None
            reason = "no_telegram"
            elapsed_ms = 0

        return summary, _R()

    monkeypatch.setattr(tg_pub, "ship_daily_summary_telegram", _stub_tg)

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, maker
    finally:
        await engine.dispose()


# ── Mock mode ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_mock_returns_deterministic_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_client(monkeypatch) as (client, _maker):
        res = await client.get("/api/v1/of-intelligence/qc/dashboard?mock=1")
        assert res.status_code == 200
        body = res.json()
        assert body["mock"] is True
        assert any(a["username"] == "luna_demo" for a in body["account_status"])
        assert any(w["severity"] == "medium" for w in body["revenue_warnings"])
        assert any(o["fan_handle"] == "@demo_fan" for o in body["fan_opportunities"])


# ── Real DB pull ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_returns_all_seven_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_client(monkeypatch) as (client, maker):
        res = await client.get("/api/v1/of-intelligence/qc/dashboard")
        assert res.status_code == 200
        body = res.json()
        for section in (
            "account_status",
            "revenue_warnings",
            "chatting_quality",
            "chatter_mistakes",
            "fan_opportunities",
            "sync_health",
            "action_list",
            "generated_at",
        ):
            assert section in body, f"missing section: {section}"
        assert body["mock"] is False


@pytest.mark.asyncio
async def test_dashboard_pulls_layer1_open_codes_into_account_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_client(monkeypatch) as (client, maker):
        async with maker() as session:
            session.add(
                OfIntelligenceAccount(
                    source="onlymonster",
                    source_id="acct-1",
                    username="luna",
                    access_status="blocked",
                )
            )
            session.add(
                OfIntelligenceAlert(
                    code="account_blocked",
                    severity="critical",
                    status="open",
                    title="luna blocked",
                    message="x",
                    account_source_id="acct-1",
                )
            )
            await session.commit()

        body = (await client.get("/api/v1/of-intelligence/qc/dashboard")).json()
        match = next(a for a in body["account_status"] if a["account_id"] == "acct-1")
        assert match["health_status"] == "blocked"
        assert "account_blocked" in match["open_layer1_codes"]


# ── fan_handle is the ONLY section that may carry fan handles ─────────────


@pytest.mark.asyncio
async def test_fan_handle_only_appears_in_fan_opportunities_not_other_sections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_client(monkeypatch) as (client, maker):
        async with maker() as session:
            session.add(
                OfIntelligenceAccount(
                    source="onlymonster",
                    source_id="acct-1",
                    username="luna",
                    access_status="active",
                )
            )
            session.add(
                OfIntelligenceChatter(
                    source="onlymonster",
                    source_id="ch-1",
                    name="Mia",
                    active=True,
                )
            )
            session.add(
                OfIntelligenceFan(
                    source="onlymonster",
                    source_id="fan-1",
                    account_source_id="acct-1",
                    username="@private_fan",
                )
            )
            msg_id = f"m-{uuid4().hex[:6]}"
            session.add(
                OfIntelligenceMessage(
                    source="onlymonster",
                    source_id=msg_id,
                    account_source_id="acct-1",
                    chatter_source_id="ch-1",
                    fan_source_id="fan-1",
                    direction="in",
                    sent_at=utcnow() - timedelta(minutes=10),
                    body="how much for the menu",
                )
            )
            session.add(
                OfIntelligenceQcFinding(
                    code="missed_buying_signal",
                    severity="high",
                    account_source_id="acct-1",
                    chatter_source_id="ch-1",
                    message_source_id=msg_id,
                    detection_phrase="fan asked about price/availability",
                )
            )
            await session.commit()

        body = (await client.get("/api/v1/of-intelligence/qc/dashboard")).json()
        # @private_fan SHOULD appear in fan_opportunities (Mode 3).
        assert any(o.get("fan_handle") == "@private_fan" for o in body["fan_opportunities"])
        # @private_fan must NOT appear in any other section's serialised form.
        import json

        for key in (
            "account_status",
            "revenue_warnings",
            "chatting_quality",
            "chatter_mistakes",
            "sync_health",
            "action_list",
        ):
            section_json = json.dumps(body[key])
            assert "@private_fan" not in section_json, f"fan handle leaked in {key}"


# ── Daily summary ?channel=telegram returns no_telegram safely ────────────


@pytest.mark.asyncio
async def test_daily_summary_channel_telegram_returns_skipped_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_client(monkeypatch) as (client, _maker):
        res = await client.post("/api/v1/of-intelligence/qc/daily-summary?channel=telegram")
        assert res.status_code == 200
        body = res.json()
        assert body["channel"] == "telegram"
        assert body["publish_ok"] is False
        assert body["publish_reason"] == "no_telegram"


@pytest.mark.asyncio
async def test_daily_summary_default_channel_is_discord(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_client(monkeypatch) as (client, _maker):
        res = await client.post("/api/v1/of-intelligence/qc/daily-summary")
        assert res.status_code == 200
        body = res.json()
        assert body["channel"] == "discord"
        # Stubbed publisher returns no_webhook; that's fine — we just verify
        # the route went down the discord path.
        assert body["publish_reason"] == "no_webhook"


@pytest.mark.asyncio
async def test_daily_summary_invalid_channel_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    async with _make_client(monkeypatch) as (client, _maker):
        res = await client.post("/api/v1/of-intelligence/qc/daily-summary?channel=signal")
        assert res.status_code == 400


# ── Privacy: no message bodies in any dashboard section ───────────────────


@pytest.mark.asyncio
async def test_no_message_bodies_anywhere_in_dashboard_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _make_client(monkeypatch) as (client, maker):
        leaky_body = "PLEASE_REFUND_ME_BODY_TEXT_DO_NOT_LEAK"
        async with maker() as session:
            session.add(
                OfIntelligenceAccount(
                    source="onlymonster",
                    source_id="acct-1",
                    username="luna",
                    access_status="active",
                )
            )
            msg_id = f"m-{uuid4().hex[:6]}"
            session.add(
                OfIntelligenceMessage(
                    source="onlymonster",
                    source_id=msg_id,
                    account_source_id="acct-1",
                    direction="in",
                    sent_at=utcnow() - timedelta(minutes=10),
                    body=leaky_body,
                )
            )
            session.add(
                OfIntelligenceQcFinding(
                    code="lazy_reply",
                    severity="medium",
                    account_source_id="acct-1",
                    message_source_id=msg_id,
                    detection_phrase="outbound too short to count as reply",
                )
            )
            await session.commit()

        body_text = (await client.get("/api/v1/of-intelligence/qc/dashboard")).text
        assert leaky_body not in body_text
