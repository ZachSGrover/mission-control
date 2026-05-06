"""QC alert formatters with allowlist-based field rendering.

The privacy contract for anything we publish to Discord is enforced here, not
at the call site.  Two layers of defense:

1. Structured input — `AlertPayload` exposes only fields that may render
   (account_username, chatter_name, code, severity, ordered facts, action,
   ref).  There is no "freeform body" field.
2. Output guard — `assert_privacy_safe()` scans the final rendered string for
   webhook URLs, Discord tokens, and any caller-supplied forbidden
   substrings (e.g. the fan handle from the source message).  If a
   misformatted template ever leaked PII into the output, this raises
   `PrivacyViolation` before the publisher sends.

Forbidden in any output, always:
  • Discord webhook URLs and bot tokens
  • Fan handles, message bodies, OnlyMonster message_ids
  • Raw API response bodies
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.services.of_intelligence.qc.severity import SEVERITY_GLYPH, Severity

# Hard cap so a runaway facts list can't fill the channel.  Discord's content
# limit is 2000; we stay well under to leave room for retries / quote escaping.
MAX_MESSAGE_CHARS = 600
MAX_TITLE_CHARS = 120
MAX_VALUE_CHARS = 80
MAX_ACTION_CHARS = 160

# Discord webhook URLs in any of the documented forms.
_WEBHOOK_URL_PATTERN = re.compile(
    r"https?://(?:discord(?:app)?\.com|ptb\.discord\.com|canary\.discord\.com)"
    r"/api/(?:v\d+/)?webhooks/\d+/[\w-]+",
    re.IGNORECASE,
)
# Discord bot tokens (3 base64url segments separated by dots, last segment ≥27).
_DISCORD_TOKEN_PATTERN = re.compile(
    r"\b[A-Za-z0-9_-]{24,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{27,}\b"
)


class PrivacyViolation(RuntimeError):
    """Raised when a rendered alert would leak a forbidden value."""


@dataclass(frozen=True)
class AlertPayload:
    """Allowlisted fields that may render to Discord.

    Anything not in this dataclass cannot reach the publisher.  Callers must
    pre-resolve display names (e.g. account.username, chatter.name) — raw
    source ids are accepted but never fan handles or message bodies.
    """

    severity: Severity
    code: str
    title: str
    account_username: str | None = None
    chatter_name: str | None = None
    facts: tuple[tuple[str, str], ...] = ()
    action: str | None = None
    ref: str | None = None


@dataclass(frozen=True)
class RolledUpPayload:
    """Single-message rollup for medium/low chatter findings."""

    severity: Severity
    window_label: str  # e.g. "last 30 min"
    total_findings: int
    chatter_count: int
    account_count: int
    lines: tuple[str, ...] = ()  # already-formatted, privacy-safe
    action: str | None = None
    refs: tuple[str, ...] = ()  # alert/finding ref ids
    title: str = "Chatter QC"


# ── Truncation helpers ───────────────────────────────────────────────────────


def _trim(value: str, limit: int) -> str:
    value = (value or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(limit - 1, 0)].rstrip() + "…"


# ── Formatters ───────────────────────────────────────────────────────────────


def format_alert(payload: AlertPayload) -> str:
    """Render a single QC alert to plain text suitable for Discord."""
    glyph = SEVERITY_GLYPH.get(payload.severity, "🟦")
    lines: list[str] = [f"{glyph} [QC] {_trim(payload.title, MAX_TITLE_CHARS)}"]

    if payload.account_username:
        lines.append(f"Account: {_trim(payload.account_username, MAX_VALUE_CHARS)}")
    if payload.chatter_name:
        lines.append(f"Chatter: {_trim(payload.chatter_name, MAX_VALUE_CHARS)}")
    for label, value in payload.facts:
        if not label or value is None or value == "":
            continue
        lines.append(f"{_trim(str(label), 32)}: {_trim(str(value), MAX_VALUE_CHARS)}")
    if payload.action:
        lines.append(f"Action: {_trim(payload.action, MAX_ACTION_CHARS)}")
    if payload.ref:
        lines.append(f"Ref: {_trim(payload.ref, 64)}")

    rendered = "\n".join(lines)
    if len(rendered) > MAX_MESSAGE_CHARS:
        rendered = rendered[: MAX_MESSAGE_CHARS - 1].rstrip() + "…"
    return rendered


def format_rollup(payload: RolledUpPayload) -> str:
    """Render a windowed digest of grouped chatter findings."""
    glyph = SEVERITY_GLYPH.get(payload.severity, "🟧")
    header = f"{glyph} [QC] {_trim(payload.title, MAX_TITLE_CHARS)} — {payload.window_label}"
    summary = (
        f"{payload.total_findings} issues across "
        f"{payload.chatter_count} chatter(s), {payload.account_count} account(s)"
    )
    out: list[str] = [header, summary]
    for line in payload.lines:
        out.append(f"• {_trim(line, MAX_VALUE_CHARS + 40)}")
    if payload.action:
        out.append(f"Action: {_trim(payload.action, MAX_ACTION_CHARS)}")
    if payload.refs:
        out.append("Refs: " + ", ".join(_trim(r, 32) for r in payload.refs[:8]))

    rendered = "\n".join(out)
    if len(rendered) > MAX_MESSAGE_CHARS:
        rendered = rendered[: MAX_MESSAGE_CHARS - 1].rstrip() + "…"
    return rendered


# ── Privacy guard ────────────────────────────────────────────────────────────


def assert_privacy_safe(
    text: str,
    *,
    forbidden_substrings: Iterable[str] = (),
) -> None:
    """Raise PrivacyViolation if the rendered text would leak a forbidden value.

    Pattern checks always run.  Callers should pass `forbidden_substrings` for
    any caller-known sensitive values (fan handles, message bodies, message
    ids).  An empty or whitespace-only substring is ignored — otherwise
    ``"" in text`` would always match.
    """
    if _WEBHOOK_URL_PATTERN.search(text):
        raise PrivacyViolation("rendered output contains a Discord webhook URL")
    if _DISCORD_TOKEN_PATTERN.search(text):
        raise PrivacyViolation("rendered output contains a Discord bot token")
    for substr in forbidden_substrings:
        if substr and substr.strip() and substr in text:
            raise PrivacyViolation(
                f"rendered output contains forbidden substring (len={len(substr)})"
            )
