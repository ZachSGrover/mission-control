# ruff: noqa: INP001
"""Unit tests for the internal usage logger and its provider wiring."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.usage import UsageEvent
from app.services.usage.logger import (
    extract_provider_usage,
    record_usage_event,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


async def _make_engine() -> AsyncEngine:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return engine


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = await _make_engine()
    Sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Sessionmaker() as s:
        yield s
    await engine.dispose()


# ── record_usage_event ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_usage_event_creates_row(session: AsyncSession) -> None:
    started = utcnow()
    ended = started + timedelta(seconds=1)
    event = await record_usage_event(
        session,
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=100,
        output_tokens=50,
        feature="messaging",
        trigger_source="telegram",
        environment="local",
        started_at=started,
        ended_at=ended,
    )
    assert event is not None
    rows = list((await session.exec(select(UsageEvent))).all())
    assert len(rows) == 1
    row = rows[0]
    assert row.provider == "openai"
    assert row.model == "gpt-4o-mini"
    assert row.input_tokens == 100
    assert row.output_tokens == 50
    assert row.total_tokens == 150
    assert row.feature == "messaging"
    assert row.trigger_source == "telegram"
    assert row.environment == "local"
    assert row.duration_ms is not None and row.duration_ms >= 1000


@pytest.mark.asyncio
async def test_record_usage_event_handles_missing_tokens(session: AsyncSession) -> None:
    """Tokens default to 0 when omitted; cost is also 0."""
    event = await record_usage_event(
        session,
        provider="anthropic",
        model="claude-haiku-4-5",
        feature="messaging",
        trigger_source="telegram",
    )
    assert event is not None
    assert event.input_tokens == 0
    assert event.output_tokens == 0
    assert event.total_tokens == 0
    assert event.estimated_cost_usd == 0.0


@pytest.mark.asyncio
async def test_record_usage_event_handles_unknown_model(session: AsyncSession) -> None:
    """Unknown model → cost defaults to 0; row still written."""
    event = await record_usage_event(
        session,
        provider="openai",
        model="some-future-model-not-in-pricing-table",
        input_tokens=500,
        output_tokens=100,
        feature="synthesize",
        trigger_source="synthesize",
    )
    assert event is not None
    assert event.estimated_cost_usd == 0.0  # unknown_model_price


@pytest.mark.asyncio
async def test_record_usage_event_does_not_store_prompt_or_response(
    session: AsyncSession,
) -> None:
    """The schema has no column that could hold prompt/response bodies."""
    await record_usage_event(
        session,
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=10,
        output_tokens=10,
        feature="messaging",
        trigger_source="telegram",
    )
    row = (await session.exec(select(UsageEvent))).one()
    # Verify every populated column is structural metadata, not free-form text.
    safe_text_columns = {
        "project",
        "feature",
        "agent_name",
        "provider",
        "model",
        "status",
        "error",
        "trigger_source",
        "environment",
        "request_id",
    }
    for col_name, value in row.model_dump().items():
        if isinstance(value, str) and col_name not in safe_text_columns:
            pytest.fail(
                f"Unexpected free-form text column '{col_name}'={value!r} — would risk body leakage."
            )


@pytest.mark.asyncio
async def test_record_usage_event_swallows_failures() -> None:
    """A broken session must not propagate the exception."""

    class BrokenSession:
        def add(self, *_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("simulated internal failure")

        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

        async def refresh(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    result = await record_usage_event(
        BrokenSession(),  # type: ignore[arg-type]
        provider="openai",
        model="gpt-4o",
        feature="messaging",
        trigger_source="telegram",
    )
    assert result is None


# ── extract_provider_usage ───────────────────────────────────────────────────


def test_extract_anthropic_usage() -> None:
    resp = SimpleNamespace(usage=SimpleNamespace(input_tokens=42, output_tokens=17))
    assert extract_provider_usage("anthropic", resp) == (42, 17)


def test_extract_openai_usage() -> None:
    resp = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=42, completion_tokens=17))
    assert extract_provider_usage("openai", resp) == (42, 17)


def test_extract_gemini_usage() -> None:
    resp = SimpleNamespace(
        usage_metadata=SimpleNamespace(prompt_token_count=42, candidates_token_count=17)
    )
    assert extract_provider_usage("gemini", resp) == (42, 17)


def test_extract_provider_usage_missing() -> None:
    """Response without usage field → (0, 0), no exception."""
    resp = SimpleNamespace()
    assert extract_provider_usage("openai", resp) == (0, 0)
    assert extract_provider_usage("anthropic", resp) == (0, 0)
    assert extract_provider_usage("gemini", resp) == (0, 0)


def test_extract_provider_usage_unknown_provider() -> None:
    assert extract_provider_usage("unknown-provider", SimpleNamespace()) == (0, 0)


# ── ai_backend wiring ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ai_backend_call_openai_records_on_success(session: AsyncSession) -> None:
    from app.core import ai_backend

    fake_completion = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22),
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=fake_completion))
        )
    )
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        reply = await ai_backend._call_openai(
            "hello", "fake-key", session, trigger_source="telegram"
        )
    assert reply == "ok"
    rows = list((await session.exec(select(UsageEvent))).all())
    assert len(rows) == 1
    assert rows[0].provider == "openai"
    assert rows[0].input_tokens == 11
    assert rows[0].output_tokens == 22
    assert rows[0].status == "ok"
    assert rows[0].trigger_source == "telegram"
    assert rows[0].feature == "messaging"


@pytest.mark.asyncio
async def test_ai_backend_call_openai_records_error_and_raises(session: AsyncSession) -> None:
    from app.core import ai_backend

    class _SimulatedFailure(RuntimeError):
        pass

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(side_effect=_SimulatedFailure("boom")))
        )
    )
    with patch("openai.AsyncOpenAI", return_value=fake_client):
        with pytest.raises(_SimulatedFailure):
            await ai_backend._call_openai("hello", "fake-key", session, trigger_source="discord")

    rows = list((await session.exec(select(UsageEvent))).all())
    assert len(rows) == 1
    assert rows[0].status == "error"
    assert rows[0].error == "_SimulatedFailure"
    assert rows[0].trigger_source == "discord"
    assert rows[0].input_tokens == 0
    assert rows[0].output_tokens == 0
