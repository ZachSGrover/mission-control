"""Creator credential vault service.

Wraps :class:`app.models.creator_credentials.CreatorCredential` with
the four operations callers need:

- :func:`create_credential` — store a new encrypted credential.
- :func:`revoke_credential` — mark active → revoked.
- :func:`rotate_credential` — atomic "create new + mark old rotated".
- :func:`get_credential_metadata` — return everything **except** the
  encrypted value or any plaintext.

Hard guardrails (fail-closed):
- If :func:`app.core.secrets_store.is_dedicated_encryption_key_configured`
  returns ``False``, all *write* operations refuse with a typed error.
  This is the Sprint-2 line in the sand: creator credentials are too
  sensitive to live under the rotation-prone auth-token fallback.
- Plaintext is never logged, never stored, never returned. Audit
  metadata only includes the credential id, provider, type, and a hash
  prefix (8 hex chars) for traceability.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.secrets_store import (
    encrypt_value,
    is_dedicated_encryption_key_configured,
)
from app.core.time import utcnow
from app.models.creator_credentials import (
    CREDENTIAL_PROVIDERS,
    CREDENTIAL_STATUSES,
    CREDENTIAL_TYPES,
    CreatorCredential,
)
from app.services.audit_log import record_audit


class CredentialVaultUnavailableError(RuntimeError):
    """Raised when the dedicated encryption key is not configured.

    Callers should treat this as a hard "no" — never fall back to
    storing a creator credential under a rotation-sensitive seed.
    """


def _validate_provider(provider: str) -> None:
    if provider not in CREDENTIAL_PROVIDERS:
        raise ValueError(f"unknown credential provider: {provider!r}")


def _validate_credential_type(credential_type: str) -> None:
    if credential_type not in CREDENTIAL_TYPES:
        raise ValueError(f"unknown credential_type: {credential_type!r}")


def _hash_prefix(plaintext: str) -> str:
    """Short, irreversible identifier for audit traceability.

    Eight hex chars of SHA-256. Cannot recover the credential from this;
    used only to correlate "this audit row refers to the same credential
    that was created earlier" without ever logging the credential itself.
    """
    return hashlib.sha256(plaintext.encode()).hexdigest()[:8]


def _require_dedicated_key() -> None:
    if not is_dedicated_encryption_key_configured():
        raise CredentialVaultUnavailableError(
            "Creator credential vault refuses writes: SETTINGS_ENCRYPTION_KEY "
            "is not set. Configure a dedicated 32-hex encryption key before "
            "storing creator-scoped credentials."
        )


async def create_credential(
    session: AsyncSession,
    *,
    organization_id: UUID | None,
    creator_id: str,
    provider: str,
    credential_type: str,
    plaintext: str,
    created_by_user_id: UUID | None = None,
    created_by_email: str | None = None,
    metadata: object | None = None,
) -> CreatorCredential:
    """Create one encrypted credential row. Plaintext is never stored or logged."""
    _validate_provider(provider)
    _validate_credential_type(credential_type)
    _require_dedicated_key()
    if not plaintext:
        raise ValueError("creator credential plaintext must not be empty")

    ciphertext = encrypt_value(plaintext)
    row = CreatorCredential(
        organization_id=organization_id,
        creator_id=creator_id,
        provider=provider,
        credential_type=credential_type,
        encrypted_value=ciphertext,
        status="active",
        created_by_user_id=created_by_user_id,
        created_by_email=created_by_email,
    )
    session.add(row)
    await session.flush()

    await record_audit(
        session,
        event_type="creator_credential.create",
        category="credential",
        action="create",
        result="success",
        severity="high",
        actor_user_id=created_by_user_id,
        actor_email=created_by_email,
        organization_id=organization_id,
        creator_id=creator_id,
        resource_type="creator_credential",
        resource_id=str(row.id),
        metadata={
            "provider": provider,
            "credential_type": credential_type,
            "hash_prefix": _hash_prefix(plaintext),
            "extra": metadata,
        },
    )
    return row


async def revoke_credential(
    session: AsyncSession,
    credential_id: UUID,
    *,
    revoked_by_user_id: UUID | None = None,
    revoked_by_email: str | None = None,
    reason: str | None = None,
) -> CreatorCredential | None:
    row = await session.get(CreatorCredential, credential_id)
    if row is None:
        return None
    if row.status not in CREDENTIAL_STATUSES:  # defensive
        return row

    row.status = "revoked"
    row.revoked_by_user_id = revoked_by_user_id
    row.revoked_by_email = revoked_by_email
    row.revoked_at = utcnow()
    session.add(row)

    await record_audit(
        session,
        event_type="creator_credential.revoke",
        category="credential",
        action="revoke",
        result="success",
        severity="critical",
        actor_user_id=revoked_by_user_id,
        actor_email=revoked_by_email,
        organization_id=row.organization_id,
        creator_id=row.creator_id,
        resource_type="creator_credential",
        resource_id=str(row.id),
        metadata={
            "provider": row.provider,
            "credential_type": row.credential_type,
            "reason": reason,
        },
    )
    return row


async def rotate_credential(
    session: AsyncSession,
    credential_id: UUID,
    *,
    new_plaintext: str,
    rotated_by_user_id: UUID | None = None,
    rotated_by_email: str | None = None,
) -> tuple[CreatorCredential | None, CreatorCredential | None]:
    """Atomically mark an existing credential rotated and create its replacement.

    Returns ``(old_row, new_row)``. If the old row does not exist,
    returns ``(None, None)`` and writes nothing.
    """
    _require_dedicated_key()
    if not new_plaintext:
        raise ValueError("rotation plaintext must not be empty")

    old = await session.get(CreatorCredential, credential_id)
    if old is None:
        return (None, None)

    now = utcnow()
    old.status = "rotated"
    old.rotated_at = now
    session.add(old)

    new = CreatorCredential(
        organization_id=old.organization_id,
        creator_id=old.creator_id,
        provider=old.provider,
        credential_type=old.credential_type,
        encrypted_value=encrypt_value(new_plaintext),
        status="active",
        created_by_user_id=rotated_by_user_id,
        created_by_email=rotated_by_email,
    )
    session.add(new)
    await session.flush()

    await record_audit(
        session,
        event_type="creator_credential.rotate",
        category="credential",
        action="rotate",
        result="success",
        severity="high",
        actor_user_id=rotated_by_user_id,
        actor_email=rotated_by_email,
        organization_id=old.organization_id,
        creator_id=old.creator_id,
        resource_type="creator_credential",
        resource_id=str(new.id),
        metadata={
            "provider": old.provider,
            "credential_type": old.credential_type,
            "rotated_from": str(old.id),
            "new_hash_prefix": _hash_prefix(new_plaintext),
        },
    )
    return (old, new)


def get_credential_metadata(row: CreatorCredential) -> dict[str, Any]:
    """Return safe-to-expose metadata for a credential row.

    Explicitly excludes ``encrypted_value`` and any plaintext-derived
    field. Suitable for both logs and API responses.
    """
    return {
        "id": str(row.id),
        "organization_id": str(row.organization_id) if row.organization_id else None,
        "creator_id": row.creator_id,
        "provider": row.provider,
        "credential_type": row.credential_type,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "rotated_at": row.rotated_at.isoformat() if row.rotated_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
    }
