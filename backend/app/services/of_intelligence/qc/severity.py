"""QC alert severity model.

Severity controls publish behavior:
  • info / low  — counted only or rolled up; never ship as standalone alerts
  • medium      — ships in the next rollup window
  • high        — ships immediately, deduped within 5 min
  • critical    — ships immediately, no cooldown caps

Glyphs and embed colors are kept here so formatters and any future UI render
the same way without each module hard-coding their own palette.
"""

from __future__ import annotations

from enum import Enum


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def coerce(cls, value: str | "Severity") -> "Severity":
        if isinstance(value, cls):
            return value
        normalized = (value or "").strip().lower()
        # Tolerate the historical "warn" label used in alerts.py.
        if normalized == "warn":
            normalized = "medium"
        try:
            return cls(normalized)
        except ValueError:
            return cls.INFO


# First character of every Discord message — operators scan glyphs.
SEVERITY_GLYPH: dict[Severity, str] = {
    Severity.INFO: "🟦",
    Severity.LOW: "⬜",
    Severity.MEDIUM: "🟧",
    Severity.HIGH: "🟧",
    Severity.CRITICAL: "🟥",
}

# Discord embed color (decimal int). Reserved for future embed switch — text
# format does not need it but the constants belong with the rest.
SEVERITY_COLOR: dict[Severity, int] = {
    Severity.INFO: 0x4A90E2,
    Severity.LOW: 0x9B9B9B,
    Severity.MEDIUM: 0xF5A623,
    Severity.HIGH: 0xEB6E1A,
    Severity.CRITICAL: 0xD0021B,
}


def ships_immediately(severity: Severity) -> bool:
    return severity in (Severity.HIGH, Severity.CRITICAL)


def bypasses_cooldown(severity: Severity) -> bool:
    return severity is Severity.CRITICAL
