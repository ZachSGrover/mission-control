"""Kill-switch row.

One DB row per active or formerly-active kill switch. The row exists
whenever the switch has *ever* been toggled — toggling it off updates
``enabled=False`` and ``disabled_at`` rather than deleting the row, so
the history is preserved.

Lookup contract:
- Global switch: ``scope="global"``, ``scope_id=None``.
- Connector switch: ``scope="connector"``, ``scope_id=connector_type``.
- Organization switch: ``scope="organization"``, ``scope_id=str(org.id)``.
- Creator switch: ``scope="creator"``, ``scope_id=creator_id``.

A switch is "active" iff ``enabled=True``. The matching service
function (``app.services.kill_switch.is_active``) treats a missing row
as **not active** but performs the safest superset check for any given
action (e.g. a creator action checks global + connector + org + creator
switches all at once and blocks if any of them is active).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlmodel import Field

from app.core.time import utcnow
from app.models.base import QueryModel

KILL_SWITCH_SCOPES: frozenset[str] = frozenset(
    {"global", "organization", "creator", "connector"},
)


class KillSwitch(QueryModel, table=True):
    """Per-scope kill switch state."""

    __tablename__ = "kill_switches"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    scope: str = Field(index=True)
    # Stored as plain string for cross-type compatibility (UUIDs / connector
    # type names / creator-id strings all flow through the same column).
    # ``None`` for the global switch.
    scope_id: str | None = Field(default=None, index=True)

    enabled: bool = Field(default=False, index=True)
    reason: str | None = Field(default=None)

    enabled_by_user_id: UUID | None = Field(default=None)
    enabled_by_email: str | None = Field(default=None)
    disabled_by_user_id: UUID | None = Field(default=None)
    disabled_by_email: str | None = Field(default=None)

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow, index=True)
    disabled_at: datetime | None = Field(default=None)
