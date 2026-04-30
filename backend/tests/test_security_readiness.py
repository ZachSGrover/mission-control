"""Sprint 6 readiness tests.

Covers:
- ``app.services.onlymonster_integration.fetch_creator_snapshot`` —
  the Sprint 6 typed seam that the future real OnlyMonster client must
  call. Verifies block / allow / read-only invariants.
- ``app.core.denial_audit.attach_denial_detail`` — explicit detail
  helper introduced to bypass keyword inference.
- ``app.api.gateways.GatewayRuntimeStatusResponse`` shape — verifies
  the runtime-status endpoint shape is constructible from a Gateway
  row without leaking the token value.

Each test is independent and uses the in-memory SQLite pattern
established in earlier sprints.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401  — registers tables
from app.core.denial_audit import _reason_category, attach_denial_detail
from app.models.audit_events import AuditEvent
from app.services.onlymonster_integration import (
    CreatorSnapshot,
    fetch_creator_snapshot,
)

# ── shared fixtures ─────────────────────────────────────────────────────────


async def _engine() -> AsyncEngine:
    e = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with e.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return e


async def _session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


class _FakeOnlyMonsterClient:
    """Test double matching the seam's expected fake-client shape."""

    def __init__(
        self, *, rows_read: int = 7, last_event_at_iso: str | None = "2026-04-28T12:00:00+00:00"
    ) -> None:
        self.rows_read = rows_read
        self.last_event_at_iso = last_event_at_iso
        self.calls: list[str] = []

    async def read_only_pull(self, *, creator_id: str) -> dict[str, object]:
        self.calls.append(creator_id)
        return {
            "rows_read": self.rows_read,
            "last_event_at_iso": self.last_event_at_iso,
        }


# ── fetch_creator_snapshot: gate-blocked path (env flag off) ────────────────


@pytest.mark.asyncio
async def test_fetch_creator_snapshot_blocks_when_gate_disabled() -> None:
    """With the env flag off, the gated wrapper short-circuits and
    ``fetch_creator_snapshot`` returns ``None`` without touching the
    fake client. A ``connector.run.blocked`` audit row is written
    (by the gated wrapper) and **no** ``connector.run.finish`` event
    is recorded by the seam.
    """
    os.environ.pop("MC_ONLYMONSTER_GATED_SYNC_ENABLED", None)
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            client = _FakeOnlyMonsterClient()
            result = await fetch_creator_snapshot(
                session,
                creator_id="creator-A",
                fake_client=client,
            )
            assert result is None
            assert client.calls == []  # client must never be invoked

            audits = (await session.exec(select(AuditEvent))).all()
            event_types = {a.event_type for a in audits}
            assert "connector.run.blocked" in event_types
            assert "connector.run.finish" not in event_types
    finally:
        await engine.dispose()


# ── fetch_creator_snapshot: gate-blocked when env on but no approval ───────


@pytest.mark.asyncio
async def test_fetch_creator_snapshot_blocks_when_no_approval() -> None:
    """Even with the env flag set, the connector gate refuses if no
    approval row exists. Returns ``None`` and does not invoke the
    fake client.
    """
    os.environ["MC_ONLYMONSTER_GATED_SYNC_ENABLED"] = "1"
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                client = _FakeOnlyMonsterClient()
                result = await fetch_creator_snapshot(
                    session,
                    creator_id="creator-A",
                    fake_client=client,
                )
                assert result is None
                assert client.calls == []
        finally:
            await engine.dispose()
    finally:
        os.environ.pop("MC_ONLYMONSTER_GATED_SYNC_ENABLED", None)


# ── fetch_creator_snapshot: success path ────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_creator_snapshot_runs_and_audits_finish_when_allowed() -> None:
    """With env flag on, approval present, and consent live, the gate
    allows, the fake client is invoked exactly once with the right
    creator_id, the seam returns a ``CreatorSnapshot`` with
    ``rows_written == 0`` (read-only invariant), and a
    ``connector.run.finish`` audit row is written carrying only the
    safe metadata fields (no fan PII).
    """
    os.environ["MC_ONLYMONSTER_GATED_SYNC_ENABLED"] = "1"
    try:
        engine = await _engine()
        try:
            from app.services import connector_approvals as approvals_svc
            from app.services import consent as consent_svc

            async with await _session(engine) as session:
                # Approval + consent for (onlymonster, creator_sync, creator-A).
                approval_row = await approvals_svc.request_approval(
                    session,
                    connector_type="onlymonster",
                    requested_action="creator_sync",
                    creator_id="creator-A",
                )
                await approvals_svc.approve(session, approval_row.id)
                await consent_svc.grant(
                    session,
                    consent_type="onlymonster_sync",
                    creator_id="creator-A",
                )
                await session.commit()

                client = _FakeOnlyMonsterClient(rows_read=42)
                result = await fetch_creator_snapshot(
                    session,
                    creator_id="creator-A",
                    fake_client=client,
                )
                assert isinstance(result, CreatorSnapshot)
                assert result.rows_read == 42
                assert result.rows_written == 0  # read-only invariant
                assert client.calls == ["creator-A"]

                audits = (await session.exec(select(AuditEvent))).all()
                finish_rows = [a for a in audits if a.event_type == "connector.run.finish"]
                assert len(finish_rows) == 1
                meta = finish_rows[0].metadata_json
                assert meta["connector_type"] == "onlymonster"
                assert meta["requested_action"] == "creator_sync"
                assert meta["rows_read"] == 42
                assert meta["rows_written"] == 0
                # The seam must never leak fan PII or message bodies through audit.
                forbidden_keys = {
                    "fan_id",
                    "fan_username",
                    "message_body",
                    "messages",
                    "subscribers",
                    "tips",
                }
                assert forbidden_keys.isdisjoint(set(meta.keys()))
        finally:
            await engine.dispose()
    finally:
        os.environ.pop("MC_ONLYMONSTER_GATED_SYNC_ENABLED", None)


# ── fetch_creator_snapshot: refusal when no real client wired ───────────────


@pytest.mark.asyncio
async def test_fetch_creator_snapshot_refuses_loudly_without_client() -> None:
    """If gates pass but no fake client is supplied, the seam raises
    a ``RuntimeError``. This catches the bug where an operator flips
    the env flag in production before wiring up the real OnlyMonster
    client.
    """
    os.environ["MC_ONLYMONSTER_GATED_SYNC_ENABLED"] = "1"
    try:
        engine = await _engine()
        try:
            from app.services import connector_approvals as approvals_svc
            from app.services import consent as consent_svc

            async with await _session(engine) as session:
                approval_row = await approvals_svc.request_approval(
                    session,
                    connector_type="onlymonster",
                    requested_action="creator_sync",
                    creator_id="creator-B",
                )
                await approvals_svc.approve(session, approval_row.id)
                await consent_svc.grant(
                    session,
                    consent_type="onlymonster_sync",
                    creator_id="creator-B",
                )
                await session.commit()

                with pytest.raises(RuntimeError, match="real client is not wired"):
                    await fetch_creator_snapshot(
                        session,
                        creator_id="creator-B",
                        fake_client=None,
                    )
        finally:
            await engine.dispose()
    finally:
        os.environ.pop("MC_ONLYMONSTER_GATED_SYNC_ENABLED", None)


# ── attach_denial_detail: explicit detail honored ───────────────────────────


def test_attach_denial_detail_overrides_keyword_inference() -> None:
    """When ``_mc_denial_detail`` is attached, the reason category
    comes from the explicit dict — *not* from the keyword scan over
    ``exc.detail``. This lets a dependency carry typed information
    without exposing it in the HTTP response body.
    """
    exc = HTTPException(status_code=403, detail="something innocuous to the user")
    attach_denial_detail(
        exc,
        dependency="require_owner",
        reason_category="role_required_owner",
        required_role="owner",
    )
    assert _reason_category(403, exc) == "role_required_owner"

    # Sanity: the public-facing detail is unchanged. The typed dict
    # rides on a private attribute, never the response body.
    assert exc.detail == "something innocuous to the user"
    assert getattr(exc, "_mc_denial_detail", None) == {
        "dependency": "require_owner",
        "reason_category": "role_required_owner",
        "required_role": "owner",
        "required_permission": None,
    }


def test_reason_category_falls_through_to_inference_without_attached_detail() -> None:
    """Without explicit detail, the keyword scan still works."""
    exc = HTTPException(status_code=403, detail="Owner role required")
    assert _reason_category(403, exc) == "role_required_owner"

    exc2 = HTTPException(status_code=401, detail="missing token")
    assert _reason_category(401, exc2) == "unauthenticated"


def test_attach_denial_detail_returns_same_exception() -> None:
    """The helper must return the same exception object so callers
    can ``raise attach_denial_detail(HTTPException(...), ...)`` in
    one expression.
    """
    exc = HTTPException(status_code=403, detail="x")
    same = attach_denial_detail(exc, dependency="d", reason_category="forbidden")
    assert same is exc


# ── gateway runtime-status: shape and token-source classification ───────────


@pytest.mark.asyncio
async def test_gateway_runtime_status_classifies_token_sources() -> None:
    """The runtime-status response must classify the three token states
    (none, legacy_plaintext, encrypted) without leaking the value.
    Tested at the level of the response model construction so we don't
    need the full FastAPI dependency chain.
    """
    from app.api.gateways import GatewayRuntimeStatusResponse

    # none
    none_resp = GatewayRuntimeStatusResponse(
        gateway_id=str(uuid4()),
        token_configured=False,
        token_source="none",
        url_set=True,
        allow_insecure_tls=False,
        disable_device_pairing=False,
    )
    assert none_resp.token_configured is False
    # The response type has no `token` or `preview` field at all.
    assert "token" not in none_resp.model_dump()
    assert "preview" not in none_resp.model_dump()

    # legacy plaintext
    legacy_resp = GatewayRuntimeStatusResponse(
        gateway_id=str(uuid4()),
        token_configured=True,
        token_source="legacy_plaintext",
        url_set=True,
        allow_insecure_tls=False,
        disable_device_pairing=False,
    )
    assert legacy_resp.token_source == "legacy_plaintext"

    # encrypted
    enc_resp = GatewayRuntimeStatusResponse(
        gateway_id=str(uuid4()),
        token_configured=True,
        token_source="encrypted",
        url_set=True,
        allow_insecure_tls=False,
        disable_device_pairing=False,
    )
    assert enc_resp.token_source == "encrypted"
