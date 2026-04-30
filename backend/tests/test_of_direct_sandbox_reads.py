"""Sprint 8D — direct OnlyFans sandbox-read tests.

Verifies the three Sprint 8D account-level read methods
(``read_account_profile``, ``read_account_stats``,
``read_revenue_summary``) when wired through the fake transport.
The other 7 read methods must still raise.

Architecture:

- In-memory SQLite per test.
- Deterministic ``FakeTransport`` configured per test with a
  path → ``TransportResponse`` map. No HTTP, no scraping, no
  network anywhere.
- ``RealOnlyFansReadOnlyClient(credential_ref=..., transport=fake)``
  is the only real client this test suite ever constructs. The
  fake transport's payloads are explicitly synthetic.
- Sandbox gate from Sprint 8C is exercised end-to-end, with the
  Sprint 8C all-pass test now landing on real-read success
  (because the three methods now have bodies) instead of
  ``real_client_not_enabled``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401  — registers tables
from app.core.onlyfans_direct_credential_ref import CredentialReference
from app.core.onlyfans_direct_schemas import (
    AccountProfileSummary,
    AccountStatsSummary,
    RevenueSummary,
    SchemaParseError,
    parse_account_profile,
    parse_account_stats,
    parse_revenue_summary,
    safe_field_counts,
)
from app.models.audit_events import AuditEvent
from app.services import creator_credentials as _cred_svc
from app.services.onlyfans_direct_connector import (
    ENV_SANDBOX_ALLOWED,
    OnlyFansDirectConnector,
)
from app.services.onlyfans_direct_owner_signoff import record_owner_signoff
from app.services.onlyfans_direct_real_client import (
    RealClientNotEnabledError,
    RealOnlyFansReadOnlyClient,
)
from app.services.onlyfans_direct_transport import (
    ChallengeDetectedError,
    FakeTransport,
    Transport,
    TransportResponse,
    UnexpectedStatusError,
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


async def _full_sandbox_setup(session: AsyncSession, *, creator_id: str) -> CredentialReference:
    """Set up every Sprint 8C sandbox prereq for ``creator_id`` and
    return the credential reference.
    """
    from app.services import connector_approvals as _approvals_svc
    from app.services import consent as _consent_svc

    ref = await _create_active_credential(session, creator_id=creator_id)
    approval_row = await _approvals_svc.request_approval(
        session,
        connector_type="onlyfans_direct",
        requested_action="read",
        creator_id=creator_id,
    )
    await _approvals_svc.approve(session, approval_row.id)
    await _consent_svc.grant(
        session,
        consent_type="onlyfans_direct_read",
        creator_id=creator_id,
    )
    await record_owner_signoff(
        session,
        creator_id=creator_id,
        owner_user_id=uuid4(),
        owner_email="owner@example.test",
        notes="sprint-8d test",
    )
    await session.commit()
    return ref


def _build_fake_transport_with_all_three_paths() -> FakeTransport:
    """Configure a fake transport with deterministic, synthetic
    responses for all three Sprint 8D paths.
    """
    return FakeTransport(
        responses={
            "/sandbox/account/profile": TransportResponse(
                status_code=200,
                json_body={
                    "creator_handle": "test-creator-001",
                    "display_name": "Test Creator (synthetic)",
                    "joined_iso": "2024-01-15T00:00:00+00:00",
                    "subscription_tier_count": 1,
                    # Unknown keys must be discarded by the parser.
                    "internal_id": "should-not-appear-in-output",
                    "follower_emails": ["should-not-leak@nope.invalid"],
                },
                content_type="application/json",
            ),
            "/sandbox/account/stats": TransportResponse(
                status_code=200,
                json_body={
                    "subscriber_count": 50,
                    "renewal_rate_pct": 60,
                    "active_chats": 3,
                    "fan_emails": ["should-not-leak@nope.invalid"],
                },
                content_type="application/json",
            ),
            "/sandbox/account/revenue-summary": TransportResponse(
                status_code=200,
                json_body={
                    "currency": "USD",
                    "month_to_date": 100,
                    "previous_month": 200,
                    "tips_subtotal": 0,
                    "ppv_subtotal": 0,
                    "subscription_subtotal": 100,
                    "per_fan_breakdown": [{"fan": "should-not-leak"}],
                },
                content_type="application/json",
            ),
        }
    )


# ── Phase 1: transport ──────────────────────────────────────────────────────


def test_fake_transport_satisfies_protocol() -> None:
    fake = FakeTransport()
    assert isinstance(fake, Transport)


def test_transport_module_has_no_network_imports() -> None:
    """Sprint 8E exemption: ``onlyfans_direct_transport.py`` may
    import ``httpx`` only. Other forbidden imports must still be
    absent.
    """
    repo_root = Path(__file__).resolve().parents[1]
    rel = "app/services/onlyfans_direct_transport.py"
    text = (repo_root / rel).read_text(encoding="utf-8")
    allowed_for_this_file = frozenset({"httpx"})
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
        if forbidden in allowed_for_this_file:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"import {forbidden}") or stripped.startswith(
                f"from {forbidden} "
            ):
                pytest.fail(f"{rel} imports {forbidden!r}: {line!r}")


# Sprint 8E: the constructor and fetch behavior of RealHTTPTransport
# is exercised in detail by ``tests/test_of_direct_sandbox_transport.py``.
# The Sprint 8D placeholder tests below have been replaced with two
# minimal smoke checks here so this file's invariants stay focused
# on the schemas / fake-client / sandbox-gate scope.


def test_real_http_transport_now_has_constructor_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sprint 8E updated `RealHTTPTransport` to require `base_url`
    and `credential_loader`. The Sprint 8D no-arg construction
    path no longer exists.
    """
    from app.services.onlyfans_direct_transport import RealHTTPTransport

    import inspect

    sig = inspect.signature(RealHTTPTransport.__init__)
    assert "base_url" in sig.parameters
    assert "credential_loader" in sig.parameters


# ── Phase 2: schemas ───────────────────────────────────────────────────────


def test_parse_account_profile_drops_unknown_keys() -> None:
    payload = {
        "creator_handle": "test-creator-001",
        "display_name": "Test Creator",
        "joined_iso": "2024-01-15T00:00:00+00:00",
        "subscription_tier_count": 2,
        "internal_id": "drop-me",
        "follower_emails": ["x@y.test"],
    }
    summary = parse_account_profile(payload)
    assert isinstance(summary, AccountProfileSummary)
    text = repr(summary).lower()
    assert "internal_id" not in text
    assert "follower_emails" not in text
    assert "@y.test" not in text


def test_parse_account_stats_clamps_renewal_rate_and_negatives() -> None:
    summary = parse_account_stats(
        {"subscriber_count": -5, "renewal_rate_pct": 150, "active_chats": -1}
    )
    assert summary.subscriber_count == 0
    assert summary.renewal_rate_pct == 100
    assert summary.active_chats == 0


def test_parse_revenue_summary_normalizes_currency_and_drops_extras() -> None:
    summary = parse_revenue_summary(
        {
            "currency": "u$d",  # bad
            "month_to_date": 100,
            "previous_month": 200,
            "tips_subtotal": 0,
            "ppv_subtotal": 0,
            "subscription_subtotal": 100,
            "per_fan_breakdown": [{"fan": "drop-me"}],
        }
    )
    assert isinstance(summary, RevenueSummary)
    assert summary.currency == "USD"  # default
    assert summary.month_to_date == 100
    assert "per_fan_breakdown" not in repr(summary).lower()
    assert "drop-me" not in repr(summary).lower()


def test_parse_refuses_non_dict_payload() -> None:
    for bad in ([], "string", 42, None):
        with pytest.raises(SchemaParseError):
            parse_account_profile(bad)


def test_safe_field_counts_returns_only_scalars() -> None:
    profile = parse_account_profile({"creator_handle": "test-creator-001"})
    counts = safe_field_counts(profile)
    # No string handles, no display names, only scalar counts.
    assert all(isinstance(v, int) for v in counts.values())
    assert "creator_handle" not in counts
    assert "display_name" not in counts


# ── Phase 3: real client read methods ──────────────────────────────────────


@pytest.mark.asyncio
async def test_read_methods_raise_without_transport() -> None:
    """Sprint 8C invariant preserved: a client constructed without
    a transport still raises for every read.
    """
    ref = CredentialReference(creator_id="c", credential_id=uuid4())
    client = RealOnlyFansReadOnlyClient(credential_ref=ref)
    with pytest.raises(RealClientNotEnabledError):
        await client.read_account_profile(creator_id="c")


@pytest.mark.asyncio
async def test_read_account_profile_via_fake_transport_returns_typed_dict() -> None:
    ref = CredentialReference(creator_id="c", credential_id=uuid4())
    fake = _build_fake_transport_with_all_three_paths()
    client = RealOnlyFansReadOnlyClient(credential_ref=ref, transport=fake)
    out = await client.read_account_profile(creator_id="c")
    assert out["creator_handle"] == "test-creator-001"
    assert "internal_id" not in out  # unknown keys discarded
    assert "follower_emails" not in out
    assert fake.calls == ["/sandbox/account/profile"]


@pytest.mark.asyncio
async def test_read_account_stats_via_fake_transport_returns_typed_dict() -> None:
    ref = CredentialReference(creator_id="c", credential_id=uuid4())
    fake = _build_fake_transport_with_all_three_paths()
    client = RealOnlyFansReadOnlyClient(credential_ref=ref, transport=fake)
    out = await client.read_account_stats(creator_id="c")
    assert out["subscriber_count"] == 50
    assert out["renewal_rate_pct"] == 60
    assert "fan_emails" not in out


@pytest.mark.asyncio
async def test_read_revenue_summary_via_fake_transport_returns_typed_dict() -> None:
    ref = CredentialReference(creator_id="c", credential_id=uuid4())
    fake = _build_fake_transport_with_all_three_paths()
    client = RealOnlyFansReadOnlyClient(credential_ref=ref, transport=fake)
    out = await client.read_revenue_summary(creator_id="c")
    assert out["currency"] == "USD"
    assert out["month_to_date"] == 100
    assert "per_fan_breakdown" not in out


@pytest.mark.asyncio
async def test_read_method_translates_401_to_challenge() -> None:
    ref = CredentialReference(creator_id="c", credential_id=uuid4())
    fake = FakeTransport(
        responses={
            "/sandbox/account/profile": TransportResponse(status_code=401, json_body=None),
        }
    )
    client = RealOnlyFansReadOnlyClient(credential_ref=ref, transport=fake)
    with pytest.raises(ChallengeDetectedError) as excinfo:
        await client.read_account_profile(creator_id="c")
    assert excinfo.value.reason_category == "login_required"


@pytest.mark.asyncio
async def test_read_method_translates_other_status_to_unexpected() -> None:
    ref = CredentialReference(creator_id="c", credential_id=uuid4())
    fake = FakeTransport(
        responses={
            "/sandbox/account/stats": TransportResponse(status_code=503, json_body=None),
        }
    )
    client = RealOnlyFansReadOnlyClient(credential_ref=ref, transport=fake)
    with pytest.raises(UnexpectedStatusError) as excinfo:
        await client.read_account_stats(creator_id="c")
    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_other_seven_read_methods_still_raise_real_client_not_enabled() -> None:
    """Even with a transport configured, the 7 unimplemented
    methods must still raise. Sprint 8D scope is exactly three.
    """
    ref = CredentialReference(creator_id="c", credential_id=uuid4())
    fake = _build_fake_transport_with_all_three_paths()
    client = RealOnlyFansReadOnlyClient(credential_ref=ref, transport=fake)
    not_implemented = [
        "read_fan_list_metadata",
        "read_chat_thread_metadata",
        "read_chat_messages",
        "read_vault_metadata",
        "read_post_metadata",
        "read_story_metadata",
        "read_mass_message_metadata",
    ]
    for method_name in not_implemented:
        method = getattr(client, method_name)
        with pytest.raises(RealClientNotEnabledError):
            await method(creator_id="c")


# ── Phase 4 + 5: sandbox dry-run with real reads ───────────────────────────


@pytest.mark.asyncio
async def test_sandbox_run_blocks_without_env_flag_even_with_real_reads() -> None:
    _clear_sandbox_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                ref = await _full_sandbox_setup(session, creator_id="creator-A")
                fake = _build_fake_transport_with_all_three_paths()
                client = RealOnlyFansReadOnlyClient(credential_ref=ref, transport=fake)
                shell = OnlyFansDirectConnector(mode="sandbox", client=client, credential_ref=ref)
                result = await shell.dry_run_sandbox(
                    session,
                    action="account_profile_read",
                    creator_id="creator-A",
                )
                assert result.allowed is False
                assert result.blocked_reason == "env_flag_disabled"
                assert fake.calls == []  # transport was never reached
        finally:
            await engine.dispose()
    finally:
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_sandbox_run_blocks_without_owner_signoff_even_with_real_reads() -> None:
    """Approval + consent + credential active, but no owner sign-off.
    The sandbox gate refuses before the transport is reached.
    """
    from app.services import connector_approvals as _approvals_svc
    from app.services import consent as _consent_svc

    _enable_sandbox_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                ref = await _create_active_credential(session, creator_id="creator-A")
                approval_row = await _approvals_svc.request_approval(
                    session,
                    connector_type="onlyfans_direct",
                    requested_action="read",
                    creator_id="creator-A",
                )
                await _approvals_svc.approve(session, approval_row.id)
                await _consent_svc.grant(
                    session,
                    consent_type="onlyfans_direct_read",
                    creator_id="creator-A",
                )
                await session.commit()
                # Note: no record_owner_signoff call.

                fake = _build_fake_transport_with_all_three_paths()
                client = RealOnlyFansReadOnlyClient(credential_ref=ref, transport=fake)
                shell = OnlyFansDirectConnector(mode="sandbox", client=client, credential_ref=ref)
                result = await shell.dry_run_sandbox(
                    session,
                    action="account_profile_read",
                    creator_id="creator-A",
                )
                assert result.allowed is False
                assert result.blocked_reason == "no_owner_signoff"
                assert fake.calls == []  # transport never reached
        finally:
            await engine.dispose()
    finally:
        _clear_sandbox_flag()
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_sandbox_run_succeeds_for_three_implemented_reads() -> None:
    _enable_sandbox_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                ref = await _full_sandbox_setup(session, creator_id="creator-A")
                fake = _build_fake_transport_with_all_three_paths()
                client = RealOnlyFansReadOnlyClient(credential_ref=ref, transport=fake)
                shell = OnlyFansDirectConnector(mode="sandbox", client=client, credential_ref=ref)
                # Run all three.
                for action in (
                    "account_profile_read",
                    "account_stats_read",
                    "revenue_summary_read",
                ):
                    result = await shell.dry_run_sandbox(
                        session,
                        action=action,
                        creator_id="creator-A",
                    )
                    assert result.allowed is True, f"{action} should pass"
                    assert result.blocked_reason is None
                    assert result.audit_event_id is not None

                # Three success rows expected, one per action.
                audits = (await session.exec(select(AuditEvent))).all()
                successes = [a for a in audits if a.event_type == "connector.sandbox.success"]
                assert len(successes) == 3
                for row in successes:
                    meta = row.metadata_json
                    assert meta["mode"] == "sandbox"
                    assert meta["rows_written"] == 0
                    assert isinstance(meta["field_counts"], dict)
                    # Only scalar counts in field_counts; no handles
                    # or display names.
                    for v in meta["field_counts"].values():
                        assert isinstance(v, int)
        finally:
            await engine.dispose()
    finally:
        _clear_sandbox_flag()
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_sandbox_run_records_session_challenged_on_401() -> None:
    _enable_sandbox_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                ref = await _full_sandbox_setup(session, creator_id="creator-A")
                # Transport responds with 401 → challenge.
                fake = FakeTransport(
                    responses={
                        "/sandbox/account/profile": TransportResponse(
                            status_code=401, json_body=None
                        ),
                    }
                )
                client = RealOnlyFansReadOnlyClient(credential_ref=ref, transport=fake)
                shell = OnlyFansDirectConnector(mode="sandbox", client=client, credential_ref=ref)
                result = await shell.dry_run_sandbox(
                    session,
                    action="account_profile_read",
                    creator_id="creator-A",
                )
                assert result.allowed is False
                assert result.blocked_reason == "challenge_detected"

                audits = (await session.exec(select(AuditEvent))).all()
                event_types = {a.event_type for a in audits}
                assert "connector.session.challenged" in event_types
                challenged = next(
                    a for a in audits if a.event_type == "connector.session.challenged"
                )
                meta = challenged.metadata_json
                assert meta["reason_category"] == "login_required"
                # No raw bodies / cookies / sessions in the audit row.
                forbidden = {
                    "response_body",
                    "raw_body",
                    "html",
                    "headers",
                    "set_cookie",
                    "cookie",
                    "session_token",
                    "x-bc",
                    "credential_value",
                }
                assert forbidden.isdisjoint(set(meta.keys()))
        finally:
            await engine.dispose()
    finally:
        _clear_sandbox_flag()
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_sandbox_run_records_failure_on_unexpected_status() -> None:
    _enable_sandbox_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                ref = await _full_sandbox_setup(session, creator_id="creator-A")
                fake = FakeTransport(
                    responses={
                        "/sandbox/account/stats": TransportResponse(
                            status_code=503, json_body=None
                        ),
                    }
                )
                client = RealOnlyFansReadOnlyClient(credential_ref=ref, transport=fake)
                shell = OnlyFansDirectConnector(mode="sandbox", client=client, credential_ref=ref)
                result = await shell.dry_run_sandbox(
                    session,
                    action="account_stats_read",
                    creator_id="creator-A",
                )
                assert result.allowed is False
                assert result.blocked_reason == "unexpected_status"
                audits = (await session.exec(select(AuditEvent))).all()
                event_types = {a.event_type for a in audits}
                assert "connector.sandbox.failed" in event_types
                fail_row = next(a for a in audits if a.event_type == "connector.sandbox.failed")
                assert fail_row.metadata_json["status_code"] == 503
        finally:
            await engine.dispose()
    finally:
        _clear_sandbox_flag()
        _clear_dedicated_key()


@pytest.mark.asyncio
async def test_sandbox_run_blocks_unimplemented_method_with_real_client_not_enabled() -> None:
    """A method outside the Sprint 8D scope (e.g. chat_message_read)
    must still land on ``real_client_not_enabled`` even when every
    other prereq passes.
    """
    _enable_sandbox_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                ref = await _full_sandbox_setup(session, creator_id="creator-A")
                fake = _build_fake_transport_with_all_three_paths()
                client = RealOnlyFansReadOnlyClient(credential_ref=ref, transport=fake)
                shell = OnlyFansDirectConnector(mode="sandbox", client=client, credential_ref=ref)
                result = await shell.dry_run_sandbox(
                    session,
                    action="chat_message_read",
                    creator_id="creator-A",
                )
                assert result.allowed is False
                assert result.blocked_reason == "real_client_not_enabled"
        finally:
            await engine.dispose()
    finally:
        _clear_sandbox_flag()
        _clear_dedicated_key()


# ── Audit safety: no raw body, no cookies, no tokens anywhere ──────────────


@pytest.mark.asyncio
async def test_no_raw_body_or_cookies_in_any_audit_row_after_sandbox_success() -> None:
    _enable_sandbox_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                ref = await _full_sandbox_setup(session, creator_id="creator-A")
                fake = _build_fake_transport_with_all_three_paths()
                client = RealOnlyFansReadOnlyClient(credential_ref=ref, transport=fake)
                shell = OnlyFansDirectConnector(mode="sandbox", client=client, credential_ref=ref)
                await shell.dry_run_sandbox(
                    session,
                    action="account_profile_read",
                    creator_id="creator-A",
                )
                await shell.dry_run_sandbox(
                    session,
                    action="revenue_summary_read",
                    creator_id="creator-A",
                )

                forbidden_keys = {
                    "raw_body",
                    "response_body",
                    "html",
                    "set_cookie",
                    "cookies",
                    "cookie",
                    "session",
                    "session_token",
                    "auth_token",
                    "x-bc",
                    "csrf",
                    "csrf_token",
                    "fan_id",
                    "fan_username",
                    "fan_handle",
                    "message_body",
                    "messages",
                    "credential_value",
                    "encrypted_value",
                    "follower_emails",
                    "fan_emails",
                    "internal_id",
                    "per_fan_breakdown",
                }
                audits = (await session.exec(select(AuditEvent))).all()
                for row in audits:
                    keys = set(row.metadata_json.keys())
                    overlap = keys & forbidden_keys
                    assert (
                        overlap == set()
                    ), f"audit row {row.event_type} carries forbidden keys: {overlap}"
        finally:
            await engine.dispose()
    finally:
        _clear_sandbox_flag()
        _clear_dedicated_key()


# ── safety: no network imports anywhere across all OF-direct files ─────────


def test_no_network_imports_after_8d() -> None:
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


# ── safety: no write methods on any new Sprint 8D surface ──────────────────


def test_no_write_methods_on_real_client_or_fake_transport() -> None:
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
        "write",
        "post_request",
        "delete_request",
        "put_request",
    }
    classes = [RealOnlyFansReadOnlyClient, FakeTransport]
    for cls in classes:
        public = {n for n in dir(cls) if not n.startswith("_")}
        intersection = public & forbidden_method_names
        assert (
            intersection == set()
        ), f"{cls.__name__} exposes write-shaped methods: {sorted(intersection)}"


def test_only_three_real_methods_implemented_after_8d() -> None:
    """Audit-level verification that exactly three methods are wired.

    Counts methods on `RealOnlyFansReadOnlyClient` that do NOT
    immediately raise `RealClientNotEnabledError` when transport is
    set. We test by inspecting code: the body of an unimplemented
    method will only have a single ``raise`` statement.
    """
    import inspect

    implemented_marker = "RealClientNotEnabledError"
    implemented: list[str] = []
    not_implemented: list[str] = []
    from app.core.onlyfans_direct_client import READ_ACTION_TO_METHOD

    for method_name in READ_ACTION_TO_METHOD.values():
        method = getattr(RealOnlyFansReadOnlyClient, method_name)
        src = inspect.getsource(method)
        # Heuristic: a method that only raises has exactly one
        # `raise` line and no `await transport.fetch`. Implemented
        # methods call `_require_transport()`.
        if "_require_transport" in src:
            implemented.append(method_name)
        elif implemented_marker in src:
            not_implemented.append(method_name)
        else:  # pragma: no cover — defensive
            pytest.fail(f"unexpected method body for {method_name!r}")

    assert sorted(implemented) == sorted(
        ["read_account_profile", "read_account_stats", "read_revenue_summary"]
    )
    assert len(not_implemented) == 7
