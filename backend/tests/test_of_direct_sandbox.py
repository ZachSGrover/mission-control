"""Sprint 8C — direct OnlyFans sandbox-mode tests.

Verifies the **prerequisite chain** of `mode="sandbox"` for the
direct OnlyFans path. Every test must prove a refusal or a fully-
gated all-pass that *still* refuses (because the real-client
skeleton's read methods raise). There is NO test that calls a
real OnlyFans surface — by design, this sprint cannot.

Test architecture: in-memory SQLite per-test, deterministic
:class:`RealOnlyFansReadOnlyClient` skeleton wrapped in the
connector, ``CredentialReference`` pointed at a vault row created
inline via ``create_credential``. No HTTP client, no fixture data
leak between tests.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401  — registers tables
from app.core.onlyfans_direct_credential_ref import (
    CredentialReference,
    check_credential_status,
)
from app.models.audit_events import AuditEvent
from app.services import creator_credentials as _cred_svc
from app.services.onlyfans_direct_connector import (
    ENV_SANDBOX_ALLOWED,
    OnlyFansDirectConnector,
    SandboxResult,
)
from app.services.onlyfans_direct_owner_signoff import (
    has_owner_signoff,
    record_owner_signoff,
)
from app.services.onlyfans_direct_real_client import (
    RealClientNotEnabledError,
    RealOnlyFansReadOnlyClient,
)
from app.services.onlyfans_direct_session_health import (
    DEFAULT_NOTIFIER,
    NoOpChallengeNotifier,
)

# ── shared fixtures ─────────────────────────────────────────────────────────


async def _engine() -> AsyncEngine:
    e = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with e.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return e


async def _session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


def _enable_sandbox_flag() -> None:
    os.environ[ENV_SANDBOX_ALLOWED] = "1"


def _clear_sandbox_flag() -> None:
    os.environ.pop(ENV_SANDBOX_ALLOWED, None)


def _set_dedicated_key() -> None:
    os.environ["SETTINGS_ENCRYPTION_KEY"] = "0" * 64
    from app.core import secrets_store as _ss

    _ss._fernet = None  # type: ignore[attr-defined]


def _clear_dedicated_key() -> None:
    os.environ.pop("SETTINGS_ENCRYPTION_KEY", None)
    from app.core import secrets_store as _ss

    _ss._fernet = None  # type: ignore[attr-defined]


async def _create_active_credential(
    session: AsyncSession, *, creator_id: str
) -> CredentialReference:
    """Helper: insert an `onlyfans_direct` `session_token` credential
    and return a CredentialReference for it.
    """
    row = await _cred_svc.create_credential(
        session,
        organization_id=None,
        creator_id=creator_id,
        provider="onlyfans_direct",
        credential_type="session_token",
        plaintext="synthetic-not-a-real-token",
    )
    await session.commit()
    return CredentialReference(
        creator_id=creator_id,
        credential_id=row.id,
        provider="onlyfans_direct",
        credential_type="session_token",
    )


async def _grant_approval_and_consent(session: AsyncSession, *, creator_id: str) -> None:
    from app.services import connector_approvals as _approvals_svc
    from app.services import consent as _consent_svc

    row = await _approvals_svc.request_approval(
        session,
        connector_type="onlyfans_direct",
        requested_action="read",
        creator_id=creator_id,
    )
    await _approvals_svc.approve(session, row.id)
    await _consent_svc.grant(
        session,
        consent_type="onlyfans_direct_read",
        creator_id=creator_id,
    )
    await session.commit()


# ── Phase 1: real client skeleton ──────────────────────────────────────────


def test_real_client_subclasses_abstract_base_and_has_no_write_methods() -> None:
    from app.core.onlyfans_direct_client import (
        READ_ACTION_TO_METHOD,
        AbstractOnlyFansReadOnlyClient,
    )
    from app.core.onlyfans_direct_policy import WRITE_ACTIONS

    assert issubclass(RealOnlyFansReadOnlyClient, AbstractOnlyFansReadOnlyClient)
    public = {n for n in dir(RealOnlyFansReadOnlyClient) if not n.startswith("_")}
    assert public.intersection(WRITE_ACTIONS) == set()
    # Every read method on the abstract base must be present on the subclass.
    for method_name in READ_ACTION_TO_METHOD.values():
        assert hasattr(RealOnlyFansReadOnlyClient, method_name)


def test_real_client_constructor_refuses_cookie_or_session_kwargs() -> None:
    from app.core.onlyfans_direct_credentials import (
        CredentialContractViolation,
    )

    ref = CredentialReference(creator_id="c", credential_id=uuid4())
    for forbidden_key in ("cookie", "session", "session_token", "x-bc", "password"):
        with pytest.raises(CredentialContractViolation):
            RealOnlyFansReadOnlyClient(credential_ref=ref, **{forbidden_key: "x"})


def test_real_client_refuses_wrong_provider_in_credential_ref() -> None:
    bad_ref = CredentialReference(creator_id="c", credential_id=uuid4(), provider="onlymonster")
    with pytest.raises(ValueError, match="onlyfans_direct"):
        RealOnlyFansReadOnlyClient(credential_ref=bad_ref)


@pytest.mark.asyncio
async def test_real_client_methods_all_raise_real_client_not_enabled() -> None:
    ref = CredentialReference(creator_id="c", credential_id=uuid4())
    client = RealOnlyFansReadOnlyClient(credential_ref=ref)
    from app.core.onlyfans_direct_client import READ_ACTION_TO_METHOD

    for method_name in READ_ACTION_TO_METHOD.values():
        method = getattr(client, method_name)
        with pytest.raises(RealClientNotEnabledError):
            await method(creator_id="c")


def test_real_client_module_has_no_network_imports() -> None:
    """Walk the real-client module file and assert no HTTP / browser
    automation library is imported.
    """
    repo_root = Path(__file__).resolve().parents[1]
    rel = "app/services/onlyfans_direct_real_client.py"
    text = (repo_root / rel).read_text(encoding="utf-8")
    for forbidden in (
        "httpx",
        "requests",
        "aiohttp",
        "urllib",
        "http.client",
        "playwright",
        "selenium",
        "browser_use",
        "selenium_wire",
        "puppeteer",
    ):
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"import {forbidden}") or stripped.startswith(
                f"from {forbidden} "
            ):
                pytest.fail(f"{rel} imports {forbidden!r}: {line!r}")


# ── Phase 2: sandbox mode constructor / refusals ───────────────────────────


def test_sandbox_mode_requires_client_and_credential_ref() -> None:
    """``mode='sandbox'`` without client or credential_ref is a
    programming error and must raise at construction.
    """
    ref = CredentialReference(creator_id="c", credential_id=uuid4())
    client = RealOnlyFansReadOnlyClient(credential_ref=ref)

    # No client → raises
    with pytest.raises(ValueError, match="requires a client"):
        OnlyFansDirectConnector(mode="sandbox", credential_ref=ref)
    # No credential_ref → raises
    with pytest.raises(ValueError, match="credential_ref"):
        OnlyFansDirectConnector(mode="sandbox", client=client)


def test_sandbox_mode_constructor_still_refuses_cookie_kwargs() -> None:
    from app.services.onlyfans_direct_connector import CookieRefusedError

    ref = CredentialReference(creator_id="c", credential_id=uuid4())
    client = RealOnlyFansReadOnlyClient(credential_ref=ref)
    with pytest.raises(CookieRefusedError):
        OnlyFansDirectConnector(
            mode="sandbox",
            client=client,
            credential_ref=ref,
            cookie="x",
        )


def test_invalid_mode_still_raises_after_8c() -> None:
    with pytest.raises(ValueError, match="Invalid mode"):
        OnlyFansDirectConnector(mode="real")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Invalid mode"):
        OnlyFansDirectConnector(mode="production")  # type: ignore[arg-type]


# ── Phase 2/3: sandbox prerequisite chain ──────────────────────────────────


@pytest.mark.asyncio
async def test_sandbox_blocks_when_env_flag_unset() -> None:
    """Default state: sandbox env flag unset → block immediately."""
    _clear_sandbox_flag()
    _set_dedicated_key()
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            ref = await _create_active_credential(session, creator_id="creator-A")
            client = RealOnlyFansReadOnlyClient(credential_ref=ref)
            shell = OnlyFansDirectConnector(mode="sandbox", client=client, credential_ref=ref)
            result = await shell.dry_run_sandbox(
                session, action="account_profile_read", creator_id="creator-A"
            )
            assert isinstance(result, SandboxResult)
            assert result.allowed is False
            assert result.blocked_reason == "env_flag_disabled"
            assert result.env_flag_set is False

            audits = (await session.exec(select(AuditEvent))).all()
            assert any(a.event_type == "connector.sandbox.blocked" for a in audits)
    finally:
        await engine.dispose()
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_sandbox_blocks_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import startup_guard

    monkeypatch.setattr(startup_guard, "is_production", lambda: True)
    _enable_sandbox_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                ref = await _create_active_credential(session, creator_id="creator-A")
                client = RealOnlyFansReadOnlyClient(credential_ref=ref)
                shell = OnlyFansDirectConnector(mode="sandbox", client=client, credential_ref=ref)
                result = await shell.dry_run_sandbox(
                    session, action="account_profile_read", creator_id="creator-A"
                )
                assert result.allowed is False
                assert result.blocked_reason == "production_environment"
                assert result.is_production is True
        finally:
            await engine.dispose()
    finally:
        _clear_sandbox_flag()
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_sandbox_blocks_when_no_approval() -> None:
    _enable_sandbox_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                ref = await _create_active_credential(session, creator_id="creator-A")
                client = RealOnlyFansReadOnlyClient(credential_ref=ref)
                shell = OnlyFansDirectConnector(mode="sandbox", client=client, credential_ref=ref)
                result = await shell.dry_run_sandbox(
                    session, action="account_profile_read", creator_id="creator-A"
                )
                assert result.allowed is False
                # The connector gate refuses with "no_approval" before
                # consent / kill switch / vault are even reached.
                assert result.blocked_reason == "no_approval"
                assert result.approval_present is False
        finally:
            await engine.dispose()
    finally:
        _clear_sandbox_flag()
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_sandbox_blocks_when_no_consent() -> None:
    from app.services import connector_approvals as _approvals_svc

    _enable_sandbox_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                ref = await _create_active_credential(session, creator_id="creator-A")
                # Approval present, consent missing.
                approval_row = await _approvals_svc.request_approval(
                    session,
                    connector_type="onlyfans_direct",
                    requested_action="read",
                    creator_id="creator-A",
                )
                await _approvals_svc.approve(session, approval_row.id)
                await session.commit()

                client = RealOnlyFansReadOnlyClient(credential_ref=ref)
                shell = OnlyFansDirectConnector(mode="sandbox", client=client, credential_ref=ref)
                result = await shell.dry_run_sandbox(
                    session, action="account_profile_read", creator_id="creator-A"
                )
                assert result.allowed is False
                assert result.blocked_reason == "no_consent"
                assert result.approval_present is True
                assert result.consent_present is False
        finally:
            await engine.dispose()
    finally:
        _clear_sandbox_flag()
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_sandbox_blocks_when_kill_switch_active() -> None:
    from app.services import kill_switch as _kill_switch_svc

    _enable_sandbox_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                ref = await _create_active_credential(session, creator_id="creator-A")
                await _grant_approval_and_consent(session, creator_id="creator-A")
                await _kill_switch_svc.enable(
                    session, scope="connector", scope_id="onlyfans_direct"
                )
                await session.commit()

                client = RealOnlyFansReadOnlyClient(credential_ref=ref)
                shell = OnlyFansDirectConnector(mode="sandbox", client=client, credential_ref=ref)
                result = await shell.dry_run_sandbox(
                    session, action="account_profile_read", creator_id="creator-A"
                )
                assert result.allowed is False
                assert result.blocked_reason == "kill_switch"
                assert result.kill_switch_blocking == "connector"
        finally:
            await engine.dispose()
    finally:
        _clear_sandbox_flag()
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_sandbox_blocks_when_credential_revoked() -> None:
    _enable_sandbox_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                ref = await _create_active_credential(session, creator_id="creator-A")
                await _grant_approval_and_consent(session, creator_id="creator-A")
                # Revoke the credential.
                await _cred_svc.revoke_credential(session, ref.credential_id)
                await session.commit()

                client = RealOnlyFansReadOnlyClient(credential_ref=ref)
                shell = OnlyFansDirectConnector(mode="sandbox", client=client, credential_ref=ref)
                result = await shell.dry_run_sandbox(
                    session, action="account_profile_read", creator_id="creator-A"
                )
                assert result.allowed is False
                assert result.blocked_reason == "credential_revoked"
                assert result.credential_status == "revoked"
        finally:
            await engine.dispose()
    finally:
        _clear_sandbox_flag()
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_sandbox_blocks_when_credential_missing() -> None:
    _enable_sandbox_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                # Approval + consent live, but credential reference
                # points at a non-existent row.
                await _grant_approval_and_consent(session, creator_id="creator-A")
                bogus_ref = CredentialReference(creator_id="creator-A", credential_id=uuid4())
                client = RealOnlyFansReadOnlyClient(credential_ref=bogus_ref)
                shell = OnlyFansDirectConnector(
                    mode="sandbox", client=client, credential_ref=bogus_ref
                )
                result = await shell.dry_run_sandbox(
                    session, action="account_profile_read", creator_id="creator-A"
                )
                assert result.allowed is False
                assert result.blocked_reason == "credential_missing"
                assert result.credential_status == "missing"
        finally:
            await engine.dispose()
    finally:
        _clear_sandbox_flag()
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_sandbox_blocks_when_no_owner_signoff() -> None:
    _enable_sandbox_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                ref = await _create_active_credential(session, creator_id="creator-A")
                await _grant_approval_and_consent(session, creator_id="creator-A")
                # Note: no owner sign-off recorded.

                client = RealOnlyFansReadOnlyClient(credential_ref=ref)
                shell = OnlyFansDirectConnector(mode="sandbox", client=client, credential_ref=ref)
                result = await shell.dry_run_sandbox(
                    session, action="account_profile_read", creator_id="creator-A"
                )
                assert result.allowed is False
                assert result.blocked_reason == "no_owner_signoff"
                assert result.owner_signoff_present is False
        finally:
            await engine.dispose()
    finally:
        _clear_sandbox_flag()
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_sandbox_all_prereqs_pass_real_client_skeleton_still_refuses() -> None:
    """Every prerequisite is satisfied. The real client skeleton's
    method raises ``RealClientNotEnabledError``; the gate captures
    that and audits ``connector.sandbox.blocked`` with reason
    ``real_client_not_enabled``.
    """
    _enable_sandbox_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                ref = await _create_active_credential(session, creator_id="creator-A")
                await _grant_approval_and_consent(session, creator_id="creator-A")
                await record_owner_signoff(
                    session,
                    creator_id="creator-A",
                    owner_user_id=uuid4(),
                    owner_email="owner@example.test",
                    notes="sprint-8c test",
                )

                client = RealOnlyFansReadOnlyClient(credential_ref=ref)
                shell = OnlyFansDirectConnector(mode="sandbox", client=client, credential_ref=ref)
                result = await shell.dry_run_sandbox(
                    session, action="account_profile_read", creator_id="creator-A"
                )
                assert result.allowed is False
                assert result.blocked_reason == "real_client_not_enabled"
                assert result.env_flag_set is True
                assert result.is_production is False
                assert result.credential_status == "active"
                assert result.approval_present is True
                assert result.consent_present is True
                assert result.kill_switch_blocking is None
                assert result.vault_available is True
                assert result.owner_signoff_present is True

                audits = (await session.exec(select(AuditEvent))).all()
                blocked = [a for a in audits if a.event_type == "connector.sandbox.blocked"]
                assert len(blocked) == 1
                meta = blocked[0].metadata_json
                assert meta["blocked_reason"] == "real_client_not_enabled"
                assert meta["mode"] == "sandbox"
                # Forbidden audit-leak keys must not appear anywhere.
                forbidden = {
                    "fan_id",
                    "fan_username",
                    "fan_handle",
                    "message_body",
                    "messages",
                    "subscribers",
                    "tips",
                    "raw",
                    "payload",
                    "html",
                    "set_cookie",
                    "session_token",
                    "credential_value",
                    "encrypted_value",
                }
                for row in audits:
                    assert forbidden.isdisjoint(set(row.metadata_json.keys()))
        finally:
            await engine.dispose()
    finally:
        _clear_sandbox_flag()
        _clear_dedicated_key()


# ── Phase 3: credential vault reference helper ─────────────────────────────


@pytest.mark.asyncio
async def test_check_credential_status_missing_returns_missing_kind() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            ref = CredentialReference(creator_id="creator-A", credential_id=uuid4())
            report = await check_credential_status(session, ref=ref)
            assert report.kind == "missing"
            assert report.exists is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_check_credential_status_active_returns_active() -> None:
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                ref = await _create_active_credential(session, creator_id="creator-A")
                report = await check_credential_status(session, ref=ref)
                assert report.kind == "active"
                assert report.exists is True
                assert report.is_active is True
        finally:
            await engine.dispose()
    finally:
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_check_credential_status_wrong_provider_refuses() -> None:
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                row = await _cred_svc.create_credential(
                    session,
                    organization_id=None,
                    creator_id="creator-A",
                    provider="onlymonster",
                    credential_type="api_key",
                    plaintext="not-a-real-token",
                )
                await session.commit()
                ref = CredentialReference(
                    creator_id="creator-A",
                    credential_id=row.id,
                    provider="onlyfans_direct",
                )
                report = await check_credential_status(session, ref=ref)
                assert report.kind == "wrong_provider"
                assert report.is_active is False
        finally:
            await engine.dispose()
    finally:
        _clear_dedicated_key()


# ── Phase 4: challenge notifier ────────────────────────────────────────────


def test_default_notifier_is_noop_returning_not_configured() -> None:
    assert isinstance(DEFAULT_NOTIFIER, NoOpChallengeNotifier)
    assert DEFAULT_NOTIFIER.status() == "not_configured"
    assert (
        DEFAULT_NOTIFIER.notify(reason_category="captcha", creator_id="creator-A")
        == "not_configured"
    )


def test_challenge_notifier_protocol_runtime_check() -> None:
    from app.services.onlyfans_direct_session_health import ChallengeNotifier

    assert isinstance(NoOpChallengeNotifier(), ChallengeNotifier)


# ── Phase 5: owner sign-off audit ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_owner_signoff_writes_event_and_has_owner_signoff_finds_it() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            assert (await has_owner_signoff(session, creator_id="creator-A")) is False
            audit_id = await record_owner_signoff(
                session,
                creator_id="creator-A",
                owner_user_id=uuid4(),
                owner_email="owner@example.test",
                notes="drill",
            )
            assert audit_id is not None
            assert (await has_owner_signoff(session, creator_id="creator-A")) is True
            # Sanity: row stored with the right event type and severity.
            audits = (await session.exec(select(AuditEvent))).all()
            golive = [a for a in audits if a.event_type == "connector.golive.sandbox"]
            assert len(golive) == 1
            assert golive[0].severity == "high"
            assert golive[0].creator_id == "creator-A"
    finally:
        await engine.dispose()


# ── safety: no network imports anywhere ────────────────────────────────────


def test_no_network_imports_in_any_of_direct_module_after_8c() -> None:
    """Sprint 8E exemption: ``onlyfans_direct_transport.py`` may
    import ``httpx`` only. Every other forbidden import remains
    refused in every OF-direct module.
    """
    repo_root = Path(__file__).resolve().parents[1]
    forbidden = {
        "httpx",
        "requests",
        "aiohttp",
        "urllib",
        "http.client",
        "playwright",
        "selenium",
        "browser_use",
        "selenium_wire",
        "puppeteer",
    }
    per_file_allowlist: dict[str, frozenset[str]] = {
        "app/services/onlyfans_direct_transport.py": frozenset({"httpx"}),
    }
    targets: list[str] = []
    for parent in (Path("app/core"), Path("app/services")):
        full = repo_root / parent
        for path in full.glob("onlyfans_direct_*.py"):
            targets.append(str(path.relative_to(repo_root)))

    for rel in targets:
        allowed = per_file_allowlist.get(rel, frozenset())
        text = (repo_root / rel).read_text(encoding="utf-8")
        for fi in forbidden:
            if fi in allowed:
                continue
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith(f"import {fi}") or stripped.startswith(f"from {fi} "):
                    pytest.fail(f"{rel} imports forbidden module {fi!r}: {line!r}")


# ── Sprint 7/8B invariants still hold ──────────────────────────────────────


def test_disabled_mode_still_default_and_no_credential_ref_required() -> None:
    """Sprint 7's default-disabled construction must still work
    after Sprint 8C."""
    shell = OnlyFansDirectConnector()
    snapshot = shell.status()
    assert snapshot.mode == "disabled"
    assert snapshot.enabled is False


def test_dry_run_mode_still_works_after_8c() -> None:
    """Sprint 8B's dry_run mode must still construct cleanly."""
    from app.services.onlyfans_direct_fake_client import (
        FakeOnlyFansReadOnlyClient,
    )

    fake = FakeOnlyFansReadOnlyClient()
    shell = OnlyFansDirectConnector(mode="dry_run", client=fake)
    snapshot = shell.status()
    assert snapshot.mode == "dry_run"
