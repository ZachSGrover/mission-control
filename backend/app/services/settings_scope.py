"""Settings scope cutover helper.

Sprint 3 introduced ``app.services.app_settings_scoped`` with the org-
scoped read/write primitives. Sprint 5 adds this thin compatibility
shim that lets existing route call sites move to org-scoped storage
behind a feature flag without rewriting every read in the codebase.

Behaviour:

- :func:`is_org_scope_enabled` — checks ``MC_APP_SETTINGS_ORG_SCOPED``.
  Defaults to **off** for safety; legacy global storage stays intact.
- :func:`get_secret_scoped` / :func:`set_secret_scoped` — wrappers that
  pick the org-scoped or global store based on the flag.

Cross-tenant leakage prevention:
- When the flag is on AND an organization_id is supplied, both reads
  and writes target the org row.
- When the flag is on AND no organization_id is supplied, behaviour
  matches legacy: global row.
- When the flag is off, behaviour matches legacy entirely.

This module never silently writes a global row when the caller passed
an org_id and the flag is on — that would be a leak. If the operator
forgot to set the flag and call sites pass org_ids, the flag-off path
just routes through legacy and the next migration window can pick up.
"""

from __future__ import annotations

import os
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.secrets_store import (
    delete_secret as _delete_secret_global,
    get_secret_with_source as _get_secret_with_source_global,
    set_secret as _set_secret_global,
)
from app.services.app_settings_scoped import (
    delete_secret_for_org,
    get_secret_for_org,
    set_secret_for_org,
)

ENV_FLAG = "MC_APP_SETTINGS_ORG_SCOPED"


def is_org_scope_enabled() -> bool:
    return os.environ.get(ENV_FLAG, "0").strip() == "1"


async def get_secret_scoped(
    session: AsyncSession,
    db_key: str,
    *,
    organization_id: UUID | None,
    fallback: str = "",
) -> tuple[str, str]:
    """Read a secret with org-scope when the flag is enabled.

    Returns ``(plaintext, source)`` where source is one of
    ``"db_org"``, ``"db_global"``, ``"env"``, or ``"none"`` /
    legacy ``"db"`` / ``"env"`` / ``"none"`` from the global path.
    """
    if is_org_scope_enabled() and organization_id is not None:
        return await get_secret_for_org(
            session, db_key, organization_id=organization_id, fallback=fallback
        )
    # Legacy global path — preserves the exact tuple shape callers expect.
    return await _get_secret_with_source_global(session, db_key, fallback=fallback)


async def set_secret_scoped(
    session: AsyncSession,
    db_key: str,
    plaintext: str,
    *,
    organization_id: UUID | None,
) -> None:
    """Write a secret with org-scope when the flag is enabled."""
    if is_org_scope_enabled() and organization_id is not None:
        await set_secret_for_org(session, db_key, plaintext, organization_id=organization_id)
        return
    await _set_secret_global(session, db_key, plaintext)


async def delete_secret_scoped(
    session: AsyncSession,
    db_key: str,
    *,
    organization_id: UUID | None,
) -> None:
    """Delete a secret with org-scope when the flag is enabled."""
    if is_org_scope_enabled() and organization_id is not None:
        await delete_secret_for_org(session, db_key, organization_id=organization_id)
        return
    await _delete_secret_global(session, db_key)
