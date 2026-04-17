"""Application settings and environment configuration loading."""

from __future__ import annotations

from pathlib import Path
from typing import Self
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.auth_mode import AuthMode
from app.core.rate_limit_backend import RateLimitBackend

BACKEND_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = BACKEND_ROOT / ".env"
LOCAL_AUTH_TOKEN_MIN_LENGTH = 50
LOCAL_AUTH_TOKEN_PLACEHOLDERS = frozenset(
    {
        "change-me",
        "changeme",
        "replace-me",
        "replace-with-strong-random-token",
    },
)


class Settings(BaseSettings):
    """Typed runtime configuration sourced from environment variables."""

    model_config = SettingsConfigDict(
        # Load `backend/.env` regardless of current working directory.
        # (Important when running uvicorn from repo root or via a process manager.)
        env_file=[DEFAULT_ENV_FILE, ".env"],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "dev"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/openclaw_agency"

    # Auth mode: "clerk" for Clerk JWT auth, "local" for shared bearer token auth.
    auth_mode: AuthMode
    local_auth_token: str = ""

    # Clerk auth (auth only; roles stored in DB)
    clerk_secret_key: str = ""
    clerk_api_url: str = "https://api.clerk.com"
    clerk_verify_iat: bool = True
    clerk_leeway: float = 10.0

    cors_origins: str = ""
    # Extra CORS origins to allow in addition to cors_origins (comma-separated).
    # Use this to add new domains (e.g. hq.digidle.com) without overwriting the
    # base CORS_ORIGINS env var.
    extra_cors_origins: str = ""
    base_url: str = ""
    # Frontend URL used for health-check CORS pings and Telegram webhook instructions.
    # Defaults to the first entry in cors_origins if not explicitly set.
    frontend_url: str = ""

    # Dedicated encryption key for API key storage — decouples secret persistence
    # from auth credentials.  If unset, falls back to LOCAL_AUTH_TOKEN / CLERK_SECRET_KEY.
    # Generate: python3 -c "import secrets; print(secrets.token_hex(32))"
    settings_encryption_key: str = ""

    # OpenAI integration (optional)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Gemini integration (optional)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Anthropic integration (optional — used for synthesis)
    anthropic_api_key: str = ""
    anthropic_synthesis_model: str = "claude-sonnet-4-5"

    # Security response headers (set to blank to disable a specific header)
    security_header_x_content_type_options: str = "nosniff"
    security_header_x_frame_options: str = "DENY"
    security_header_referrer_policy: str = "strict-origin-when-cross-origin"
    security_header_permissions_policy: str = ""

    # Webhook payload size limit in bytes (default 1 MB).
    webhook_max_payload_bytes: int = 1_048_576

    # Rate limiting
    rate_limit_backend: RateLimitBackend = RateLimitBackend.MEMORY
    rate_limit_redis_url: str = ""

    # Trusted reverse-proxy IPs/CIDRs for client-IP extraction from
    # Forwarded / X-Forwarded-For headers.  Comma-separated.
    # Leave empty to always use the direct peer address.
    trusted_proxies: str = ""

    # Database lifecycle
    db_auto_migrate: bool = False

    # RQ queueing / dispatch
    rq_redis_url: str = "redis://localhost:6379/0"
    rq_queue_name: str = "default"
    rq_dispatch_throttle_seconds: float = 15.0
    rq_dispatch_max_retries: int = 3
    rq_dispatch_retry_base_seconds: float = 10.0
    rq_dispatch_retry_max_seconds: float = 120.0

    # OpenClaw gateway runtime compatibility
    gateway_min_version: str = "2026.02.9"

    # GitHub save — enables one-click push from the Save button.
    # Add to backend/.env:
    #   GITHUB_PAT=ghp_yourtoken
    #   GITHUB_USERNAME=ZachSGrover
    #   GITHUB_REPO=ZachSGrover/mission-control
    github_pat: str = ""
    github_username: str = ""
    github_repo: str = ""

    # Mission Control RBAC — optional env-pinned owner.
    # When set, the clerk_user_id matching this value is always treated as owner
    # regardless of DB state.  Leave blank to use auto-seed (first caller) logic.
    owner_user_id: str = ""

    # Logging
    log_level: str = "INFO"
    log_format: str = "text"
    log_use_utc: bool = False
    request_log_slow_ms: int = Field(default=1000, ge=0)
    request_log_include_health: bool = False

    @model_validator(mode="after")
    def _defaults(self) -> Self:
        if self.auth_mode == AuthMode.CLERK:
            if not self.clerk_secret_key.strip():
                raise ValueError(
                    "CLERK_SECRET_KEY must be set and non-empty when AUTH_MODE=clerk.",
                )
        elif self.auth_mode == AuthMode.LOCAL:
            token = self.local_auth_token.strip()
            if (
                not token
                or len(token) < LOCAL_AUTH_TOKEN_MIN_LENGTH
                or token.lower() in LOCAL_AUTH_TOKEN_PLACEHOLDERS
            ):
                raise ValueError(
                    "LOCAL_AUTH_TOKEN must be at least 50 characters and non-placeholder when AUTH_MODE=local.",
                )

        base_url = self.base_url.strip()
        if not base_url:
            raise ValueError("BASE_URL must be set and non-empty.")
        parsed_base_url = urlparse(base_url)
        if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
            raise ValueError(
                "BASE_URL must be an absolute http(s) URL (e.g. http://localhost:8000).",
            )
        self.base_url = base_url.rstrip("/")

        # Rate-limit: fall back to rq_redis_url if using redis backend
        # with no explicit rate-limit URL. If both are blank, fail fast
        # with a clear configuration error.
        if (
            self.rate_limit_backend == RateLimitBackend.REDIS
            and not self.rate_limit_redis_url.strip()
        ):
            fallback_url = self.rq_redis_url.strip()
            if not fallback_url:
                raise ValueError(
                    "RATE_LIMIT_REDIS_URL or RQ_REDIS_URL must be set and non-empty "
                    "when RATE_LIMIT_BACKEND=redis.",
                )
            self.rate_limit_redis_url = fallback_url

        # In dev, default to applying Alembic migrations at startup to avoid
        # schema drift (e.g. missing newly-added columns).
        if "db_auto_migrate" not in self.model_fields_set and self.environment == "dev":
            self.db_auto_migrate = True
        return self


settings = Settings()
