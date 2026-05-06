# ruff: noqa: INP001
"""Scheduler API tests — owner-only, no live sends."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.mc_roles import require_owner
from app.api.of_qc_scheduler import router as scheduler_router
from app.core.auth import AuthContext, get_auth_context
from app.db.session import get_session
from app.models.of_qc_discord_status import OfQcDiscordStatus
from app.models.of_qc_scheduler_job import OfQcSchedulerJob


@contextlib.asynccontextmanager
async def _make_client() -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(scheduler_router)
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

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, maker
    finally:
        await engine.dispose()


# ── /status (initial) ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_initial_state_all_toggles_off() -> None:
    async with _make_client() as (client, _maker):
        res = await client.get("/api/v1/of-qc-scheduler/status")
        assert res.status_code == 200
        body = res.json()
        for k in ("daily_qc_enabled", "live_send_enabled", "discord_enabled", "telegram_enabled"):
            assert body[k] is False, f"{k} must default to False"
        assert body["last_run_at"] is None
        assert body["next_run_at"] is None
        assert body["recent_jobs"] == []
        assert body["tick_interval_seconds"] > 0


# ── /enabled ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enabled_endpoint_flips_only_provided_fields() -> None:
    async with _make_client() as (client, maker):
        # Flip daily_qc_enabled, leave live_send_enabled alone.
        res = await client.put(
            "/api/v1/of-qc-scheduler/enabled",
            json={"daily_qc_enabled": True},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["daily_qc_enabled"] is True
        assert body["live_send_enabled"] is False  # unchanged

        # Flip live_send_enabled too.
        res = await client.put(
            "/api/v1/of-qc-scheduler/enabled",
            json={"live_send_enabled": True},
        )
        body = res.json()
        assert body["daily_qc_enabled"] is True
        assert body["live_send_enabled"] is True

        # Verify persistence.
        async with maker() as session:
            row = await session.get(OfQcDiscordStatus, 1)
            assert row is not None
            assert row.daily_qc_enabled is True
            assert row.live_send_enabled is True


@pytest.mark.asyncio
async def test_enabled_endpoint_rejects_empty_body() -> None:
    async with _make_client() as (client, _maker):
        res = await client.put("/api/v1/of-qc-scheduler/enabled", json={})
        assert res.status_code == 400


# ── /run-now (sandbox) ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_now_sandbox_returns_synthetic_summary_no_db_or_publish() -> None:
    async with _make_client() as (client, maker):
        res = await client.post("/api/v1/of-qc-scheduler/run-now")
        assert res.status_code == 200
        body = res.json()
        assert body["job_kind"] == "manual_sandbox"
        assert body["triggered_by"] == "manual"
        assert body["accounts_checked"] >= 1
        assert body["findings_simulated"] >= 1
        assert "synthetic" in body["note"].lower()
        # No real OF tables touched.
        async with maker() as session:
            jobs = (await session.exec(select(OfQcSchedulerJob))).all()
            assert len(jobs) == 1
            assert jobs[0].job_kind == "manual_sandbox"


@pytest.mark.asyncio
async def test_run_now_sandbox_payload_has_no_fan_handle_or_body() -> None:
    """Sandbox uses synthetic data; no real fan handles or bodies anywhere."""
    async with _make_client() as (client, _maker):
        res = await client.post("/api/v1/of-qc-scheduler/run-now")
        text = res.text
        # Forbidden patterns — the actual sandbox uses only "<account>"-style
        # placeholders and "Mia (sandbox)" labels.  None of these substrings
        # may appear in the response body.
        for forbidden in ("@somefan", "fan_xyz", "private_fan_handle", "<msg-body>"):
            assert forbidden not in text


# ── /run-now-real respects daily_qc_enabled ──────────────────────────────


@pytest.mark.asyncio
async def test_run_now_real_records_skipped_when_daily_qc_disabled() -> None:
    async with _make_client() as (client, maker):
        res = await client.post("/api/v1/of-qc-scheduler/run-now-real")
        assert res.status_code == 200
        body = res.json()
        # The status response reflects the latest job — which is "skipped".
        assert body["last_status"] == "skipped"
        assert body["last_skipped_reason"] == "daily_qc_disabled"

        async with maker() as session:
            jobs = (await session.exec(select(OfQcSchedulerJob))).all()
            assert len(jobs) == 1
            assert jobs[0].status == "skipped"
            assert jobs[0].triggered_by == "manual"


# ── recent-jobs surface ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recent_jobs_returns_audit_trail() -> None:
    async with _make_client() as (client, _maker):
        # Run a sandbox + a real-run-while-disabled.
        await client.post("/api/v1/of-qc-scheduler/run-now")
        await client.post("/api/v1/of-qc-scheduler/run-now-real")

        res = await client.get("/api/v1/of-qc-scheduler/recent-jobs")
        body = res.json()
        kinds = [r["job_kind"] for r in body]
        statuses = [r["status"] for r in body]
        assert "manual_sandbox" in kinds
        assert "daily_evaluate" in kinds
        # "skipped" must appear (the real-run with toggle off).
        assert "skipped" in statuses
