"""Privacy mode design for the OF QC Discord publisher.

Three modes are *recognised*; only ``SAFE_SUMMARY`` is implemented today.
Any other mode falls back to Safe Summary at render time.  This module
keeps the surface stable so adding Internal Detail later is additive
instead of a rewrite.

Modes
-----

``SAFE_SUMMARY`` (default, current implementation)
  Discord shows: account display name, chatter name, category, severity,
  counts, timing, and dashboard ref.  No fan handles.  No message bodies.
  No raw API responses.  No tokens or webhook URLs (always forbidden by
  the privacy guard regardless of mode).

``INTERNAL_DETAIL`` (future, NOT YET ALLOWED at render time)
  Will require all four conditions before render is allowed:
    1. Operator-set ``privacy_mode == 'internal_detail'`` on the
       singleton ``of_qc_discord_status`` row.
    2. ``MC_OF_QC_DISCORD_INTERNAL_DETAIL_CHANNEL_OK=1`` env asserting
       the configured webhook points to a private owner-only channel.
    3. Caller-supplied excerpt cap (chars + sanitization rules).
    4. A green privacy-leak test suite covering: fan handle inclusion is
       opt-in, body is truncated + sanitized, no payment data, no raw
       API response, no PII.

  Until *all four* conditions are present, ``effective_mode()`` resolves
  to ``SAFE_SUMMARY`` even when the operator has flipped the toggle.
  This keeps the door open without ever shipping more detail than
  v1 promised.

``DASHBOARD_FULL`` (not a Discord mode)
  Reserved label for dashboard rendering — dashboard can show full
  internal context based on permissions.  Discord publisher MUST never
  resolve to this mode under any condition.
"""

from __future__ import annotations

import os
from enum import Enum

from app.core.logging import get_logger

logger = get_logger(__name__)


class PrivacyMode(str, Enum):
    SAFE_SUMMARY = "safe_summary"
    INTERNAL_DETAIL = "internal_detail"

    @classmethod
    def coerce(cls, value: str | "PrivacyMode" | None) -> "PrivacyMode":
        if isinstance(value, cls):
            return value
        if not value:
            return cls.SAFE_SUMMARY
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            return cls.SAFE_SUMMARY


_INTERNAL_DETAIL_CHANNEL_OK_ENV = "MC_OF_QC_DISCORD_INTERNAL_DETAIL_CHANNEL_OK"


def internal_detail_gate_open() -> bool:
    """Has the operator asserted the webhook points to a private channel?

    Internal Detail mode requires this in addition to the DB toggle.
    Currently always reads the env var; future versions can layer additional
    checks (per-webhook channel category lookup, etc.).
    """
    return (os.environ.get(_INTERNAL_DETAIL_CHANNEL_OK_ENV) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def effective_mode(
    *,
    requested: PrivacyMode | str | None,
    excerpt_cap: int | None = None,
) -> PrivacyMode:
    """Resolve the mode that the renderer is allowed to use *right now*.

    Returns ``SAFE_SUMMARY`` unless every condition for Internal Detail
    is satisfied.  Logs once when an operator-requested upgrade is
    refused so they can see why their config didn't take effect.
    """
    requested_mode = PrivacyMode.coerce(requested)
    if requested_mode is PrivacyMode.SAFE_SUMMARY:
        return PrivacyMode.SAFE_SUMMARY

    # Internal Detail requested.  Refuse until every gate is open.
    if not internal_detail_gate_open():
        logger.warning(
            "of_qc.privacy_mode.refused requested=%s reason=channel_gate_closed",
            requested_mode.value,
        )
        return PrivacyMode.SAFE_SUMMARY

    if excerpt_cap is None or excerpt_cap <= 0 or excerpt_cap > 80:
        logger.warning(
            "of_qc.privacy_mode.refused requested=%s reason=invalid_excerpt_cap",
            requested_mode.value,
        )
        return PrivacyMode.SAFE_SUMMARY

    # Internal Detail rendering itself isn't implemented in v1.  We log the
    # would-be unlock and still return Safe Summary.  When we add the
    # renderer, drop this final guard.
    logger.warning(
        "of_qc.privacy_mode.refused requested=%s reason=renderer_not_implemented",
        requested_mode.value,
    )
    return PrivacyMode.SAFE_SUMMARY
