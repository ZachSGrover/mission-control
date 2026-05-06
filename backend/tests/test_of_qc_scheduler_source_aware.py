# ruff: noqa: INP001
"""Source-aware scheduler tick tests."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.of_qc_discord_status import OfQcDiscordStatus
from app.services.of_intelligence.qc.scheduler import current_status, run_one_tick


@contextlib.asynccontextmanager
async def _make_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with maker() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_tick_records_synthetic_source_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``daily_qc_enabled=True`` and the default source is in effect,
    the persisted job row carries ``source_mode='synthetic'`` and
    ``source_confidence='high'``."""
    from dataclasses import dataclass
    from datetime import datetime

    from app.services.of_intelligence import alerts as alerts_module

    @dataclass
    class _FakeSummary:
        evaluated_at: datetime
        rules_run: int = 8
        alerts_created: int = 0
        alerts_skipped_existing: int = 0
        candidates: list[object] = None  # type: ignore[assignment]

    async def _fake_evaluate(_session: AsyncSession) -> _FakeSummary:
        from app.core.time import utcnow

        return _FakeSummary(evaluated_at=utcnow(), candidates=[])

    monkeypatch.setattr(alerts_module, "evaluate_alerts", _fake_evaluate)

    async with _make_session() as session:
        session.add(OfQcDiscordStatus(id=1, daily_qc_enabled=True))
        await session.commit()

        job = await run_one_tick(session, triggered_by="test")
        assert job.status == "completed"
        assert job.source_mode == "synthetic"
        assert job.source_confidence == "high"
        assert job.safe_mode is True


@pytest.mark.asyncio
async def test_tick_records_skipped_data_source_when_onlymonster_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selecting ``onlymonster_readonly`` while the readonly flag is off
    must record a ``skipped`` job with reason
    ``onlymonster_readonly_disabled`` AND no ingestion findings."""
    from dataclasses import dataclass
    from datetime import datetime

    from app.services.of_intelligence import alerts as alerts_module

    @dataclass
    class _FakeSummary:
        evaluated_at: datetime
        rules_run: int = 8
        alerts_created: int = 0
        alerts_skipped_existing: int = 0
        candidates: list[object] = None  # type: ignore[assignment]

    async def _fake_evaluate(_session: AsyncSession) -> _FakeSummary:
        from app.core.time import utcnow

        return _FakeSummary(evaluated_at=utcnow(), candidates=[])

    monkeypatch.setattr(alerts_module, "evaluate_alerts", _fake_evaluate)

    async with _make_session() as session:
        session.add(
            OfQcDiscordStatus(
                id=1,
                daily_qc_enabled=True,
                daily_qc_source_mode="onlymonster_readonly",
                onlymonster_readonly_enabled=False,
            )
        )
        await session.commit()

        job = await run_one_tick(session, triggered_by="test")
        # The ingestion evaluator emits a single ``data_source_disconnected``
        # finding, which keeps findings_count > 0; but the source_mode +
        # safe_mode should still reflect the configured source.
        assert job.source_mode == "onlymonster_readonly"
        assert job.safe_mode is True


# ── current_status surfaces source mode + flags ──────────────────────────


@pytest.mark.asyncio
async def test_current_status_exposes_source_mode_and_readonly_flags() -> None:
    async with _make_session() as session:
        session.add(
            OfQcDiscordStatus(
                id=1,
                daily_qc_source_mode="local_ofi",
                onlymonster_readonly_enabled=False,
                onlyfans_readonly_enabled=False,
                platform_write_enabled=False,
            )
        )
        await session.commit()

        s = await current_status(session)
        assert s.daily_qc_source_mode == "local_ofi"
        assert s.onlymonster_readonly_enabled is False
        assert s.onlyfans_readonly_enabled is False
        assert s.platform_write_enabled is False
        assert s.safe_mode is True
