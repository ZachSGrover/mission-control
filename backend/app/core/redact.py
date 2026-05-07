"""Metadata redaction for audit logs.

A small, paranoid helper used by :mod:`app.services.audit_log` to make
sure no caller accidentally writes a credential, token, or session
identifier into the ``audit_events.metadata_json`` column.

Why a custom redactor and not a third-party one?
- We want zero new dependencies on the audit-log path.
- The set of forbidden keys is small, hand-curated, and matches the
  vocabulary used elsewhere in this codebase.
- Failure mode must be loud at the call site, not silent.

Usage::

    safe, was_redacted = redact_metadata({"user": "alice", "token": "..."})
    # safe == {"user": "alice", "token": "[REDACTED]"}
    # was_redacted is True

Contracts:
- The original input is **not** mutated.
- Lists, tuples, sets, and dicts are walked recursively.
- Any key whose lower-cased name appears in :data:`FORBIDDEN_KEYS` (or
  matches one of :data:`FORBIDDEN_KEY_FRAGMENTS` as a substring) has its
  value replaced by ``"[REDACTED]"``.
- A value that itself looks like a leading-edge bearer/secret string
  (e.g. ``"Bearer eyJ…"``) is also redacted regardless of key, as a
  defence in depth against odd metadata shapes.
- If the resulting structure is over :data:`MAX_TOTAL_BYTES` once
  serialised to JSON, it is replaced by a small summary that records
  the original size — never the original payload.
"""

from __future__ import annotations

import json
from typing import Final

REDACTED_PLACEHOLDER: Final[str] = "[REDACTED]"

# Exact (case-insensitive) key matches.
FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "password",
        "token",
        "secret",
        "cookie",
        "session",
        "apikey",
        "api_key",
        "authorization",
        "bearer",
        "credential",
        "credentials",
        "privatekey",
        "private_key",
        "refreshtoken",
        "refresh_token",
        "accesstoken",
        "access_token",
        "clientsecret",
        "client_secret",
        "encryptionkey",
        "encryption_key",
    }
)

# Substring matches. Any key containing one of these (lower-cased) is
# treated as forbidden. Keeps us safe against ``user_password_hash``,
# ``oauth_access_token``, ``stripe_secret_key``, etc.
FORBIDDEN_KEY_FRAGMENTS: Final[tuple[str, ...]] = (
    "password",
    "secret",
    "token",
    "cookie",
    "apikey",
    "api_key",
    "authorization",
    "bearer ",  # only the prefix form, not e.g. "submarine"
    "private_key",
    "privatekey",
    "encryption_key",
    "encryptionkey",
    "client_secret",
    "clientsecret",
)

# Heuristic value-side checks (defence in depth).
# These catch values whose key was not blacklisted but whose content
# is clearly a credential.
_VALUE_PREFIXES: Final[tuple[str, ...]] = (
    "Bearer ",
    "bearer ",
    "Basic ",
)

# Large blob safety net. 16 KiB is plenty for an audit row metadata
# payload; anything larger is summarised, not stored.
MAX_TOTAL_BYTES: Final[int] = 16 * 1024
MAX_STRING_BYTES: Final[int] = 4 * 1024


def _is_forbidden_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in FORBIDDEN_KEYS:
        return True
    return any(frag in lowered for frag in FORBIDDEN_KEY_FRAGMENTS)


def _looks_like_credential_value(value: object) -> bool:
    if not isinstance(value, str):
        return False
    return any(value.startswith(p) for p in _VALUE_PREFIXES)


def _truncate_string(value: str) -> str:
    if len(value.encode("utf-8")) <= MAX_STRING_BYTES:
        return value
    return value[: MAX_STRING_BYTES // 2] + "…[truncated]"


class _RedactionState:
    """Mutable accumulator used during the single recursion pass."""

    __slots__ = ("redacted",)

    def __init__(self) -> None:
        self.redacted = False

    def mark(self) -> None:
        self.redacted = True


def _walk(value: object, state: _RedactionState) -> object:
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if _is_forbidden_key(key):
                state.mark()
                out[key] = REDACTED_PLACEHOLDER
                continue
            walked = _walk(raw_value, state)
            if _looks_like_credential_value(raw_value):
                state.mark()
                out[key] = REDACTED_PLACEHOLDER
            else:
                out[key] = walked
        return out

    if isinstance(value, list):
        return [_walk(item, state) for item in value]

    if isinstance(value, tuple):
        # Convert to list for JSON-friendliness; tuples have no JSON form.
        return [_walk(item, state) for item in value]

    if isinstance(value, set):
        return [_walk(item, state) for item in sorted(value, key=repr)]

    if isinstance(value, str):
        if _looks_like_credential_value(value):
            state.mark()
            return REDACTED_PLACEHOLDER
        return _truncate_string(value)

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    # Anything exotic — fall back to repr() truncated, never the raw object.
    return _truncate_string(repr(value))


def redact_metadata(payload: object) -> tuple[dict[str, object], bool]:
    """Return a redacted, JSON-safe copy of ``payload`` plus a "was anything
    redacted" flag.

    - The original ``payload`` is never mutated.
    - The returned structure is always a ``dict`` (top-level non-dict
      inputs are wrapped in ``{"value": ...}`` so audit storage keeps
      a stable shape).
    - If the redacted structure exceeds :data:`MAX_TOTAL_BYTES` once
      JSON-encoded, it is replaced by a tiny summary (never the
      original content).
    """

    state = _RedactionState()

    if isinstance(payload, dict):
        walked = _walk(payload, state)
        # _walk on a dict always returns a dict; this assertion narrows
        # the type for mypy.
        assert isinstance(walked, dict)
        result: dict[str, object] = walked
    else:
        wrapped = _walk(payload, state)
        result = {"value": wrapped}

    # Size cap (defence against metadata blobs becoming a covert channel).
    try:
        encoded = json.dumps(result, default=_truncate_string)
    except (TypeError, ValueError):
        return (
            {
                "value": REDACTED_PLACEHOLDER,
                "redaction_note": "metadata was not JSON-serialisable",
            },
            True,
        )

    if len(encoded.encode("utf-8")) > MAX_TOTAL_BYTES:
        return (
            {
                "value": REDACTED_PLACEHOLDER,
                "redaction_note": "metadata exceeded size cap",
                "original_byte_size": len(encoded.encode("utf-8")),
            },
            True,
        )

    return result, state.redacted
