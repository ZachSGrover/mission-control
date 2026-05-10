# ruff: noqa: INP001
"""Owner-gate tests for /api/v1/git/save.

The git save endpoint stages, commits, and pushes to origin/main. Until a
proper build-request and approval flow exists, only the owner may trigger it.

These tests verify:
  • owner can call /api/v1/git/save (gate passes; underlying behavior runs)
  • operator is denied at the gate (403)
  • builder is denied at the gate (403)
  • viewer is denied at the gate (403)
  • unauthenticated user is denied (401)
  • the gate runs *before* any git work or credential lookup
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.git_save import SaveResponse
from app.api.git_save import router as git_save_router
from app.api.mc_roles import get_mc_role, require_owner
from app.core.auth import AuthContext, get_auth_context
from app.db.session import get_session

# ── Test client builder ──────────────────────────────────────────────────


@contextlib.asynccontextmanager
async def _make_client(
    *,
    role: str | None = "owner",
    actor_user_id: str = "u-test-owner",
) -> AsyncIterator[tuple[AsyncClient, dict[str, Any]]]:
    """Build a FastAPI app with only the git_save router mounted.

    Set ``role=None`` to simulate an unauthenticated caller — the auth
    dependency raises 401 before role resolution runs.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    app = FastAPI()
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(git_save_router)
    app.include_router(api_v1)

    # Track whether the underlying handler executed beyond the gate.
    state: dict[str, Any] = {"handler_invoked": False}

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    async def _override_auth() -> AuthContext:
        if role is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        from app.models.users import User

        user = User(
            clerk_user_id=actor_user_id,
            email="actor@test.local",
            name="Test Actor",
        )
        return AuthContext(actor_type="user", user=user)

    async def _override_role() -> str:
        if role is None:
            # Should never reach here — auth raises 401 first.
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return role

    async def _override_owner_dep(resolved_role: str = role or "viewer") -> str:
        # Mirror the behavior of the real require_owner dependency.
        if role is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if role != "owner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Owner access required.",
            )
        return "owner"

    # Stub the heavy git work so the test never shells out and never reads
    # secrets. If the gate is correctly applied, only owner reaches this stub.
    def _fake_do_save(_pat: str, _username: str, _repo: str) -> SaveResponse:
        state["handler_invoked"] = True
        return SaveResponse(
            status="no_changes",
            message="stubbed — gate passed",
        )

    # Also stub get_secret so tests cannot accidentally read environment
    # variables or the secrets store.
    async def _fake_get_secret(*_args: Any, **kwargs: Any) -> str:
        # Return whatever fallback the caller passed, or empty string.
        return str(kwargs.get("fallback", ""))

    import app.api.git_save as git_save_mod

    original_do_save = git_save_mod._do_save
    original_get_secret = git_save_mod.get_secret
    git_save_mod._do_save = _fake_do_save  # type: ignore[assignment]
    git_save_mod.get_secret = _fake_get_secret  # type: ignore[assignment]

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_auth_context] = _override_auth
    app.dependency_overrides[get_mc_role] = _override_role
    app.dependency_overrides[require_owner] = _override_owner_dep

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, state
    finally:
        git_save_mod._do_save = original_do_save  # type: ignore[assignment]
        git_save_mod.get_secret = original_get_secret  # type: ignore[assignment]
        await engine.dispose()


# ── Owner allowed ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_git_save_owner_allowed() -> None:
    async with _make_client(role="owner") as (client, state):
        res = await client.post("/api/v1/git/save")
        assert res.status_code == 200, res.text
        body = res.json()
        # Underlying handler ran (stub returned no_changes).
        assert body["status"] == "no_changes"
        assert state["handler_invoked"] is True


# ── Non-owner denied ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_git_save_operator_denied() -> None:
    async with _make_client(role="operator") as (client, state):
        res = await client.post("/api/v1/git/save")
        assert res.status_code == 403
        # Gate must short-circuit before the handler executes.
        assert state["handler_invoked"] is False


@pytest.mark.asyncio
async def test_git_save_builder_denied() -> None:
    async with _make_client(role="builder") as (client, state):
        res = await client.post("/api/v1/git/save")
        assert res.status_code == 403
        assert state["handler_invoked"] is False


@pytest.mark.asyncio
async def test_git_save_viewer_denied() -> None:
    async with _make_client(role="viewer") as (client, state):
        res = await client.post("/api/v1/git/save")
        assert res.status_code == 403
        assert state["handler_invoked"] is False


@pytest.mark.asyncio
async def test_git_save_unauthenticated_denied() -> None:
    async with _make_client(role=None) as (client, state):
        res = await client.post("/api/v1/git/save")
        assert res.status_code == 401
        assert state["handler_invoked"] is False


# ── Sanity: owner gate is wired via require_owner ────────────────────────


def test_git_save_route_uses_require_owner_dependency() -> None:
    """Static check: the /git/save route must depend on require_owner.

    Catches accidental future regressions where someone replaces the gate
    with AUTH_DEP (signed-in only) again.
    """
    target = next(
        (r for r in git_save_router.routes if getattr(r, "path", None) == "/git/save"),
        None,
    )
    assert target is not None, "git_save_router missing /git/save route"
    deps = getattr(target, "dependant", None)
    assert deps is not None
    # Walk every parameter dependency on the endpoint and confirm
    # require_owner is present somewhere in the dependency tree.
    seen: list[Any] = []

    def _collect(d: Any) -> None:
        for sub in getattr(d, "dependencies", []) or []:
            seen.append(sub.call)
            _collect(sub)
        # Endpoint params with Depends(...) show up as sub_dependencies too.
        for sub in getattr(d, "params", []) or []:
            call = getattr(sub, "call", None)
            if call is not None:
                seen.append(call)

    _collect(deps)
    # Direct param-level Depends — easier path: inspect endpoint signature.
    import inspect

    sig = inspect.signature(target.endpoint)
    for param in sig.parameters.values():
        default = param.default
        # FastAPI Depends stores the dependency callable on .dependency
        dep_callable = getattr(default, "dependency", None)
        if dep_callable is not None:
            seen.append(dep_callable)

    assert require_owner in seen, (
        f"/git/save must depend on require_owner; saw: "
        f"{[getattr(c, '__name__', repr(c)) for c in seen]}"
    )
