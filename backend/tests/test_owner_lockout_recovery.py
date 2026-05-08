# ruff: noqa: INP001
"""Tests for the owner self-lockout recovery patches.

Covers:
  • ``_resolve_role`` returns ``(owner, disabled=False)`` even when the
    persisted ``mc_user_roles`` row has ``disabled=True``.  Without this
    invariant a stale or accidentally-flipped flag would lock the owner
    out of every privileged endpoint, including the Users page used to
    repair the row.
  • ``set_user_role`` rejects an attempt to disable the caller's own
    account with HTTP 400 ("You cannot disable your own account.").
    Combined with the resolution bypass, this closes the loophole.
  • Non-owner roles (operator, builder, viewer) cannot list users or
    modify the allowlist — owner-only invariant is preserved.
  • ``role: "operator"`` is accepted by the allowed-users invite flow.
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

from app.api.mc_allowed_users import router as allowed_users_router
from app.api.mc_roles import (
    _resolve_role,
    get_mc_role,
    require_operator,
    require_owner,
)
from app.api.mc_roles import router as mc_roles_router
from app.core.auth import AuthContext, get_auth_context
from app.core.auth_mode import AuthMode
from app.core.config import settings
from app.db.session import get_session
from app.models.mc_role import ROLE_RANK, MCUserRole

ACTOR_ID = "u-zach-owner"
ACTOR_EMAIL = "owner@test.local"


@contextlib.asynccontextmanager
async def _make_client(
    *,
    role: str = "owner",
    actor_user_id: str = ACTOR_ID,
    actor_email: str | None = ACTOR_EMAIL,
) -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(mc_roles_router)
    api_v1.include_router(allowed_users_router)
    app.include_router(api_v1)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    async def _override_auth() -> AuthContext:
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
            yield ac, maker
    finally:
        await engine.dispose()


# ── Patch B: owner row never resolves as disabled ───────────────────────


@pytest.fixture
def _clerk_auth_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the resolution path past the AuthMode.LOCAL short-circuit.

    Local mode unconditionally returns ``(owner, False)``; we need to
    reach the DB-row branch to exercise the owner-disabled bypass and
    the non-owner-still-disabled invariant.
    """
    monkeypatch.setattr(settings, "auth_mode", AuthMode.CLERK)
    monkeypatch.setattr(settings, "owner_user_id", "")


@pytest.mark.asyncio
async def test_resolve_role_owner_with_disabled_true_returns_not_disabled(
    _clerk_auth_mode: None,
) -> None:
    """A stale ``disabled=true`` flag on an owner row must not lock them out."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with maker() as session:
            session.add(
                MCUserRole(clerk_user_id=ACTOR_ID, role="owner", disabled=True),
            )
            await session.commit()

        async with maker() as session:
            role, disabled = await _resolve_role(ACTOR_ID, session)
            assert role == "owner"
            assert disabled is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_role_non_owner_disabled_still_disabled(
    _clerk_auth_mode: None,
) -> None:
    """Bypass is owner-only — a disabled operator/builder/viewer stays disabled."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        for non_owner in ("operator", "builder", "viewer"):
            async with maker() as session:
                existing = (
                    await session.exec(
                        select(MCUserRole).where(MCUserRole.clerk_user_id == ACTOR_ID),
                    )
                ).first()
                if existing is not None:
                    await session.delete(existing)
                    await session.commit()
                session.add(
                    MCUserRole(clerk_user_id=ACTOR_ID, role=non_owner, disabled=True),
                )
                await session.commit()

            async with maker() as session:
                role, disabled = await _resolve_role(ACTOR_ID, session)
                assert role == non_owner, f"role for {non_owner}"
                assert disabled is True, f"disabled for {non_owner}"
    finally:
        await engine.dispose()


# ── Patch A: owner cannot disable themselves ────────────────────────────


@pytest.mark.asyncio
async def test_owner_cannot_disable_their_own_account() -> None:
    """Owner self-disable is rejected with a clear 400 error."""
    async with _make_client(role="owner") as (client, _maker):
        res = await client.put(
            f"/api/v1/roles/users/{ACTOR_ID}",
            json={"role": "owner", "disabled": True},
        )
        assert res.status_code == 400
        assert res.json()["detail"] == "You cannot disable your own account."


@pytest.mark.asyncio
async def test_owner_can_still_disable_another_user() -> None:
    """Disabling other accounts is unaffected."""
    async with _make_client(role="owner") as (client, _maker):
        res = await client.put(
            "/api/v1/roles/users/u-someone-else",
            json={"role": "viewer", "disabled": True},
        )
        assert res.status_code == 200, res.text
        assert res.json()["disabled"] is True


# ── Owner-only invariant on Users surfaces ──────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operator", "builder", "viewer"])
async def test_non_owner_cannot_list_role_users(role: str) -> None:
    async with _make_client(role=role) as (client, _maker):
        res = await client.get("/api/v1/roles/users")
        assert res.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operator", "builder", "viewer"])
async def test_non_owner_cannot_set_role(role: str) -> None:
    async with _make_client(role=role) as (client, _maker):
        res = await client.put(
            "/api/v1/roles/users/u-target",
            json={"role": "operator", "disabled": False},
        )
        assert res.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operator", "builder", "viewer"])
async def test_non_owner_cannot_list_allowed_users(role: str) -> None:
    async with _make_client(role=role) as (client, _maker):
        res = await client.get("/api/v1/allowed-users")
        assert res.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["operator", "builder", "viewer"])
async def test_non_owner_cannot_invite_allowed_user(role: str) -> None:
    async with _make_client(role=role) as (client, _maker):
        res = await client.post(
            "/api/v1/allowed-users",
            json={"email": "newcomer@test.local", "role": "viewer"},
        )
        assert res.status_code == 403


# ── Operator role accepted by invite flow ───────────────────────────────


@pytest.mark.asyncio
async def test_invite_flow_accepts_operator_role() -> None:
    """The COO is invited as 'operator' — verify the API accepts it."""
    async with _make_client(role="owner") as (client, _maker):
        res = await client.post(
            "/api/v1/allowed-users",
            json={"email": "coo@test.local", "role": "operator"},
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["email"] == "coo@test.local"
        assert body["role"] == "operator"
        assert body["pending"] is True
