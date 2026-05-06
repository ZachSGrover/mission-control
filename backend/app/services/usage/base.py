"""Common collector contract shared across provider-specific implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

CollectorStatus = Literal["ok", "error", "not_configured"]
CollectorSource = Literal["live", "manual", "placeholder"]


@dataclass
class CollectorResult:
    """Outcome of one provider snapshot fetch.

    Always returned — never raises.  Errors are captured in ``error`` so the
    orchestrator can persist a snapshot row marked ``status="error"`` for the
    UI to display.

    A collector with no admin credentials configured returns
    ``status="not_configured"`` and ``source="placeholder"`` so the user gets
    a clear "set up an admin key" message instead of a silent zero.
    """

    provider: str
    status: CollectorStatus = "not_configured"
    source: CollectorSource = "placeholder"
    period_start: datetime | None = None
    period_end: datetime | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    requests: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    raw: str | None = None
    notes: list[str] = field(default_factory=list)
