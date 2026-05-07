"""Smoke test for the /api/v1/security/status admin endpoint.

We exercise the route handler directly (not through the FastAPI test
client) because the project's existing fixtures are minimal and we
only want to verify the response shape, the missing-prerequisite
hints, and that no secrets leak. Auth is bypassed by passing a
fabricated ``AuthContext``.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401  — registers tables
from app.api.security_admin import security_status
from app.core.auth import AuthContext
from app.services import connector_approvals as approvals_svc
from app.services import consent as consent_svc
from app.services import kill_switch as kill_switch_svc


async def _engine() -> AsyncEngine:
    e = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with e.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return e


async def _session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


def _ctx() -> AuthContext:
    # No user attached — covers the "system caller" path.
    return AuthContext(actor_type="user", user=None)


@pytest.mark.asyncio
async def test_security_status_empty_state_flags_missing_prereqs() -> None:
    os.environ.pop("SETTINGS_ENCRYPTION_KEY", None)
    from app.core import secrets_store as _ss

    _ss._fernet = None  # type: ignore[attr-defined]

    engine = await _engine()
    try:
        async with await _session(engine) as session:
            res = await security_status(_ctx(), "owner", session)

            assert res.encryption_key_dedicated is False
            assert res.kill_switches == []
            assert res.approvals_pending == 0
            assert res.approvals_approved_live == 0
            assert res.consents_granted_live == 0
            assert res.creator_credentials_active == 0

            joined = " | ".join(res.missing_prerequisites)
            assert "SETTINGS_ENCRYPTION_KEY" in joined
            assert "creator credentials" in joined
            assert "client consents" in joined
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_security_status_reports_kill_switch_and_counts() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            # populate some state
            row = await approvals_svc.request_approval(
                session,
                connector_type="onlymonster",
                requested_action="creator_sync",
                creator_id="creator-A",
            )
            await approvals_svc.approve(session, row.id)
            await consent_svc.grant(
                session,
                consent_type="onlymonster_sync",
                creator_id="creator-A",
            )
            await kill_switch_svc.enable(session, scope="connector", scope_id="onlyfans_direct")
            await session.commit()

            res = await security_status(_ctx(), "owner", session)

            scopes = {(s.scope, s.scope_id, s.enabled) for s in res.kill_switches}
            assert ("connector", "onlyfans_direct", True) in scopes
            assert res.approvals_approved_live >= 1
            assert res.consents_granted_live >= 1
            assert res.audit_events_7d >= 3  # at least: request, approve, consent, KS
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_security_status_response_does_not_include_raw_metadata() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            await approvals_svc.request_approval(
                session,
                connector_type="discord",
                requested_action="connect",
                requested_by_email="alice@example.com",
            )
            await session.commit()
            res = await security_status(_ctx(), "owner", session)
            text = res.model_dump_json()
            # No actor email leaks through the aggregate response.
            assert "alice@example.com" not in text
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_security_status_records_dedicated_key_when_set() -> None:
    os.environ["SETTINGS_ENCRYPTION_KEY"] = "0" * 64
    from app.core import secrets_store as _ss

    _ss._fernet = None  # type: ignore[attr-defined]

    engine = await _engine()
    try:
        async with await _session(engine) as session:
            res = await security_status(_ctx(), "owner", session)
            assert res.encryption_key_dedicated is True
            joined = " | ".join(res.missing_prerequisites)
            assert "SETTINGS_ENCRYPTION_KEY" not in joined
    finally:
        os.environ.pop("SETTINGS_ENCRYPTION_KEY", None)
        _ss._fernet = None  # type: ignore[attr-defined]
        await engine.dispose()
