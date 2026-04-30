"""Schema definitions for the Hermes diagnostic alert UI.

Read-only models that mirror the JSON written by ``scripts/hermes-alert.sh``
to ``$MC_STATE_DIR/alerts/<alert_id>.json``. The backend never writes to the
alert state directory; this module is only for surfacing what's already on
disk to the Mission Control UI.
"""

from __future__ import annotations

from typing import Literal

from sqlmodel import SQLModel

Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
AlertStatus = Literal[
    "healthy",
    "degraded",
    "failed",
    "blocked",
    "rate_limited",
    "disconnected",
    "unknown",
    "resolved",
]


class HermesIncident(SQLModel):
    """One Hermes alert as surfaced to the UI."""

    alert_id: str
    system: str
    status: AlertStatus
    severity: Severity
    exact_issue: str
    evidence: list[str]
    likely_cause: str
    business_impact: str
    recommended_fix: str
    claude_prompt: str
    timestamp: str | None = None
    last_fired_at_unix: int | None = None
    failure_count: int | None = None
    first_seen: str | None = None
    resolved_at: str | None = None


class HermesSystemStatus(SQLModel):
    """Current health snapshot for one monitored system."""

    name: str
    status: AlertStatus
    severity: Severity | None = None
    last_alert_id: str | None = None
    last_alert_at: str | None = None
    note: str | None = None


class HermesStatus(SQLModel):
    """Overview-page payload."""

    overall: AlertStatus
    summary: str
    systems: list[HermesSystemStatus]
    active_incident_count: int
    repeated_incident_count: int
    last_alert: HermesIncident | None = None
    last_resolved: HermesIncident | None = None
    state_dir_present: bool
    parse_warnings: int


class HermesIncidentList(SQLModel):
    """List endpoint payload — keeps room for paging or warnings later."""

    incidents: list[HermesIncident]
    parse_warnings: int


class HermesRepairPlan(SQLModel):
    """Read-only repair plan derived from an incident."""

    alert_id: str
    repair_mode: Literal["manual", "advisory"]
    inspect_checklist: list[str]
    recommended_next_action: str
    claude_prompt: str
    approval_required: bool
    blocked_actions: list[str]
    rollback_notes: str


class HermesSafetyRules(SQLModel):
    """Static safety-rules payload for the Safety page."""

    auto_inspect: str
    auto_restart: str
    auto_commit: str
    auto_push: str
    auto_deploy: str
    secret_rotation: str
    database_writes: str
    onlyfans_writes: str
    onlymonster_writes: str
    browser_automation: str
    restarts: str
