# ruff: noqa: INP001
"""Manual / sanitized Daily-QC import tests.

Proves the offline import → existing-detectors → report path works, is
privacy-safe, never calls a live connector, never performs write actions
against a real system, and is idempotent on re-import.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.of_intelligence import OfIntelligenceMessage
from app.services.of_intelligence.qc.manual_import import (
    EXCERPT_CAP,
    REPORT_EXCERPT_CAP,
    SOURCE_MANUAL,
    ManualImportError,
    load_batch,
    parse_csv,
    parse_json,
    run_manual_import,
)

FIXTURES = Path(__file__).resolve().parents[1] / "app/services/of_intelligence/qc/fixtures"


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


def _json_batch():
    return parse_json((FIXTURES / "manual_sample.json").read_text())


def _csv_batch():
    return parse_csv((FIXTURES / "manual_sample.csv").read_text())


# 1. Sample import works (JSON + CSV).
@pytest.mark.asyncio
async def test_json_sample_import_runs():
    async with _make_session() as session:
        report = await run_manual_import(session, _json_batch())
    assert report["counts"]["messages_processed"] == 12
    assert report["load"]["messages_loaded"] == 12
    assert report["counts"]["accounts"] == 2


@pytest.mark.asyncio
async def test_csv_sample_import_runs():
    async with _make_session() as session:
        report = await run_manual_import(session, _csv_batch())
    assert report["load"]["messages_loaded"] == 7
    assert report["counts"]["accounts"] == 2


# 2. No live connectors are called (no socket allowed during a run).
@pytest.mark.asyncio
async def test_no_network_access(monkeypatch):
    import socket

    def _boom(*_a, **_k):  # pragma: no cover - only fires on violation
        raise AssertionError("manual import must not open a network socket")

    monkeypatch.setattr(socket.socket, "connect", _boom)
    monkeypatch.setattr(socket.socket, "connect_ex", _boom)
    async with _make_session() as session:
        report = await run_manual_import(session, _json_batch())
    assert report["live_connection"] is False
    assert report["safe_mode"] is True


# 3. No write actions happen against any real system — only the manual source
#    is written, and only into the throwaway session we control.
@pytest.mark.asyncio
async def test_only_manual_source_written():
    async with _make_session() as session:
        await run_manual_import(session, _json_batch())
        rows = (await session.exec(select(OfIntelligenceMessage))).all()
    assert rows
    assert all(r.source == SOURCE_MANUAL for r in rows)


# 4. Real secrets are not required — and credential-like fields are rejected.
@pytest.mark.asyncio
async def test_rejects_credential_like_fields():
    bad = '{"records": [{"creator_alias": "x", "direction": "in", "cookie": "abc"}]}'
    with pytest.raises(ManualImportError):
        parse_json(bad)


# 5. Detectors produce findings from the sample.
@pytest.mark.asyncio
async def test_detectors_produce_findings():
    async with _make_session() as session:
        report = await run_manual_import(session, _json_batch())
    assert report["counts"]["findings_total"] > 0
    # The sample intentionally contains a refund line, a rude reply, buying
    # signals, objections, content requests, and a revenue baseline drop.
    assert report["safety_privacy"], "expected a refund/safety finding"
    assert report["missed_sales"], "expected missed-sales findings"
    assert report["chatter_quality"], "expected a rude-reply finding"
    assert report["content_requests"], "expected content-request findings"


# 6. Report/API returns structured results with all sections present.
@pytest.mark.asyncio
async def test_report_shape():
    async with _make_session() as session:
        report = await run_manual_import(session, _json_batch())
    for key in (
        "summary",
        "chatter_quality",
        "missed_sales",
        "whale_vip",
        "content_requests",
        "revenue_warnings",
        "safety_privacy",
        "recommended_actions",
        "by_creator",
        "by_chatter",
    ):
        assert key in report
    assert report["whale_vip"], "expected at least one VIP/whale entry"
    assert report["recommended_actions"]


# 7. Excerpts are capped and privacy-safe — no raw body leaks into the report.
@pytest.mark.asyncio
async def test_excerpts_capped_and_no_raw_body():
    async with _make_session() as session:
        report = await run_manual_import(session, _json_batch())
        rows = (await session.exec(select(OfIntelligenceMessage))).all()
    bodies = {r.body for r in rows if r.body}
    # Stored bodies never exceed the load cap.
    assert all(len(b) <= EXCERPT_CAP for b in bodies)
    # Report excerpts are capped harder and only appear in content_requests.
    for item in report["content_requests"]:
        assert len(item["safe_excerpt"]) <= REPORT_EXCERPT_CAP
    # No full raw body string appears verbatim in the structured findings.
    findings_blob = str(
        report["chatter_quality"]
        + report["missed_sales"]
        + report["safety_privacy"]
        + report["revenue_warnings"]
    )
    for body in bodies:
        if len(body) > REPORT_EXCERPT_CAP:
            assert body not in findings_blob


# 8. Re-running the same import does not duplicate rows (idempotent dedupe).
@pytest.mark.asyncio
async def test_reimport_is_idempotent():
    async with _make_session() as session:
        first = await load_batch(session, _json_batch())
        second = await load_batch(session, _json_batch())
        rows = (await session.exec(select(OfIntelligenceMessage))).all()
    assert first.messages_loaded == 12
    assert second.messages_loaded == 0
    assert second.messages_skipped_duplicate == 12
    assert len(rows) == 12


# 9. Long bodies are truncated on load.
@pytest.mark.asyncio
async def test_long_body_truncated_on_load():
    long_text = "x" * 5000
    batch = parse_json(
        '{"records": [{"creator_alias": "luna_demo", "fan_alias": "f1", '
        '"direction": "in", "text": "' + long_text + '"}]}'
    )
    async with _make_session() as session:
        await load_batch(session, batch)
        rows = (
            await session.exec(
                select(OfIntelligenceMessage).where(
                    col(OfIntelligenceMessage.direction) == "in"
                )
            )
        ).all()
    assert rows
    assert all(len(r.body) <= EXCERPT_CAP for r in rows if r.body)
