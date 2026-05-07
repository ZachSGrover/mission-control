"""Direct OnlyFans connector — credential safety contract.

Sprint 7: codifies *how* credentials may and may not flow through
Mission Control for the future direct OnlyFans connector. This
module is **policy + assertions**, not a vault implementation. The
real vault lives at
:mod:`app.services.creator_credentials` and at
:class:`app.models.creator_credentials.CreatorCredential`; this
module declares the rules a future caller must follow when
interacting with that vault for the OnlyFans direct path.

Rules (binding):

1. Future credentials MUST be stored only in
   :class:`CreatorCredential`. No env-var, no file on disk, no
   ``app_settings`` row, no log line.
2. Raw cookies are FORBIDDEN. ``Set-Cookie`` headers,
   browser-export cookie blobs, and OnlyFans-specific cookies
   (``x-bc``, ``auth_id``, ``sess``, etc.) must never enter the
   vault as a credential value or as part of a metadata field. A
   future implementation that needs cookie-derived auth must
   exchange the cookie for a session blob inside an isolated
   process and store only the session blob.
3. Frontend session storage is FORBIDDEN: no
   :func:`localStorage`, :func:`sessionStorage`, or :func:`cookie`
   write of any OF-related credential data. The CI guardrail in
   :mod:`tests.test_public_secret_guardrail` already greps for the
   public-env-var anti-pattern; this contract extends that to the
   OF-specific paths.
4. API responses MUST never include credential value, preview, or
   length. The status surface returns booleans and enum strings
   only (see :class:`OnlyFansDirectConnector.status`).
5. Revocation is a vault-side operation
   (:func:`app.services.creator_credentials.revoke_credential`).
   Rotation is "create new + mark old rotated"
   (:func:`app.services.creator_credentials.rotate_credential`).
   Both write audit rows.

This module exposes:

- :func:`assert_no_forbidden_credential_keys` — runtime check used
  by tests and by the connector shell to refuse cookie/session
  inputs.
- :data:`FORBIDDEN_CREDENTIAL_KEYS` — the exact set of keys we will
  refuse on input.
- :data:`FRONTEND_FORBIDDEN_PATTERNS` — strings whose presence in
  the frontend bundle would indicate a contract violation. Used by
  a Sprint 7 test to scan the frontend source.
"""

from __future__ import annotations

from typing import Final, Mapping

# Keys that MUST NEVER appear in a credentials-shaped dict handed to
# the direct OnlyFans connector or its future client. Each represents
# a cookie, session token, or plaintext credential. The connector
# shell raises :class:`CookieRefusedError` on any of these; the
# helper below is the single source of truth.
FORBIDDEN_CREDENTIAL_KEYS: Final[frozenset[str]] = frozenset(
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
        "x-bc",
        "x_bc",
        "user_id",
    }
)


# Patterns whose presence in the frontend source would indicate a
# direct violation of the credential safety contract. The Sprint 7
# test :func:`tests.test_of_direct_readiness.test_frontend_has_no_of_credential_storage`
# scans the frontend tree for these and asserts none are present.
#
# These are case-sensitive substrings. Add to the list when a new
# storage anti-pattern is discovered; do not remove without owner
# review.
FRONTEND_FORBIDDEN_PATTERNS: Final[tuple[str, ...]] = (
    "localStorage.setItem('of_session",
    'localStorage.setItem("of_session',
    "localStorage.setItem('onlyfans_cookie",
    'localStorage.setItem("onlyfans_cookie',
    "sessionStorage.setItem('of_session",
    'sessionStorage.setItem("of_session',
    "document.cookie = 'of_session",
    'document.cookie = "of_session',
    "OF_RAW_COOKIE",
    "ONLYFANS_RAW_SESSION",
)


class CredentialContractViolation(RuntimeError):
    """Raised when a caller hands the OnlyFans direct path a
    credentials-shaped dict containing forbidden keys.
    """


def assert_no_forbidden_credential_keys(payload: Mapping[str, object]) -> None:
    """Raise :class:`CredentialContractViolation` if ``payload``
    contains any key in :data:`FORBIDDEN_CREDENTIAL_KEYS`.

    Used by tests and by the connector shell. The check is
    case-insensitive on the key (callers sometimes capitalise),
    but exact on the value's containing dict — we do not recurse.
    Recursion would imply we have a use-case for nested credential
    dicts, which we don't.
    """
    lowercased = {k.lower() for k in payload.keys()}
    forbidden = FORBIDDEN_CREDENTIAL_KEYS & lowercased
    if forbidden:
        raise CredentialContractViolation(
            "OnlyFans direct credential contract violated: payload contains "
            f"forbidden keys {sorted(forbidden)}. Direct OnlyFans credentials "
            "must flow through the creator credential vault only — never as "
            "raw cookies, session tokens, or plaintext fields."
        )


def revocation_runbook() -> str:
    """Short text the security admin UI / runbook can reference.

    Stating the procedure in code (not just docs) makes it harder
    for it to drift away from the implementation.
    """
    return (
        "Revocation procedure for an OnlyFans direct credential:\n"
        "  1. Owner toggles connector kill switch:\n"
        "     POST /api/v1/security/kill-switches/enable\n"
        "     scope='connector', scope_id='onlyfans_direct'.\n"
        "  2. Vault revoke:\n"
        "     app.services.creator_credentials.revoke_credential(\n"
        "         session, credential_id=<id>, actor_user_id=<owner>)\n"
        "  3. Creator-side: reset OnlyFans password and re-pair 2FA.\n"
        "     This is the creator's action; we cannot perform it.\n"
        "  4. Audit confirm:\n"
        "     SELECT * FROM audit_events\n"
        "     WHERE event_type IN ('kill_switch.toggle','credential.revoke')\n"
        "       AND created_at >= now() - interval '1 hour'\n"
        "     ORDER BY created_at DESC;\n"
        "  5. Re-pair only after a fresh signed consent and a clean\n"
        "     readiness checklist run.\n"
    )


def rotation_runbook() -> str:
    """Procedure for rotating a credential without revoking the creator
    relationship.
    """
    return (
        "Rotation procedure for an OnlyFans direct credential:\n"
        "  1. Vault rotate (atomic):\n"
        "     app.services.creator_credentials.rotate_credential(\n"
        "         session, old_credential_id=<id>, new_value=<new>,\n"
        "         actor_user_id=<owner>)\n"
        "     Writes 'credential.rotate' audit row.\n"
        "  2. Confirm session_health=='healthy' on the next dry_run\n"
        "     before re-enabling any non-dry-run path.\n"
        "  3. If the rotation followed a suspected leak, also walk\n"
        "     docs/security/incident-drill-token-leak.md.\n"
    )
