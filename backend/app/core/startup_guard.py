"""Startup-time security guardrail.

Sprint 3 hardening: in production, the application refuses to come up
without a dedicated ``SETTINGS_ENCRYPTION_KEY``. This closes the worst
shape of risk R2 (audit-doc) where a misconfigured prod instance would
silently fall back to encrypting under the auth token, then become
unreadable on the next auth-secret rotation.

Local / dev / test still allows the fallback for ergonomic reasons —
the guard is environment-aware.
"""

from __future__ import annotations

from app.core.config import settings as app_settings
from app.core.logging import get_logger
from app.core.secrets_store import is_dedicated_encryption_key_configured

logger = get_logger(__name__)


class InsecureProductionStartupError(RuntimeError):
    """Raised when production starts without a dedicated encryption key."""


# Environments treated as "production-like" for the purpose of this
# guard. Anything else (``dev``, ``test``, ``local``, etc.) is allowed
# to fall back to the auth-token seed.
PRODUCTION_ENVIRONMENTS: frozenset[str] = frozenset({"production", "prod"})


def is_production() -> bool:
    return app_settings.environment.lower() in PRODUCTION_ENVIRONMENTS


def assert_production_encryption_configured() -> None:
    """Refuse to proceed if production is missing the dedicated encryption key.

    Raises :class:`InsecureProductionStartupError` with a message that
    does **not** include any actual key value (it can't — it has none
    to log).
    """
    if not is_production():
        return
    if is_dedicated_encryption_key_configured():
        return
    msg = (
        "InsecureProductionStartupError: ENVIRONMENT is "
        f"'{app_settings.environment}' but SETTINGS_ENCRYPTION_KEY is "
        "not set. Refusing to start. Generate a dedicated 32-hex value "
        'with `python3 -c "import secrets; print(secrets.token_hex(32))"` '
        "and set it in the production environment."
    )
    # The logger.warning here is the only output — never the key value.
    logger.warning("startup_guard.refused environment=%s", app_settings.environment)
    raise InsecureProductionStartupError(msg)
