"""QC findings — append-only per-message detector hits.

Each detector that matches a single message writes one row here.  The rollup
engine groups findings by (chatter, code, account) over a window and
emits one Discord rollup alert when thresholds are crossed.  Findings
remain in the table for the dashboard.

This is Layer 2 (Business QC Assistant) infrastructure — distinct from
``of_intelligence_alerts`` which carries the higher-signal individual /
critical alerts (Layer 1 system health + Phase 1 critical QC risks).

Privacy: only privacy-safe fields are stored (no body, no fan handle).
``message_source_id`` is the OnlyMonster message id — kept as an internal
reference for the dashboard but never rendered in Discord.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Index
from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class OfIntelligenceQcFinding(SQLModel, table=True):
    """One detector hit on one message.  Append-only."""

    __tablename__ = "of_intelligence_qc_findings"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        Index("ix_ofi_qcf_code_created", "code", "created_at"),
        Index("ix_ofi_qcf_chatter_code", "chatter_source_id", "code"),
        Index("ix_ofi_qcf_account", "account_source_id"),
        Index("ix_ofi_qcf_rolled", "rolled_up_at"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    code: str = Field(max_length=64, index=True)
    severity: str = Field(max_length=16)
    account_source_id: str | None = Field(default=None, max_length=255)
    chatter_source_id: str | None = Field(default=None, max_length=255)
    message_source_id: str | None = Field(default=None, max_length=255)
    detection_phrase: str = Field(max_length=128)
    created_at: datetime = Field(default_factory=utcnow, index=True)
    rolled_up_at: datetime | None = Field(default=None, index=True)
    # Operator-review state — set when an owner marks the finding handled
    # in the dashboard.  Keeps the rollup loop unaffected (rolled_up_at
    # drives Discord ship dedup), but lets the dashboard filter open
    # vs. closed work.
    reviewed_at: datetime | None = Field(default=None, index=True)
    reviewed_by: str | None = Field(default=None, max_length=255)

    @property
    def dashboard_ref(self) -> str:
        """Stable reference string safe to render anywhere — never leaks
        the raw UUID outside ``qc/finding/`` namespace."""
        return f"qc/finding/{self.id}"
