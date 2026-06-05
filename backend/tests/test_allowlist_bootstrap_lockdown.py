# ruff: noqa: INP001
"""Regression tests for the allowlist bootstrap bypass.

Bug: when an owner is configured via ``OWNER_USER_ID`` (the normal hosted
setup), the env-owner bypass returned without seeding an ``mc_allowed_users``
row. The table stayed empty, so the bootstrap branch ("empty allowlist → admit
the first caller") then silently admitted the next *stranger* with full access.

These tests pin the fail-closed behavior:
  • A stranger is denied (403) when an env owner is configured, even with an
    empty allowlist.
  • A stranger is denied when a DB owner role exists, even with an empty
    allowlist.
  • The env owner is seeded into the allowlist on first sign-in.
  • Genuine first-run bootstrap (no owner anywhere) still admits the first
    caller — the legitimate self-hosted setup path.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth import _check_allowlist
from app.core.config import settings
from app.models.mc_allowed_user import MCAllowedUser
from app.models.mc_role import MCUserRole

OWNER_ID = "u-owner"
STRANGER_ID = "u-stranger"


@contextlib.asynccontextmanager
async def _session() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield maker
    finally:
        await engine.dispose()


async def _allowlist_ids(maker: async_sessionmaker[AsyncSession]) -> set[str | None]:
    async with maker() as session:
        rows = (await session.exec(select(MCAllowedUser))).all()
        return {row.clerk_user_id for row in rows}


@pytest.mark.asyncio
async def test_stranger_denied_when_env_owner_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty allowlist + env owner set → stranger is denied, not bootstrapped in."""
    monkeypatch.setattr(settings, "owner_user_id", OWNER_ID)
    async with _session() as maker, maker() as session:
        with pytest.raises(HTTPException) as exc:
            await _check_allowlist(session, STRANGER_ID, email="stranger@x.com")
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_stranger_denied_when_db_owner_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty allowlist + a DB owner role → stranger is denied."""
    monkeypatch.setattr(settings, "owner_user_id", "")
    async with _session() as maker:
        async with maker() as session:
            session.add(MCUserRole(clerk_user_id=OWNER_ID, role="owner", disabled=False))
            await session.commit()
        async with maker() as session:
            with pytest.raises(HTTPException) as exc:
                await _check_allowlist(session, STRANGER_ID, email="stranger@x.com")
            assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_env_owner_is_seeded_into_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env owner's first sign-in seeds a row so the table is never falsely empty."""
    monkeypatch.setattr(settings, "owner_user_id", OWNER_ID)
    async with _session() as maker:
        async with maker() as session:
            await _check_allowlist(session, OWNER_ID, email="owner@x.com")
        assert OWNER_ID in await _allowlist_ids(maker)


@pytest.mark.asyncio
async def test_genuine_first_run_bootstrap_still_admits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No owner anywhere + empty allowlist → first caller is admitted (legit path)."""
    monkeypatch.setattr(settings, "owner_user_id", "")
    async with _session() as maker:
        async with maker() as session:
            await _check_allowlist(session, STRANGER_ID, email="first@x.com")
        assert STRANGER_ID in await _allowlist_ids(maker)
