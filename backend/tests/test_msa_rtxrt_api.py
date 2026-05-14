# ruff: noqa: INP001
"""Tests for the MSA RT/X job-queue bridge API."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.mc_roles import (
    get_mc_role,
    require_operator,
    require_owner,
)
from app.api.msa_rtxrt import router as msa_rtxrt_router
from app.core.auth import AuthContext, get_auth_context
from app.core.config import settings
from app.db.session import get_session
from app.models.audit_event import AuditEvent
from app.models.mc_role import ROLE_RANK
from app.models.msa_rtxrt_job import (
    STATUS_BLOCKED,
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
)
from app.models.msa_rtxrt_runner_heartbeat import MsaRtxrtRunnerHeartbeat

RUNNER_TOKEN = "test-runner-token-msa-rtxrt"


@contextlib.asynccontextmanager
async def _make_client(
    *,
    role: str = "owner",
    actor_user_id: str = "u-test",
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    """Spin up an in-memory FastAPI app with the MSA RT/X router."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(msa_rtxrt_router)
    app.include_router(api_v1)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    async def _override_auth() -> AuthContext:
        from app.models.users import User

        return AuthContext(
            actor_type="user",
            user=User(
                clerk_user_id=actor_user_id,
                email=f"{actor_user_id}@test.local",
                name="Test Actor",
            ),
        )

    async def _override_role() -> str:
        return role

    async def _override_owner_dep() -> str:
        if role != "owner":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner only")
        return "owner"

    async def _override_operator_dep() -> str:
        if ROLE_RANK.get(role, 0) < ROLE_RANK["operator"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator only")
        return role

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_auth_context] = _override_auth
    app.dependency_overrides[get_mc_role] = _override_role
    app.dependency_overrides[require_owner] = _override_owner_dep
    app.dependency_overrides[require_operator] = _override_operator_dep

    # Force the runner-auth dep to see a known token. (settings is a global
    # singleton; mutating it for the duration of the async-context is the
    # least-invasive way to pin the expected value for tests.)
    prev_token = settings.msa_rtxrt_runner_token
    settings.msa_rtxrt_runner_token = RUNNER_TOKEN
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, maker
    finally:
        settings.msa_rtxrt_runner_token = prev_token
        await engine.dispose()


def _dry_run_body(kind: str = "dry_run_blast") -> dict[str, Any]:
    return {"kind": kind}


def _live_one_body(kind: str = "live_one_blast") -> dict[str, Any]:
    return {"kind": kind, "confirm_live": "YES", "max_test_actions": 1}


# ── POST /jobs — operator dry-run ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_operator_can_create_dry_run_job() -> None:
    async with _make_client(role="operator") as (client, _maker):
        res = await client.post("/api/v1/msa-rtxrt/jobs", json=_dry_run_body())
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["kind"] == "dry_run_blast"
        assert body["status"] == STATUS_QUEUED
        assert body["dry_run"] is True
        assert body["live_one"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    ["smoke", "dry_run_dm", "dry_run_repost", "dry_run_builder", "dry_run_scan"],
)
async def test_operator_can_create_each_dry_run_kind(kind: str) -> None:
    async with _make_client(role="operator") as (client, _maker):
        res = await client.post("/api/v1/msa-rtxrt/jobs", json={"kind": kind})
        assert res.status_code == 201, res.text
        assert res.json()["kind"] == kind


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["builder", "viewer"])
async def test_builder_or_viewer_cannot_create_job(role: str) -> None:
    async with _make_client(role=role) as (client, _maker):
        res = await client.post("/api/v1/msa-rtxrt/jobs", json=_dry_run_body())
        assert res.status_code == 403


# ── POST /jobs — live-one gates ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_operator_cannot_create_live_one_job() -> None:
    async with _make_client(role="operator") as (client, _maker):
        res = await client.post("/api/v1/msa-rtxrt/jobs", json=_live_one_body())
        assert res.status_code == 403
        assert "owner" in res.text.lower()


@pytest.mark.asyncio
async def test_owner_can_create_live_one_with_all_flags() -> None:
    async with _make_client(role="owner") as (client, _maker):
        res = await client.post("/api/v1/msa-rtxrt/jobs", json=_live_one_body())
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["live_one"] is True
        assert body["dry_run"] is False
        assert body["max_test_actions"] == 1


@pytest.mark.asyncio
async def test_owner_live_one_requires_confirm_live_yes() -> None:
    async with _make_client(role="owner") as (client, _maker):
        body = _live_one_body()
        body["confirm_live"] = "yes"  # case-sensitive
        res = await client.post("/api/v1/msa-rtxrt/jobs", json=body)
        assert res.status_code == 400
        assert "CONFIRM_LIVE_TEST" in res.text


@pytest.mark.asyncio
async def test_owner_live_one_requires_max_test_actions_one() -> None:
    async with _make_client(role="owner") as (client, _maker):
        body = _live_one_body()
        body["max_test_actions"] = 0
        res = await client.post("/api/v1/msa-rtxrt/jobs", json=body)
        assert res.status_code == 400
        assert "MAX_TEST_ACTIONS" in res.text


# ── POST /jobs — mass-live rejection ────────────────────────────────────────


@pytest.mark.asyncio
async def test_mass_live_kind_is_rejected_for_owner() -> None:
    async with _make_client(role="owner") as (client, _maker):
        res = await client.post(
            "/api/v1/msa-rtxrt/jobs",
            json={"kind": "live_all_blast", "confirm_live": "YES", "max_test_actions": 1},
        )
        assert res.status_code == 400
        assert "mass live" in res.text


@pytest.mark.asyncio
async def test_unknown_kind_is_rejected() -> None:
    async with _make_client(role="owner") as (client, _maker):
        res = await client.post("/api/v1/msa-rtxrt/jobs", json={"kind": "not_a_real_kind"})
        assert res.status_code == 400


# ── Audit logging ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_creating_a_job_writes_an_audit_event() -> None:
    async with _make_client(role="operator", actor_user_id="u-op") as (client, maker):
        await client.post("/api/v1/msa-rtxrt/jobs", json=_dry_run_body())
        async with maker() as session:
            rows = (await session.exec(select(AuditEvent))).all()
        actions = {r.action for r in rows}
        assert "msa_rtxrt.job.create" in actions


@pytest.mark.asyncio
async def test_mass_live_attempt_writes_blocked_audit_event() -> None:
    async with _make_client(role="owner", actor_user_id="u-owner") as (client, maker):
        await client.post(
            "/api/v1/msa-rtxrt/jobs",
            json={"kind": "live_mass_blast", "confirm_live": "YES", "max_test_actions": 1},
        )
        async with maker() as session:
            rows = (await session.exec(select(AuditEvent))).all()
        actions = {r.action for r in rows}
        assert "msa_rtxrt.job.create.blocked_mass_live" in actions


@pytest.mark.asyncio
async def test_non_owner_live_one_attempt_writes_denied_audit_event() -> None:
    async with _make_client(role="operator", actor_user_id="u-op") as (client, maker):
        await client.post("/api/v1/msa-rtxrt/jobs", json=_live_one_body())
        async with maker() as session:
            rows = (await session.exec(select(AuditEvent))).all()
        actions = {r.action for r in rows}
        assert "msa_rtxrt.job.create.denied_non_owner" in actions


# ── Runner poll ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runner_poll_returns_null_when_queue_empty() -> None:
    async with _make_client(role="owner") as (client, _maker):
        res = await client.get(
            "/api/v1/msa-rtxrt/runner/poll",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
        )
        assert res.status_code == 200, res.text
        assert res.json() == {"job": None}


@pytest.mark.asyncio
async def test_runner_poll_claims_next_queued_job() -> None:
    async with _make_client(role="owner") as (client, _maker):
        created = (await client.post("/api/v1/msa-rtxrt/jobs", json=_dry_run_body())).json()
        res = await client.get(
            "/api/v1/msa-rtxrt/runner/poll?runner_id=claw-1",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["job"] is not None
        assert body["job"]["id"] == created["id"]
        assert body["job"]["status"] == STATUS_RUNNING
        assert body["job"]["runner_id"] == "claw-1"
        assert body["job"]["started_at"] is not None


@pytest.mark.asyncio
async def test_runner_poll_requires_correct_token() -> None:
    async with _make_client(role="owner") as (client, _maker):
        # No header → 401
        no_header = await client.get("/api/v1/msa-rtxrt/runner/poll")
        assert no_header.status_code == 401
        # Wrong token → 401
        wrong = await client.get(
            "/api/v1/msa-rtxrt/runner/poll",
            headers={"X-MSA-RTXRT-Runner-Token": "definitely-wrong"},
        )
        assert wrong.status_code == 401


@pytest.mark.asyncio
async def test_runner_poll_returns_503_when_token_unconfigured() -> None:
    async with _make_client(role="owner") as (client, _maker):
        settings.msa_rtxrt_runner_token = ""  # disable
        res = await client.get(
            "/api/v1/msa-rtxrt/runner/poll",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
        )
        assert res.status_code == 503


# ── Runner PATCH ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runner_can_patch_job_to_succeeded() -> None:
    async with _make_client(role="owner") as (client, _maker):
        created = (await client.post("/api/v1/msa-rtxrt/jobs", json=_dry_run_body())).json()
        # Claim it first.
        await client.get(
            "/api/v1/msa-rtxrt/runner/poll",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
        )
        # Report success.
        res = await client.patch(
            f"/api/v1/msa-rtxrt/jobs/{created['id']}",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
            json={
                "status": STATUS_SUCCEEDED,
                "summary": "dry-run blast complete",
                "stdout_excerpt": "200 candidates processed, 0 sent.",
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == STATUS_SUCCEEDED
        assert body["summary"] == "dry-run blast complete"
        assert body["finished_at"] is not None


@pytest.mark.asyncio
async def test_runner_patch_rejects_illegal_transition() -> None:
    async with _make_client(role="owner") as (client, _maker):
        created = (await client.post("/api/v1/msa-rtxrt/jobs", json=_dry_run_body())).json()
        # queued -> succeeded is NOT an allowed transition (must go through running first).
        res = await client.patch(
            f"/api/v1/msa-rtxrt/jobs/{created['id']}",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
            json={"status": STATUS_SUCCEEDED},
        )
        assert res.status_code == 400
        assert "illegal transition" in res.text


@pytest.mark.asyncio
async def test_runner_patch_can_block_a_queued_job() -> None:
    """If the runner refuses to even start (e.g. safety gate locally), it can block the row."""
    async with _make_client(role="owner") as (client, _maker):
        created = (await client.post("/api/v1/msa-rtxrt/jobs", json=_dry_run_body())).json()
        # queued -> blocked is allowed (runner refused to run).
        res = await client.patch(
            f"/api/v1/msa-rtxrt/jobs/{created['id']}",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
            json={
                "status": STATUS_BLOCKED,
                "error_excerpt": "local runner safety gate refused live mode",
            },
        )
        assert res.status_code == 200
        assert res.json()["status"] == STATUS_BLOCKED


@pytest.mark.asyncio
async def test_runner_patch_writes_audit_for_failure() -> None:
    async with _make_client(role="owner") as (client, maker):
        created = (await client.post("/api/v1/msa-rtxrt/jobs", json=_dry_run_body())).json()
        await client.get(
            "/api/v1/msa-rtxrt/runner/poll",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
        )
        await client.patch(
            f"/api/v1/msa-rtxrt/jobs/{created['id']}",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
            json={"status": STATUS_FAILED, "error_excerpt": "script crashed"},
        )
        async with maker() as session:
            rows = (await session.exec(select(AuditEvent))).all()
        actions = {r.action for r in rows}
        assert "msa_rtxrt.job.failed" in actions


# ── GET /jobs ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_jobs_returns_most_recent_first() -> None:
    async with _make_client(role="operator") as (client, _maker):
        await client.post("/api/v1/msa-rtxrt/jobs", json={"kind": "smoke"})
        await client.post("/api/v1/msa-rtxrt/jobs", json={"kind": "dry_run_dm"})
        res = await client.get("/api/v1/msa-rtxrt/jobs")
        assert res.status_code == 200
        items = res.json()["items"]
        assert [it["kind"] for it in items] == ["dry_run_dm", "smoke"]


@pytest.mark.asyncio
async def test_list_jobs_filters_by_status() -> None:
    async with _make_client(role="operator") as (client, _maker):
        await client.post("/api/v1/msa-rtxrt/jobs", json={"kind": "smoke"})
        res = await client.get("/api/v1/msa-rtxrt/jobs?status=queued")
        assert res.status_code == 200
        assert len(res.json()["items"]) == 1
        res2 = await client.get("/api/v1/msa-rtxrt/jobs?status=succeeded")
        assert res2.status_code == 200
        assert res2.json()["items"] == []


@pytest.mark.asyncio
async def test_list_jobs_rejects_invalid_status() -> None:
    async with _make_client(role="operator") as (client, _maker):
        res = await client.get("/api/v1/msa-rtxrt/jobs?status=banana")
        assert res.status_code == 400


# ── No raw secret values in responses ───────────────────────────────────────


@pytest.mark.asyncio
async def test_no_runner_token_appears_anywhere_in_responses() -> None:
    async with _make_client(role="owner") as (client, _maker):
        created = (await client.post("/api/v1/msa-rtxrt/jobs", json=_dry_run_body())).json()
        polled = await client.get(
            "/api/v1/msa-rtxrt/runner/poll",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
        )
        listed = await client.get("/api/v1/msa-rtxrt/jobs")
        for blob in (created, polled.json(), listed.json()):
            assert RUNNER_TOKEN not in str(blob)


# ── Sanity: cancelled transitions ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancelled_is_terminal() -> None:
    """If a job lands in cancelled, no further patch is allowed."""
    async with _make_client(role="owner") as (client, _maker):
        created = (await client.post("/api/v1/msa-rtxrt/jobs", json=_dry_run_body())).json()
        # queued -> cancelled is allowed.
        res = await client.patch(
            f"/api/v1/msa-rtxrt/jobs/{created['id']}",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
            json={"status": STATUS_CANCELLED},
        )
        assert res.status_code == 200
        # cancelled -> anything else is illegal.
        res2 = await client.patch(
            f"/api/v1/msa-rtxrt/jobs/{created['id']}",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
            json={"status": STATUS_SUCCEEDED},
        )
        assert res2.status_code == 400


# ── Pure-function tests for the service layer ───────────────────────────────


def test_service_validate_kind_blocks_mass_live() -> None:
    from app.services.msa_rtxrt_jobs import MassLiveBlockedError, validate_kind

    for kind in ("live_all_blast", "live_mass_dm", "live_batch_scan", "live_many"):
        with pytest.raises(MassLiveBlockedError):
            validate_kind(kind)


def test_service_validate_kind_rejects_unknown() -> None:
    from app.services.msa_rtxrt_jobs import UnknownKindError, validate_kind

    with pytest.raises(UnknownKindError):
        validate_kind("not_a_real_kind")


def test_service_validate_live_one_request_passes_with_all_flags() -> None:
    from app.services.msa_rtxrt_jobs import validate_live_one_request

    validate_live_one_request(kind="live_one_blast", confirm_live="YES", max_test_actions=1)


def test_service_validate_transition_blocks_terminal() -> None:
    from app.services.msa_rtxrt_jobs import (
        IllegalTransitionError,
        validate_transition,
    )

    with pytest.raises(IllegalTransitionError):
        validate_transition(STATUS_SUCCEEDED, STATUS_RUNNING)


# ── Heartbeat / runner-status ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runner_poll_writes_heartbeat_on_empty_queue() -> None:
    """An idle poll (empty queue) still upserts a heartbeat row."""
    async with _make_client(role="owner") as (client, maker):
        res = await client.get(
            "/api/v1/msa-rtxrt/runner/poll?runner_id=claw-1",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
        )
        assert res.status_code == 200
        assert res.json() == {"job": None}
        async with maker() as session:
            rows = (await session.exec(select(MsaRtxrtRunnerHeartbeat))).all()
        assert len(rows) == 1
        assert rows[0].runner_id == "claw-1"
        assert rows[0].last_status == "idle"


@pytest.mark.asyncio
async def test_runner_poll_writes_busy_heartbeat_when_claiming_job() -> None:
    async with _make_client(role="owner") as (client, maker):
        # Enqueue something for the runner to claim.
        await client.post("/api/v1/msa-rtxrt/jobs", json={"kind": "smoke"})
        res = await client.get(
            "/api/v1/msa-rtxrt/runner/poll?runner_id=claw-1",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
        )
        assert res.status_code == 200
        assert res.json()["job"]["kind"] == "smoke"
        async with maker() as session:
            rows = (await session.exec(select(MsaRtxrtRunnerHeartbeat))).all()
        assert rows[0].last_status == "busy"


@pytest.mark.asyncio
async def test_invalid_token_does_not_write_heartbeat() -> None:
    """Wrong runner token must not produce any heartbeat row."""
    async with _make_client(role="owner") as (client, maker):
        res = await client.get(
            "/api/v1/msa-rtxrt/runner/poll?runner_id=intruder",
            headers={"X-MSA-RTXRT-Runner-Token": "definitely-wrong"},
        )
        assert res.status_code == 401
        async with maker() as session:
            rows = (await session.exec(select(MsaRtxrtRunnerHeartbeat))).all()
        assert rows == []


@pytest.mark.asyncio
async def test_runner_poll_without_runner_id_does_not_crash_or_write() -> None:
    async with _make_client(role="owner") as (client, maker):
        res = await client.get(
            "/api/v1/msa-rtxrt/runner/poll",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
        )
        assert res.status_code == 200
        async with maker() as session:
            rows = (await session.exec(select(MsaRtxrtRunnerHeartbeat))).all()
        assert rows == []  # No id → no row written


@pytest.mark.asyncio
async def test_runner_status_endpoint_operator_can_read() -> None:
    """Operator+ can read /runner/status; structure is privacy-safe."""
    async with _make_client(role="operator") as (client, _maker):
        # Seed a heartbeat by polling once (operator token isn't valid for
        # poll — use the runner token).
        await client.get(
            "/api/v1/msa-rtxrt/runner/poll?runner_id=claw-1",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
        )
        res = await client.get("/api/v1/msa-rtxrt/runner/status")
        assert res.status_code == 200
        body = res.json()
        assert body["any_online"] is True
        assert body["freshness_seconds"] == 90
        assert len(body["runners"]) == 1
        runner = body["runners"][0]
        assert runner["runner_id"] == "claw-1"
        assert runner["status"] == "online"
        assert runner["last_status"] == "idle"
        assert runner["seconds_since_seen"] <= 90


@pytest.mark.asyncio
async def test_runner_status_endpoint_viewer_blocked() -> None:
    async with _make_client(role="viewer") as (client, _maker):
        res = await client.get("/api/v1/msa-rtxrt/runner/status")
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_runner_status_returns_empty_when_no_runners_ever_polled() -> None:
    async with _make_client(role="operator") as (client, _maker):
        res = await client.get("/api/v1/msa-rtxrt/runner/status")
        assert res.status_code == 200
        body = res.json()
        assert body["runners"] == []
        assert body["any_online"] is False


@pytest.mark.asyncio
async def test_runner_status_does_not_leak_runner_token() -> None:
    """Sanity: the runner-token value never appears in /runner/status output."""
    async with _make_client(role="operator") as (client, _maker):
        await client.get(
            "/api/v1/msa-rtxrt/runner/poll?runner_id=claw-1",
            headers={"X-MSA-RTXRT-Runner-Token": RUNNER_TOKEN},
        )
        res = await client.get("/api/v1/msa-rtxrt/runner/status")
        assert RUNNER_TOKEN not in res.text
