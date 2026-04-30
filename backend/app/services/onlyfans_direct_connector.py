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

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.connector_gate import GateVerdict, is_connector_action_allowed
from app.core.onlyfans_direct_client import (
    READ_ACTION_TO_METHOD,
    OnlyFansReadOnlyClient,
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

logger = logging.getLogger(__name__)


CONNECTOR_TYPE: Final[str] = "onlyfans_direct"

# When a future sprint wires the real OnlyFans client, replace this
# string with the import path of the read-only client class. The class
# must implement only the read actions in
# ``app.core.onlyfans_direct_policy.READ_ACTIONS`` and must not have any
# method that performs a write of any kind.
_REAL_CLIENT_TODO: Final[str] = (
    "app.integrations.onlyfans.client.OnlyFansReadOnlyClient (not yet present)"
)

ConnectorMode = Literal["disabled", "dry_run"]


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
        if mode not in ("disabled", "dry_run"):
            raise ValueError(
                f"Invalid mode {mode!r}. Sprint 8B supports 'disabled' "
                "(default) and 'dry_run' only. There is no production mode."
            )
        if mode == "dry_run" and client is None:
            raise ValueError(
                "mode='dry_run' requires a client (OnlyFansReadOnlyClient). "
                "Sprint 8B accepts only the fake client; pass FakeOnlyFansReadOnlyClient()."
            )
        # Intentionally drop other kwargs on the floor.
        self._mode: ConnectorMode = mode
        self._client: OnlyFansReadOnlyClient | None = client

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
        notes = (
            "Direct OnlyFans connector is disabled. Read-only "
            "implementation has not been written. See "
            "docs/security/direct-onlyfans-readiness-checklist.md."
            if self._mode == "disabled"
            else (
                "Direct OnlyFans connector is in dry_run mode. The "
                "configured client is a fake implementation backed by "
                "Sprint 7 fixtures; there is no real network call. "
                "Production mode does not exist."
            )
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
