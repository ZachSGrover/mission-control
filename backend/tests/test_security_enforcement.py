"""Sprint 5 enforcement tests.

Covers the gated OnlyMonster scaffold, gateway token cutover masking,
org-scope settings flag, Clerk webhook verifier (Svix-or-fallback),
approval/consent creation endpoints, and PII redactor improvements.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401  — registers tables
from app.api.security_admin import (
    ApprovalCreateRequest,
    ConsentGrantRequest,
    create_approval,
    create_consent,
)
from app.core.auth import AuthContext
from app.core.clerk_webhook_verify import (
    WebhookVerificationError,
    verify_webhook,
)
from app.core.pii_redact import redact_for_llm
from app.models.audit_event import AuditEvent
from app.services.gated_onlymonster_sync import (
    gated_onlymonster_creator_sync,
)
from app.services.gated_onlymonster_sync import is_enabled as is_om_gate_enabled
from app.services.settings_scope import (
    get_secret_scoped,
    is_org_scope_enabled,
    set_secret_scoped,
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


# ────────────────────── gated OnlyMonster scaffold ───────────────────────────


@pytest.mark.asyncio
async def test_gated_onlymonster_refuses_when_env_disabled() -> None:
    os.environ.pop("MC_ONLYMONSTER_GATED_SYNC_ENABLED", None)
    assert is_om_gate_enabled() is False
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            calls = {"n": 0}

            async def fake_runner() -> str:
                calls["n"] += 1
                return "should_not_run"

            result = await gated_onlymonster_creator_sync(
                session,
                organization_id=None,
                creator_id="creator-A",
                sync_callable=fake_runner,
            )
            assert result.allowed is False
            assert result.verdict.detail == "scaffold_disabled"
            assert calls["n"] == 0

            audits = (await session.exec(select(AuditEvent))).all()
            assert any(a.event_type == "connector.run.blocked" for a in audits)
            blocked = next(a for a in audits if a.event_type == "connector.run.blocked")
            assert blocked.metadata_json["verdict_reason"] == "scaffold_disabled"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_gated_onlymonster_routes_through_gate_when_enabled() -> None:
    os.environ["MC_ONLYMONSTER_GATED_SYNC_ENABLED"] = "1"
    try:
        assert is_om_gate_enabled() is True
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                calls = {"n": 0}

                async def fake_runner() -> str:
                    calls["n"] += 1
                    return "ran"

                # No approval, no consent → gate blocks.
                result = await gated_onlymonster_creator_sync(
                    session,
                    organization_id=None,
                    creator_id="creator-A",
                    sync_callable=fake_runner,
                )
                assert result.allowed is False
                # First failure short-circuits to ``no_approval``.
                assert result.verdict.reason == "no_approval"
                assert calls["n"] == 0
        finally:
            await engine.dispose()
    finally:
        os.environ.pop("MC_ONLYMONSTER_GATED_SYNC_ENABLED", None)


# ─────────────────────── gateway token cutover ──────────────────────────────


@pytest.mark.asyncio
async def test_get_gateway_masks_token_by_default() -> None:
    from copy import copy

    from app.api.gateways import _mask_gateway_token
    from app.models.gateways import Gateway

    gw = Gateway(
        organization_id=uuid4(),
        name="g",
        url="https://x.test",
        workspace_root="/tmp",
        token="legacy-not-real-token-value",
    )
    masked = _mask_gateway_token(gw)
    assert masked.token is None
    # Original is not mutated.
    assert gw.token == "legacy-not-real-token-value"
    # ``copy`` semantics: independent objects.
    assert masked is not gw
    _ = copy  # prevent unused import lint


# ────────────────────── settings scope feature flag ─────────────────────────


@pytest.mark.asyncio
async def test_settings_scope_flag_off_uses_legacy_global() -> None:
    os.environ.pop("MC_APP_SETTINGS_ORG_SCOPED", None)
    _set_dedicated_key()
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            org_id = uuid4()
            await set_secret_scoped(session, "test.key", "value-A", organization_id=org_id)
            await session.commit()

            assert is_org_scope_enabled() is False
            # With flag off, the value lands in the global row even
            # though we passed an org_id. Reading without an org_id
            # still finds it.
            v, src = await get_secret_scoped(session, "test.key", organization_id=None)
            assert v == "value-A"
            assert src in ("db", "db_global", "env")
    finally:
        _clear_dedicated_key()
        await engine.dispose()


@pytest.mark.asyncio
async def test_settings_scope_flag_on_isolates_orgs() -> None:
    os.environ["MC_APP_SETTINGS_ORG_SCOPED"] = "1"
    _set_dedicated_key()
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            org_a = uuid4()
            org_b = uuid4()
            await set_secret_scoped(session, "test.key", "value-A", organization_id=org_a)
            await session.commit()

            v_b, src_b = await get_secret_scoped(
                session, "test.key", organization_id=org_b, fallback=""
            )
            # org_b sees nothing (no global, no org-b row).
            assert v_b == ""
            assert src_b == "none"

            v_a, src_a = await get_secret_scoped(session, "test.key", organization_id=org_a)
            assert v_a == "value-A"
            assert src_a == "db_org"
    finally:
        os.environ.pop("MC_APP_SETTINGS_ORG_SCOPED", None)
        _clear_dedicated_key()
        await engine.dispose()


# ──────────────────── Clerk webhook verifier ────────────────────────────────


def test_webhook_verify_no_secret_raises() -> None:
    with pytest.raises(WebhookVerificationError):
        verify_webhook(payload=b"x", headers={}, secret="", shared_secret_header="x")


def test_webhook_verify_shared_secret_ok_in_dev_no_svix() -> None:
    # Force-disable production guard. Svix isn't installed in this venv,
    # so the shared-secret fallback is the path under test.
    os.environ.pop("CLERK_WEBHOOK_ALLOW_SHARED_SECRET", None)
    from app.core import config as _c

    original = _c.settings.environment
    _c.settings.environment = "dev"
    try:
        # Should not raise.
        verify_webhook(
            payload=b"{}",
            headers={},
            secret="dev-secret-12345",
            shared_secret_header="dev-secret-12345",
        )
    finally:
        _c.settings.environment = original


def test_webhook_verify_shared_secret_refused_in_prod_without_opt_in() -> None:
    os.environ.pop("CLERK_WEBHOOK_ALLOW_SHARED_SECRET", None)
    from app.core import config as _c

    original = _c.settings.environment
    _c.settings.environment = "production"
    try:
        with pytest.raises(WebhookVerificationError):
            verify_webhook(
                payload=b"{}",
                headers={},
                secret="prod-secret-12345",
                shared_secret_header="prod-secret-12345",
            )
    finally:
        _c.settings.environment = original


def test_webhook_verify_shared_secret_allowed_in_prod_with_opt_in() -> None:
    os.environ["CLERK_WEBHOOK_ALLOW_SHARED_SECRET"] = "1"
    from app.core import config as _c

    original = _c.settings.environment
    _c.settings.environment = "production"
    try:
        verify_webhook(
            payload=b"{}",
            headers={},
            secret="prod-secret-12345",
            shared_secret_header="prod-secret-12345",
        )
    finally:
        _c.settings.environment = original
        os.environ.pop("CLERK_WEBHOOK_ALLOW_SHARED_SECRET", None)


# ───────────────── approval + consent creation endpoints ────────────────────


@pytest.mark.asyncio
async def test_create_approval_endpoint_starts_pending() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            row = await create_approval(
                ApprovalCreateRequest(
                    connector_type="onlymonster",
                    requested_action="creator_sync",
                    creator_id="creator-A",
                    risk_level="medium",
                    reason="initial setup",
                ),
                _ctx(),
                "owner",
                session,
            )
            assert row.status == "pending"
            assert row.connector_type == "onlymonster"
            audits = (await session.exec(select(AuditEvent))).all()
            assert any(a.event_type == "connector.approval.request" for a in audits)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_approval_rejects_unknown_connector_type() -> None:
    from fastapi import HTTPException

    engine = await _engine()
    try:
        async with await _session(engine) as session:
            with pytest.raises(HTTPException) as excinfo:
                await create_approval(
                    ApprovalCreateRequest(
                        connector_type="not_a_connector",
                        requested_action="x",
                    ),
                    _ctx(),
                    "owner",
                    session,
                )
            assert excinfo.value.status_code == 400
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_consent_endpoint_grants_immediately() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            row = await create_consent(
                ConsentGrantRequest(
                    consent_type="onlymonster_sync",
                    creator_id="creator-A",
                    source="signed_pdf",
                    document_reference="docusign:abc123",
                ),
                _ctx(),
                "owner",
                session,
            )
            assert row.status == "granted"
            assert row.consent_type == "onlymonster_sync"
            audits = (await session.exec(select(AuditEvent))).all()
            assert any(a.event_type == "consent.grant" for a in audits)
    finally:
        await engine.dispose()


# ──────────────────── PII redactor improvements ─────────────────────────────


def test_pii_redact_labelled_name_caught() -> None:
    text = "Full Name: Alice Smith\nName: Bob Jones the Third"
    out, applied, counts = redact_for_llm(text)
    assert applied is True
    assert "Alice Smith" not in out
    assert "Bob Jones" not in out
    assert counts.get("labelled_name", 0) >= 2


def test_pii_redact_unlabelled_name_preserved() -> None:
    # Sanity: "Aria Veil" without a "Name:" label should still survive
    # because the redactor is conservative and only catches labelled cases.
    text = "Creator Aria Veil hit her weekly target."
    out, applied, counts = redact_for_llm(text)
    assert "Aria Veil" in out
    assert counts.get("labelled_name", 0) == 0


def test_pii_redact_street_address_caught() -> None:
    text = "Ship to 1234 Elm Street and copy 5678 Maple Ave."
    out, applied, counts = redact_for_llm(text)
    assert applied is True
    assert "1234 Elm" not in out
    assert "5678 Maple" not in out
    assert counts.get("street_address", 0) >= 2


def test_pii_redact_business_strings_still_intact() -> None:
    # The Sprint-4 baseline test should still hold under Sprint 5
    # additions — names + addresses are the only new buckets.
    text = "Creator-A FY24Q1 mass-message id mm-001 to fan-segment-7"
    out, applied, _counts = redact_for_llm(text)
    assert applied is False
    assert out == text
