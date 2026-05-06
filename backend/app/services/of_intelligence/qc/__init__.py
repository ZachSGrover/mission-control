"""OF Intelligence — assistant QC subsystem.

Discord is the reporting channel; the product is QC monitoring.  Public
surface is intentionally narrow until the upstream detectors are wired in.
"""

from app.services.of_intelligence.qc.formatters import (
    AlertPayload,
    PrivacyViolation,
    RolledUpPayload,
    assert_privacy_safe,
    format_alert,
    format_rollup,
)
from app.services.of_intelligence.qc.publisher import (
    PublishResult,
    is_enabled,
    publish,
)
from app.services.of_intelligence.qc.severity import (
    SEVERITY_COLOR,
    SEVERITY_GLYPH,
    Severity,
    bypasses_cooldown,
    ships_immediately,
)

__all__ = [
    "AlertPayload",
    "PrivacyViolation",
    "PublishResult",
    "RolledUpPayload",
    "SEVERITY_COLOR",
    "SEVERITY_GLYPH",
    "Severity",
    "assert_privacy_safe",
    "bypasses_cooldown",
    "format_alert",
    "format_rollup",
    "is_enabled",
    "publish",
    "ships_immediately",
]
