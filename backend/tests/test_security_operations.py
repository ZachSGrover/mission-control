"""Sprint 4 operations tests.

Covers the new admin route handlers, the audit-retention scheduler,
the clerk-webhook stub, the denial-audit enrichment, and the new PII
patterns. Each block is independent and reuses the in-memory SQLite
pattern from earlier sprints.
"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401  — registers tables
from app.api.security_admin import (
    ApprovalDecisionRequest,
    ConsentRevokeRequest,
    GatePreviewRequest,
    KillSwitchToggleRequest,
    approve_approval,
    disable_kill_switch,
    enable_kill_switch,
    list_approvals,
    list_consents,
    migrate_gateway_tokens,
    preview_connector_gate,
    reject_approval,
    revoke_approval,
    revoke_consent,
)
from app.core.auth import AuthContext
from app.core.pii_redact import redact_for_llm
from app.models.audit_events import AuditEvent
from app.services import connector_approvals as approvals_svc
from app.services import consent as consent_svc
from app.services.audit_retention_scheduler import (
    is_dry_run,
    is_scheduler_enabled,
    run_retention_pass,
)


def _ctx() -> AuthContext:
    return AuthContext(actor_type="user", user=None)


def _set_dedicated_key() -> None:
    os.environ["SETTINGS_ENCRYPTION_KEY"] = "0" * 64
    from app.core import secrets_store as _ss

    _ss._fernet = None  # type: ignore[attr-defined]


def _clear_dedicated_key() -> None:
    os.environ.pop("SETTINGS_ENCRYPTION_KEY", None)
    from app.core import secrets_store as _ss

    _ss._fernet = None  # type: ignore[attr-defined]


async def _engine() -> AsyncEngine:
    e = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with e.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return e


async def _session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


# ── kill switch endpoints ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enable_then_disable_global_kill_switch_via_endpoints() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            row = await enable_kill_switch(
                KillSwitchToggleRequest(scope="global", reason="drill"),
                _ctx(),
                "owner",
                session,
            )
            assert row.enabled is True
            assert row.scope == "global"

            row = await disable_kill_switch(
                KillSwitchToggleRequest(scope="global", reason="all-clear"),
                _ctx(),
                "owner",
                session,
            )
            assert row.enabled is False

            audits = (await session.exec(select(AuditEvent))).all()
            event_types = {a.event_type for a in audits}
            assert "kill_switch.enable" in event_types
            assert "kill_switch.disable" in event_types
    finally:
        await engine.dispose()


# ── approvals endpoints ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approval_decision_endpoints_full_lifecycle() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            row = await approvals_svc.request_approval(
                session,
                connector_type="onlymonster",
                requested_action="creator_sync",
                creator_id="creator-A",
            )
            await session.commit()

            approved = await approve_approval(
                row.id, ApprovalDecisionRequest(reason="ok"), _ctx(), "owner", session
            )
            assert approved.status == "approved"

            revoked = await revoke_approval(
                row.id, ApprovalDecisionRequest(reason="post-incident"), _ctx(), "owner", session
            )
            assert revoked.status == "revoked"

            rejected_row = await approvals_svc.request_approval(
                session,
                connector_type="discord",
                requested_action="connect",
            )
            await session.commit()
            rejected = await reject_approval(
                rejected_row.id,
                ApprovalDecisionRequest(reason="not for this org"),
                _ctx(),
                "owner",
                session,
            )
            assert rejected.status == "rejected"

            listing = await list_approvals(_ctx(), "owner", session, only_pending=False, limit=10)
            assert {a.status for a in listing} == {"revoked", "rejected"}
    finally:
        await engine.dispose()


# ── consent endpoints ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consent_listing_and_revocation_endpoint() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            row = await consent_svc.grant(
                session,
                consent_type="onlymonster_sync",
                creator_id="creator-A",
            )
            await session.commit()

            live_only = await list_consents(_ctx(), "owner", session, only_live=True, limit=10)
            assert len(live_only) == 1
            assert live_only[0].id == str(row.id)

            revoked = await revoke_consent(
                row.id, ConsentRevokeRequest(reason="creator request"), _ctx(), "owner", session
            )
            assert revoked.status == "revoked"

            still_live = await list_consents(_ctx(), "owner", session, only_live=True, limit=10)
            assert still_live == []
    finally:
        await engine.dispose()


# ── gateway migration endpoint ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gateway_migration_endpoint_refuses_without_dedicated_key() -> None:
    _clear_dedicated_key()
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as excinfo:
                await migrate_gateway_tokens(_ctx(), "owner", session, dry_run=False)
            assert excinfo.value.status_code == 409
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_gateway_migration_endpoint_dry_run_audits_invocation() -> None:
    _set_dedicated_key()
    engine = await _engine()
    try:
        from app.models.gateways import Gateway

        async with await _session(engine) as session:
            session.add(
                Gateway(
                    organization_id=uuid4(),
                    name="g",
                    url="https://example.test",
                    workspace_root="/tmp",
                    token="legacy-not-real",
                )
            )
            await session.commit()

            result = await migrate_gateway_tokens(_ctx(), "owner", session, dry_run=True)
            assert result.scanned == 1
            assert result.migrated == 1
            assert result.dry_run is True

            audits = (await session.exec(select(AuditEvent))).all()
            assert any(a.event_type == "gateway.token.migrate.invoke" for a in audits)
    finally:
        _clear_dedicated_key()
        await engine.dispose()


# ── connector gate preview endpoint ────────────────────────────────────────


@pytest.mark.asyncio
async def test_connector_gate_preview_endpoint_audits_outcome() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            verdict = await preview_connector_gate(
                GatePreviewRequest(
                    connector_type="onlymonster",
                    requested_action="creator_sync",
                    creator_id="creator-X",
                ),
                _ctx(),
                "owner",
                session,
            )
            assert verdict.allowed is False
            assert verdict.reason == "no_approval"

            audits = (await session.exec(select(AuditEvent))).all()
            assert any(a.event_type == "connector.gate.preview" for a in audits)
    finally:
        await engine.dispose()


# ── audit retention scheduler ───────────────────────────────────────────────


def test_retention_scheduler_defaults_to_dry_run_and_disabled() -> None:
    os.environ.pop("MC_AUDIT_RETENTION_ENABLED", None)
    os.environ.pop("MC_AUDIT_RETENTION_DRY_RUN", None)
    assert is_scheduler_enabled() is False
    assert is_dry_run() is True


def test_retention_scheduler_real_delete_requires_explicit_opt_in() -> None:
    os.environ["MC_AUDIT_RETENTION_DRY_RUN"] = "0"
    try:
        assert is_dry_run() is False
    finally:
        os.environ.pop("MC_AUDIT_RETENTION_DRY_RUN", None)


@pytest.mark.asyncio
async def test_retention_pass_writes_audit_event() -> None:
    # Use dry-run explicitly so this test never deletes anything. The
    # scheduler imports ``async_session_maker`` by reference at module
    # load time, so we patch the module-level reference directly.
    engine = await _engine()
    try:
        from sqlmodel.ext.asyncio.session import AsyncSession as _AS

        from app.services import audit_retention_scheduler as scheduler_mod

        original = scheduler_mod.async_session_maker

        def _factory() -> _AS:
            return _AS(engine, expire_on_commit=False)

        scheduler_mod.async_session_maker = _factory  # type: ignore[assignment]
        try:
            preview = await run_retention_pass(dry_run=True)
            assert isinstance(preview, dict)
            async with _factory() as s:
                rows = (await s.exec(select(AuditEvent))).all()
                assert any(a.event_type == "audit.retention.preview" for a in rows)
        finally:
            scheduler_mod.async_session_maker = original  # type: ignore[assignment]
    finally:
        await engine.dispose()


# ── PII redactor improvements ──────────────────────────────────────────────


def test_pii_redact_anthropic_key_is_caught() -> None:
    text = "use sk-ant-abcdefghijklmnopqrstuvwxyzABC"
    out, applied, counts = redact_for_llm(text)
    assert applied is True
    assert "sk-ant-" not in out
    assert counts.get("vendor_key", 0) >= 1


def test_pii_redact_x_api_key_header_pair_is_caught() -> None:
    text = "Set X-API-Key: secret-thirty-chars-aaaa-bbbb on the request"
    out, applied, counts = redact_for_llm(text)
    assert applied is True
    assert "secret-thirty-chars" not in out
    assert counts.get("header_pair", 0) >= 1 or counts.get("vendor_key", 0) >= 1


def test_pii_redact_business_strings_still_intact() -> None:
    text = "Creator-A FY24Q1 — mass-message id mm-001 sent to fan-segment-7"
    out, applied, _counts = redact_for_llm(text)
    assert applied is False
    assert out == text


# ── denial audit reason categorisation (pure, fast) ─────────────────────────


def test_denial_audit_reason_category_is_safe() -> None:
    from fastapi import HTTPException

    from app.core.denial_audit import _reason_category

    assert _reason_category(401, HTTPException(401)) == "unauthenticated"
    assert (
        _reason_category(403, HTTPException(403, detail="Owner role required."))
        == "role_required_owner"
    )
    assert (
        _reason_category(403, HTTPException(403, detail="Allowlist check failed.")) == "allowlist"
    )
    assert _reason_category(403, HTTPException(403, detail="User disabled.")) == "user_disabled"
    assert _reason_category(403, HTTPException(403, detail="generic")) == "forbidden"


# ── clerk webhook ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clerk_webhook_refuses_without_secret_set() -> None:
    os.environ.pop("CLERK_WEBHOOK_SECRET", None)
    from fastapi import HTTPException

    from app.api.clerk_webhooks import (
        ClerkWebhookEnvelope,
        receive_clerk_webhook,
    )

    engine = await _engine()
    try:
        async with await _session(engine) as session:

            class _Req:
                headers: dict[str, str] = {}
                client = type("_C", (), {"host": "1.2.3.4"})()

                async def body(self) -> bytes:
                    return b"{}"

            with pytest.raises(HTTPException) as excinfo:
                await receive_clerk_webhook(
                    request=_Req(),  # type: ignore[arg-type]
                    body=ClerkWebhookEnvelope(type="session.created"),
                    session=session,
                    x_mission_control_webhook_secret=None,
                )
            assert excinfo.value.status_code == 503
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_clerk_webhook_rejects_bad_signature() -> None:
    os.environ["CLERK_WEBHOOK_SECRET"] = "test-secret-12345"
    from fastapi import HTTPException

    from app.api.clerk_webhooks import (
        ClerkWebhookEnvelope,
        receive_clerk_webhook,
    )

    engine = await _engine()
    try:
        async with await _session(engine) as session:

            class _Req:
                headers: dict[str, str] = {}
                client = type("_C", (), {"host": "1.2.3.4"})()

                async def body(self) -> bytes:
                    return b"{}"

            with pytest.raises(HTTPException) as excinfo:
                await receive_clerk_webhook(
                    request=_Req(),  # type: ignore[arg-type]
                    body=ClerkWebhookEnvelope(type="session.created"),
                    session=session,
                    x_mission_control_webhook_secret="WRONG",
                )
            assert excinfo.value.status_code == 401
    finally:
        os.environ.pop("CLERK_WEBHOOK_SECRET", None)
        await engine.dispose()


@pytest.mark.asyncio
async def test_clerk_webhook_records_login_audit_on_session_created() -> None:
    os.environ["CLERK_WEBHOOK_SECRET"] = "test-secret-12345"
    from app.api.clerk_webhooks import (
        ClerkWebhookEnvelope,
        receive_clerk_webhook,
    )

    engine = await _engine()
    try:
        async with await _session(engine) as session:

            class _Req:
                headers: dict[str, str] = {"user-agent": "test-runner"}
                client = type("_C", (), {"host": "1.2.3.4"})()

                async def body(self) -> bytes:
                    return b"{}"

            await receive_clerk_webhook(
                request=_Req(),  # type: ignore[arg-type]
                body=ClerkWebhookEnvelope(
                    type="session.created",
                    data={
                        "user_id": "user_abc",
                        "user": {
                            "id": "user_abc",
                            "email_addresses": [{"email_address": "alice@example.com"}],
                        },
                    },
                ),
                session=session,
                x_mission_control_webhook_secret="test-secret-12345",
            )

            audits = (await session.exec(select(AuditEvent))).all()
            assert any(a.event_type == "auth.login.success" for a in audits)
            login_row = next(a for a in audits if a.event_type == "auth.login.success")
            assert login_row.actor_email == "alice@example.com"
            # No tokens / cookies in metadata.
            md_str = str(login_row.metadata_json)
            assert "secret" not in md_str.lower()
            assert "cookie" not in md_str.lower()
    finally:
        os.environ.pop("CLERK_WEBHOOK_SECRET", None)
        await engine.dispose()


# Trivial sanity: scheduler supervisor exits cleanly when not enabled.


@pytest.mark.asyncio
async def test_retention_supervisor_returns_immediately_when_disabled() -> None:
    os.environ.pop("MC_AUDIT_RETENTION_ENABLED", None)
    from app.services.audit_retention_scheduler import run_retention_supervisor

    # Should return without raising and without entering the loop.
    await asyncio.wait_for(run_retention_supervisor(), timeout=2)
