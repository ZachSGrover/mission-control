"""Settings API — manage encrypted API keys at runtime without restart."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth import AuthContext, get_auth_context
from app.core.secrets_store import (
    PROVIDER_KEYS,
    delete_secret,
    get_secret,
    mask_key,
    set_secret,
)
from app.db.session import get_session

router = APIRouter(prefix="/settings", tags=["settings"])
AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)


class ApiKeyStatus(BaseModel):
    configured: bool
    preview: str | None = None


class ApiKeysResponse(BaseModel):
    openai: ApiKeyStatus
    gemini: ApiKeyStatus
    anthropic: ApiKeyStatus


class SetApiKeyRequest(BaseModel):
    key: str


async def _load_status(
    provider: str,
    session: AsyncSession,
    env_fallback: str,
) -> ApiKeyStatus:
    db_key = PROVIDER_KEYS[provider]
    value = await get_secret(session, db_key, fallback=env_fallback)
    configured = bool(value.strip())
    return ApiKeyStatus(configured=configured, preview=mask_key(value) if configured else None)


@router.get("/api-keys", response_model=ApiKeysResponse)
async def get_api_keys(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ApiKeysResponse:
    """Return configuration status (not the raw keys) for all API providers."""
    from app.core.config import settings

    openai_status = await _load_status("openai", session, settings.openai_api_key)
    gemini_status = await _load_status("gemini", session, settings.gemini_api_key)
    anthropic_status = await _load_status("anthropic", session, "")

    return ApiKeysResponse(
        openai=openai_status,
        gemini=gemini_status,
        anthropic=anthropic_status,
    )


@router.put("/api-keys/{provider}", response_model=ApiKeyStatus)
async def upsert_api_key(
    provider: str,
    body: SetApiKeyRequest,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ApiKeyStatus:
    """Save an API key for the given provider.  Takes effect immediately."""
    if provider not in PROVIDER_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider '{provider}'. Valid: {sorted(PROVIDER_KEYS)}",
        )
    key_value = body.key.strip()
    if not key_value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Key value must not be empty.",
        )
    db_key = PROVIDER_KEYS[provider]
    await set_secret(session, db_key, key_value)
    return ApiKeyStatus(configured=True, preview=mask_key(key_value))


@router.delete("/api-keys/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(
    provider: str,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> None:
    """Remove the stored API key for the given provider (reverts to .env if set)."""
    if provider not in PROVIDER_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown provider '{provider}'. Valid: {sorted(PROVIDER_KEYS)}",
        )
    db_key = PROVIDER_KEYS[provider]
    await delete_secret(session, db_key)
