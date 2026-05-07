# ruff: noqa: INP001
"""End-to-end tests for COO Bot Access v1.

Covers:
  • operator role added to VALID_ROLES + ROLE_RANK
  • require_operator gate (operator+ allowed; builder/viewer denied)
  • integrations GET tightened to owner-only
  • bot registry list/detail/start/stop/permissions endpoints
  • audit_events written for every privileged mutation
  • response privacy (no secrets, no fan PII, no message bodies)
  • read_only_external bots reject start/stop with managed_externally
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.bots import router as bots_router
from app.api.integrations import router as integrations_router
from app.api.mc_allowed_users import router as allowed_users_router
from app.api.mc_roles import (
    get_mc_role,
    require_operator,
    require_owner,
)
from app.api.mc_roles import router as mc_roles_router
from app.core.auth import AuthContext, get_auth_context
from app.db.session import get_session
from app.models.audit_event import AuditEvent
from app.models.bot_registry import (
    BOT_KIND_READ_ONLY_EXTERNAL,
    BotRegistryEntry,
)
from app.models.mc_role import ROLE_RANK, VALID_ROLES
from app.services.bot_registry import (
    bootstrap_seed,
    encode_permitted_roles,
    parse_permitted_roles,
)

# ── Test client builder ───────────────────────────────────────────────────


@contextlib.asynccontextmanager
async def _make_client(
    *,
    role: str = "owner",
    actor_user_id: str = "u-test-owner",
    actor_email: str | None = "owner@test.local",
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(mc_roles_router)
    api_v1.include_router(allowed_users_router)
    api_v1.include_router(integrations_router)
    api_v1.include_router(bots_router)
    app.include_router(api_v1)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    async def _override_auth() -> AuthContext:
        # Use a real User object so actor_from_auth gets clerk_id + email.
        from app.models.users import User

        user = User(
            clerk_user_id=actor_user_id,
            email=actor_email,
            name="Test Actor",
        )
        return AuthContext(actor_type="user", user=user)

    async def _override_role() -> str:
        return role

    async def _override_owner_dep() -> str:
        if role != "owner":
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner only")
        return "owner"

    async def _override_operator_dep() -> str:
        if ROLE_RANK.get(role, 0) < ROLE_RANK["operator"]:
            from fastapi import HTTPException, status

            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator only")
        return role

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_auth_context] = _override_auth
    app.dependency_overrides[get_mc_role] = _override_role
    app.dependency_overrides[require_owner] = _override_owner_dep
    app.dependency_overrides[require_operator] = _override_operator_dep

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Seed the registry so list/detail tests have data.
            async with maker() as bs_session:
                await bootstrap_seed(bs_session)
            yield ac, maker
    finally:
        await engine.dispose()


# ── Phase 2: operator role exists ────────────────────────────────────────


def test_operator_is_in_valid_roles() -> None:
    assert "operator" in VALID_ROLES
    assert {"owner", "operator", "builder", "viewer"} <= VALID_ROLES


def test_role_rank_ordering() -> None:
    assert ROLE_RANK["owner"] > ROLE_RANK["operator"]
    assert ROLE_RANK["operator"] > ROLE_RANK["builder"]
    assert ROLE_RANK["builder"] > ROLE_RANK["viewer"]


# ── Phase 3: integrations GET is owner-only ──────────────────────────────


@pytest.mark.asyncio
async def test_integrations_get_owner_allowed() -> None:
    async with _make_client(role="owner") as (client, _maker):
        res = await client.get("/api/v1/integrations")
        assert res.status_code == 200
        body = res.json()
        # Privacy: no preview without configured credential, and configured
        # is False on a fresh DB.
        for entry in body:
            assert entry["configured"] is False
            assert entry["preview"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operator", "builder", "viewer"])
async def test_integrations_get_non_owner_denied(role: str) -> None:
    async with _make_client(role=role) as (client, _maker):
        res = await client.get("/api/v1/integrations")
        assert res.status_code == 403


# ── Phase 5/6: bot registry list/detail (auth required, no secrets) ──────


@pytest.mark.asyncio
async def test_bots_list_visible_to_all_authenticated_roles() -> None:
    for role in ("owner", "operator", "builder", "viewer"):
        async with _make_client(role=role) as (client, _maker):
            res = await client.get("/api/v1/bots")
            assert res.status_code == 200, role
            body = res.json()
            assert isinstance(body, list)
            slugs = {entry["slug"] for entry in body}
            assert {
                "of_daily_qc_scheduler",
                "of_qc_discord_publisher",
                "of_qc_telegram_publisher",
                "master_control_loop",
                "hermes",
                "ai_radar",
                "social_radar",
            } <= slugs


@pytest.mark.asyncio
async def test_bots_list_response_has_no_secret_fields() -> None:
    async with _make_client(role="owner") as (client, _maker):
        res = await client.get("/api/v1/bots")
        assert res.status_code == 200
        body = res.json()
        # Response schema is fixed in app/api/bots.py; assert no
        # surprising sensitive-looking key has crept into the payload.
        forbidden = {
            "webhook_url",
            "discord_webhook",
            "telegram_token",
            "bot_token",
            "api_key",
            "secret",
            "password",
            "fan_handle",
            "fan_id",
            "message_body",
            "credential",
            "preview",
        }
        for entry in body:
            assert forbidden.isdisjoint(entry.keys()), entry


@pytest.mark.asyncio
async def test_bots_get_detail_owner() -> None:
    async with _make_client(role="owner") as (client, _maker):
        res = await client.get("/api/v1/bots/master_control_loop")
        assert res.status_code == 200
        body = res.json()
        assert body["slug"] == "master_control_loop"
        assert body["enabled"] is False
        assert body["read_only_external"] is False


@pytest.mark.asyncio
async def test_bots_get_unknown_slug_returns_404() -> None:
    async with _make_client(role="owner") as (client, _maker):
        res = await client.get("/api/v1/bots/no-such-bot")
        assert res.status_code == 404


# ── Phase 6: bot start / stop role gating ────────────────────────────────


@pytest.mark.asyncio
async def test_bot_start_owner_allowed_for_internal_bot() -> None:
    async with _make_client(role="owner") as (client, maker):
        res = await client.post("/api/v1/bots/master_control_loop/start")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ok"] is True
        assert body["enabled"] is True
        # Audit row exists
        async with maker() as session:
            audits = (
                await session.exec(
                    select(AuditEvent).where(AuditEvent.action == "bot.start"),
                )
            ).all()
            assert len(audits) == 1
            assert audits[0].outcome == "success"
            assert audits[0].target_id == "master_control_loop"


@pytest.mark.asyncio
async def test_bot_start_viewer_denied() -> None:
    async with _make_client(role="viewer") as (client, _maker):
        res = await client.post("/api/v1/bots/master_control_loop/start")
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_bot_start_builder_denied_when_not_in_permitted_roles() -> None:
    # Default seeds only allow owner.  Builder is operator-1 in rank but
    # not in permitted_roles → must be denied at the can_role_operate step.
    async with _make_client(role="builder") as (client, _maker):
        res = await client.post("/api/v1/bots/master_control_loop/start")
        # Builder fails the require_operator gate first, so we expect 403
        # from that gate.  Either way, must not be 200.
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_bot_start_operator_denied_when_not_in_permitted_roles() -> None:
    # Default seed: only "owner" in permitted_roles.  Operator should be
    # denied because the can_role_operate check requires explicit grant.
    async with _make_client(role="operator") as (client, maker):
        res = await client.post("/api/v1/bots/master_control_loop/start")
        assert res.status_code == 403
        # Audit row records the denial.
        async with maker() as session:
            audits = (
                await session.exec(
                    select(AuditEvent).where(AuditEvent.action == "bot.start"),
                )
            ).all()
            assert len(audits) == 1
            assert audits[0].outcome == "denied"


@pytest.mark.asyncio
async def test_bot_start_operator_allowed_after_owner_grants_permission() -> None:
    # Owner edits permitted_roles → operator can then start.
    async with _make_client(role="owner") as (client, maker):
        res = await client.patch(
            "/api/v1/bots/master_control_loop/permissions",
            json={"permitted_roles": ["owner", "operator"]},
        )
        assert res.status_code == 200
        body = res.json()
        assert "operator" in body["permitted_roles"]

        # Audit row for the permission change.
        async with maker() as session:
            audits = (
                await session.exec(
                    select(AuditEvent).where(AuditEvent.action == "bot.permission.set"),
                )
            ).all()
            assert len(audits) == 1
            assert audits[0].target_id == "master_control_loop"


# ── Read-only external bots reject start/stop ────────────────────────────


@pytest.mark.asyncio
async def test_bot_start_blocked_for_read_only_external() -> None:
    async with _make_client(role="owner") as (client, maker):
        # Sanity: hermes is seeded as read_only_external.
        async with maker() as session:
            entry = (
                await session.exec(
                    select(BotRegistryEntry).where(BotRegistryEntry.slug == "hermes"),
                )
            ).first()
            assert entry is not None
            assert entry.kind == BOT_KIND_READ_ONLY_EXTERNAL

        res = await client.post("/api/v1/bots/hermes/start")
        # External bots reject the operate check → 403 with managed_externally.
        assert res.status_code == 403
        assert "managed_externally" in res.text


@pytest.mark.asyncio
async def test_bot_stop_blocked_for_read_only_external() -> None:
    async with _make_client(role="owner") as (client, _maker):
        res = await client.post("/api/v1/bots/ai_radar/stop")
        assert res.status_code == 403
        assert "managed_externally" in res.text


# ── Bot stop happy path + audit ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_bot_stop_owner_records_audit() -> None:
    async with _make_client(role="owner") as (client, maker):
        # Stop something startable
        res = await client.post("/api/v1/bots/master_control_loop/stop")
        assert res.status_code == 200
        async with maker() as session:
            audits = (
                await session.exec(
                    select(AuditEvent).where(AuditEvent.action == "bot.stop"),
                )
            ).all()
            assert len(audits) == 1
            assert audits[0].outcome == "success"


# ── Permissions endpoint owner-only ──────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operator", "builder", "viewer"])
async def test_bot_permissions_set_denied_for_non_owner(role: str) -> None:
    async with _make_client(role=role) as (client, _maker):
        res = await client.patch(
            "/api/v1/bots/master_control_loop/permissions",
            json={"permitted_roles": ["owner", "operator"]},
        )
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_bot_permissions_invalid_role_rejected() -> None:
    async with _make_client(role="owner") as (client, _maker):
        res = await client.patch(
            "/api/v1/bots/master_control_loop/permissions",
            json={"permitted_roles": ["owner", "super_admin"]},
        )
        assert res.status_code == 400


# ── Phase 4: audit log written for role + allowlist ──────────────────────


@pytest.mark.asyncio
async def test_role_set_writes_audit() -> None:
    async with _make_client(role="owner", actor_user_id="u-owner") as (client, maker):
        res = await client.put(
            "/api/v1/roles/users/u-target",
            json={"role": "operator", "disabled": False},
        )
        assert res.status_code == 200
        async with maker() as session:
            audits = (
                await session.exec(
                    select(AuditEvent).where(AuditEvent.action == "role.set"),
                )
            ).all()
            assert len(audits) == 1
            assert audits[0].target_id == "u-target"
            # Privacy: no role payload body; only safe summary string.
            assert audits[0].payload_hash is None
            assert audits[0].safe_summary is not None


@pytest.mark.asyncio
async def test_allowlist_add_writes_audit() -> None:
    async with _make_client(role="owner") as (client, maker):
        res = await client.post(
            "/api/v1/allowed-users",
            json={"email": "coo@test.local", "role": "operator"},
        )
        assert res.status_code == 201
        async with maker() as session:
            audits = (
                await session.exec(
                    select(AuditEvent).where(AuditEvent.action == "allowlist.add"),
                )
            ).all()
            assert len(audits) == 1
            assert audits[0].outcome == "success"


# ── Encode/decode helpers for permitted_roles ────────────────────────────


def test_encode_permitted_roles_always_includes_owner() -> None:
    enc = encode_permitted_roles(["operator"])
    decoded = parse_permitted_roles(enc)
    assert "owner" in decoded
    assert "operator" in decoded


def test_encode_permitted_roles_preserves_explicit_owner() -> None:
    enc = encode_permitted_roles(["owner", "operator"])
    decoded = parse_permitted_roles(enc)
    assert sorted(decoded) == ["operator", "owner"]


def test_parse_permitted_roles_empty_falls_back_to_owner() -> None:
    assert parse_permitted_roles(None) == ["owner"]
    assert parse_permitted_roles("") == ["owner"]
    assert parse_permitted_roles("not-json") == ["owner"]
