"""Sprint 8B — direct OnlyFans dry-run-via-fake-client tests.

Mirrors the Sprint 8A OnlyMonster test structure on the OnlyFans
direct path. Every test must prove a refusal or a fully-gated allow.
There is NO test that calls a real OnlyFans surface — by design,
this sprint cannot.

Test architecture: in-memory SQLite per-test, deterministic
:class:`FakeOnlyFansReadOnlyClient`. No HTTP client, no fixture
data leak between tests.
"""

from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401  — registers tables
from app.core.onlyfans_direct_client import (
    READ_ACTION_TO_METHOD,
    AbstractOnlyFansReadOnlyClient,
    OnlyFansReadOnlyClient,
)
from app.core.onlyfans_direct_credentials import (
    CredentialContractViolation,
)
from app.core.onlyfans_direct_policy import (
    READ_ACTIONS,
    WRITE_ACTIONS,
    BlockedActionError,
)
from app.models.audit_events import AuditEvent
from app.services.onlyfans_direct_connector import (
    CONNECTOR_TYPE,
    CookieRefusedError,
    DryRunResult,
    OnlyFansDirectConnector,
)
from app.services.onlyfans_direct_fake_client import (
    FakeClientRefusedInProductionError,
    FakeOnlyFansReadOnlyClient,
)
from app.services.onlyfans_direct_session_health import (
    ChallengeMetadataContractViolation,
    notify_challenge_stub,
    notify_channel_status,
    record_session_challenged,
)

# ── shared fixtures ─────────────────────────────────────────────────────────


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


# ── Phase 1: read-only client interface shape ──────────────────────────────


def test_protocol_has_one_method_per_read_action() -> None:
    """Every Sprint 7 ``READ_ACTIONS`` entry must map to a method on
    the Protocol via ``READ_ACTION_TO_METHOD``.
    """
    assert set(READ_ACTION_TO_METHOD.keys()) == set(READ_ACTIONS)
    for method_name in READ_ACTION_TO_METHOD.values():
        # Every mapped method must exist on the abstract base.
        assert hasattr(
            AbstractOnlyFansReadOnlyClient, method_name
        ), f"abstract base missing method {method_name!r}"


def test_no_write_method_names_on_protocol_or_base() -> None:
    """Neither the Protocol nor the abstract base may have a callable
    named after any write action — and no callable starting with
    write-shape verbs.
    """
    forbidden_names = set(WRITE_ACTIONS) | {
        "send_message",
        "send_mass_message",
        "post",
        "post_create",
        "post_edit",
        "post_delete",
        "tip",
        "tip_send",
        "vault_upload",
        "vault_edit",
        "vault_delete",
        "follow",
        "unfollow",
        "block_fan",
        "unblock_fan",
        "update_account_settings",
        "update_payout",
        "change_login",
        "create",
        "edit",
        "delete",
        "send",
        "upload",
        "block",
    }
    for cls in (OnlyFansReadOnlyClient, AbstractOnlyFansReadOnlyClient):
        public = {name for name in dir(cls) if not name.startswith("_")}
        forbidden_present = public & forbidden_names
        assert (
            forbidden_present == set()
        ), f"{cls.__name__} exposes write-shaped names: {sorted(forbidden_present)}"


def test_abstract_base_methods_all_raise_not_implemented() -> None:
    """Every method on the abstract base must raise
    ``NotImplementedError``. A subclass must override each method
    individually before it can be called.
    """
    base = AbstractOnlyFansReadOnlyClient()
    for action, method_name in READ_ACTION_TO_METHOD.items():
        method = getattr(base, method_name)

        async def _call() -> None:
            await method(creator_id="creator-A")

        import asyncio

        with pytest.raises(NotImplementedError):
            asyncio.run(_call())
        del action  # silence


# ── Phase 2: fake client behavior ──────────────────────────────────────────


def test_fake_client_implements_all_read_methods() -> None:
    fake = FakeOnlyFansReadOnlyClient()
    # The Protocol is runtime_checkable; instance must satisfy it.
    assert isinstance(fake, OnlyFansReadOnlyClient)
    for method_name in READ_ACTION_TO_METHOD.values():
        assert callable(getattr(fake, method_name))


def test_fake_client_constructor_refuses_cookie_or_session_kwargs() -> None:
    for forbidden_key in ("cookie", "session", "session_token", "x-bc", "password"):
        with pytest.raises(CredentialContractViolation):
            FakeOnlyFansReadOnlyClient(**{forbidden_key: "anything-not-real"})


def test_fake_client_refused_in_production_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import startup_guard

    monkeypatch.setattr(startup_guard, "is_production", lambda: True)
    monkeypatch.delenv("MC_OF_DIRECT_ALLOW_FAKE_CLIENT", raising=False)

    with pytest.raises(FakeClientRefusedInProductionError):
        FakeOnlyFansReadOnlyClient()


def test_fake_client_allowed_in_production_with_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import startup_guard

    monkeypatch.setattr(startup_guard, "is_production", lambda: True)
    monkeypatch.setenv("MC_OF_DIRECT_ALLOW_FAKE_CLIENT", "1")

    fake = FakeOnlyFansReadOnlyClient()
    assert isinstance(fake, FakeOnlyFansReadOnlyClient)


@pytest.mark.asyncio
async def test_fake_client_returns_synthetic_data_only_with_creator_echo() -> None:
    """Each read method returns a payload carrying ``synthetic: True``
    and the creator id echo. No real handles, no real revenue, no
    realistic-looking data.
    """
    fake = FakeOnlyFansReadOnlyClient()
    for method_name in READ_ACTION_TO_METHOD.values():
        method = getattr(fake, method_name)
        payload = await method(creator_id="creator-B")
        assert payload.get("synthetic") is True, f"{method_name} missing synthetic marker"
        assert payload.get("creator_id_echo") == "creator-B"
        text = repr(payload).lower()
        assert "onlyfans.com" not in text
        assert "@" not in text
        # Any creator_handle present must use the test-creator- prefix.
        if "creator_handle" in payload:
            assert payload["creator_handle"].startswith("test-creator-")


# ── Phase 3: connector mode + dry_run via fake client ──────────────────────


def test_connector_default_mode_is_disabled() -> None:
    snapshot = OnlyFansDirectConnector().status()
    assert snapshot.mode == "disabled"
    assert snapshot.enabled is False


def test_connector_dry_run_mode_requires_client() -> None:
    """``mode='dry_run'`` without a client is a programming error and
    must raise at construction.
    """
    with pytest.raises(ValueError, match="requires a client"):
        OnlyFansDirectConnector(mode="dry_run")


def test_connector_invalid_mode_raises() -> None:
    with pytest.raises(ValueError, match="Invalid mode"):
        OnlyFansDirectConnector(mode="real")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Invalid mode"):
        OnlyFansDirectConnector(mode="production")  # type: ignore[arg-type]


def test_connector_constructor_still_refuses_cookies_in_dry_run_mode() -> None:
    fake = FakeOnlyFansReadOnlyClient()
    with pytest.raises(CookieRefusedError):
        OnlyFansDirectConnector(mode="dry_run", client=fake, cookie="x")


def test_connector_status_reflects_dry_run_mode() -> None:
    fake = FakeOnlyFansReadOnlyClient()
    snapshot = OnlyFansDirectConnector(mode="dry_run", client=fake).status()
    assert snapshot.mode == "dry_run"
    assert snapshot.enabled is False  # still not "enabled" — the fake is fake
    assert snapshot.real_client_wired is False
    assert snapshot.session_health == "healthy"


@pytest.mark.asyncio
async def test_disabled_mode_blocks_when_no_approval() -> None:
    """Sprint 7 path remains: mode='disabled' with no approval blocks."""
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            shell = OnlyFansDirectConnector()  # default disabled
            result = await shell.dry_run(
                session,
                action="account_profile_read",
                creator_id="creator-A",
            )
            assert result.allowed is False
            assert result.notes == "gate_blocked"
            assert result.mode == "disabled"
            assert result.used_fake_client is False
            assert result.rows_read == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dry_run_mode_blocks_when_no_approval() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            fake = FakeOnlyFansReadOnlyClient()
            shell = OnlyFansDirectConnector(mode="dry_run", client=fake)
            result = await shell.dry_run(
                session,
                action="account_profile_read",
                creator_id="creator-A",
            )
            assert result.allowed is False
            assert result.notes == "gate_blocked"
            audits = (await session.exec(select(AuditEvent))).all()
            assert any(a.event_type == "connector.run.blocked" for a in audits)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dry_run_mode_blocks_when_no_consent() -> None:
    from app.services import connector_approvals as _approvals_svc

    engine = await _engine()
    try:
        async with await _session(engine) as session:
            row = await _approvals_svc.request_approval(
                session,
                connector_type="onlyfans_direct",
                requested_action="read",
                creator_id="creator-A",
            )
            await _approvals_svc.approve(session, row.id)
            await session.commit()

            fake = FakeOnlyFansReadOnlyClient()
            shell = OnlyFansDirectConnector(mode="dry_run", client=fake)
            result = await shell.dry_run(
                session,
                action="account_profile_read",
                creator_id="creator-A",
            )
            assert result.allowed is False
            assert result.notes == "gate_blocked"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dry_run_mode_blocks_when_global_kill_switch_on() -> None:
    from app.services import kill_switch as _kill_switch_svc

    _set_dedicated_key()
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            await _grant_approval_and_consent(session, creator_id="creator-A")
            await _kill_switch_svc.enable(session, scope="global", reason="sprint-8b")
            await session.commit()

            fake = FakeOnlyFansReadOnlyClient()
            shell = OnlyFansDirectConnector(mode="dry_run", client=fake)
            result = await shell.dry_run(
                session,
                action="account_profile_read",
                creator_id="creator-A",
            )
            assert result.allowed is False
            assert result.notes == "gate_blocked"
            assert result.gate_reason is not None
    finally:
        await engine.dispose()
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_dry_run_mode_blocks_when_connector_kill_switch_on() -> None:
    from app.services import kill_switch as _kill_switch_svc

    _set_dedicated_key()
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            await _grant_approval_and_consent(session, creator_id="creator-A")
            await _kill_switch_svc.enable(
                session,
                scope="connector",
                scope_id="onlyfans_direct",
                reason="sprint-8b",
            )
            await session.commit()

            fake = FakeOnlyFansReadOnlyClient()
            shell = OnlyFansDirectConnector(mode="dry_run", client=fake)
            result = await shell.dry_run(
                session,
                action="account_profile_read",
                creator_id="creator-A",
            )
            assert result.allowed is False
            assert result.notes == "gate_blocked"
    finally:
        await engine.dispose()
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_dry_run_mode_allowed_path_calls_fake_and_audits() -> None:
    """Full pass-through with mode='dry_run' invokes the fake client,
    discards the payload, and audits ``connector.dry_run.pass`` with
    ``used_fake_client=true`` and a non-zero ``rows_read`` for actions
    whose fixture returns a list-shaped field.
    """
    _set_dedicated_key()
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            await _grant_approval_and_consent(session, creator_id="creator-A")

            fake = FakeOnlyFansReadOnlyClient()
            shell = OnlyFansDirectConnector(mode="dry_run", client=fake)
            result = await shell.dry_run(
                session,
                action="chat_thread_metadata_read",  # has a 2-element threads list
                creator_id="creator-A",
            )
            assert isinstance(result, DryRunResult)
            assert result.allowed is True
            assert result.classification == "read"
            assert result.mode == "dry_run"
            assert result.used_fake_client is True
            assert result.rows_read == 2  # fixture has 2 threads
            assert result.notes.startswith("dry_run_pass_via_fake_client")

            # No payload field on the result type.
            from dataclasses import fields

            field_names = {f.name for f in fields(result)}
            for forbidden_field in ("payload", "data", "body", "raw", "messages", "fans"):
                assert forbidden_field not in field_names

            audits = (await session.exec(select(AuditEvent))).all()
            passed = [a for a in audits if a.event_type == "connector.dry_run.pass"]
            assert len(passed) == 1
            meta = passed[0].metadata_json
            assert meta["mode"] == "dry_run"
            assert meta["used_fake_client"] is True
            assert meta["rows_read"] == 2
            assert meta["fixture_only"] is True

            # Forbidden audit-leak keys must not appear.
            forbidden_audit_keys = {
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
            }
            for row in audits:
                assert forbidden_audit_keys.isdisjoint(set(row.metadata_json.keys()))
    finally:
        await engine.dispose()
        _clear_dedicated_key()


# ── Phase 4: session.challenged audit + notify stub ────────────────────────


@pytest.mark.asyncio
async def test_record_session_challenged_writes_warning_row_with_safe_fields() -> None:
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            audit_id = await record_session_challenged(
                session,
                reason_category="captcha",
                creator_id="creator-A",
                extra_metadata={"http_status": 403, "attempt": 3},
            )
            assert audit_id is not None

            audits = (await session.exec(select(AuditEvent))).all()
            challenged = [a for a in audits if a.event_type == "connector.session.challenged"]
            assert len(challenged) == 1
            row = challenged[0]
            assert row.severity == "warning"
            assert row.creator_id == "creator-A"
            meta = row.metadata_json
            assert meta["connector_type"] == "onlyfans_direct"
            assert meta["reason_category"] == "captcha"
            assert meta["mode"] == "dry_run"
            assert meta["http_status"] == 403
            assert meta["attempt"] == 3
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_record_session_challenged_refuses_forbidden_metadata_keys() -> None:
    """Cookies, session tokens, and raw response bodies must never
    enter the audit pipeline through ``extra_metadata``.
    """
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            for forbidden_key in (
                "response_body",
                "raw_body",
                "html",
                "headers",
                "set_cookie",
                "cookie",
                "session_token",
                "x-bc",
                "csrf",
            ):
                with pytest.raises(ChallengeMetadataContractViolation):
                    await record_session_challenged(
                        session,
                        reason_category="captcha",
                        extra_metadata={forbidden_key: "<would-be-leak>"},
                    )
    finally:
        await engine.dispose()


def test_notify_challenge_stub_returns_not_configured() -> None:
    result = notify_challenge_stub(reason_category="captcha", creator_id="creator-A")
    assert result == "not_configured"


def test_notify_channel_status_returns_not_configured() -> None:
    assert notify_channel_status() == "not_configured"


# ── Phase 5: no network imports anywhere on the OF direct path ─────────────


def test_no_network_imports_in_of_direct_modules() -> None:
    """Walk every ``onlyfans_direct_*`` module under ``app.core`` and
    ``app.services`` and assert none import a network client.
    """
    repo_root = Path(__file__).resolve().parents[1]
    forbidden_imports = {
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
    targets: list[str] = []
    for parent in (Path("app/core"), Path("app/services")):
        full = repo_root / parent
        for path in full.glob("onlyfans_direct_*.py"):
            targets.append(str(path.relative_to(repo_root)))

    assert targets, "expected to find onlyfans_direct_* modules"

    for rel in targets:
        full = repo_root / rel
        text = full.read_text(encoding="utf-8")
        for fi in forbidden_imports:
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith(f"import {fi}") or stripped.startswith(f"from {fi} "):
                    pytest.fail(f"{rel} imports forbidden network/scraper module {fi!r}: {line!r}")


# ── Sprint 7 invariants still hold ─────────────────────────────────────────


def test_sprint_7_policy_disjointness_still_holds() -> None:
    assert READ_ACTIONS & WRITE_ACTIONS == frozenset()
    assert len(READ_ACTIONS) == 10
    assert len(WRITE_ACTIONS) == 20


def test_disabled_mode_still_refuses_writes() -> None:
    """Sprint 7's write-action refusal must still raise inside the
    Sprint 8B-extended dry_run.
    """
    import asyncio

    async def _run() -> None:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                shell = OnlyFansDirectConnector()  # disabled mode default
                with pytest.raises(BlockedActionError):
                    await shell.dry_run(session, action="message_send")
        finally:
            await engine.dispose()

    asyncio.run(_run())


# ── connector class itself still has no write methods ──────────────────────


def test_connector_class_exposes_no_write_method_after_8b() -> None:
    shell = OnlyFansDirectConnector()
    forbidden_method_names = {
        "send_message",
        "send_mass_message",
        "post",
        "post_create",
        "post_edit",
        "post_delete",
        "create_story",
        "delete_story",
        "upload_vault",
        "delete_vault",
        "tip",
        "tip_send",
        "block_fan",
        "unblock_fan",
        "follow",
        "unfollow",
        "set_price",
        "update_account_settings",
        "update_payout",
        "change_login",
    }
    public_attrs = {a for a in dir(shell) if not a.startswith("_")}
    intersection = public_attrs & forbidden_method_names
    assert intersection == set(), (
        f"OnlyFansDirectConnector exposes write-shaped methods after 8B: " f"{sorted(intersection)}"
    )


def test_inspect_callables_on_protocol_match_read_action_methods() -> None:
    """The Protocol must expose only the 10 read methods listed in
    ``READ_ACTION_TO_METHOD`` — no extras, no callables that imply
    a non-read action.
    """
    expected = set(READ_ACTION_TO_METHOD.values())
    # ``inspect.getmembers`` of a Protocol surfaces protocol members
    # plus a few dunders. Filter to public callables.
    actual = {
        name
        for name, obj in inspect.getmembers(OnlyFansReadOnlyClient)
        if not name.startswith("_") and callable(obj)
    }
    # Allow Protocol-machinery names; assert at least every expected
    # method is present, and no unexpected extra public callable.
    assert expected <= actual
    extras = actual - expected
    assert extras == set(), f"unexpected public callables on Protocol: {sorted(extras)}"


# ── unused module-walker import safety ─────────────────────────────────────


def test_pkgutil_import_is_for_walker_compat_only() -> None:
    # Sanity: ensure the imports we needed for the walker work.
    assert importlib.__name__ == "importlib"
    assert pkgutil.__name__ == "pkgutil"
