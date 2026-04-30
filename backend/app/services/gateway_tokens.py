"""Gateway-token storage helpers.

Sprint 3 hardening for the long-standing risk that ``gateways.token``
was plaintext on disk. New writes go through :func:`set_token` which
encrypts under the same Fernet machinery as ``app_settings``. Reads
prefer the new ``encrypted_token`` column and fall back to the legacy
plaintext ``token`` column for rows created before this sprint.

Operational note: the migrator :func:`migrate_legacy_tokens` is **not**
auto-run. An operator should run it once after deploy to move every
legacy plaintext value into the encrypted column. The migrator never
deletes data — it only encrypts and clears the legacy column.

Audit:
- :func:`set_token` records ``gateway.token.set`` at severity
  ``warning``. The old ``token`` column is cleared on encrypt-write so
  one row never holds both plaintext and ciphertext.
- :func:`migrate_legacy_tokens` records one
  ``gateway.token.legacy_migrated`` row per migrated gateway at
  ``high``.

API hygiene: callers must use :func:`token_preview` for any
operator-facing display. The plaintext is never logged, never returned
in audit metadata, and never appears outside the function scope of
:func:`get_token`.
"""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.secrets_store import (
    decrypt_value,
    encrypt_value,
    is_dedicated_encryption_key_configured,
)
from app.core.time import utcnow
from app.models.gateways import Gateway
from app.services.audit_log import record_audit


def token_preview(plaintext: str | None) -> str | None:
    """Return a non-reversible 8-char SHA-256 prefix for operator display.

    Useful for "is this still the same token I configured?" without ever
    exposing the secret. Returns ``None`` for empty / missing values.
    """
    if not plaintext:
        return None
    return hashlib.sha256(plaintext.encode()).hexdigest()[:8]


async def set_token(
    session: AsyncSession,
    gateway: Gateway,
    plaintext: str | None,
    *,
    actor_user_id: UUID | None = None,
    actor_email: str | None = None,
) -> Gateway:
    """Encrypt ``plaintext`` and store it on ``gateway.encrypted_token``.

    Side effects:
    - ``gateway.encrypted_token`` is set to Fernet ciphertext (or empty
      if ``plaintext`` is ``None``).
    - ``gateway.token`` (legacy plaintext column) is cleared so the row
      never holds both forms.
    - ``gateway.updated_at`` is bumped.
    - The session has the audit row appended; caller commits.
    """
    if plaintext:
        gateway.encrypted_token = encrypt_value(plaintext)
    else:
        gateway.encrypted_token = None
    # Always clear the legacy plaintext column on any write. Legacy
    # rows that never got migrated keep their old token until either
    # this writer or the migrator touches them.
    gateway.token = None
    gateway.updated_at = utcnow()
    session.add(gateway)

    await record_audit(
        session,
        event_type="gateway.token.set",
        category="credential",
        action="put" if plaintext else "delete",
        result="success",
        severity="warning" if plaintext else "high",
        actor_user_id=actor_user_id,
        actor_email=actor_email,
        organization_id=gateway.organization_id,
        resource_type="gateway",
        resource_id=str(gateway.id),
        metadata={
            "gateway_id": str(gateway.id),
            "preview": token_preview(plaintext),
        },
    )
    return gateway


def get_token(gateway: Gateway) -> str | None:
    """Return the gateway's plaintext token, or ``None`` if unset.

    Decryption-then-fallback order:
    1. ``encrypted_token`` if set — decrypt it.
    2. Legacy ``token`` column — return as-is.

    A decrypt failure on the encrypted column returns ``None`` rather
    than the legacy value, so a corrupted ciphertext never silently
    falls back to plaintext.
    """
    if gateway.encrypted_token:
        plaintext = decrypt_value(gateway.encrypted_token)
        return plaintext or None
    if gateway.token:
        return gateway.token
    return None


async def migrate_legacy_tokens(
    session: AsyncSession,
    *,
    actor_email: str | None = None,
    dry_run: bool = True,
) -> tuple[int, int]:
    """One-shot helper that moves every plaintext ``gateways.token`` into
    ``encrypted_token`` and clears the legacy column.

    Returns ``(scanned, migrated)``. On ``dry_run=True`` (default), no
    rows are mutated — only the count is reported. The migrator refuses
    to run if :func:`is_dedicated_encryption_key_configured` returns
    False; encrypting under the auth-token fallback would create rows
    that become unreadable on the next auth-secret rotation.

    Each successfully migrated row records a
    ``gateway.token.legacy_migrated`` audit at severity ``high``.
    """
    if not is_dedicated_encryption_key_configured():
        raise RuntimeError(
            "gateway token migrator refuses to run: " "SETTINGS_ENCRYPTION_KEY is not set."
        )

    scanned = 0
    migrated = 0
    rows = (await session.exec(select(Gateway))).all()
    for gw in rows:
        scanned += 1
        if not gw.token:
            continue
        if gw.encrypted_token:
            # Already migrated by hand — leave the legacy column for
            # the operator to clear once they've verified.
            continue
        if dry_run:
            migrated += 1
            continue
        gw.encrypted_token = encrypt_value(gw.token)
        gw.token = None
        gw.updated_at = utcnow()
        session.add(gw)
        await record_audit(
            session,
            event_type="gateway.token.legacy_migrated",
            category="credential",
            action="migrate",
            result="success",
            severity="high",
            actor_email=actor_email,
            organization_id=gw.organization_id,
            resource_type="gateway",
            resource_id=str(gw.id),
            metadata={"gateway_id": str(gw.id)},
        )
        migrated += 1
    return scanned, migrated
