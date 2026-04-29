"""Read-only Hermes diagnostic alert endpoints.

Surfaces the JSON state files written by ``scripts/hermes-alert.sh`` to
``$MC_STATE_DIR/alerts/`` so the Mission Control UI can render incidents,
repair plans, and an overview.

This router never writes alert state, never sends notifications, never
restarts services, and never reads ``~/.hermes/.env``. It only reads the
alert state directory and renders what's there.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_org_admin
from app.schemas.hermes import (
    HermesIncident,
    HermesIncidentList,
    HermesRepairPlan,
    HermesSafetyRules,
    HermesStatus,
    HermesSystemStatus,
)
from app.services.organizations import OrganizationContext

router = APIRouter(prefix="/hermes", tags=["hermes"])

ORG_ADMIN_DEP = Depends(require_org_admin)


# ── Configuration ────────────────────────────────────────────────────────────
def _alerts_dir() -> Path:
    """Resolve the Hermes alert state directory.

    Honours ``MC_STATE_DIR`` from the environment (matching the shell library)
    and falls back to ``/tmp/mc-system``. Always returns the ``alerts/``
    subdirectory regardless of whether it exists; callers must check.
    """

    base = os.environ.get("MC_STATE_DIR") or "/tmp/mc-system"
    return Path(base) / "alerts"


# ── Loading + parsing ────────────────────────────────────────────────────────
def _load_one(path: Path) -> tuple[HermesIncident | None, bool]:
    """Parse a single alert state file. Returns (incident, parse_failed)."""

    try:
        raw = json.loads(path.read_text())
    except Exception:
        return None, True

    # State files written by --check-dedupe are wrapped:
    #   {"last_fired_at": <unix>, "alert": {...}}
    # State files written by templates without dedupe are bare alert dicts.
    if isinstance(raw, dict) and "alert" in raw and isinstance(raw["alert"], dict):
        alert = raw["alert"]
        last_fired = raw.get("last_fired_at")
        last_fired_unix = (
            int(last_fired) if isinstance(last_fired, (int, float)) else None
        )
    elif isinstance(raw, dict):
        alert = raw
        last_fired_unix = None
    else:
        return None, True

    try:
        return (
            HermesIncident(
                alert_id=str(alert.get("alert_id") or path.stem),
                system=str(alert.get("system") or "Unknown system"),
                status=str(alert.get("status") or "unknown"),  # type: ignore[arg-type]
                severity=str(alert.get("severity") or "MEDIUM"),  # type: ignore[arg-type]
                exact_issue=str(alert.get("exact_issue") or ""),
                evidence=list(alert.get("evidence") or []),
                likely_cause=str(alert.get("likely_cause") or ""),
                business_impact=str(alert.get("business_impact") or ""),
                recommended_fix=str(alert.get("recommended_fix") or ""),
                claude_prompt=str(alert.get("claude_prompt") or ""),
                timestamp=alert.get("timestamp"),
                last_fired_at_unix=last_fired_unix,
                failure_count=alert.get("failure_count"),
                first_seen=alert.get("first_seen"),
                resolved_at=alert.get("resolved_at"),
            ),
            False,
        )
    except Exception:
        return None, True


def _load_all() -> tuple[list[HermesIncident], int, bool]:
    """Read every alert state file in MC_STATE_DIR/alerts.

    Returns ``(incidents, parse_warnings, dir_present)``. Sorted newest first
    by ``last_fired_at_unix`` (falling back to filesystem mtime).
    """

    d = _alerts_dir()
    if not d.is_dir():
        return [], 0, False

    incidents: list[HermesIncident] = []
    warnings = 0
    for entry in sorted(d.glob("*.json")):
        if entry.name.endswith(".tmp"):
            continue
        incident, failed = _load_one(entry)
        if failed:
            warnings += 1
            continue
        if incident is not None:
            incidents.append(incident)

    incidents.sort(
        key=lambda inc: (inc.last_fired_at_unix or 0),
        reverse=True,
    )
    return incidents, warnings, True


# ── Overview helpers ─────────────────────────────────────────────────────────
SEVERITY_RANK: dict[str, int] = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}

# The systems we always surface on the overview page, even when no alert has
# ever fired for them. Maps display name to a synthetic "no recent issues"
# fallback note.
DEFAULT_SYSTEMS: list[str] = [
    "OpenClaw Gateway",
    "Mission Control Backend",
    "Mission Control Frontend",
    "Postgres Database",
    "Redis",
    "Discord Bot (Hermes notify path)",
    "Telegram Bot (Hermes notify path)",
    "Local Machine",
]


def _is_active(incident: HermesIncident) -> bool:
    """An incident counts as 'active' if its last status was a failure mode."""

    return incident.status in {
        "failed",
        "degraded",
        "blocked",
        "disconnected",
        "rate_limited",
        "unknown",
    }


def _build_systems(incidents: list[HermesIncident]) -> list[HermesSystemStatus]:
    """Pick the most-recent incident per system; fill in the defaults."""

    by_system: dict[str, HermesIncident] = {}
    for inc in incidents:  # already newest-first
        if inc.system not in by_system:
            by_system[inc.system] = inc

    out: list[HermesSystemStatus] = []
    seen: set[str] = set()
    for name in DEFAULT_SYSTEMS:
        seen.add(name)
        most_recent = by_system.get(name)
        if most_recent is None:
            out.append(
                HermesSystemStatus(
                    name=name,
                    status="healthy",
                    note="no recent alert state recorded",
                )
            )
        else:
            out.append(
                HermesSystemStatus(
                    name=name,
                    status=most_recent.status,
                    severity=most_recent.severity,
                    last_alert_id=most_recent.alert_id,
                    last_alert_at=most_recent.timestamp,
                    note=None,
                )
            )

    # Surface any system Hermes saw that isn't in the default list.
    for name, inc in by_system.items():
        if name in seen:
            continue
        out.append(
            HermesSystemStatus(
                name=name,
                status=inc.status,
                severity=inc.severity,
                last_alert_id=inc.alert_id,
                last_alert_at=inc.timestamp,
                note=None,
            )
        )

    return out


def _summarize(
    *,
    active: list[HermesIncident],
    overall: str,
    state_dir_present: bool,
) -> str:
    """One-line founder summary."""

    if not state_dir_present:
        return (
            "No Hermes alert state directory found yet. Once a watchdog fires "
            "an alert, incident state will appear here."
        )
    if not active:
        return "All monitored Hermes systems are healthy or have no active incidents."
    crit = sum(1 for i in active if i.severity == "CRITICAL")
    high = sum(1 for i in active if i.severity == "HIGH")
    parts: list[str] = []
    if crit:
        parts.append(f"{crit} CRITICAL")
    if high:
        parts.append(f"{high} HIGH")
    rest = len(active) - crit - high
    if rest > 0:
        parts.append(f"{rest} other")
    return f"{len(active)} active incident(s): " + ", ".join(parts) + "."


# ── Endpoints ────────────────────────────────────────────────────────────────
@router.get("/status", response_model=HermesStatus)
async def get_status(_ctx: OrganizationContext = ORG_ADMIN_DEP) -> HermesStatus:
    """Overview-page payload."""

    incidents, warnings, dir_present = _load_all()
    active = [i for i in incidents if _is_active(i)]
    repeated = [i for i in active if (i.failure_count or 0) >= 3]

    if not dir_present or not incidents:
        overall: str = "healthy"
    elif any(i.severity == "CRITICAL" for i in active):
        overall = "failed"
    elif any(i.severity == "HIGH" for i in active):
        overall = "degraded"
    elif active:
        overall = "degraded"
    else:
        overall = "healthy"

    last_alert = incidents[0] if incidents else None
    last_resolved = next(
        (i for i in incidents if i.status == "resolved"),
        None,
    )

    return HermesStatus(
        overall=overall,  # type: ignore[arg-type]
        summary=_summarize(
            active=active,
            overall=overall,
            state_dir_present=dir_present,
        ),
        systems=_build_systems(incidents),
        active_incident_count=len(active),
        repeated_incident_count=len(repeated),
        last_alert=last_alert,
        last_resolved=last_resolved,
        state_dir_present=dir_present,
        parse_warnings=warnings,
    )


@router.get("/incidents", response_model=HermesIncidentList)
async def list_incidents(
    _ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> HermesIncidentList:
    """All incident state files, newest first."""

    incidents, warnings, _ = _load_all()
    return HermesIncidentList(incidents=incidents, parse_warnings=warnings)


# ── Repair plan ──────────────────────────────────────────────────────────────
_INSPECT_LINE = re.compile(r"^\s*\d+\.\s*(.+?)\s*$")

# System → blocked actions hard-coded for the v1 read-only Repair Center.
# Any action listed here is *forbidden* by safety rules; the UI shows them as
# disabled so the operator can read but not click.
BLOCKED_ACTIONS_BY_SYSTEM: dict[str, list[str]] = {
    "OpenClaw Gateway": [
        "regenerate gateway auth token",
        "modify cloudflared / Cloudflare Access",
        "restart backend or frontend",
    ],
    "Mission Control Backend": [
        "run database migrations",
        "modify auth provider / Clerk",
        "redeploy production",
    ],
    "Mission Control Frontend": [
        "skip type checks",
        "force-deploy a broken build",
        "modify backend or auth",
    ],
    "Postgres Database": [
        "drop or truncate tables",
        "run migrations",
        "modify Redis or backend code",
    ],
    "Redis": [
        "modify Redis config",
        "modify Postgres",
        "redeploy services",
    ],
    "Discord Bot (Hermes notify path)": [
        "print or paste bot token",
        "modify Telegram path",
    ],
    "Telegram Bot (Hermes notify path)": [
        "print or paste bot token",
        "modify Discord path",
    ],
    "Local Machine": [
        "redeploy or rebuild",
        "restart services that are already healthy",
    ],
}


def _inspect_checklist(claude_prompt: str) -> list[str]:
    """Best-effort extraction of the numbered Inspect block in a repair prompt.

    Templates write prompts in the form:
        Inspect:
          1. ...
          2. ...
        Fix the root cause...

    We pull the numbered lines under the ``Inspect:`` heading. If the prompt
    doesn't follow that shape we return an empty list.
    """

    lines = claude_prompt.splitlines()
    out: list[str] = []
    started = False
    for line in lines:
        if not started:
            # Templates write "<system> is down. Inspect:" — the word
            # appears mid-sentence, not at the start of a line.
            if "inspect:" in line.lower():
                started = True
            continue
        stripped = line.strip()
        if not stripped:
            continue
        m = _INSPECT_LINE.match(line)
        if m:
            out.append(m.group(1))
        else:
            # First non-numbered, non-blank line ends the inspect block.
            break
    return out


def _safe_default_prompt(incident: HermesIncident) -> str:
    """Synthesize a generic safe Claude repair prompt when one is missing."""

    return (
        f"{incident.system} is in state '{incident.status}' (severity "
        f"{incident.severity}). Inspect the relevant logs, identify the root "
        f"cause from the evidence below, and propose a fix.\n\n"
        f"Evidence:\n"
        + ("\n".join(f"  - {e}" for e in incident.evidence) or "  (none)")
        + "\n\nRecommended fix: "
        + (incident.recommended_fix or "(not specified)")
        + "\n\nDo NOT take destructive action without confirming the root "
        "cause. Do NOT touch unrelated systems. Report back with: root "
        "cause, what you changed, current health status, and any remaining "
        "issues."
    )


@router.get("/repair-plan/{alert_id}", response_model=HermesRepairPlan)
async def get_repair_plan(
    alert_id: str,
    _ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> HermesRepairPlan:
    """Derive a read-only repair plan for one incident.

    No automation, no restart, no deploy — this endpoint just packages the
    information from the alert state file into the shape the Repair Center
    UI consumes.
    """

    incidents, _warnings, dir_present = _load_all()
    if not dir_present:
        raise HTTPException(status_code=404, detail="alert state dir missing")

    match = next((i for i in incidents if i.alert_id == alert_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="alert_id not found")

    prompt = match.claude_prompt or _safe_default_prompt(match)

    return HermesRepairPlan(
        alert_id=match.alert_id,
        repair_mode="manual",
        inspect_checklist=_inspect_checklist(prompt),
        recommended_next_action=match.recommended_fix
        or "Inspect the evidence and decide manually.",
        claude_prompt=prompt,
        approval_required=True,
        blocked_actions=BLOCKED_ACTIONS_BY_SYSTEM.get(match.system, []),
        rollback_notes=(
            "Each rewired Hermes hook has a "
            "~/.hermes/hooks/<hook>.sh.bak.20260428 next to it. To revert a "
            "specific hook, mv the .bak file over the live file. The launchd "
            "job runs the file directly; no daemon restart is required."
        ),
    )


# ── Static safety rules ──────────────────────────────────────────────────────
@router.get("/safety", response_model=HermesSafetyRules)
async def get_safety_rules(
    _ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> HermesSafetyRules:
    """Return the documented safety constraints for the v1 read-only UI."""

    return HermesSafetyRules(
        auto_inspect="future",
        auto_restart="disabled",
        auto_commit="never",
        auto_push="never",
        auto_deploy="never",
        secret_rotation="manual only",
        database_writes="approval required",
        onlyfans_writes="blocked",
        onlymonster_writes="blocked",
        browser_automation="blocked",
        restarts="approval required",
    )


# Helpers exposed to test code.
__all__: Iterable[str] = (
    "router",
    "_alerts_dir",
    "_load_all",
    "_inspect_checklist",
    "BLOCKED_ACTIONS_BY_SYSTEM",
)
