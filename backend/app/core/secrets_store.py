"""Runtime secrets store: encrypted API keys persisted in the database.

Keys are encrypted with Fernet symmetric encryption.

Encryption key priority (most stable to least stable):
  1. SETTINGS_ENCRYPTION_KEY env var — a dedicated 32+ char hex string you set
     once and never rotate. This is the safest option. Generate with:
       python3 -c "import secrets; print(secrets.token_hex(32))"
  2. LOCAL_AUTH_TOKEN — used as fallback when SETTINGS_ENCRYPTION_KEY is absent.
  3. CLERK_SECRET_KEY — last resort when neither above is set.

IMPORTANT: If you change option 2 or 3 without setting option 1, previously
stored keys become unreadable. Re-save them in Settings → API Keys.
Set SETTINGS_ENCRYPTION_KEY once to decouple encryption from auth credentials.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Supported providers ──────────────────────────────────────────────────────

PROVIDER_KEYS: dict[str, str] = {
    "openai": "api_key.openai",
    "gemini": "api_key.gemini",
    "anthropic": "api_key.anthropic",
}

# Admin / billing keys used only by the Usage Tracker collectors.  Separate
# from the inference keys above — admin keys can read org-wide usage/cost
# but are not interchangeable with regular API keys.
ADMIN_PROVIDER_KEYS: dict[str, str] = {
    "openai": "admin_key.openai",
    "anthropic": "admin_key.anthropic",
}

GITHUB_KEYS: dict[str, str] = {
    "github_username": "github.username",
    "github_pat": "github.pat",
    "github_repo": "github.repo",
}

# ── Fernet helpers ───────────────────────────────────────────────────────────

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        import os

        from app.core.config import settings

        # Priority 1: dedicated encryption key — immune to auth credential rotation.
        dedicated = os.environ.get("SETTINGS_ENCRYPTION_KEY", "").strip()
        if dedicated:
            source = dedicated.encode()
        else:
            # Priority 2/3: derive from auth credential (rotation-sensitive).
            source = (settings.local_auth_token or settings.clerk_secret_key).encode()

        if not source:
            raise RuntimeError(
                "secrets_store: no encryption seed available. "
                "Set SETTINGS_ENCRYPTION_KEY, LOCAL_AUTH_TOKEN, or CLERK_SECRET_KEY."
            )

        key_bytes = hashlib.sha256(source).digest()
        fernet_key = base64.urlsafe_b64encode(key_bytes)
        _fernet = Fernet(fernet_key)
    return _fernet


def _encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str, *, db_key: str = "unknown") -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        logger.warning(
            "secrets_store: decrypt_failed key=%s — "
            "the encryption seed (CLERK_SECRET_KEY / LOCAL_AUTH_TOKEN) may have changed "
            "since this key was saved. Re-save the key in Settings → API Keys to fix.",
            db_key,
        )
        return ""


# ── Public interface ─────────────────────────────────────────────────────────


async def get_secret(session: AsyncSession, db_key: str, fallback: str = "") -> str:
    """Return the decrypted secret for *db_key*, or *fallback* if not stored.

    Priority: DB (decrypted) → fallback (ENV var passed by caller).
    Logs at DEBUG which source was used, and at WARNING when decryption fails.
    """
    from app.models.app_setting import AppSetting

    result = await session.exec(select(AppSetting).where(AppSetting.key == db_key))
    row = result.first()
    if row and row.value:
        decrypted = _decrypt(row.value, db_key=db_key)
        if decrypted:
            logger.debug("secrets_store: key_source=db key=%s", db_key)
            return decrypted
        # Decryption failed — fall through to ENV fallback below.

    if fallback.strip():
        logger.debug("secrets_store: key_source=env key=%s", db_key)
        return fallback.strip()

    logger.debug(
        "secrets_store: key_source=none key=%s — not in DB and no ENV fallback set",
        db_key,
    )
    return ""


async def get_secret_with_source(
    session: AsyncSession, db_key: str, fallback: str = ""
) -> tuple[str, str]:
    """Like get_secret but also returns the source: 'db' | 'env' | 'none'.

    Used by the settings status endpoint so the UI can show which source
    each key is coming from, making it easier to diagnose misconfigurations.
    """
    from app.models.app_setting import AppSetting

    result = await session.exec(select(AppSetting).where(AppSetting.key == db_key))
    row = result.first()
    if row and row.value:
        decrypted = _decrypt(row.value, db_key=db_key)
        if decrypted:
            return decrypted, "db"

    if fallback.strip():
        return fallback.strip(), "env"

    return "", "none"


async def set_secret(session: AsyncSession, db_key: str, plaintext: str) -> None:
    """Encrypt and upsert *plaintext* under *db_key*."""
    from app.core.time import utcnow
    from app.models.app_setting import AppSetting

    result = await session.exec(select(AppSetting).where(AppSetting.key == db_key))
    row = result.first()
    encrypted = _encrypt(plaintext)
    if row:
        row.value = encrypted
        row.updated_at = utcnow()
        session.add(row)
    else:
        session.add(AppSetting(key=db_key, value=encrypted))
    await session.commit()


async def delete_secret(session: AsyncSession, db_key: str) -> None:
    """Remove the stored secret for *db_key* (falls back to .env after this)."""
    from app.models.app_setting import AppSetting

    result = await session.exec(select(AppSetting).where(AppSetting.key == db_key))
    row = result.first()
    if row:
        await session.delete(row)
        await session.commit()


async def get_api_key(provider: str, session: AsyncSession, env_fallback: str = "") -> str:
    """Return the API key for *provider* — DB value takes priority over .env."""
    db_key = PROVIDER_KEYS.get(provider)
    if not db_key:
        return env_fallback
    return await get_secret(session, db_key, fallback=env_fallback.strip())


async def get_api_key_with_source(
    provider: str, session: AsyncSession, env_fallback: str = ""
) -> tuple[str, str]:
    """Return (key, source) for *provider* — source is 'db' | 'env' | 'none'."""
    db_key = PROVIDER_KEYS.get(provider)
    if not db_key:
        src = "env" if env_fallback.strip() else "none"
        return env_fallback.strip(), src
    return await get_secret_with_source(session, db_key, fallback=env_fallback.strip())


def mask_key(key: str) -> str | None:
    """Return a preview string suitable for display (never reveals the full key)."""
    if not key:
        return None
    visible = min(10, len(key))
    dots = min(24, max(4, len(key) - visible))
    return key[:visible] + "•" * dots
