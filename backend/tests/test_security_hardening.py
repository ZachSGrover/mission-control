"""Sprint 3 hardening tests — gateway tokens, scoped settings, prod
guard, denial audit, retention, PII redaction, gated runs.

One file because the helpers are small and share the in-memory DB
pattern. Each block is independent and can be read in isolation.
"""

from __future__ import annotations

import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401  — registers tables
from app.core.pii_redact import redact_for_llm
from app.core.startup_guard import (
    InsecureProductionStartupError,
    assert_production_encryption_configured,
    is_production,
)
from app.core.time import utcnow
from app.models.audit_events import AuditEvent
from app.models.gateways import Gateway


async def _engine() -> AsyncEngine:
    e = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with e.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return e


async def _session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


def _set_dedicated_key() -> None:
    os.environ["SETTINGS_ENCRYPTION_KEY"] = "0" * 64
    from app.core import secrets_store as _ss

    _ss._fernet = None  # type: ignore[attr-defined]


def _clear_dedicated_key() -> None:
    os.environ.pop("SETTINGS_ENCRYPTION_KEY", None)
    from app.core import secrets_store as _ss

    _ss._fernet = None  # type: ignore[attr-defined]


# ────────────────────────── gateway tokens ──────────────────────────


@pytest.mark.asyncio
async def test_gateway_set_token_encrypts_and_clears_legacy_column() -> None:
    _set_dedicated_key()
    engine = await _engine()
    try:
        from app.services.gateway_tokens import get_token, set_token

        async with await _session(engine) as session:
            org_id = uuid4()
            gw = Gateway(
                organization_id=org_id,
                name="test-gateway",
                url="https://example.test",
                workspace_root="/tmp/x",
                token="legacy-plaintext-not-real",
            )
            session.add(gw)
            await session.commit()

            await set_token(
                session,
                gw,
                "new-secret-not-real",
                actor_email="owner@example.com",
            )
            await session.commit()

            assert gw.encrypted_token
            assert gw.encrypted_token != "new-secret-not-real"
            assert gw.token is None  # legacy column cleared

            assert get_token(gw) == "new-secret-not-real"

            audits = (await session.exec(select(AuditEvent))).all()
            assert any(a.event_type == "gateway.token.set" for a in audits)
    finally:
        _clear_dedicated_key()
        await engine.dispose()


@pytest.mark.asyncio
async def test_gateway_get_token_falls_back_to_legacy_column() -> None:
    _set_dedicated_key()
    engine = await _engine()
    try:
        from app.services.gateway_tokens import get_token

        async with await _session(engine) as session:
            org_id = uuid4()
            gw = Gateway(
                organization_id=org_id,
                name="legacy",
                url="https://example.test",
                workspace_root="/tmp/x",
                token="legacy-plaintext-not-real",
            )
            session.add(gw)
            await session.commit()

            assert get_token(gw) == "legacy-plaintext-not-real"
    finally:
        _clear_dedicated_key()
        await engine.dispose()


@pytest.mark.asyncio
async def test_gateway_legacy_migrator_dry_run_then_real() -> None:
    _set_dedicated_key()
    engine = await _engine()
    try:
        from app.services.gateway_tokens import migrate_legacy_tokens

        async with await _session(engine) as session:
            for i in range(3):
                gw = Gateway(
                    organization_id=uuid4(),
                    name=f"gw-{i}",
                    url="https://example.test",
                    workspace_root=f"/tmp/{i}",
                    token=f"legacy-{i}-not-real",
                )
                session.add(gw)
            await session.commit()

            scanned, migrated = await migrate_legacy_tokens(session, dry_run=True)
            assert scanned == 3 and migrated == 3
            # No row should have changed.
            rows = (await session.exec(select(Gateway))).all()
            assert all(r.token and not r.encrypted_token for r in rows)

            scanned, migrated = await migrate_legacy_tokens(session, dry_run=False)
            await session.commit()
            assert migrated == 3
            rows = (await session.exec(select(Gateway))).all()
            assert all(r.encrypted_token and not r.token for r in rows)
    finally:
        _clear_dedicated_key()
        await engine.dispose()


@pytest.mark.asyncio
async def test_gateway_migrator_refuses_without_dedicated_key() -> None:
    _clear_dedicated_key()
    engine = await _engine()
    try:
        from app.services.gateway_tokens import migrate_legacy_tokens

        async with await _session(engine) as session:
            with pytest.raises(RuntimeError):
                await migrate_legacy_tokens(session, dry_run=False)
    finally:
        await engine.dispose()


# ─────────────────────── app_settings_scoped ────────────────────────


@pytest.mark.asyncio
async def test_app_settings_scoped_org_read_prefers_org_value() -> None:
    _set_dedicated_key()
    engine = await _engine()
    try:
        from app.services.app_settings_scoped import (
            get_secret_for_org,
            set_secret_for_org,
        )

        async with await _session(engine) as session:
            org_a = uuid4()
            org_b = uuid4()
            await set_secret_for_org(session, "api_key.openai", "GLOBAL-KEY", organization_id=None)
            await set_secret_for_org(session, "api_key.openai", "ORG-A-KEY", organization_id=org_a)
            await session.commit()

            val_a, src_a = await get_secret_for_org(
                session, "api_key.openai", organization_id=org_a
            )
            assert (val_a, src_a) == ("ORG-A-KEY", "db_org")

            val_b, src_b = await get_secret_for_org(
                session, "api_key.openai", organization_id=org_b
            )
            assert (val_b, src_b) == ("GLOBAL-KEY", "db_global")

            val_none, src_none = await get_secret_for_org(
                session, "api_key.openai", organization_id=None
            )
            assert (val_none, src_none) == ("GLOBAL-KEY", "db_global")
    finally:
        _clear_dedicated_key()
        await engine.dispose()


@pytest.mark.asyncio
async def test_app_settings_scoped_no_cross_tenant_leakage() -> None:
    _set_dedicated_key()
    engine = await _engine()
    try:
        from app.services.app_settings_scoped import (
            get_secret_for_org,
            set_secret_for_org,
        )

        async with await _session(engine) as session:
            org_a = uuid4()
            org_b = uuid4()
            await set_secret_for_org(session, "secret.x", "A_VALUE", organization_id=org_a)
            await session.commit()

            val_b, src_b = await get_secret_for_org(
                session, "secret.x", organization_id=org_b, fallback=""
            )
            assert val_b == "" and src_b == "none"
    finally:
        _clear_dedicated_key()
        await engine.dispose()


# ──────────────────────── production guard ──────────────────────────


def test_startup_guard_dev_environment_passes() -> None:
    _clear_dedicated_key()
    from app.core import config as _c

    original = _c.settings.environment
    _c.settings.environment = "dev"
    try:
        # Should not raise.
        assert_production_encryption_configured()
    finally:
        _c.settings.environment = original


def test_startup_guard_production_without_key_raises() -> None:
    _clear_dedicated_key()
    from app.core import config as _c

    original = _c.settings.environment
    _c.settings.environment = "production"
    try:
        with pytest.raises(InsecureProductionStartupError):
            assert_production_encryption_configured()
    finally:
        _c.settings.environment = original


def test_startup_guard_production_with_key_passes() -> None:
    _set_dedicated_key()
    from app.core import config as _c

    original = _c.settings.environment
    _c.settings.environment = "production"
    try:
        # Should not raise.
        assert_production_encryption_configured()
        assert is_production() is True
    finally:
        _c.settings.environment = original
        _clear_dedicated_key()


# ──────────────────────── audit retention ───────────────────────────


@pytest.mark.asyncio
async def test_audit_retention_preview_counts_old_rows() -> None:
    engine = await _engine()
    try:
        from app.services.audit_retention import (
            cutoff_for_category,
            preview_purge,
        )

        async with await _session(engine) as session:
            now = utcnow()
            # An ancient credential row → eligible.
            old = AuditEvent(
                event_type="t",
                category="credential",
                action="put",
                result="success",
                created_at=now - timedelta(days=800),
            )
            # A recent auth row → not eligible (auth is 90d).
            recent = AuditEvent(
                event_type="t",
                category="auth",
                action="login",
                result="success",
                created_at=now - timedelta(days=10),
            )
            # An ancient auth row → eligible (>90d).
            old_auth = AuditEvent(
                event_type="t",
                category="auth",
                action="login",
                result="success",
                created_at=now - timedelta(days=120),
            )
            for r in (old, recent, old_auth):
                session.add(r)
            await session.commit()

            preview = await preview_purge(session, now=now)
            assert preview.get("credential", 0) == 1
            assert preview.get("auth", 0) == 1
            assert "session" not in preview  # never present

            # Sanity: cutoff for `auth` is 90 days, for `credential` 730.
            assert cutoff_for_category("auth", now=now) > cutoff_for_category("credential", now=now)
    finally:
        await engine.dispose()


# ─────────────────────── PII redactor ───────────────────────────────


def test_pii_redact_email_and_phone() -> None:
    text = "Contact alice@example.com or +1 555 123 4567 about the issue."
    out, applied, counts = redact_for_llm(text)
    assert applied is True
    assert "alice@example.com" not in out
    assert "555" not in out
    assert counts.get("email") == 1
    assert counts.get("phone") == 1


def test_pii_redact_bearer_token_and_openai_key() -> None:
    text = (
        "Use Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.something.signature; "
        "and key sk-test-abcdefghijklmnopqrstuvwx for testing"
    )
    out, applied, counts = redact_for_llm(text)
    assert applied is True
    assert "Bearer" not in out or "[REDACTED]" in out
    # Check no obviously-key-like substring survives.
    assert "sk-test-abcdefghijklmnopqrstuvwx" not in out


def test_pii_redact_preserves_normal_business_strings() -> None:
    text = "Creator-A reported Q2 revenue down 15%; mass-message id mm-001 sent."
    out, applied, counts = redact_for_llm(text)
    assert applied is False
    assert out == text
    assert counts == {}


def test_pii_redact_returns_new_string_does_not_mutate() -> None:
    text = "see x@yz.io for details"
    out, _, _ = redact_for_llm(text)
    assert out != text
    # Original input stays valid after redaction (not mutated).
    assert "x@yz.io" in text


# ────────────────────── connector run wrapper ───────────────────────


@pytest.mark.asyncio
async def test_run_with_gate_blocks_when_no_approval() -> None:
    engine = await _engine()
    try:
        from app.services.connector_run import run_with_gate

        async with await _session(engine) as session:
            calls = {"n": 0}

            async def runner() -> str:
                calls["n"] += 1
                return "should_not_run"

            result = await run_with_gate(
                session,
                connector_type="onlymonster",
                requested_action="creator_sync",
                creator_id="creator-A",
                run_callable=runner,
            )
            await session.commit()

            assert result.allowed is False
            assert result.verdict.reason == "no_approval"
            assert calls["n"] == 0  # runner never invoked

            audits = (await session.exec(select(AuditEvent))).all()
            assert any(a.event_type == "connector.run.blocked" for a in audits)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_with_gate_runs_when_approval_and_consent_present() -> None:
    engine = await _engine()
    try:
        from app.services import connector_approvals as approvals_svc
        from app.services import consent as consent_svc
        from app.services.connector_run import run_with_gate

        async with await _session(engine) as session:
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
            await session.commit()

            async def runner() -> str:
                return "ran_ok"

            result = await run_with_gate(
                session,
                connector_type="onlymonster",
                requested_action="creator_sync",
                creator_id="creator-A",
                run_callable=runner,
            )
            assert result.allowed is True
            assert result.value == "ran_ok"
    finally:
        await engine.dispose()


# ──────────────────────── denial audit hook ─────────────────────────


def test_denial_audit_throttle_dedupes() -> None:
    from app.core import denial_audit as da

    # Reset any cached state from prior tests.
    da._last_audit.clear()  # type: ignore[attr-defined]

    key: tuple[str, str, int] = ("1.2.3.4", "/api/v1/x", 401)
    now = 100.0
    assert da._should_audit(key, now) is True  # first call → audit
    assert da._should_audit(key, now + 10) is False  # within window → throttled
    assert da._should_audit(key, now + da.THROTTLE_WINDOW_SECONDS + 1) is True  # new window
