"""Sprint 7 direct-OnlyFans readiness tests.

Covers the policy module, the disabled connector shell, the
fixture-only dry-run path, rate-limit and session-health
scaffolding, and the credential safety contract. Every test must
prove a refusal. There are no positive-flow "make a real call"
tests — by design, this sprint cannot make one.

Test architecture: in-memory SQLite per-test, `record_audit` is the
only network-adjacent surface and it operates against the local DB.
No HTTP client, no fixture data leak between tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401  — registers tables
from app.core.onlyfans_direct_credentials import (
    FORBIDDEN_CREDENTIAL_KEYS,
    FRONTEND_FORBIDDEN_PATTERNS,
    CredentialContractViolation,
    assert_no_forbidden_credential_keys,
    revocation_runbook,
    rotation_runbook,
)
from app.core.onlyfans_direct_policy import (
    READ_ACTIONS,
    WRITE_ACTIONS,
    BlockedActionError,
    classify_action,
    evaluate_action,
    is_read_action,
    is_write_action,
    require_read_action,
)
from app.core.onlyfans_direct_rate_policy import (
    CHALLENGE_REACTION,
    DEFAULT_BACKOFF,
    DEFAULT_MAX_REQUESTS_PER_HOUR,
    DEFAULT_MAX_REQUESTS_PER_MINUTE,
    describe_session_health,
    is_unhealthy,
)
from app.models.audit_events import AuditEvent
from app.services.onlyfans_direct_connector import (
    CONNECTOR_TYPE,
    ConnectorNotEnabledError,
    CookieRefusedError,
    OnlyFansDirectConnector,
)
from app.services.onlyfans_direct_fixtures import fixture_payload_for

# ── shared fixtures ─────────────────────────────────────────────────────────


async def _engine() -> AsyncEngine:
    e = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with e.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return e


async def _session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


# ── policy module ──────────────────────────────────────────────────────────


def test_read_and_write_action_sets_are_disjoint() -> None:
    """No action may be classified as both read and write — that
    would let one set silently grant what the other forbids.
    """
    assert READ_ACTIONS & WRITE_ACTIONS == frozenset()


def test_every_listed_read_action_classifies_as_read() -> None:
    for action in READ_ACTIONS:
        assert classify_action(action) == "read"
        assert is_read_action(action)
        assert not is_write_action(action)
        verdict = evaluate_action(action)
        assert verdict.allowed is True
        assert verdict.classification == "read"
        # require_read_action must NOT raise for any read action.
        require_read_action(action)


def test_every_listed_write_action_is_blocked() -> None:
    """The brief enumerates 20 write actions. Every single one must
    classify as write and refuse.
    """
    expected_writes = {
        "message_send",
        "post_create",
        "post_edit",
        "post_delete",
        "story_create",
        "story_delete",
        "vault_upload",
        "vault_edit",
        "vault_delete",
        "mass_message_send",
        "price_change",
        "subscription_change",
        "tip_send",
        "fan_block",
        "fan_unblock",
        "follow",
        "unfollow",
        "account_settings_update",
        "payout_update",
        "login_change",
    }
    assert expected_writes <= WRITE_ACTIONS

    for action in expected_writes:
        assert classify_action(action) == "write"
        assert is_write_action(action)
        assert not is_read_action(action)
        verdict = evaluate_action(action)
        assert verdict.allowed is False
        assert verdict.classification == "write"
        with pytest.raises(BlockedActionError):
            require_read_action(action)


def test_unknown_action_fails_closed() -> None:
    """Anything not in either list must fail closed."""
    for unknown in (
        "",
        "totally_made_up_action",
        "READ_ACTIONS",
        "../../../etc/passwd",
        "account_profile_read ",  # trailing whitespace differs
    ):
        verdict = evaluate_action(unknown)
        assert verdict.allowed is False
        assert verdict.classification == "unknown"
        with pytest.raises(BlockedActionError):
            require_read_action(unknown)


# ── disabled connector shell ───────────────────────────────────────────────


def test_connector_status_reports_disabled_and_no_real_client() -> None:
    snapshot = OnlyFansDirectConnector().status()
    assert snapshot.connector_type == CONNECTOR_TYPE
    assert snapshot.mode == "disabled"
    assert snapshot.enabled is False
    assert snapshot.real_client_wired is False
    assert snapshot.session_health == "disabled"
    assert snapshot.rate_max_per_minute == DEFAULT_MAX_REQUESTS_PER_MINUTE
    assert snapshot.rate_max_per_hour == DEFAULT_MAX_REQUESTS_PER_HOUR


def test_connector_refuses_cookie_or_session_kwargs() -> None:
    """Constructing the shell with any forbidden credential key must
    raise immediately. The check covers the full contract list.
    """
    for forbidden_key in FORBIDDEN_CREDENTIAL_KEYS:
        with pytest.raises(CookieRefusedError):
            OnlyFansDirectConnector(**{forbidden_key: "anything-not-real"})


def test_connector_exposes_no_write_method() -> None:
    """The shell must not expose any callable named after a write
    action. If a future contributor adds one, this test fails.
    """
    shell = OnlyFansDirectConnector()
    public_attrs = {a for a in dir(shell) if not a.startswith("_")}
    # Specific foot-guns the brief named.
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
    intersection = public_attrs & forbidden_method_names
    assert intersection == set(), (
        f"OnlyFansDirectConnector exposes write-shaped public methods: " f"{sorted(intersection)}"
    )


@pytest.mark.asyncio
async def test_connector_fetch_refuses_loudly() -> None:
    """The disabled shell's ``fetch`` must always raise. Any future
    sprint that wants to enable real reads must do so explicitly via a
    dry-run-then-graduated path — never by silently flipping fetch.
    """
    shell = OnlyFansDirectConnector()
    with pytest.raises(ConnectorNotEnabledError):
        await shell.fetch()


# ── dry-run + fixture mode ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dry_run_refuses_write_action_with_blocked_action_error() -> None:
    """A dry-run for a write action must raise — the only safe answer.

    Also verifies an audit row was written before the raise so a
    forensic reviewer can see the attempt.
    """
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            shell = OnlyFansDirectConnector()
            with pytest.raises(BlockedActionError):
                await shell.dry_run(session, action="message_send")

            audits = (await session.exec(select(AuditEvent))).all()
            blocked = [a for a in audits if a.event_type == "connector.run.blocked"]
            assert len(blocked) == 1
            meta = blocked[0].metadata_json
            assert meta["connector_type"] == CONNECTOR_TYPE
            assert meta["requested_action"] == "message_send"
            assert meta["policy_classification"] == "write"
            assert meta["mode"] == "dry_run"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dry_run_refuses_unknown_action_without_raise_returns_blocked() -> None:
    """Unknown actions return a blocked verdict without raising. The
    raise-on-write rule is specifically for write actions; unknown
    actions are policy-blocked but recoverable for the caller.
    """
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            shell = OnlyFansDirectConnector()
            result = await shell.dry_run(session, action="nope_not_a_real_action")
            assert result.allowed is False
            assert result.classification == "unknown"
            assert result.policy_reason == "unknown_action_fail_closed"
            assert result.gate_reason is None
            assert result.used_fixture is False
            assert result.notes == "policy_refused"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dry_run_read_action_blocks_without_approval_and_consent() -> None:
    """For a legitimate read action, the policy passes but the
    connector gate must block because no approval / consent / vault
    exists. The audit row records the gate reason.
    """
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            shell = OnlyFansDirectConnector()
            result = await shell.dry_run(
                session,
                action="account_profile_read",
                creator_id="creator-A",
            )
            assert result.allowed is False
            assert result.classification == "read"
            assert result.policy_reason == "read_allowed_by_policy"
            assert result.gate_reason is not None  # gate was consulted
            assert result.notes == "gate_blocked"
            assert result.used_fixture is False
            assert result.audit_event_id is not None

            audits = (await session.exec(select(AuditEvent))).all()
            blocked = [a for a in audits if a.event_type == "connector.run.blocked"]
            assert len(blocked) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dry_run_passes_with_approval_consent_and_vault_uses_fixture_only() -> None:
    """Full pass-through: approval + consent live, vault available
    (encryption key set). The dry-run must produce a fixture-only
    result with no payload field, and audit ``connector.dry_run.pass``.
    """
    import os

    from app.services import connector_approvals as approvals_svc
    from app.services import consent as consent_svc

    # Set a dedicated encryption key so the gate's vault check passes.
    os.environ["SETTINGS_ENCRYPTION_KEY"] = "0" * 64
    from app.core import secrets_store as _ss

    _ss._fernet = None  # type: ignore[attr-defined]

    engine = await _engine()
    try:
        async with await _session(engine) as session:
            row = await approvals_svc.request_approval(
                session,
                connector_type="onlyfans_direct",
                requested_action="read",
                creator_id="creator-A",
            )
            await approvals_svc.approve(session, row.id)
            await consent_svc.grant(
                session,
                consent_type="onlyfans_direct_read",
                creator_id="creator-A",
            )
            await session.commit()

            shell = OnlyFansDirectConnector()
            result = await shell.dry_run(
                session,
                action="account_profile_read",
                creator_id="creator-A",
            )
            assert result.allowed is True
            assert result.classification == "read"
            assert result.used_fixture is True
            assert result.notes.startswith("dry_run_pass_fixture_only")
            assert result.audit_event_id is not None

            # No payload field exists on the result type — verify by
            # checking the dataclass fields list explicitly.
            from dataclasses import fields

            field_names = {f.name for f in fields(result)}
            for forbidden_field in ("payload", "data", "body", "raw"):
                assert forbidden_field not in field_names

            audits = (await session.exec(select(AuditEvent))).all()
            passed = [a for a in audits if a.event_type == "connector.dry_run.pass"]
            assert len(passed) == 1
            meta = passed[0].metadata_json
            assert meta["fixture_only"] is True
            assert meta["mode"] == "dry_run"
    finally:
        await engine.dispose()
        os.environ.pop("SETTINGS_ENCRYPTION_KEY", None)
        _ss._fernet = None  # type: ignore[attr-defined]


def test_fixtures_carry_synthetic_marker_and_no_real_handles() -> None:
    """Every fixture must carry ``synthetic: True`` and use the
    ``test-creator-`` / ``test-fan-`` placeholder prefixes only.
    """
    for action in READ_ACTIONS:
        payload = fixture_payload_for(action)
        assert payload.get("synthetic") is True, f"missing synthetic marker for {action}"
        # No real-looking handles. We accept the placeholder prefixes
        # only, and forbid anything that looks like an OnlyFans domain
        # or real-handle pattern.
        text = repr(payload).lower()
        assert "onlyfans.com" not in text
        assert "@" not in text  # no email addresses
        # If a creator_handle is set, it must use the test-creator- prefix.
        if "creator_handle" in payload:
            assert payload["creator_handle"].startswith(
                "test-creator-"
            ), f"non-placeholder creator_handle in fixture for {action}: {payload['creator_handle']!r}"


def test_fixture_for_unknown_action_returns_default_synthetic_payload() -> None:
    payload = fixture_payload_for("not_a_real_action")
    assert payload["synthetic"] is True
    assert "default_fixture" in payload.get("note", "")


# ── rate-limit + session-health scaffolding ─────────────────────────────────


def test_rate_limit_defaults_are_conservative() -> None:
    """The point of these constants is to be conservative; this
    test catches silent inflation.
    """
    assert DEFAULT_MAX_REQUESTS_PER_MINUTE <= 30
    assert DEFAULT_MAX_REQUESTS_PER_HOUR <= 600
    assert DEFAULT_BACKOFF.initial_seconds >= 1.0
    assert DEFAULT_BACKOFF.max_seconds >= DEFAULT_BACKOFF.initial_seconds
    assert 0.0 < DEFAULT_BACKOFF.jitter_fraction <= 0.5
    assert DEFAULT_BACKOFF.max_retries >= 1


def test_challenge_reaction_does_not_silently_retry() -> None:
    """A challenge response must stop, audit, notify, and require
    manual review — never silently retry.
    """
    assert CHALLENGE_REACTION.stop is True
    assert CHALLENGE_REACTION.audit is True
    assert CHALLENGE_REACTION.notify is True
    assert CHALLENGE_REACTION.require_manual_review is True


def test_session_health_unhealthy_classification() -> None:
    # "healthy", "disabled", "not_configured" do not block a new run start.
    for ok in ("healthy", "disabled", "not_configured"):
        assert is_unhealthy(ok) is False  # type: ignore[arg-type]
    # Everything else must be classified as unhealthy.
    for bad in ("challenged", "expired", "revoked", "blocked", "error"):
        assert is_unhealthy(bad) is True  # type: ignore[arg-type]


def test_session_health_descriptions_are_audit_safe() -> None:
    """Descriptions must be short strings with no platform response
    bodies or user-supplied content baked in.
    """
    for status in (
        "disabled",
        "not_configured",
        "healthy",
        "challenged",
        "expired",
        "revoked",
        "blocked",
        "error",
    ):
        text = describe_session_health(status)  # type: ignore[arg-type]
        assert isinstance(text, str)
        assert 0 < len(text) < 200


# ── credential safety contract ──────────────────────────────────────────────


def test_assert_no_forbidden_credential_keys_refuses_each_key() -> None:
    """Every key in :data:`FORBIDDEN_CREDENTIAL_KEYS` must trigger a
    contract-violation error.
    """
    for key in FORBIDDEN_CREDENTIAL_KEYS:
        with pytest.raises(CredentialContractViolation):
            assert_no_forbidden_credential_keys({key: "anything-not-real"})


def test_assert_no_forbidden_credential_keys_is_case_insensitive() -> None:
    """Operators sometimes capitalise. The check must catch
    ``Cookie`` and ``COOKIE`` as well as ``cookie``.
    """
    with pytest.raises(CredentialContractViolation):
        assert_no_forbidden_credential_keys({"Cookie": "x"})
    with pytest.raises(CredentialContractViolation):
        assert_no_forbidden_credential_keys({"COOKIE": "x"})
    with pytest.raises(CredentialContractViolation):
        assert_no_forbidden_credential_keys({"X-Bc": "x"})


def test_assert_no_forbidden_credential_keys_passes_clean_payload() -> None:
    """A clean payload (vault id, expiry, comment) must not be
    refused. The contract is targeted at credential-shaped inputs,
    not arbitrary metadata.
    """
    assert_no_forbidden_credential_keys(
        {
            "credential_id": "vault-uuid-here",
            "expires_at": "2027-01-01T00:00:00Z",
            "note": "rotated by drill",
        }
    )


def test_runbook_strings_mention_audit_and_kill_switch() -> None:
    rev = revocation_runbook()
    rot = rotation_runbook()
    assert "kill" in rev.lower() or "kill_switch" in rev.lower()
    assert "audit" in rev.lower()
    assert "rotate" in rot.lower()
    assert "audit" in rot.lower() or "credential.rotate" in rot


def test_frontend_has_no_of_credential_storage() -> None:
    """Scan the frontend source tree for the forbidden patterns in
    :data:`FRONTEND_FORBIDDEN_PATTERNS`. If any pattern is found,
    the credential safety contract has been violated.

    Skipped if the frontend tree is not present (CI runners without
    the frontend checkout).
    """
    repo_root = Path(__file__).resolve().parents[2]
    frontend_src = repo_root / "frontend" / "src"
    if not frontend_src.exists():
        pytest.skip("frontend/src not available in this environment")

    hits: list[str] = []
    for path in frontend_src.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in (".ts", ".tsx", ".js", ".jsx"):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in FRONTEND_FORBIDDEN_PATTERNS:
            if pattern in content:
                hits.append(f"{path.relative_to(repo_root)}: {pattern!r}")
    assert hits == [], (
        "OnlyFans direct credential safety contract violated — frontend "
        "contains forbidden storage patterns:\n  " + "\n  ".join(hits)
    )
