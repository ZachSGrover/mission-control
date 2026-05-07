"""Direct OnlyFans sandbox credential reference.

Sprint 8C: a typed reference that points at a row in
:class:`app.models.creator_credentials.CreatorCredential` **without
ever carrying the credential value**. The real read-only client
skeleton accepts a :class:`CredentialReference` in its constructor
instead of a credential string — the Sprint 7 contract that "raw
cookies / sessions / passwords are forbidden" is enforced at the
constructor signature level.

This module exposes:

- :class:`CredentialReference` — a frozen dataclass carrying only
  ``(creator_id, credential_id, provider, credential_type)``. No
  encrypted value, no decrypted value, no preview, no length.
- :class:`CredentialStatusReport` — a frozen dataclass carrying the
  metadata fields the security admin and sandbox gate need to
  reason about the credential without ever touching the encrypted
  value.
- :func:`check_credential_status` — async helper that resolves a
  reference against ``creator_credentials`` and returns the
  status report. Returns a "missing" report if the row doesn't
  exist; never raises for ordinary "not found" cases.

This module performs **no decryption** and **no I/O** beyond a
single SELECT. It cannot leak the credential value — there is no
code path here that touches ``encrypted_value`` at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.creator_credentials import CreatorCredential

# The only provider this reference is valid for. Sprint 8C is direct
# OnlyFans only; the helper refuses references with any other provider
# so a future caller doesn't accidentally point this at an OnlyMonster
# credential row (which has different semantics).
ALLOWED_PROVIDER: Final[str] = "onlyfans_direct"


CredentialStatusKind = Literal[
    "missing",  # no row matches the reference
    "active",  # row exists, status="active", not rotated, not revoked
    "rotated",  # row exists, status="rotated"
    "revoked",  # row exists, status="revoked" or revoked_at set
    "wrong_provider",  # row exists but its provider != onlyfans_direct
    "stale",  # row is active but rotated_at set (treated as expired-shaped)
]


@dataclass(frozen=True)
class CredentialReference:
    """Reference to a vault row, value-free by construction.

    The fields here are the *metadata* a caller could derive from
    the security admin UI — ids and provenance — never the
    credential value itself. The real client skeleton consumes this
    reference to look up status before any (future) decryption.
    """

    creator_id: str
    credential_id: UUID
    provider: str = ALLOWED_PROVIDER
    credential_type: str = "session_token"


@dataclass(frozen=True)
class CredentialStatusReport:
    """Status snapshot of a credential row, value-free.

    This is what the sandbox gate, the admin UI, and the audit
    pipeline see. There is no ``value`` / ``preview`` / ``length``
    field — those would be category errors here.
    """

    kind: CredentialStatusKind
    exists: bool
    is_active: bool
    is_revoked: bool
    is_rotated: bool
    provider: str | None  # None if missing
    credential_type: str | None
    creator_id: str
    credential_id: UUID
    notes: str


async def check_credential_status(
    session: AsyncSession,
    *,
    ref: CredentialReference,
) -> CredentialStatusReport:
    """Resolve ``ref`` against the vault and return a status report.

    Never returns or touches the encrypted value. Returns a
    ``"missing"`` report if no row matches, ``"wrong_provider"`` if
    the row exists under a different provider, ``"revoked"`` /
    ``"rotated"`` / ``"active"`` / ``"stale"`` otherwise.

    The caller (the sandbox gate) is expected to treat anything
    other than ``"active"`` as a hard refusal.
    """
    stmt = (
        select(CreatorCredential)
        .where(CreatorCredential.id == ref.credential_id)
        .where(CreatorCredential.creator_id == ref.creator_id)
    )
    result = await session.exec(stmt)
    row = result.first()

    if row is None:
        return CredentialStatusReport(
            kind="missing",
            exists=False,
            is_active=False,
            is_revoked=False,
            is_rotated=False,
            provider=None,
            credential_type=None,
            creator_id=ref.creator_id,
            credential_id=ref.credential_id,
            notes="No credential row matches the reference.",
        )

    if row.provider != ALLOWED_PROVIDER:
        return CredentialStatusReport(
            kind="wrong_provider",
            exists=True,
            is_active=False,
            is_revoked=row.revoked_at is not None,
            is_rotated=row.rotated_at is not None,
            provider=row.provider,
            credential_type=row.credential_type,
            creator_id=ref.creator_id,
            credential_id=ref.credential_id,
            notes=(
                f"Credential row provider is {row.provider!r}; sandbox "
                f"requires {ALLOWED_PROVIDER!r}. Refused."
            ),
        )

    if row.status == "revoked" or row.revoked_at is not None:
        return CredentialStatusReport(
            kind="revoked",
            exists=True,
            is_active=False,
            is_revoked=True,
            is_rotated=row.rotated_at is not None,
            provider=row.provider,
            credential_type=row.credential_type,
            creator_id=ref.creator_id,
            credential_id=ref.credential_id,
            notes="Credential is revoked. Pair a fresh credential.",
        )

    if row.status == "rotated":
        return CredentialStatusReport(
            kind="rotated",
            exists=True,
            is_active=False,
            is_revoked=False,
            is_rotated=True,
            provider=row.provider,
            credential_type=row.credential_type,
            creator_id=ref.creator_id,
            credential_id=ref.credential_id,
            notes="Credential has been rotated. Use the successor row.",
        )

    if row.status == "active" and row.rotated_at is not None:
        # Active but with rotated_at set is a half-state; treat as
        # stale so the caller can refuse without making a decision
        # about whether to use the old or the new row.
        return CredentialStatusReport(
            kind="stale",
            exists=True,
            is_active=True,
            is_revoked=False,
            is_rotated=True,
            provider=row.provider,
            credential_type=row.credential_type,
            creator_id=ref.creator_id,
            credential_id=ref.credential_id,
            notes=(
                "Credential is active but rotated_at is set — treat as "
                "stale and refuse until a fresh successor is paired."
            ),
        )

    return CredentialStatusReport(
        kind="active",
        exists=True,
        is_active=True,
        is_revoked=False,
        is_rotated=False,
        provider=row.provider,
        credential_type=row.credential_type,
        creator_id=ref.creator_id,
        credential_id=ref.credential_id,
        notes="Credential is active.",
    )
