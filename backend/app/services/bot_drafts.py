"""Service helpers for ``BotDraft`` — slug normalization, secret-pattern
rejection, RT Bot placeholder seeding.

Privacy contract:
  • Free-text fields submitted by operators must not contain anything
    that looks like a secret.  ``reject_secret_like`` runs a small
    pattern check; matching values raise ``SecretLikeFieldError`` which
    the API turns into HTTP 400.
  • The placeholder RT Bot draft is intentionally empty of any platform
    credentials — it is metadata only, sandbox-only, and exists so the
    UI can render an entry while the live RT Bot work proceeds out-of-
    band on its own branch.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlmodel import select

from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.bot_draft import (
    DRAFT_STATUS_DRAFT,
    BotDraft,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = get_logger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,127}$")


# ── Secret-pattern rejection ────────────────────────────────────────────────

# Substrings that indicate the caller is trying to paste a real secret
# into a draft field.  The check is case-insensitive on the substring;
# the prefixed token patterns are matched case-sensitively because they
# correspond to actual provider tokens.
_SECRET_SUBSTRINGS: tuple[str, ...] = (
    "api_key",
    "api-key",
    "apikey",
    "secret",
    "password",
    "passwd",
    "bearer ",
    "authorization:",
    "auth_token",
    "session=",
    "session_token",
    "cookie:",
    "set-cookie",
    "webhook_url",
    "discord.com/api/webhooks/",
    "hooks.slack.com/",
    "hooks.zapier.com/",
    "private_key",
    "client_secret",
    "database_url",
    "postgres://",
    "postgresql://",
)

# Prefixes matching common token shapes.  These are case-sensitive.
_SECRET_PREFIXES: tuple[str, ...] = (
    "sk_live_",
    "sk_test_",
    "pk_live_",
    "rk_live_",
    "ghp_",
    "github_pat_",
    "xoxb-",
    "xoxp-",
    "AKIA",
    "ASIA",
    "Bearer ey",
    "eyJhbGciOi",  # JWT-ish opener
)


class SecretLikeFieldError(ValueError):
    """Raised when a caller-submitted field looks like a secret value."""

    def __init__(self, field: str, hint: str):
        self.field = field
        self.hint = hint
        super().__init__(
            f"Field '{field}' looks like a credential ({hint}). "
            "Bot drafts must not contain secrets, tokens, cookies, "
            "webhook URLs, or database URLs.",
        )


def _looks_like_secret(value: str) -> str | None:
    """Return a short reason if *value* looks credential-like, else None."""
    if not value:
        return None
    lower = value.lower()
    for needle in _SECRET_SUBSTRINGS:
        if needle in lower:
            return f"contains '{needle}'"
    for prefix in _SECRET_PREFIXES:
        if value.startswith(prefix) or f" {prefix}" in value or f"\n{prefix}" in value:
            return f"starts with '{prefix}'"
    return None


def reject_secret_like(field: str, value: str | None) -> None:
    """Raise ``SecretLikeFieldError`` if *value* looks credential-like."""
    if value is None:
        return
    hint = _looks_like_secret(value)
    if hint is not None:
        raise SecretLikeFieldError(field, hint)


def normalize_slug(slug: str) -> str:
    """Lowercase + validate a draft slug.  Raises ``ValueError`` on bad input."""
    cleaned = (slug or "").strip().lower()
    if not _SLUG_RE.match(cleaned):
        raise ValueError(
            "Slug must be 2-128 chars, lowercase letters/digits/'_'/'-', "
            "starting with a letter or digit.",
        )
    return cleaned


# ── Tools-needed JSON encode/decode ─────────────────────────────────────────


def encode_tools_needed(tools: Sequence[str] | None) -> str | None:
    if tools is None:
        return None
    cleaned = sorted({str(t).strip() for t in tools if str(t).strip()})
    if not cleaned:
        return None
    return json.dumps(cleaned)


def parse_tools_needed(json_text: str | None) -> list[str]:
    if not json_text:
        return []
    try:
        decoded = json.loads(json_text)
    except (TypeError, ValueError):
        return []
    if not isinstance(decoded, list):
        return []
    return [str(t) for t in decoded if isinstance(t, str)]


# ── Validation entry point used by the API ─────────────────────────────────


@dataclass(frozen=True)
class DraftFields:
    """All caller-supplied free-text fields, validated together."""

    name: str | None = None
    purpose: str | None = None
    category: str | None = None
    description: str | None = None
    owner: str | None = None
    trigger_type: str | None = None
    input_requirements: str | None = None
    output_requirements: str | None = None
    prompt_template: str | None = None
    dashboard_notes: str | None = None
    tools_needed: tuple[str, ...] | None = None


def validate_no_secrets(fields: DraftFields | Mapping[str, object]) -> None:
    """Run the secret-pattern check across every free-text field.

    Raises ``SecretLikeFieldError`` on first match so the operator gets
    a focused error message identifying which field tripped the rule.
    """
    if isinstance(fields, DraftFields):
        items: list[tuple[str, str | None]] = [
            ("name", fields.name),
            ("purpose", fields.purpose),
            ("category", fields.category),
            ("description", fields.description),
            ("owner", fields.owner),
            ("trigger_type", fields.trigger_type),
            ("input_requirements", fields.input_requirements),
            ("output_requirements", fields.output_requirements),
            ("prompt_template", fields.prompt_template),
            ("dashboard_notes", fields.dashboard_notes),
        ]
        for field, value in items:
            reject_secret_like(field, value)
        for tool in fields.tools_needed or ():
            reject_secret_like("tools_needed", tool)
        return

    for mapping_field, mapping_value in fields.items():
        if isinstance(mapping_value, str):
            reject_secret_like(mapping_field, mapping_value)
        elif isinstance(mapping_value, list):
            for v in mapping_value:
                if isinstance(v, str):
                    reject_secret_like(mapping_field, v)


# ── RT Bot placeholder seed ────────────────────────────────────────────────


RT_BOT_SLUG = "rt_bot"


async def bootstrap_seed(session: "AsyncSession", *, actor: str = "system") -> int:
    """Seed the placeholder RT Bot draft if it does not already exist.

    Idempotent — existing rows are not overwritten so any owner edits
    survive restarts (mirrors ``bot_registry.bootstrap_seed``).
    """
    result = await session.exec(select(BotDraft).where(BotDraft.slug == RT_BOT_SLUG))
    if result.first() is not None:
        return 0
    now = utcnow()
    row = BotDraft(
        slug=RT_BOT_SLUG,
        name="RT Bot",
        purpose="Retweet and outreach operations bot.",
        category="growth",
        description=(
            "Placeholder draft — awaiting exported Claude cowork automation "
            "spec.  Sandbox-only.  Not connected to X/Twitter, AdsPower, "
            "PhantomBuster, or any browser automation."
        ),
        owner="founder",
        status=DRAFT_STATUS_DRAFT,
        sandbox_mode=True,
        risk_level="medium",
        approval_required=True,
        trigger_type="manual",
        input_requirements="(spec pending)",
        output_requirements="(spec pending)",
        prompt_template=None,
        dashboard_notes="Placeholder until live RT Bot is brought into Mission Control.",
        tools_needed_json=encode_tools_needed([]),
        created_by=actor,
        updated_by=actor,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    logger.info("[bot_drafts] seeded placeholder RT Bot draft")
    return 1
