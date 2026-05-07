"""Org-scoped app-settings reads and writes.

Sprint 3 hardening for the long-standing risk that ``app_settings`` is
a flat key→value namespace shared across every tenant. Cross-tenant
collision is now possible to *avoid* using this helper, while leaving
legacy global rows intact so existing call sites keep working.

How it avoids the ``key`` PK collision (without a schema migration):

- A global setting still uses the original key, e.g. ``api_key.openai``,
  with ``organization_id=NULL``. This is the legacy / fallback row.
- An org-scoped setting uses a derived key
  ``org:{uuid}.{key}``, with ``organization_id=org_id``. The derived
  key encodes the scope so the existing ``key`` PK never collides.

Reads via :func:`get_secret_for_org` prefer the org-scoped row and
fall back to the global one. Writes via :func:`set_secret_for_org`
always go to the org-scoped row when an ``organization_id`` is given.

This is a foundation: a future sprint can drop the synthetic key
prefix and promote ``(key, organization_id)`` to a unique constraint
once every caller has been migrated. For now, the seam is the helpers
in this module.
"""

from __future__ import annotations

from uuid import UUID

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.secrets_store import _decrypt, _encrypt  # private helpers, OK in same package
from app.core.time import utcnow
from app.models.app_setting import AppSetting

ORG_KEY_PREFIX = "org:"


def _scoped_key(key: str, organization_id: UUID | None) -> str:
    """Derive the storage key for ``(key, organization_id)``.

    Returns the bare ``key`` when ``organization_id`` is ``None``
    (legacy/global). Returns ``org:{uuid}.{key}`` for org-scoped rows.
    """
    if organization_id is None:
        return key
    return f"{ORG_KEY_PREFIX}{organization_id}.{key}"


async def _get_row(
    session: AsyncSession, key: str, organization_id: UUID | None
) -> AppSetting | None:
    storage_key = _scoped_key(key, organization_id)
    stmt = select(AppSetting).where(AppSetting.key == storage_key)
    result = await session.exec(stmt)
    return result.first()


async def get_secret_for_org(
    session: AsyncSession,
    key: str,
    *,
    organization_id: UUID | None,
    fallback: str = "",
) -> tuple[str, str]:
    """Read a secret for ``(key, organization_id)`` with fall-through.

    Resolution order:
    1. Org-scoped row matching the derived key — if present and
       decryptable, return ``(plaintext, "db_org")``.
    2. Global row matching the plain key — if present and decryptable,
       return ``(plaintext, "db_global")``.
    3. ``fallback`` value — return ``(fallback, "env")`` if non-empty,
       else ``("", "none")``.

    Cross-tenant leakage is prevented because each org's data lives
    under a distinct storage key. Two orgs that both set
    ``api_key.openai`` end up with two separate rows; neither sees the
    other.
    """
    if organization_id is not None:
        row = await _get_row(session, key, organization_id)
        if row and row.value:
            plaintext = _decrypt(row.value, db_key=_scoped_key(key, organization_id))
            if plaintext:
                return plaintext, "db_org"

    row = await _get_row(session, key, None)
    if row and row.value:
        plaintext = _decrypt(row.value, db_key=key)
        if plaintext:
            return plaintext, "db_global"

    if fallback:
        return fallback, "env"
    return "", "none"


async def set_secret_for_org(
    session: AsyncSession,
    key: str,
    plaintext: str,
    *,
    organization_id: UUID | None,
) -> AppSetting:
    """Upsert ``(key, organization_id)`` with the encrypted ``plaintext``.

    Caller is responsible for any audit row and for committing the
    session. This helper only touches the row.
    """
    storage_key = _scoped_key(key, organization_id)
    row = await _get_row(session, key, organization_id)
    ciphertext = _encrypt(plaintext)
    if row is None:
        row = AppSetting(
            key=storage_key,
            value=ciphertext,
            updated_at=utcnow(),
            organization_id=organization_id,
        )
        session.add(row)
    else:
        row.value = ciphertext
        row.updated_at = utcnow()
        row.organization_id = organization_id
        session.add(row)
    return row


async def delete_secret_for_org(
    session: AsyncSession,
    key: str,
    *,
    organization_id: UUID | None,
) -> bool:
    """Delete the row for ``(key, organization_id)``. Returns True if a row was removed."""
    row = await _get_row(session, key, organization_id)
    if row is None:
        return False
    await session.delete(row)
    return True
