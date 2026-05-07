"""Mission Control safety event log — append-only safety/kill-switch records.

Distinct from ``AuditEvent``: ``AuditEvent`` records *who did what* at a
privileged surface; ``SafetyEvent`` records *what tripped a safety
gate* (kill switch activated, duplicate-run prevention fired, MVP
live-write attempt blocked).  The two tables are correlated by
``run_id`` when the event is run-scoped.

Privacy contract:
  • ``description`` is a short coded reason — never raw error payloads,
    never message bodies, never credentials.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel

from app.core.time import utcnow

# Severity vocabulary.  Free-form column for forward-compat; current
# call sites stick to these three.
SAFETY_SEVERITY_INFO = "info"
SAFETY_SEVERITY_WARNING = "warning"
SAFETY_SEVERITY_CRITICAL = "critical"

VALID_SEVERITIES: frozenset[str] = frozenset(
    {SAFETY_SEVERITY_INFO, SAFETY_SEVERITY_WARNING, SAFETY_SEVERITY_CRITICAL}
)


class SafetyEvent(SQLModel, table=True):
    """One safety-gate trip on Mission Control's bot surface."""

    __tablename__ = "safety_events"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    run_id: UUID | None = Field(default=None, index=True)
    event_type: str = Field(index=True, max_length=64)
    severity: str = Field(default=SAFETY_SEVERITY_INFO, index=True, max_length=16)
    description: str = Field(max_length=512)
    resolved: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utcnow, index=True)


__all__ = [
    "SAFETY_SEVERITY_CRITICAL",
    "SAFETY_SEVERITY_INFO",
    "SAFETY_SEVERITY_WARNING",
    "SafetyEvent",
    "VALID_SEVERITIES",
]
