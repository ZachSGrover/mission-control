"""Settings API — manage encrypted API keys at runtime without restart."""

from __future__ import annotations

from fastapi import (  # noqa: F401 (Depends used in param defaults)
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.mc_roles import require_owner
from app.core.auth import AuthContext, get_auth_context
from app.core.secrets_store import (
    GITHUB_KEYS,
    PROVIDER_KEYS,
    delete_secret,
    get_api_key_with_source,
    get_secret,
    get_secret_with_source,
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
    # "db" = stored encrypted in DB, "env" = read from environment variable, "none" = not set
    source: str = "none"


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
    value, source = await get_api_key_with_source(provider, session, env_fallback)
    configured = bool(value.strip())
    return ApiKeyStatus(
        configured=configured,
        preview=mask_key(value) if configured else None,
        source=source,
    )


@router.get("/api-keys", response_model=ApiKeysResponse)
async def get_api_keys(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ApiKeysResponse:
    """Return configuration status (not the raw keys) for all API providers."""
    from app.core.config import settings

    openai_status = await _load_status("openai", session, settings.openai_api_key)
    gemini_status = await _load_status("gemini", session, settings.gemini_api_key)
    # BUG FIX: was hardcoded "" — now correctly passes settings.anthropic_api_key as fallback
    anthropic_status = await _load_status("anthropic", session, settings.anthropic_api_key)

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
    _role: str = Depends(require_owner),
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
    _role: str = Depends(require_owner),
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


# ── GitHub credentials ────────────────────────────────────────────────────────


class GitHubFieldStatus(BaseModel):
    configured: bool
    preview: str | None = None


class GitHubStatusResponse(BaseModel):
    github_username: GitHubFieldStatus
    github_pat: GitHubFieldStatus
    github_repo: GitHubFieldStatus


class SetGitHubFieldRequest(BaseModel):
    value: str


@router.get("/github", response_model=GitHubStatusResponse)
async def get_github_settings(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> GitHubStatusResponse:
    """Return configuration status of GitHub credentials."""
    from app.core.config import settings as app_settings

    results: dict[str, GitHubFieldStatus] = {}
    env_fallbacks = {
        "github_username": app_settings.github_username,
        "github_pat": app_settings.github_pat,
        "github_repo": app_settings.github_repo,
    }
    for field, db_key in GITHUB_KEYS.items():
        value = await get_secret(session, db_key, fallback=env_fallbacks[field])
        configured = bool(value.strip())
        # PAT is masked; username/repo shown as-is (not sensitive)
        if configured:
            preview = mask_key(value) if field == "github_pat" else value
        else:
            preview = None
        results[field] = GitHubFieldStatus(configured=configured, preview=preview)

    return GitHubStatusResponse(**results)


@router.put("/github/{field}", response_model=GitHubFieldStatus)
async def upsert_github_field(
    field: str,
    body: SetGitHubFieldRequest,
    _: AuthContext = AUTH_DEP,
    _role: str = Depends(require_owner),
    session: AsyncSession = SESSION_DEP,
) -> GitHubFieldStatus:
    """Save a GitHub credential field. Takes effect immediately."""
    if field not in GITHUB_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown field '{field}'. Valid: {sorted(GITHUB_KEYS)}",
        )
    value = body.value.strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Value must not be empty.",
        )
    db_key = GITHUB_KEYS[field]
    await set_secret(session, db_key, value)
    preview = mask_key(value) if field == "github_pat" else value
    return GitHubFieldStatus(configured=True, preview=preview)


@router.delete("/github/{field}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_github_field(
    field: str,
    _: AuthContext = AUTH_DEP,
    _role: str = Depends(require_owner),
    session: AsyncSession = SESSION_DEP,
) -> None:
    """Remove a stored GitHub credential (reverts to .env fallback if set)."""
    if field not in GITHUB_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown field '{field}'. Valid: {sorted(GITHUB_KEYS)}",
        )
    db_key = GITHUB_KEYS[field]
    await delete_secret(session, db_key)
