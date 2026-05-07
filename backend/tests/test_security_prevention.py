"""Sprint 2 prevention controls — service + gate tests.

Combined into one file because the four services are small, share the
same in-memory DB pattern, and are best read alongside the gate that
composes them.
"""

from __future__ import annotations

import os
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401  — registers all SQLModel tables
from app.core.connector_gate import is_connector_action_allowed
from app.core.time import utcnow
from app.models.audit_events import AuditEvent
from app.models.client_consents import ClientConsent
from app.models.connector_approvals import ConnectorApproval
from app.models.creator_credentials import CreatorCredential
from app.models.kill_switches import KillSwitch
from app.services import connector_approvals as approvals_svc
from app.services import consent as consent_svc
from app.services import kill_switch as kill_switch_svc
from app.services.creator_credentials import (
    CredentialVaultUnavailableError,
    create_credential,
    get_credential_metadata,
    revoke_credential,
    rotate_credential,
)


async def _engine() -> AsyncEngine:
    e = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with e.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return e


async def _session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


def _set_dedicated_key() -> None:
    """Set a dedicated encryption key so the vault accepts writes.

    We're not connecting any real account; the value here is a
    deterministic test fixture.
    """
    os.environ["SETTINGS_ENCRYPTION_KEY"] = "0" * 64

    # Drop the cached fernet so the new key is picked up.
    from app.core import secrets_store as _ss

    _ss._fernet = None  # type: ignore[attr-defined]


def _clear_dedicated_key() -> None:
    os.environ.pop("SETTINGS_ENCRYPTION_KEY", None)
    from app.core import secrets_store as _ss

    _ss._fernet = None  # type: ignore[attr-defined]


# ───────────────────────────── connector approvals ─────────────────────────────


@pytest.mark.asyncio
async def test_connector_approval_request_then_approve_then_revoke() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            user_id = uuid4()
            row = await approvals_svc.request_approval(
                session,
                connector_type="onlyfans_direct",
                requested_action="read",
                organization_id=None,
                creator_id="creator-A",
                requested_by_user_id=user_id,
                requested_by_email="alice@example.com",
                risk_level="high",
            )
            await session.commit()
            assert row.status == "pending"

            await approvals_svc.approve(
                session,
                row.id,
                approver_user_id=user_id,
                approver_email="owner@example.com",
            )
            await session.commit()

            live = await approvals_svc.is_approved(
                session,
                connector_type="onlyfans_direct",
                requested_action="read",
                creator_id="creator-A",
            )
            assert live is not None
            assert live.id == row.id

            await approvals_svc.revoke(
                session,
                row.id,
                revoker_user_id=user_id,
                revoker_email="owner@example.com",
                reason="testing",
            )
            await session.commit()

            still_live = await approvals_svc.is_approved(
                session,
                connector_type="onlyfans_direct",
                requested_action="read",
                creator_id="creator-A",
            )
            assert still_live is None  # revoked → not live

            audits = (await session.exec(select(AuditEvent))).all()
            event_types = {a.event_type for a in audits}
            assert "connector.approval.request" in event_types
            assert "connector.approval.approve" in event_types
            assert "connector.approval.revoke" in event_types
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_connector_approval_expiry_makes_it_inactive() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            row = await approvals_svc.request_approval(
                session,
                connector_type="onlymonster",
                requested_action="creator_sync",
                expires_at=utcnow() - timedelta(seconds=1),
                creator_id="creator-X",
            )
            await approvals_svc.approve(session, row.id)
            await session.commit()

            live = await approvals_svc.is_approved(
                session,
                connector_type="onlymonster",
                requested_action="creator_sync",
                creator_id="creator-X",
            )
            assert live is None  # already expired
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_connector_approval_unknown_type_rejected() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            with pytest.raises(ValueError):
                await approvals_svc.request_approval(
                    session,
                    connector_type="not_a_connector",
                    requested_action="x",
                )
    finally:
        await engine.dispose()


# ───────────────────────────── kill switches ─────────────────────────────────


@pytest.mark.asyncio
async def test_kill_switch_global_blocks_everything() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            await kill_switch_svc.enable(
                session,
                scope="global",
                actor_email="owner@example.com",
                reason="incident drill",
            )
            await session.commit()

            blocked = await kill_switch_svc.check_action_allowed(
                session,
                connector_type="onlymonster",
                organization_id=uuid4(),
                creator_id="anyone",
            )
            assert blocked == ("global", None)

            audits = (await session.exec(select(AuditEvent))).all()
            assert any(a.event_type == "kill_switch.enable" for a in audits)
            assert any(a.severity == "critical" for a in audits)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_kill_switch_per_connector_blocks_only_that_connector() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            await kill_switch_svc.enable(
                session,
                scope="connector",
                scope_id="onlyfans_direct",
                actor_email="owner@example.com",
            )
            await session.commit()

            assert await kill_switch_svc.check_action_allowed(
                session, connector_type="onlyfans_direct"
            ) == ("connector", "onlyfans_direct")
            assert (
                await kill_switch_svc.check_action_allowed(session, connector_type="onlymonster")
                is None
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_kill_switch_disable_clears_block() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            await kill_switch_svc.enable(session, scope="global")
            await session.commit()
            assert await kill_switch_svc.is_active(session, scope="global")

            await kill_switch_svc.disable(session, scope="global", reason="all clear")
            await session.commit()
            assert not await kill_switch_svc.is_active(session, scope="global")

            row = (await session.exec(select(KillSwitch))).one()
            assert row.disabled_at is not None
    finally:
        await engine.dispose()


# ───────────────────────────── consent ───────────────────────────────────────


@pytest.mark.asyncio
async def test_consent_grant_revoke_lifecycle() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            row = await consent_svc.grant(
                session,
                consent_type="onlyfans_direct_read",
                creator_id="creator-Z",
                source="signed_pdf",
                document_reference="docusign:abc123",
            )
            await session.commit()
            assert row.status == "granted"

            live = await consent_svc.is_granted(
                session,
                consent_type="onlyfans_direct_read",
                creator_id="creator-Z",
            )
            assert live is not None
            assert live.id == row.id

            await consent_svc.revoke(
                session,
                consent_id=row.id,
                reason="creator request",
            )
            await session.commit()

            still_live = await consent_svc.is_granted(
                session,
                consent_type="onlyfans_direct_read",
                creator_id="creator-Z",
            )
            assert still_live is None

            audits = (await session.exec(select(AuditEvent))).all()
            assert any(a.event_type == "consent.grant" for a in audits)
            assert any(a.event_type == "consent.revoke" for a in audits)

            consents = (await session.exec(select(ClientConsent))).all()
            assert len(consents) == 1  # row preserved, not deleted
            assert consents[0].status == "revoked"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_consent_unknown_type_returns_none() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            assert (
                await consent_svc.is_granted(
                    session,
                    consent_type="not_a_real_consent",
                    creator_id="anyone",
                )
                is None
            )
    finally:
        await engine.dispose()


# ───────────────────────────── creator credentials ──────────────────────────


@pytest.mark.asyncio
async def test_creator_vault_refuses_writes_without_dedicated_key() -> None:
    _clear_dedicated_key()
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            with pytest.raises(CredentialVaultUnavailableError):
                await create_credential(
                    session,
                    organization_id=None,
                    creator_id="creator-Q",
                    provider="internal",  # safe placeholder
                    credential_type="api_key",
                    plaintext="placeholder-not-a-real-token",
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_creator_vault_create_revoke_rotate_with_dedicated_key() -> None:
    _set_dedicated_key()
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            row = await create_credential(
                session,
                organization_id=None,
                creator_id="creator-Q",
                provider="internal",
                credential_type="api_key",
                plaintext="placeholder-not-a-real-token",
            )
            await session.commit()

            assert row.encrypted_value
            assert row.encrypted_value != "placeholder-not-a-real-token"

            md = get_credential_metadata(row)
            assert "encrypted_value" not in md
            assert md["provider"] == "internal"
            assert md["status"] == "active"

            old, new = await rotate_credential(
                session,
                row.id,
                new_plaintext="placeholder-rotated-not-a-real-token",
                rotated_by_email="owner@example.com",
            )
            await session.commit()
            assert old is not None and new is not None
            assert old.status == "rotated"
            assert new.status == "active"
            assert new.encrypted_value != old.encrypted_value

            await revoke_credential(
                session,
                new.id,
                revoked_by_email="owner@example.com",
                reason="end of test",
            )
            await session.commit()

            rows = (
                await session.exec(
                    select(CreatorCredential).where(CreatorCredential.creator_id == "creator-Q")
                )
            ).all()
            statuses = {r.status for r in rows}
            assert statuses == {"rotated", "revoked"}

            audits = (
                await session.exec(select(AuditEvent).where(AuditEvent.category == "credential"))
            ).all()
            event_types = {a.event_type for a in audits}
            assert "creator_credential.create" in event_types
            assert "creator_credential.rotate" in event_types
            assert "creator_credential.revoke" in event_types

            # No raw plaintext should appear in any audit metadata.
            for a in audits:
                serialised = str(a.metadata_json)
                assert "placeholder-not-a-real-token" not in serialised
                assert "placeholder-rotated-not-a-real-token" not in serialised
    finally:
        _clear_dedicated_key()
        await engine.dispose()


# ───────────────────────────── connector gate ───────────────────────────────


@pytest.mark.asyncio
async def test_gate_blocks_unknown_connector() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            verdict = await is_connector_action_allowed(
                session,
                connector_type="not_a_connector",
                requested_action="x",
            )
            assert not verdict.allowed
            assert verdict.reason == "unknown_connector"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_gate_blocks_when_no_approval() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            verdict = await is_connector_action_allowed(
                session,
                connector_type="onlymonster",
                requested_action="creator_sync",
                creator_id="creator-Y",
            )
            assert not verdict.allowed
            assert verdict.reason == "no_approval"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_gate_blocks_when_kill_switch_active() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            row = await approvals_svc.request_approval(
                session,
                connector_type="onlymonster",
                requested_action="creator_sync",
                creator_id="creator-Y",
            )
            await approvals_svc.approve(session, row.id)
            await consent_svc.grant(
                session,
                consent_type="onlymonster_sync",
                creator_id="creator-Y",
            )
            await kill_switch_svc.enable(session, scope="global")
            await session.commit()

            verdict = await is_connector_action_allowed(
                session,
                connector_type="onlymonster",
                requested_action="creator_sync",
                creator_id="creator-Y",
            )
            assert not verdict.allowed
            assert verdict.reason == "kill_switch_global"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_gate_blocks_when_consent_missing_for_consent_required_action() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            row = await approvals_svc.request_approval(
                session,
                connector_type="onlyfans_direct",
                requested_action="read",
                creator_id="creator-Y",
            )
            await approvals_svc.approve(session, row.id)
            await session.commit()

            verdict = await is_connector_action_allowed(
                session,
                connector_type="onlyfans_direct",
                requested_action="read",
                creator_id="creator-Y",
            )
            assert not verdict.allowed
            assert verdict.reason == "no_consent"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_gate_blocks_onlyfans_direct_when_vault_unavailable() -> None:
    _clear_dedicated_key()
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            row = await approvals_svc.request_approval(
                session,
                connector_type="onlyfans_direct",
                requested_action="read",
                creator_id="creator-V",
            )
            await approvals_svc.approve(session, row.id)
            await consent_svc.grant(
                session,
                consent_type="onlyfans_direct_read",
                creator_id="creator-V",
            )
            await session.commit()

            verdict = await is_connector_action_allowed(
                session,
                connector_type="onlyfans_direct",
                requested_action="read",
                creator_id="creator-V",
            )
            assert not verdict.allowed
            assert verdict.reason == "vault_unavailable"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_gate_allows_when_all_prerequisites_satisfied() -> None:
    _set_dedicated_key()
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            row = await approvals_svc.request_approval(
                session,
                connector_type="onlyfans_direct",
                requested_action="read",
                creator_id="creator-W",
            )
            await approvals_svc.approve(session, row.id)
            await consent_svc.grant(
                session,
                consent_type="onlyfans_direct_read",
                creator_id="creator-W",
            )
            await session.commit()

            verdict = await is_connector_action_allowed(
                session,
                connector_type="onlyfans_direct",
                requested_action="read",
                creator_id="creator-W",
            )
            assert verdict.allowed
            assert verdict.reason == "ok"
    finally:
        _clear_dedicated_key()
        await engine.dispose()


# Phase 5 tiny check: dedicated key sentinel is honest about env state.


def test_is_dedicated_key_configured_reflects_env_var() -> None:
    from app.core.secrets_store import is_dedicated_encryption_key_configured

    _clear_dedicated_key()
    assert is_dedicated_encryption_key_configured() is False

    _set_dedicated_key()
    try:
        assert is_dedicated_encryption_key_configured() is True
    finally:
        _clear_dedicated_key()


# Capture-check: the user_id test below ensures actor_user_id flows
# through to audit metadata for traceability.


@pytest.mark.asyncio
async def test_audit_metadata_records_actor_correctly() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            actor: UUID = uuid4()
            row = await approvals_svc.request_approval(
                session,
                connector_type="discord",
                requested_action="connect",
                requested_by_user_id=actor,
                requested_by_email="alice@example.com",
            )
            await session.commit()

            audits = (await session.exec(select(AuditEvent))).all()
            relevant = [a for a in audits if a.event_type == "connector.approval.request"]
            assert relevant
            assert relevant[0].actor_user_id == actor
            assert relevant[0].actor_email == "alice@example.com"
            assert relevant[0].resource_id == str(row.id)
    finally:
        await engine.dispose()
