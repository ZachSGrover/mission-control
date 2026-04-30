"""Sprint 8A — OnlyMonster gated production-proof tests.

Proves the connector gate, approval, consent, and kill-switch chain
all hold on the OnlyMonster path with a fake client wired into the
seam. There are NO live integration calls; every test sets up its
own in-memory SQLite database and a deterministic
:class:`FakeOnlyMonsterClient`.

What this suite proves end-to-end:

- The seam refuses to run when the env flag is off.
- The gate refuses to run when approval is missing.
- The gate refuses to run when consent is missing.
- The gate refuses to run when the global kill switch is on.
- The gate refuses to run when the connector kill switch is on.
- A fully approved + consented run audits both
  ``connector.run.finish`` (from the seam) and
  ``connector.gated_proof.success`` (from the wrapper).
- Production refuses the fake client unless
  ``MC_ONLYMONSTER_ALLOW_FAKE_CLIENT=1``.
- The Sprint 7 direct-OnlyFans policy module is untouched.
- The OnlyMonster path exposes no write methods.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

import app.models  # noqa: F401  — registers tables
from app.models.audit_events import AuditEvent
from app.services.onlymonster_fake_client import (
    FakeClientRefusedInProductionError,
    FakeOnlyMonsterClient,
    resolve_onlymonster_client,
)
from app.services.onlymonster_gate_proof import (
    CONNECTOR_TYPE,
    REQUESTED_ACTION,
    GatedProofResult,
    run_onlymonster_gated_proof,
)

# ── shared fixtures ─────────────────────────────────────────────────────────


async def _engine() -> AsyncEngine:
    e = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with e.connect() as conn, conn.begin():
        await conn.run_sync(SQLModel.metadata.create_all)
    return e


async def _session(engine: AsyncEngine) -> AsyncSession:
    return AsyncSession(engine, expire_on_commit=False)


def _enable_env_flag() -> None:
    os.environ["MC_ONLYMONSTER_GATED_SYNC_ENABLED"] = "1"


def _clear_env_flag() -> None:
    os.environ.pop("MC_ONLYMONSTER_GATED_SYNC_ENABLED", None)


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
        connector_type="onlymonster",
        requested_action="creator_sync",
        creator_id=creator_id,
    )
    await _approvals_svc.approve(session, row.id)
    await _consent_svc.grant(
        session,
        consent_type="onlymonster_sync",
        creator_id=creator_id,
    )
    await session.commit()


# ── env-flag refusal (gated wrapper layer) ──────────────────────────────────


@pytest.mark.asyncio
async def test_blocked_when_env_flag_off_audits_blocked() -> None:
    """With the gated wrapper's env flag off, the seam returns None
    and the proof wrapper records ``connector.gated_proof.blocked``
    in addition to the seam's ``connector.run.blocked``.
    """
    _clear_env_flag()
    engine = await _engine()
    try:
        async with await _session(engine) as session:
            result = await run_onlymonster_gated_proof(
                session,
                creator_id="creator-A",
                fake_client=FakeOnlyMonsterClient(),
            )
            assert isinstance(result, GatedProofResult)
            assert result.allowed is False
            assert result.error_category == "gate_blocked_or_disabled"
            assert result.rows_read == 0
            assert result.rows_written == 0
            assert result.used_fake_client is True

            audits = (await session.exec(select(AuditEvent))).all()
            event_types = {a.event_type for a in audits}
            assert "connector.run.blocked" in event_types
            assert "connector.gated_proof.blocked" in event_types
            assert "connector.run.finish" not in event_types
            assert "connector.gated_proof.success" not in event_types
    finally:
        await engine.dispose()


# ── missing approval ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blocked_when_no_approval_audits_blocked() -> None:
    """Env flag on, no approval row. The seam routes through the
    real gate and the gate refuses with ``no_approval``.
    """
    _enable_env_flag()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                result = await run_onlymonster_gated_proof(
                    session,
                    creator_id="creator-A",
                    fake_client=FakeOnlyMonsterClient(),
                )
                assert result.allowed is False
                assert result.error_category == "gate_blocked_or_disabled"

                audits = (await session.exec(select(AuditEvent))).all()
                event_types = {a.event_type for a in audits}
                assert "connector.run.blocked" in event_types
                assert "connector.gated_proof.blocked" in event_types
                assert "connector.gated_proof.success" not in event_types
        finally:
            await engine.dispose()
    finally:
        _clear_env_flag()


# ── missing consent ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blocked_when_no_consent_audits_blocked() -> None:
    """Env flag on, approval present, no consent. The gate must
    refuse — consent is required for the (onlymonster, creator_sync)
    pair.
    """
    _enable_env_flag()
    try:
        from app.services import connector_approvals as _approvals_svc

        engine = await _engine()
        try:
            async with await _session(engine) as session:
                row = await _approvals_svc.request_approval(
                    session,
                    connector_type="onlymonster",
                    requested_action="creator_sync",
                    creator_id="creator-A",
                )
                await _approvals_svc.approve(session, row.id)
                await session.commit()

                result = await run_onlymonster_gated_proof(
                    session,
                    creator_id="creator-A",
                    fake_client=FakeOnlyMonsterClient(),
                )
                assert result.allowed is False
                assert result.error_category == "gate_blocked_or_disabled"
                assert result.audit_event_id is not None

                audits = (await session.exec(select(AuditEvent))).all()
                blocked_seam = [a for a in audits if a.event_type == "connector.run.blocked"]
                blocked_proof = [
                    a for a in audits if a.event_type == "connector.gated_proof.blocked"
                ]
                assert len(blocked_seam) >= 1
                assert len(blocked_proof) == 1
        finally:
            await engine.dispose()
    finally:
        _clear_env_flag()


# ── global kill switch ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blocked_when_global_kill_switch_on() -> None:
    _enable_env_flag()
    try:
        from app.services import kill_switch as _kill_switch_svc

        engine = await _engine()
        try:
            async with await _session(engine) as session:
                await _grant_approval_and_consent(session, creator_id="creator-A")
                await _kill_switch_svc.enable(session, scope="global", reason="sprint-8a test")
                await session.commit()

                result = await run_onlymonster_gated_proof(
                    session,
                    creator_id="creator-A",
                    fake_client=FakeOnlyMonsterClient(),
                )
                assert result.allowed is False
                assert result.error_category == "gate_blocked_or_disabled"

                audits = (await session.exec(select(AuditEvent))).all()
                event_types = {a.event_type for a in audits}
                assert "connector.run.blocked" in event_types
                assert "connector.gated_proof.blocked" in event_types
                assert "connector.gated_proof.success" not in event_types
        finally:
            await engine.dispose()
    finally:
        _clear_env_flag()


# ── connector kill switch ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blocked_when_connector_kill_switch_on() -> None:
    _enable_env_flag()
    try:
        from app.services import kill_switch as _kill_switch_svc

        engine = await _engine()
        try:
            async with await _session(engine) as session:
                await _grant_approval_and_consent(session, creator_id="creator-A")
                await _kill_switch_svc.enable(
                    session,
                    scope="connector",
                    scope_id="onlymonster",
                    reason="sprint-8a test",
                )
                await session.commit()

                result = await run_onlymonster_gated_proof(
                    session,
                    creator_id="creator-A",
                    fake_client=FakeOnlyMonsterClient(),
                )
                assert result.allowed is False
                assert result.error_category == "gate_blocked_or_disabled"

                audits = (await session.exec(select(AuditEvent))).all()
                event_types = {a.event_type for a in audits}
                assert "connector.gated_proof.blocked" in event_types
                assert "connector.gated_proof.success" not in event_types
        finally:
            await engine.dispose()
    finally:
        _clear_env_flag()


# ── allowed dry-run passes and audits ───────────────────────────────────────


@pytest.mark.asyncio
async def test_allowed_dry_run_passes_and_audits_finish_and_proof_success() -> None:
    """Full pass-through: env flag, approval, consent, vault. The
    seam writes ``connector.run.finish``; the proof wrapper writes
    ``connector.gated_proof.success``. Both rows reference the same
    creator for forensic joining.
    """
    _enable_env_flag()
    _set_dedicated_key()
    try:
        engine = await _engine()
        try:
            async with await _session(engine) as session:
                await _grant_approval_and_consent(session, creator_id="creator-A")

                result = await run_onlymonster_gated_proof(
                    session,
                    creator_id="creator-A",
                    fake_client=FakeOnlyMonsterClient(rows_read=11),
                )
                assert result.allowed is True
                assert result.connector_type == CONNECTOR_TYPE
                assert result.requested_action == REQUESTED_ACTION
                assert result.rows_read == 11
                assert result.rows_written == 0  # invariant
                assert result.error_category is None
                assert result.audit_event_id is not None
                assert result.used_fake_client is True

                audits = (await session.exec(select(AuditEvent))).all()
                seam_finish = [a for a in audits if a.event_type == "connector.run.finish"]
                proof_success = [
                    a for a in audits if a.event_type == "connector.gated_proof.success"
                ]
                assert len(seam_finish) == 1
                assert len(proof_success) == 1
                # Both reference the same creator
                assert seam_finish[0].creator_id == "creator-A"
                assert proof_success[0].creator_id == "creator-A"

                proof_meta = proof_success[0].metadata_json
                assert proof_meta["rows_read"] == 11
                assert proof_meta["rows_written"] == 0
                assert proof_meta["used_fake_client"] is True

                # No fan PII / message body in any audit row.
                forbidden = {
                    "fan_id",
                    "fan_username",
                    "fan_handle",
                    "message_body",
                    "messages",
                    "subscribers",
                    "tips",
                }
                for row in audits:
                    assert forbidden.isdisjoint(set(row.metadata_json.keys()))
        finally:
            await engine.dispose()
    finally:
        _clear_env_flag()
        _clear_dedicated_key()


# ── fake client refused in production ───────────────────────────────────────


def test_fake_client_resolves_in_non_production() -> None:
    """Outside production, the fake client is selected without
    needing the allow flag.
    """
    fake = FakeOnlyMonsterClient()
    resolved = resolve_onlymonster_client(fake_client=fake)
    assert resolved is fake


def test_fake_client_refused_in_production_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """In production, the fake is refused unless
    ``MC_ONLYMONSTER_ALLOW_FAKE_CLIENT=1``.
    """
    from app.core import startup_guard

    monkeypatch.setattr(startup_guard, "is_production", lambda: True)
    monkeypatch.delenv("MC_ONLYMONSTER_ALLOW_FAKE_CLIENT", raising=False)

    fake = FakeOnlyMonsterClient()
    with pytest.raises(FakeClientRefusedInProductionError):
        resolve_onlymonster_client(fake_client=fake)


def test_fake_client_allowed_in_production_with_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """The flag is the explicit drill-mode opt-in."""
    from app.core import startup_guard

    monkeypatch.setattr(startup_guard, "is_production", lambda: True)
    monkeypatch.setenv("MC_ONLYMONSTER_ALLOW_FAKE_CLIENT", "1")

    fake = FakeOnlyMonsterClient()
    resolved = resolve_onlymonster_client(fake_client=fake)
    assert resolved is fake


@pytest.mark.asyncio
async def test_proof_run_in_production_without_flag_audits_refusal_and_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the proof wrapper is invoked in production with only a
    fake client and no allow flag, it audits a
    ``connector.gated_proof.blocked`` row with
    ``error_category=fake_refused_in_production`` and re-raises.
    """
    from app.core import startup_guard

    monkeypatch.setattr(startup_guard, "is_production", lambda: True)
    monkeypatch.delenv("MC_ONLYMONSTER_ALLOW_FAKE_CLIENT", raising=False)

    engine = await _engine()
    try:
        async with await _session(engine) as session:
            with pytest.raises(FakeClientRefusedInProductionError):
                await run_onlymonster_gated_proof(
                    session,
                    creator_id="creator-A",
                    fake_client=FakeOnlyMonsterClient(),
                )

            audits = (await session.exec(select(AuditEvent))).all()
            blocked = [a for a in audits if a.event_type == "connector.gated_proof.blocked"]
            assert len(blocked) == 1
            assert blocked[0].metadata_json["error_category"] == "fake_refused_in_production"
            assert blocked[0].metadata_json["used_fake_client"] is True
    finally:
        await engine.dispose()


# ── Sprint 7 direct-OnlyFans policy is untouched ────────────────────────────


def test_sprint_7_direct_onlyfans_policy_remains_intact() -> None:
    """Sprint 8A must not relax any Sprint 7 invariant.

    Re-imports the policy module and asserts the read/write sets
    are unchanged in shape.
    """
    from app.core.onlyfans_direct_policy import (
        READ_ACTIONS,
        WRITE_ACTIONS,
        classify_action,
    )

    # Disjointness invariant.
    assert READ_ACTIONS & WRITE_ACTIONS == frozenset()
    # Counts (Sprint 7 brief).
    assert len(READ_ACTIONS) == 10
    assert len(WRITE_ACTIONS) == 20
    # Sample assertions across the boundary.
    assert classify_action("message_send") == "write"
    assert classify_action("account_profile_read") == "read"


def test_disabled_of_direct_shell_still_refuses_writes() -> None:
    """The Sprint 7 disabled shell must still refuse writes; Sprint
    8A must not have introduced a write surface anywhere on the OF
    direct path.
    """
    from app.core.onlyfans_direct_policy import BlockedActionError, require_read_action

    for action in (
        "message_send",
        "post_create",
        "tip_send",
        "mass_message_send",
    ):
        with pytest.raises(BlockedActionError):
            require_read_action(action)


# ── OnlyMonster path exposes no write surface ───────────────────────────────


def test_onlymonster_modules_expose_no_write_callables() -> None:
    """Walk the OnlyMonster modules' public callables. None may be
    named after a write action.
    """
    from app.services import (
        gated_onlymonster_sync,
        onlymonster_fake_client,
        onlymonster_gate_proof,
        onlymonster_integration,
    )

    forbidden = {
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
    }
    for mod in (
        onlymonster_fake_client,
        onlymonster_gate_proof,
        onlymonster_integration,
        gated_onlymonster_sync,
    ):
        public = {name for name in dir(mod) if not name.startswith("_")}
        intersection = public & forbidden
        assert (
            intersection == set()
        ), f"{mod.__name__} exposes write-shaped callables: {sorted(intersection)}"


# ── result type carries no payload field ────────────────────────────────────


def test_gated_proof_result_has_no_payload_field() -> None:
    """The result type must never carry a ``payload`` / ``data`` /
    ``raw`` / ``body`` field. The seam already discards row content;
    this layer mirrors that invariant.
    """
    from dataclasses import fields

    field_names = {f.name for f in fields(GatedProofResult)}
    for forbidden in ("payload", "data", "raw", "body", "messages", "fans"):
        assert forbidden not in field_names


# ── fake client doesn't open a network connection ───────────────────────────


@pytest.mark.asyncio
async def test_fake_client_returns_synthetic_payload_only() -> None:
    """The fake's payload must carry ``synthetic: True`` and echo
    the creator id without any other realistic-looking data.
    """
    fake = FakeOnlyMonsterClient(rows_read=3)
    payload = await fake.read_only_pull(creator_id="creator-X")
    assert payload["synthetic"] is True
    assert payload["rows_read"] == 3
    assert payload["creator_id_echo"] == "creator-X"
    text = repr(payload).lower()
    assert "onlyfans.com" not in text
    assert "@" not in text  # no email addresses
