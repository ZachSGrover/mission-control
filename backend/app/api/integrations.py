"""
Integration credential management — AdsPower, PhantomBuster, etc.

Credentials are stored encrypted in the same secrets store as AI provider keys.
Pattern mirrors app_settings.py exactly.

Endpoints:
  GET    /api/v1/integrations            → list all integration credential statuses
  PUT    /api/v1/integrations/{name}     → save/update credential
  DELETE /api/v1/integrations/{name}     → clear credential
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.mc_roles import require_owner
from app.core.auth import AuthContext, get_auth_context
from app.core.secrets_store import mask_key
from app.db.session import get_session
from app.services.audit_log import actor_from_auth, record_audit
from app.services.settings_scope import (
    delete_secret_scoped,
    get_secret_scoped,
    set_secret_scoped,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])
AUTH_DEP = Depends(get_auth_context)
OWNER_DEP = Depends(require_owner)
SESSION_DEP = Depends(get_session)

# ── Supported integrations ────────────────────────────────────────────────────
# Map public name → DB secret key.  Add new integrations here only.

INTEGRATION_KEYS: dict[str, str] = {
    "adspower": "adspower_api_key",
    "phantombuster": "phantombuster_api_key",
    # OnlyMonster — first data source for OnlyFans Intelligence.  Reuses the
    # same DB key as the dedicated OFI router so saving in either place takes
    # effect everywhere immediately.
    "onlymonster": "onlymonster.api_key",
}

INTEGRATION_META: dict[str, dict[str, str]] = {
    "adspower": {
        "label": "AdsPower",
        "description": "Anti-detect browser automation. API key from AdsPower profile → API.",
        "placeholder": "adspower-...",
        "docs_url": "https://www.adspower.com/api-docs",
    },
    "phantombuster": {
        "label": "PhantomBuster",
        "description": "Cloud automation phantoms for LinkedIn, scraping, lead gen.",
        "placeholder": "pb_...",
        "docs_url": "https://phantombuster.com/api",
    },
    "onlymonster": {
        "label": "OnlyMonster",
        "description": "Data source for OnlyFans Intelligence — accounts, fans, chats, revenue, mass messages.",
        "placeholder": "om_...",
        "docs_url": "https://www.onlymonster.ai",
    },
}


# ── Schemas ───────────────────────────────────────────────────────────────────


class IntegrationStatus(BaseModel):
    name: str
    label: str
    description: str
    placeholder: str
    docs_url: str
    configured: bool
    preview: str | None = None
    source: str = "none"  # "db" | "none"


class SetCredentialRequest(BaseModel):
    key: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=list[IntegrationStatus])
async def list_integrations(
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> list[IntegrationStatus]:
    """Return credential status for all supported integrations.

    Owner-only.  Even masked previews of integration keys are gated to the
    owner so operator/builder/viewer roles cannot enumerate which platform
    credentials are wired up.

    Sprint 6: route through the scoped wrapper. ``organization_id=None``
    keeps legacy global behaviour today; future sprints can resolve the
    caller's org context and pass it here without re-touching this file.
    """
    result: list[IntegrationStatus] = []
    for name, db_key in INTEGRATION_KEYS.items():
        value, source = await get_secret_scoped(session, db_key, organization_id=None)
        configured = bool(value and value.strip())
        meta = INTEGRATION_META[name]
        result.append(
            IntegrationStatus(
                name=name,
                label=meta["label"],
                description=meta["description"],
                placeholder=meta["placeholder"],
                docs_url=meta["docs_url"],
                configured=configured,
                preview=mask_key(value) if configured else None,
                source=source,
            )
        )
    return result


@router.put("/{name}", response_model=IntegrationStatus)
async def save_credential(
    name: str,
    body: SetCredentialRequest,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> IntegrationStatus:
    """Save or update the API key for an integration. Takes effect immediately."""
    if name not in INTEGRATION_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown integration '{name}'. Valid: {sorted(INTEGRATION_KEYS)}",
        )
    value = body.key.strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential value must not be empty.",
        )
    db_key = INTEGRATION_KEYS[name]
    # Sprint 6: route credential write through the scoped wrapper so
    # future per-org isolation lands without re-touching this file.
    await set_secret_scoped(session, db_key, value, organization_id=None)
    actor_id, actor_email = actor_from_auth(auth)
    # Privacy: never include the credential value or its preview in the
    # audit row.  We only record that a write happened for this integration.
    # Uses PR #21's canonical record_audit signature so the integration row
    # joins the same audit_events stream as role/allowlist/bot operations.
    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="integration.write",
        target_type="integration",
        target_id=name,
        outcome="success",
        safe_summary=f"credential set for integration={name}",
        request=request,
    )
    await session.commit()
    meta = INTEGRATION_META[name]
    return IntegrationStatus(
        name=name,
        label=meta["label"],
        description=meta["description"],
        placeholder=meta["placeholder"],
        docs_url=meta["docs_url"],
        configured=True,
        preview=mask_key(value),
        source="db",
    )


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    name: str,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: AsyncSession = SESSION_DEP,
) -> None:
    """Remove the stored credential for an integration."""
    if name not in INTEGRATION_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown integration '{name}'. Valid: {sorted(INTEGRATION_KEYS)}",
        )
    db_key = INTEGRATION_KEYS[name]
    # Sprint 6: scoped delete for forward compatibility with per-org isolation.
    await delete_secret_scoped(session, db_key, organization_id=None)
    actor_id, actor_email = actor_from_auth(auth)
    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="integration.delete",
        target_type="integration",
        target_id=name,
        outcome="success",
        safe_summary=f"credential cleared for integration={name}",
        request=request,
    )
    await session.commit()
