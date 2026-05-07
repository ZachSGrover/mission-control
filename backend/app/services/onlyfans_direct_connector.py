"""Direct OnlyFans connector — disabled shell.

Sprint 7: a **disabled** shell for a future direct OnlyFans
read-only connector. The shell exists to:

- Pin the public surface a future implementation must conform to.
- Make every safety check (policy, gate, kill switch, vault) the
  default code path — so a future contributor cannot land a working
  connector that skips any of them.
- Provide a tested ``dry_run`` that proves the gating chain end-to-end
  using fixture data only.
- Refuse, loudly, every disallowed input shape (raw cookies,
  session blobs, plaintext credentials in constructor args).

What the shell does NOT do, and MUST NOT do:

- It does not perform network calls. Ever. There is no HTTP client
  attached.
- It does not accept a real cookie, session token, or password.
- It does not expose methods for any of the actions in
  :data:`app.core.onlyfans_direct_policy.WRITE_ACTIONS`.
- It does not have a "production mode" toggle. The only mode it
  exposes is dry-run with fixtures.

When a future Sprint 8+ wires the real client, the wiring point is
documented at :data:`_REAL_CLIENT_TODO`. Replacing that string and
implementing the real fetch must keep every safety check in place —
the dry-run path is the contract.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.connector_gate import GateVerdict, is_connector_action_allowed
from app.core.logging import get_logger
from app.core.onlyfans_direct_client import (
    READ_ACTION_TO_METHOD,
    OnlyFansReadOnlyClient,
)
from app.core.onlyfans_direct_credential_ref import (
    CredentialReference,
    check_credential_status,
)
from app.core.onlyfans_direct_policy import (
    BlockedActionError,
    PolicyVerdict,
    evaluate_action,
)
from app.core.onlyfans_direct_rate_policy import (
    DEFAULT_BACKOFF,
    DEFAULT_MAX_REQUESTS_PER_HOUR,
    DEFAULT_MAX_REQUESTS_PER_MINUTE,
    SessionHealth,
)
from app.services.audit_log import record_audit
from app.services.onlyfans_direct_fixtures import fixture_payload_for

logger = get_logger(__name__)


CONNECTOR_TYPE: Final[str] = "onlyfans_direct"

# When a future sprint wires the real OnlyFans client, replace this
# string with the import path of the read-only client class. The class
# must implement only the read actions in
# ``app.core.onlyfans_direct_policy.READ_ACTIONS`` and must not have any
# method that performs a write of any kind.
_REAL_CLIENT_TODO: Final[str] = (
    "app.integrations.onlyfans.client.OnlyFansReadOnlyClient (not yet present)"
)

ConnectorMode = Literal["disabled", "dry_run", "sandbox"]


# Forbidden input keys. If a caller hands the constructor a credentials
# dict that contains any of these keys, we refuse before any code that
# could touch them runs. The check is conservative — it errs on the
# side of refusing legitimate-looking dicts, because that surface is
# never the right shape for this connector anyway.
_FORBIDDEN_CREDENTIAL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "cookie",
        "cookies",
        "set_cookie",
        "session",
        "session_id",
        "session_token",
        "auth_token",
        "csrf",
        "csrf_token",
        "password",
        "x-bc",  # OnlyFans browser cookie
        "x_bc",
        "user_id",  # OF user id without vault wrapper is also a leak
    }
)


class CookieRefusedError(RuntimeError):
    """Raised when a caller hands the connector raw-cookie / session
    style data. The direct OnlyFans connector will only ever accept
    credentials through the creator credential vault.
    """


class ConnectorNotEnabledError(RuntimeError):
    """Raised when a caller asks the disabled shell to perform a
    real-mode action. This is a hard refusal — the disabled shell has
    no real mode.
    """


@dataclass(frozen=True)
class ConnectorStatus:
    """Read-only status snapshot for the security admin / OF intelligence UI.

    Sprint 7 always reports ``mode="disabled"``. Sprint 8+ may flip
    ``mode`` to ``"dry_run"`` for a sandbox creator behind explicit
    approvals; production mode is post-MVP and gated by the readiness
    checklist.
    """

    connector_type: str
    mode: ConnectorMode
    enabled: bool
    real_client_wired: bool
    rate_max_per_minute: int
    rate_max_per_hour: int
    backoff_initial_seconds: float
    backoff_max_seconds: float
    session_health: SessionHealth
    notes: str


@dataclass(frozen=True)
class DryRunResult:
    """Outcome of :meth:`OnlyFansDirectConnector.dry_run`.

    All fields are safe to surface in audit rows and admin UI.
    There is **no** ``payload`` or ``data`` field — the fixture
    payload is computed and discarded; only the metadata that proves
    the gating chain was exercised is preserved.
    """

    allowed: bool
    classification: str  # "read" | "write" | "unknown"
    policy_reason: str
    gate_reason: str | None
    gate_detail: str | None
    connector_type: str
    requested_action: str
    creator_id: str | None
    organization_id: str | None
    audit_event_id: str | None
    used_fixture: bool
    notes: str
    # Sprint 8B additions. Safe scalars only.
    mode: ConnectorMode = "disabled"
    used_fake_client: bool = False
    rows_read: int = 0  # number of records the fake returned (0 in disabled mode)


# Sprint 8C: env flag that gates the sandbox attempt path.
ENV_SANDBOX_ALLOWED: Final[str] = "MC_OF_DIRECT_SANDBOX_ALLOWED"


# Sprint 8E: only these three actions can be selected via the
# sandbox path. Sprint 8D made the other 7 raise via the real
# client skeleton; Sprint 8E makes the refusal explicit at the
# selector layer too, so a future caller cannot accidentally
# route an unimplemented action through the sandbox gate and
# trigger an audit-noisy ``real_client_not_enabled`` block.
ALLOWED_SANDBOX_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "account_profile_read",
        "account_stats_read",
        "revenue_summary_read",
    }
)


# Sprint 8C: SandboxBlockedReason vocabulary. Anything not in this set
# means the gate has a new failure mode that hasn't been added — fail
# closed by classifying as "unknown_error".
SandboxBlockedReason = Literal[
    "env_flag_disabled",
    "production_environment",
    "policy_refused",
    "credential_missing",
    "credential_revoked",
    "credential_rotated",
    "credential_stale",
    "credential_wrong_provider",
    "no_approval",
    "no_consent",
    "kill_switch",
    "vault_unavailable",
    "no_owner_signoff",
    "real_client_not_enabled",  # all checks pass but the skeleton refuses
    "challenge_detected",  # Sprint 8D: platform served challenge / login redirect
    "unexpected_status",  # Sprint 8D: non-200, non-challenge response
    "unknown_error",
]


# Sprint 8D: bridge ChallengeDetectedError.reason_category strings to
# the Sprint 8B ChallengeReason vocabulary on session_health. The
# transport may use slightly different names; normalize to the fixed
# Sprint 8B set so the audit row's reason_category is meaningful.
_VALID_CHALLENGE_REASONS = frozenset(
    {
        "captcha",
        "login_required",
        "rate_limit_response",
        "unexpected_status",
        "unexpected_html",
        "session_expired",
        "session_revoked",
        "platform_block",
        "other",
    }
)


def _normalize_challenge_reason(raw: str) -> str:
    """Return ``raw`` if it's in the fixed vocabulary, else ``"other"``."""
    return raw if raw in _VALID_CHALLENGE_REASONS else "other"


@dataclass(frozen=True)
class SandboxResult:
    """Outcome of :meth:`OnlyFansDirectConnector.dry_run_sandbox`.

    All fields are safe scalars / enums. There is **no** ``payload``,
    ``data``, ``raw``, ``messages``, or ``fans`` field. The Sprint 8C
    skeleton's read methods all raise; even when all prerequisites
    pass, the result records the *attempt*, not any retrieved data.
    """

    allowed: bool
    blocked_reason: SandboxBlockedReason | None
    connector_type: str
    requested_action: str
    creator_id: str | None
    organization_id: str | None
    audit_event_id: str | None
    notes: str
    # Sandbox prereq breakdown — useful for the admin UI / runbooks.
    env_flag_set: bool
    is_production: bool
    credential_status: str  # CredentialStatusKind enum value
    approval_present: bool
    consent_present: bool
    kill_switch_blocking: str | None
    vault_available: bool
    owner_signoff_present: bool
    notify_channel_status: str  # ChallengeNotifyStatus enum value


def _safe_rows_read(payload: object) -> int:
    """Compute a safe scalar count of records in a fake-client payload.

    Inspects only the dict shape — never persists or returns the
    payload itself. Looks for common list-shaped fields (``messages``,
    ``threads``, ``items``, ``posts``, ``stories``, ``campaigns``,
    ``fans_sample_metadata``) and returns the largest length found.
    Falls back to 0 if the payload is not a dict or has no list field.
    Worst-case behaviour is to under-report — never to leak content.
    """
    if not isinstance(payload, dict):
        return 0
    candidates = (
        "messages",
        "threads",
        "items",
        "posts",
        "stories",
        "campaigns",
        "fans_sample_metadata",
    )
    best = 0
    for key in candidates:
        value = payload.get(key)
        if isinstance(value, list):
            best = max(best, len(value))
    return best


class OnlyFansDirectConnector:
    """Disabled shell for a future direct OnlyFans read-only connector.

    Construction is restricted: any kwargs containing forbidden
    credential keys (raw cookies, session blobs, passwords) raise
    :class:`CookieRefusedError`. The shell does not store credentials
    at all in this sprint; the future real client will resolve the
    credential at call time from
    :class:`app.models.creator_credentials.CreatorCredential`.

    The shell exposes:

    - :meth:`status` — ``ConnectorStatus`` for the UI.
    - :meth:`dry_run` — runs the policy + gate + audit chain against
      a fixture, never the network. Refuses write actions.

    There are NO methods named ``send_message``, ``post``, ``tip``,
    ``mass_message``, etc. The class definition is the contract: if
    you can't see a method here, the connector cannot perform that
    action. Adding one would require landing a write method, which
    would in turn fail the Sprint 7 tests.
    """

    def __init__(
        self,
        *,
        mode: ConnectorMode = "disabled",
        client: OnlyFansReadOnlyClient | None = None,
        credential_ref: CredentialReference | None = None,
        **kwargs: Any,
    ) -> None:
        forbidden = _FORBIDDEN_CREDENTIAL_KEYS & set(kwargs.keys())
        if forbidden:
            raise CookieRefusedError(
                "OnlyFansDirectConnector refuses to construct with credential-shaped "
                f"keyword arguments: {sorted(forbidden)}. Direct OnlyFans credentials "
                "must be resolved through the creator credential vault, never passed "
                "as cookies, session tokens, or plaintext."
            )
        if mode not in ("disabled", "dry_run", "sandbox"):
            raise ValueError(
                f"Invalid mode {mode!r}. Sprint 8C supports 'disabled' "
                "(default), 'dry_run', and 'sandbox'. There is no production mode."
            )
        if mode == "dry_run" and client is None:
            raise ValueError(
                "mode='dry_run' requires a client (OnlyFansReadOnlyClient). "
                "Sprint 8B accepts only the fake client; pass FakeOnlyFansReadOnlyClient()."
            )
        if mode == "sandbox":
            if client is None:
                raise ValueError(
                    "mode='sandbox' requires a client (OnlyFansReadOnlyClient). "
                    "Sprint 8C accepts only the RealOnlyFansReadOnlyClient skeleton; "
                    "every read method on the skeleton still raises until Sprint 8D."
                )
            if credential_ref is None:
                raise ValueError(
                    "mode='sandbox' requires a credential_ref (CredentialReference). "
                    "Raw cookie/session/password kwargs are forbidden."
                )
        # Intentionally drop other kwargs on the floor.
        self._mode: ConnectorMode = mode
        self._client: OnlyFansReadOnlyClient | None = client
        self._credential_ref: CredentialReference | None = credential_ref

    # ── status ──────────────────────────────────────────────────────────────

    def status(self) -> ConnectorStatus:
        """Return the current operational status snapshot.

        Always reports ``mode="disabled"`` and ``real_client_wired=False``
        in this sprint. The fields exist so the admin UI can render
        the same shape unchanged when Sprint 8+ flips them.
        """
        # Sprint 8B: mode reflects the constructor arg. ``enabled`` and
        # ``real_client_wired`` remain False — the disabled mode is the
        # default, and dry_run only ever uses the fake client.
        if self._mode == "disabled":
            notes = (
                "Direct OnlyFans connector is disabled. Read-only "
                "implementation has not been written. See "
                "docs/security/direct-onlyfans-readiness-checklist.md."
            )
        elif self._mode == "dry_run":
            notes = (
                "Direct OnlyFans connector is in dry_run mode. The "
                "configured client is a fake implementation backed by "
                "Sprint 7 fixtures; there is no real network call. "
                "Production mode does not exist."
            )
        else:
            # sandbox
            notes = (
                "Direct OnlyFans connector is in sandbox mode. The "
                "configured client is the Sprint 8C real-client "
                "skeleton; every read method still raises until "
                "Sprint 8D wires the real network call."
            )
        return ConnectorStatus(
            connector_type=CONNECTOR_TYPE,
            mode=self._mode,
            enabled=False,
            real_client_wired=False,
            rate_max_per_minute=DEFAULT_MAX_REQUESTS_PER_MINUTE,
            rate_max_per_hour=DEFAULT_MAX_REQUESTS_PER_HOUR,
            backoff_initial_seconds=DEFAULT_BACKOFF.initial_seconds,
            backoff_max_seconds=DEFAULT_BACKOFF.max_seconds,
            session_health="disabled" if self._mode == "disabled" else "healthy",
            notes=notes,
        )

    # ── dry-run ─────────────────────────────────────────────────────────────

    async def dry_run(
        self,
        session: AsyncSession,
        *,
        action: str,
        creator_id: str | None = None,
        organization_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        actor_email: str | None = None,
    ) -> DryRunResult:
        """Run the policy + gate + audit chain against a fixture payload.

        This is the only execution surface this sprint exposes. It
        proves the chain works end-to-end and produces an auditable
        record without touching the network or any real credentials.

        Refusal layers, in order:

        1. Policy: write or unknown actions raise
           :class:`BlockedActionError` *before* the gate is consulted,
           so a misclassified action never even gets to the gate.
        2. Gate: missing approval, missing consent, kill switch on,
           or vault unavailable yield a blocked verdict.
        3. Connector enabled: the shell is permanently
           ``mode="disabled"`` in this sprint, so the dry-run never
           returns a real-network result. Even on full pass-through,
           the dry run only computes a fixture payload and records
           the fact it would have attempted a fetch.
        """
        # 1. Policy check — pure-function refusal of writes/unknowns.
        verdict_policy: PolicyVerdict = evaluate_action(action)
        if not verdict_policy.allowed:
            audit_id = await self._audit_blocked(
                session,
                action=action,
                policy=verdict_policy,
                gate=None,
                organization_id=organization_id,
                creator_id=creator_id,
                actor_user_id=actor_user_id,
                actor_email=actor_email,
            )
            # Raise so test code that *should* never even ask for a
            # write fails loudly, while code paths that legitimately
            # call ``dry_run`` for read actions never see this branch.
            if verdict_policy.classification == "write":
                raise BlockedActionError(
                    f"dry_run refused: {action!r} is a write action; "
                    "the direct OnlyFans connector cannot implement writes."
                )
            return DryRunResult(
                allowed=False,
                classification=verdict_policy.classification,
                policy_reason=verdict_policy.reason,
                gate_reason=None,
                gate_detail=None,
                connector_type=CONNECTOR_TYPE,
                requested_action=action,
                creator_id=creator_id,
                organization_id=str(organization_id) if organization_id else None,
                audit_event_id=audit_id,
                used_fixture=False,
                notes="policy_refused",
            )

        # 2. Gate check — composes kill switch / approval / consent / vault.
        gate_verdict: GateVerdict = await is_connector_action_allowed(
            session,
            connector_type=CONNECTOR_TYPE,
            requested_action="read",
            organization_id=organization_id,
            creator_id=creator_id,
        )
        if not gate_verdict.allowed:
            audit_id = await self._audit_blocked(
                session,
                action=action,
                policy=verdict_policy,
                gate=gate_verdict,
                organization_id=organization_id,
                creator_id=creator_id,
                actor_user_id=actor_user_id,
                actor_email=actor_email,
            )
            return DryRunResult(
                allowed=False,
                classification="read",
                policy_reason=verdict_policy.reason,
                gate_reason=gate_verdict.reason,
                gate_detail=gate_verdict.detail,
                connector_type=CONNECTOR_TYPE,
                requested_action=action,
                creator_id=creator_id,
                organization_id=str(organization_id) if organization_id else None,
                audit_event_id=audit_id,
                used_fixture=False,
                notes="gate_blocked",
            )

        # 3a. mode="dry_run" — call the configured client. Sprint 8B
        # accepts only the fake; the fake's constructor enforces
        # production refusal via MC_OF_DIRECT_ALLOW_FAKE_CLIENT.
        if self._mode == "dry_run" and self._client is not None:
            method_name = READ_ACTION_TO_METHOD.get(action)
            if method_name is None:
                # Should never happen — policy already classified as
                # read, which means action is in READ_ACTIONS, which
                # means it must be in READ_ACTION_TO_METHOD. Defensive.
                raise RuntimeError(
                    f"No client method mapped for read action {action!r}; "
                    "READ_ACTION_TO_METHOD is out of sync with READ_ACTIONS."
                )
            method = getattr(self._client, method_name)
            payload = await method(creator_id=creator_id or "")
            # Compute a safe scalar summary and DROP the payload before
            # any further code can see it. We never persist, audit, or
            # return the payload itself.
            rows_read = _safe_rows_read(payload)
            del payload

            audit_id = await self._audit_dry_run_pass(
                session,
                action=action,
                organization_id=organization_id,
                creator_id=creator_id,
                actor_user_id=actor_user_id,
                actor_email=actor_email,
                used_fake_client=True,
                rows_read=rows_read,
            )
            return DryRunResult(
                allowed=True,
                classification="read",
                policy_reason=verdict_policy.reason,
                gate_reason=gate_verdict.reason,
                gate_detail=gate_verdict.detail,
                connector_type=CONNECTOR_TYPE,
                requested_action=action,
                creator_id=creator_id,
                organization_id=str(organization_id) if organization_id else None,
                audit_event_id=audit_id,
                used_fixture=True,
                notes=(
                    "dry_run_pass_via_fake_client — production mode does "
                    "not exist; the client is a fake implementation."
                ),
                mode="dry_run",
                used_fake_client=True,
                rows_read=rows_read,
            )

        # 3b. mode="disabled" (Sprint 7 path). Compute and discard the
        # fixture payload; record the dry-run pass; return.
        _fixture = fixture_payload_for(action)
        del _fixture  # explicit drop so reviewers see the no-leak intent.

        audit_id = await self._audit_dry_run_pass(
            session,
            action=action,
            organization_id=organization_id,
            creator_id=creator_id,
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            used_fake_client=False,
            rows_read=0,
        )
        return DryRunResult(
            allowed=True,
            classification="read",
            policy_reason=verdict_policy.reason,
            gate_reason=gate_verdict.reason,
            gate_detail=gate_verdict.detail,
            connector_type=CONNECTOR_TYPE,
            requested_action=action,
            creator_id=creator_id,
            organization_id=str(organization_id) if organization_id else None,
            audit_event_id=audit_id,
            used_fixture=True,
            notes=(
                "dry_run_pass_fixture_only — connector is disabled; "
                f"future real implementation must replace {_REAL_CLIENT_TODO}."
            ),
            mode="disabled",
            used_fake_client=False,
            rows_read=0,
        )

    # ── audit helpers ───────────────────────────────────────────────────────

    async def _audit_blocked(
        self,
        session: AsyncSession,
        *,
        action: str,
        policy: PolicyVerdict,
        gate: GateVerdict | None,
        organization_id: UUID | None,
        creator_id: str | None,
        actor_user_id: UUID | None,
        actor_email: str | None,
    ) -> str | None:
        row = await record_audit(
            session,
            event_type="connector.run.blocked",
            category="connector",
            action="dry_run",
            result="blocked",
            severity="warning" if policy.classification == "write" else "info",
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            organization_id=organization_id,
            creator_id=creator_id,
            resource_type="connector_run",
            resource_id=f"{CONNECTOR_TYPE}:{action}",
            metadata={
                "connector_type": CONNECTOR_TYPE,
                "requested_action": action,
                "policy_classification": policy.classification,
                "policy_reason": policy.reason,
                "gate_reason": gate.reason if gate else None,
                "gate_detail": gate.detail if gate else None,
                "mode": "dry_run",
            },
        )
        await session.commit()
        return str(row.id) if row is not None else None

    async def _audit_dry_run_pass(
        self,
        session: AsyncSession,
        *,
        action: str,
        organization_id: UUID | None,
        creator_id: str | None,
        actor_user_id: UUID | None,
        actor_email: str | None,
        used_fake_client: bool = False,
        rows_read: int = 0,
    ) -> str | None:
        row = await record_audit(
            session,
            event_type="connector.dry_run.pass",
            category="connector",
            action="dry_run",
            result="success",
            severity="info",
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            organization_id=organization_id,
            creator_id=creator_id,
            resource_type="connector_run",
            resource_id=f"{CONNECTOR_TYPE}:{action}",
            metadata={
                "connector_type": CONNECTOR_TYPE,
                "requested_action": action,
                "mode": "dry_run",
                "fixture_only": True,
                "used_fake_client": used_fake_client,
                "rows_read": rows_read,
            },
        )
        await session.commit()
        return str(row.id) if row is not None else None

    # ── Sprint 8C: sandbox dry-run with all prerequisite gates ──────────────

    async def dry_run_sandbox(
        self,
        session: AsyncSession,
        *,
        action: str,
        creator_id: str,
        organization_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        actor_email: str | None = None,
    ) -> SandboxResult:
        """Run the sandbox-mode prerequisite chain end-to-end.

        Sandbox mode requires ALL of:

        1. ``MC_OF_DIRECT_SANDBOX_ALLOWED=1`` env flag.
        2. Non-production environment.
        3. Action is in :data:`READ_ACTIONS` (policy gate).
        4. Connector approval row live for ``(onlyfans_direct, read,
           creator_id)``.
        5. Client consent live for ``onlyfans_direct_read`` /
           ``creator_id``.
        6. No kill switch active at any scope (global / connector /
           organization / creator).
        7. Vault available (dedicated encryption key configured).
        8. Credential vault row resolved through the configured
           reference is ``"active"`` (not missing, revoked, rotated,
           stale, or wrong provider).
        9. Owner sign-off audit row exists for the creator
           (``connector.golive.sandbox``).

        On any miss: returns a :class:`SandboxResult` with
        ``allowed=False``, populated ``blocked_reason``, and writes
        a ``connector.sandbox.blocked`` audit row.

        On all-pass: invokes the configured client's read method
        (which is the Sprint 8C skeleton — every method raises
        :class:`RealClientNotEnabledError`). Captures the exception,
        writes ``connector.sandbox.blocked`` with reason
        ``real_client_not_enabled``, and returns ``allowed=False``.

        **There is no path through this method that performs a real
        network call.** A future Sprint 8D will replace the real
        client's method bodies; this gate is structurally complete
        already.
        """
        from app.services import connector_approvals as _approvals_svc
        from app.services import consent as _consent_svc
        from app.services import kill_switch as _kill_switch_svc
        from app.services.onlyfans_direct_session_health import DEFAULT_NOTIFIER

        # 0. Mode check — only sandbox mode may run this method.
        if self._mode != "sandbox":
            raise RuntimeError(
                f"dry_run_sandbox requires mode='sandbox'; current mode is "
                f"{self._mode!r}. Construct OnlyFansDirectConnector(mode='sandbox', ...)."
            )

        # Default everything to "not yet checked" so the result can
        # surface the prereq snapshot whichever step we exit on.
        env_flag_set = os.environ.get(ENV_SANDBOX_ALLOWED, "0").strip() == "1"
        from app.core.secrets_store import (
            is_dedicated_encryption_key_configured,
        )
        from app.core.startup_guard import is_production as _is_production

        in_prod = _is_production()
        cred_status_str = "unknown"
        approval_present = False
        consent_present = False
        kill_blocking: tuple[str, str | None] | None = None
        vault_available = is_dedicated_encryption_key_configured()
        owner_signoff_present = False
        notify_status = DEFAULT_NOTIFIER.status()

        async def _audit_blocked(reason: SandboxBlockedReason, notes: str) -> SandboxResult:
            audit_row = await record_audit(
                session,
                event_type="connector.sandbox.blocked",
                category="connector",
                action="dry_run_sandbox",
                result="blocked",
                severity="info",
                actor_user_id=actor_user_id,
                actor_email=actor_email,
                organization_id=organization_id,
                creator_id=creator_id,
                resource_type="connector_run",
                resource_id=f"{CONNECTOR_TYPE}:sandbox:{action}",
                metadata={
                    "connector_type": CONNECTOR_TYPE,
                    "requested_action": action,
                    "mode": "sandbox",
                    "blocked_reason": reason,
                },
            )
            await session.commit()
            return SandboxResult(
                allowed=False,
                blocked_reason=reason,
                connector_type=CONNECTOR_TYPE,
                requested_action=action,
                creator_id=creator_id,
                organization_id=str(organization_id) if organization_id else None,
                audit_event_id=str(audit_row.id) if audit_row is not None else None,
                notes=notes,
                env_flag_set=env_flag_set,
                is_production=in_prod,
                credential_status=cred_status_str,
                approval_present=approval_present,
                consent_present=consent_present,
                kill_switch_blocking=kill_blocking[0] if kill_blocking else None,
                vault_available=vault_available,
                owner_signoff_present=owner_signoff_present,
                notify_channel_status=notify_status,
            )

        # 1. env flag
        if not env_flag_set:
            return await _audit_blocked(
                "env_flag_disabled",
                f"Set {ENV_SANDBOX_ALLOWED}=1 to enable the sandbox path.",
            )
        # 2. production refusal
        if in_prod:
            return await _audit_blocked(
                "production_environment",
                "Sandbox mode is non-production only.",
            )
        # 3. policy
        verdict_policy: PolicyVerdict = evaluate_action(action)
        if not verdict_policy.allowed:
            if verdict_policy.classification == "write":
                # Same as Sprint 7: write actions raise loudly so a
                # test that asks for a write fails loud.
                raise BlockedActionError(f"dry_run_sandbox refused: {action!r} is a write action.")
            return await _audit_blocked("policy_refused", verdict_policy.reason)
        # Sprint 8E: explicit allowlist for sandbox-runnable actions.
        # The Sprint 8D real client will also refuse the other 7 reads
        # (they raise RealClientNotEnabledError), but failing earlier
        # here means the audit row says "real_client_not_enabled" with
        # the unimplemented action name — useful for runbooks.
        if action not in ALLOWED_SANDBOX_ACTIONS:
            return await _audit_blocked(
                "real_client_not_enabled",
                (
                    f"action {action!r} is not in the Sprint 8E sandbox "
                    f"allowlist {sorted(ALLOWED_SANDBOX_ACTIONS)}. "
                    "Other read methods are still unimplemented."
                ),
            )
        # 4-7. connector gate (kill switch, approval, consent, vault)
        gate_verdict: GateVerdict = await is_connector_action_allowed(
            session,
            connector_type=CONNECTOR_TYPE,
            requested_action="read",
            organization_id=organization_id,
            creator_id=creator_id,
        )
        # Populate snapshot fields from the gate's component checks
        # so the result carries full prereq breakdown even on block.
        approval_row = await _approvals_svc.is_approved(
            session,
            connector_type=CONNECTOR_TYPE,
            requested_action="read",
            organization_id=organization_id,
            creator_id=creator_id,
        )
        approval_present = approval_row is not None
        consent_row = await _consent_svc.is_granted(
            session,
            consent_type="onlyfans_direct_read",
            organization_id=organization_id,
            creator_id=creator_id,
        )
        consent_present = consent_row is not None
        kill_blocking = await _kill_switch_svc.check_action_allowed(
            session,
            connector_type=CONNECTOR_TYPE,
            organization_id=organization_id,
            creator_id=creator_id,
        )
        if not gate_verdict.allowed:
            reason: SandboxBlockedReason
            if gate_verdict.reason in (
                "kill_switch_global",
                "kill_switch_connector",
                "kill_switch_organization",
                "kill_switch_creator",
            ):
                reason = "kill_switch"
            elif gate_verdict.reason in ("no_approval", "approval_expired", "approval_revoked"):
                reason = "no_approval"
            elif gate_verdict.reason == "no_consent":
                reason = "no_consent"
            elif gate_verdict.reason == "vault_unavailable":
                reason = "vault_unavailable"
            else:
                reason = "unknown_error"
            return await _audit_blocked(
                reason,
                f"Connector gate blocked: {gate_verdict.reason} / {gate_verdict.detail}",
            )
        # 8. credential vault reference status
        if self._credential_ref is None:
            # Constructor enforces non-None for sandbox mode, but
            # mypy can't see that here; defensive guard.
            return await _audit_blocked(
                "credential_missing",
                "Internal: sandbox mode is missing credential_ref.",
            )
        cred_report = await check_credential_status(session, ref=self._credential_ref)
        cred_status_str = cred_report.kind
        if cred_report.kind != "active":
            mapping: dict[str, SandboxBlockedReason] = {
                "missing": "credential_missing",
                "revoked": "credential_revoked",
                "rotated": "credential_rotated",
                "stale": "credential_stale",
                "wrong_provider": "credential_wrong_provider",
            }
            return await _audit_blocked(
                mapping.get(cred_report.kind, "credential_missing"),
                cred_report.notes,
            )
        # 9. owner sign-off
        from app.services.onlyfans_direct_owner_signoff import has_owner_signoff

        owner_signoff_present = await has_owner_signoff(
            session,
            creator_id=creator_id,
            organization_id=organization_id,
        )
        if not owner_signoff_present:
            return await _audit_blocked(
                "no_owner_signoff",
                (
                    "No connector.golive.sandbox audit row found for this "
                    "creator. Record one via record_owner_signoff."
                ),
            )

        # All prerequisites pass. Invoke the configured client's
        # read method. Sprint 8D wires three real reads (profile,
        # stats, revenue) through the configured transport; the
        # other 7 still raise RealClientNotEnabledError. The
        # connector wrapper handles success / challenge / unexpected
        # status without ever surfacing a raw payload.
        from app.services.onlyfans_direct_real_client import (
            RealClientNotEnabledError,
        )
        from app.services.onlyfans_direct_session_health import (
            DEFAULT_NOTIFIER,
            record_session_challenged,
        )
        from app.services.onlyfans_direct_transport import (
            ChallengeDetectedError,
            UnexpectedStatusError,
        )

        if self._client is None:
            return await _audit_blocked(
                "real_client_not_enabled",
                "Sandbox mode has no client configured.",
            )
        method_name = READ_ACTION_TO_METHOD.get(action)
        if method_name is None:
            return await _audit_blocked(
                "unknown_error",
                f"No client method mapped for read action {action!r}.",
            )
        method = getattr(self._client, method_name)
        try:
            summary = await method(creator_id=creator_id)
        except RealClientNotEnabledError:
            return await _audit_blocked(
                "real_client_not_enabled",
                (
                    "All sandbox prerequisites pass; this read method is "
                    "not implemented in Sprint 8D. Allowed methods: "
                    "read_account_profile, read_account_stats, "
                    "read_revenue_summary."
                ),
            )
        except ChallengeDetectedError as exc:
            # Audit the challenge with safe metadata, call the
            # notifier (no-op in 8D), and return blocked. The
            # reason_category is narrowed via cast — runtime check
            # in _normalize_challenge_reason ensures it's in the
            # fixed Sprint 8B vocabulary before this point.
            from typing import cast

            from app.services.onlyfans_direct_session_health import ChallengeReason

            normalized = cast(ChallengeReason, _normalize_challenge_reason(exc.reason_category))
            await record_session_challenged(
                session,
                reason_category=normalized,
                creator_id=creator_id,
                organization_id=organization_id,
                actor_user_id=actor_user_id,
                actor_email=actor_email,
                extra_metadata={
                    "status_code": exc.status_code if exc.status_code else 0,
                    "requested_action": action,
                },
            )
            DEFAULT_NOTIFIER.notify(
                reason_category=normalized,
                creator_id=creator_id,
            )
            return await _audit_blocked(
                "challenge_detected",
                f"Challenge detected during sandbox read: {exc.reason_category}",
            )
        except UnexpectedStatusError as exc:
            audit_row = await record_audit(
                session,
                event_type="connector.sandbox.failed",
                category="connector",
                action="dry_run_sandbox",
                result="failed",
                severity="warning",
                actor_user_id=actor_user_id,
                actor_email=actor_email,
                organization_id=organization_id,
                creator_id=creator_id,
                resource_type="connector_run",
                resource_id=f"{CONNECTOR_TYPE}:sandbox:{action}",
                metadata={
                    "connector_type": CONNECTOR_TYPE,
                    "requested_action": action,
                    "mode": "sandbox",
                    "status_code": exc.status_code,
                    "blocked_reason": "unexpected_status",
                },
            )
            await session.commit()
            return SandboxResult(
                allowed=False,
                blocked_reason="unexpected_status",
                connector_type=CONNECTOR_TYPE,
                requested_action=action,
                creator_id=creator_id,
                organization_id=str(organization_id) if organization_id else None,
                audit_event_id=str(audit_row.id) if audit_row is not None else None,
                notes=f"Unexpected platform status {exc.status_code}.",
                env_flag_set=env_flag_set,
                is_production=in_prod,
                credential_status=cred_status_str,
                approval_present=approval_present,
                consent_present=consent_present,
                kill_switch_blocking=kill_blocking[0] if kill_blocking else None,
                vault_available=vault_available,
                owner_signoff_present=owner_signoff_present,
                notify_channel_status=notify_status,
            )

        # Success path. ``summary`` is a small typed dataclass-as-dict
        # already filtered through the allowlist parser. We never
        # persist or return the raw response; we audit only the safe
        # field counts.
        from app.core.onlyfans_direct_schemas import safe_field_counts

        # The summary dict came from summary_to_safe_dict; reconstruct
        # the dataclass for safe_field_counts to use isinstance checks.
        # We do this inline rather than threading dataclass instances
        # through the API because the wrapper here only needs counts.
        field_counts: dict[str, int] = {}
        if action == "account_profile_read":
            from app.core.onlyfans_direct_schemas import parse_account_profile

            field_counts = safe_field_counts(parse_account_profile(summary))
        elif action == "account_stats_read":
            from app.core.onlyfans_direct_schemas import parse_account_stats

            field_counts = safe_field_counts(parse_account_stats(summary))
        elif action == "revenue_summary_read":
            from app.core.onlyfans_direct_schemas import parse_revenue_summary

            field_counts = safe_field_counts(parse_revenue_summary(summary))

        success_row = await record_audit(
            session,
            event_type="connector.sandbox.success",
            category="connector",
            action="dry_run_sandbox",
            result="success",
            severity="info",
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            organization_id=organization_id,
            creator_id=creator_id,
            resource_type="connector_run",
            resource_id=f"{CONNECTOR_TYPE}:sandbox:{action}",
            metadata={
                "connector_type": CONNECTOR_TYPE,
                "requested_action": action,
                "mode": "sandbox",
                "field_counts": field_counts,
                "rows_written": 0,
            },
        )
        await session.commit()
        return SandboxResult(
            allowed=True,
            blocked_reason=None,
            connector_type=CONNECTOR_TYPE,
            requested_action=action,
            creator_id=creator_id,
            organization_id=str(organization_id) if organization_id else None,
            audit_event_id=str(success_row.id) if success_row is not None else None,
            notes="Sandbox read passed all prerequisites and returned a typed summary.",
            env_flag_set=env_flag_set,
            is_production=in_prod,
            credential_status=cred_status_str,
            approval_present=approval_present,
            consent_present=consent_present,
            kill_switch_blocking=kill_blocking[0] if kill_blocking else None,
            vault_available=vault_available,
            owner_signoff_present=owner_signoff_present,
            notify_channel_status=notify_status,
        )

    # ── refusal of any "real" mode call ─────────────────────────────────────

    async def fetch(self, *args: Any, **kwargs: Any) -> None:
        """Refuse every real-mode call.

        Defined so that any future code path that calls ``connector.fetch(...)``
        encounters a hard refusal instead of silently succeeding. Sprint 8+
        is expected to replace this with a real read-only fetch behind
        ``mode="dry_run"`` first, then a guarded production mode behind
        the readiness checklist.
        """
        del args, kwargs
        raise ConnectorNotEnabledError(
            "OnlyFansDirectConnector.fetch is not implemented. The direct "
            "OnlyFans connector is disabled in this build. Use dry_run() "
            "for fixture-mode validation; do not attempt real network calls."
        )
