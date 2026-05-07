"""Tests for app.services.audit_log.record_audit.

Mirrors the in-memory SQLite pattern from
``test_organizations_service.py`` / ``test_task_agent_permissions.py``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

# Ensure all models are registered with SQLModel.metadata.
import app.models  # noqa: F401  (registration side-effect)
from app.models.audit_event import AuditEvent
from app.services.audit_log import record_audit_event


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


async def _make_session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_record_audit_writes_a_row() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            user_id = uuid4()
            event = await record_audit_event(
                session,
                event_type="credential.save",
                category="credential",
                action="put",
                result="success",
                severity="info",
                actor_user_id=user_id,
                actor_email="alice@example.com",
                resource_type="integration",
                resource_id="onlymonster",
            )
            await session.commit()

            assert event is not None
            assert event.id is not None
            rows = (await session.exec(select(AuditEvent))).all()
            assert len(rows) == 1
            row = rows[0]
            assert row.actor_user_id == user_id
            assert row.actor_email == "alice@example.com"
            assert row.event_type == "credential.save"
            assert row.category == "credential"
            assert row.result == "success"
            assert row.redacted is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_record_audit_redacts_metadata() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            await record_audit_event(
                session,
                event_type="credential.save",
                category="credential",
                action="put",
                result="success",
                metadata={"provider": "onlymonster", "api_key": "super-secret"},
            )
            await session.commit()

            row = (await session.exec(select(AuditEvent))).one()
            assert row.redacted is True
            assert row.metadata_json["provider"] == "onlymonster"
            assert row.metadata_json["api_key"] == "[REDACTED]"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_record_audit_rejects_unknown_category() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            event = await record_audit_event(
                session,
                event_type="nope",
                category="nonsense",  # type: ignore[arg-type]
                action="x",
                result="success",
            )
            await session.commit()
            assert event is None
            rows = (await session.exec(select(AuditEvent))).all()
            assert rows == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_record_audit_strict_raises_on_unknown_category() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            with pytest.raises(ValueError):
                await record_audit_event(
                    session,
                    event_type="nope",
                    category="nonsense",  # type: ignore[arg-type]
                    action="x",
                    result="success",
                    strict=True,
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_record_audit_does_not_commit() -> None:
    engine = await _make_engine()
    try:
        async with await _make_session(engine) as session:
            await record_audit_event(
                session,
                event_type="auth.login",
                category="auth",
                action="login",
                result="success",
            )
            # Without commit, a *new* session should see no rows.
            await session.rollback()
            rows = (await session.exec(select(AuditEvent))).all()
            assert rows == []
    finally:
        await engine.dispose()
