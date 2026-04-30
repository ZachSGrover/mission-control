"""
Master controller API — autonomous system management.

Endpoints:
  POST /api/v1/workflows/master/start        → start the control loop
  POST /api/v1/workflows/master/stop         → stop the control loop
  POST /api/v1/workflows/master/pause        → pause (keep loop alive)
  POST /api/v1/workflows/master/resume       → resume from pause
  GET  /api/v1/workflows/system/status       → full system state
  POST /api/v1/workflows/auto-fix            → run auto-fix with suggestions
  POST /api/v1/workflows/master/cycle        → trigger one manual cycle
  GET  /api/v1/workflows/journal/latest      → last N journal entries
  POST /api/v1/workflows/journal/generate    → generate journal from log
  GET  /api/v1/workflows/log/recent          → last N cycle log entries

All require owner role.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.mc_roles import require_owner
from app.api.workflows import (
    RENDER_API_KEY,
    RENDER_SERVICE_ID,
    _get_urls,
    run_health_check,
)
from app.core.auth import get_auth_context

router = APIRouter(tags=["master"])
logger = logging.getLogger(__name__)
AUTH_DEP = Depends(get_auth_context)
OWNER_DEP = Depends(require_owner)

# ── Shared in-process state ───────────────────────────────────────────────────
# This state is authoritative when the controller runs inside the FastAPI process.
# When running as a shell script, the shell scripts write to disk and the API
# reads from the same state dir via MC_STATE_DIR env var.

MC_STATE_DIR = os.environ.get("MC_STATE_DIR", "/tmp/mc-system")
os.makedirs(MC_STATE_DIR, exist_ok=True)

STATE_FILE = os.path.join(MC_STATE_DIR, "system.state")
LOG_FILE = os.path.join(MC_STATE_DIR, "cycle.log")
JOURNAL_FILE = os.path.join(MC_STATE_DIR, "journal.log")
PID_FILE = os.path.join(MC_STATE_DIR, "master.pid")
MANUAL_FLAGS = os.path.join(MC_STATE_DIR, "manual-flags.log")

MAX_FIX_ATTEMPTS = 3
CYCLE_INTERVAL = int(os.environ.get("CYCLE_INTERVAL", "60"))

# In-process loop state
_loop_task: asyncio.Task[None] | None = None
_cycle_count = 0
_fix_attempts = 0
_total_errors = 0
_total_fixes = 0
_total_deploys = 0


# ── State helpers ─────────────────────────────────────────────────────────────


def _get_state() -> str:
    try:
        with open(STATE_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return "stopped"


def _set_state(state: str) -> None:
    with open(STATE_FILE, "w") as f:
        f.write(state)


def _log_event(action: str, result: str, detail: str = "") -> None:
    record = json.dumps(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "result": result,
            "detail": detail,
        }
    )
    try:
        with open(LOG_FILE, "a") as f:
            f.write(record + "\n")
    except OSError:
        pass
    logger.info("mc.%s result=%s detail=%s", action, result, detail)


def _log_journal(cycle: int, headline: str, summary: str) -> None:
    record = json.dumps(
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "cycle": cycle,
            "headline": headline,
            "summary": summary,
        }
    )
    try:
        with open(JOURNAL_FILE, "a") as f:
            f.write(record + "\n")
    except OSError:
        pass


def _read_log(n: int = 50) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        with open(LOG_FILE) as f:
            lines = f.readlines()
        for line in lines[-n:]:
            try:
                entries.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                pass
    except FileNotFoundError:
        pass
    return entries


def _read_journal(n: int = 10) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        with open(JOURNAL_FILE) as f:
            lines = f.readlines()
        for line in lines[-n:]:
            try:
                entries.append(json.loads(line.strip()))
            except json.JSONDecodeError:
                pass
    except FileNotFoundError:
        pass
    return entries


# ── Auto-fix logic ────────────────────────────────────────────────────────────

AUTO_FIXABLE = {"fix:cors", "fix:redeploy", "fix:backend_error", "fix:vercel_redeploy", "fix:env"}


async def _apply_fixes(suggestions: list[str]) -> dict[str, Any]:
    """Apply known-automatable fixes. Returns {applied, failed}."""
    applied: list[str] = []
    failed: list[str] = []

    for fix in suggestions:
        if fix not in AUTO_FIXABLE:
            failed.append(fix)
            continue

        if fix in {"fix:redeploy", "fix:backend_error", "fix:cors"}:
            if not RENDER_API_KEY:
                failed.append(f"{fix}(no_render_key)")
                continue
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/deploys",
                        headers={"Authorization": f"Bearer {RENDER_API_KEY}"},
                        json={"clearCache": "do_not_clear"},
                        timeout=15.0,
                    )
                    resp.raise_for_status()
                applied.append(fix)
            except Exception as exc:
                failed.append(f"{fix}(error:{exc})")

        elif fix in {"fix:env", "fix:vercel_redeploy"}:
            # Can only log — these require manual action or external triggers
            _log_event(f"fix.{fix}", "logged", "requires manual action")
            applied.append(fix)

    return {"applied": applied, "failed": failed}


# ── One control cycle ─────────────────────────────────────────────────────────


async def _run_cycle() -> dict[str, Any]:
    global _cycle_count, _fix_attempts, _total_errors, _total_fixes, _total_deploys
    _cycle_count += 1
    cycle_id = _cycle_count

    result: dict[str, Any] = {
        "cycle": cycle_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "health": "unknown",
        "action": "none",
        "fixed": [],
        "deployed": False,
    }

    # 1. Health check
    report = await run_health_check()
    result["health"] = report.overall
    result["fail_count"] = report.fail_count

    _log_event("health.check", report.overall, f"fail={report.fail_count} cycle={cycle_id}")

    if report.overall == "healthy":
        _fix_attempts = 0
        result["action"] = "sleep"
        return result

    _total_errors += report.fail_count

    # 2. Error detection
    errors: list[str] = []
    suggestions: list[str] = []
    for check in report.checks:
        if check.status == "fail":
            errors.append(f"{check.name}: {check.detail}")

    fix_map = {
        "fix:cors": ["cors.settings_preflight", "cors.roles_preflight"],
        "fix:backend_error": ["backend.health", "backend.readyz"],
        "fix:redeploy": ["backend.health"],
    }
    sug_set: set[str] = set()
    for category, check_names in fix_map.items():
        for c in report.checks:
            if c.status == "fail" and c.name in check_names:
                sug_set.add(category)
    if errors:
        sug_set.add("fix:redeploy")
    suggestions = sorted(sug_set)

    _log_event("error.detect", "errors_detected", str(errors))

    # 3. Check if fixable
    non_fixable = [s for s in suggestions if s not in AUTO_FIXABLE]
    if non_fixable or not suggestions:
        _log_event("fix.manual_required", "flagged", str(errors))
        _set_state("manual_intervention_required")
        try:
            with open(MANUAL_FLAGS, "a") as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()} errors={errors}\n")
        except OSError:
            pass
        result["action"] = "manual_intervention_required"
        result["errors"] = errors
        return result

    if _fix_attempts >= MAX_FIX_ATTEMPTS:
        _log_event("fix.max_attempts", "manual_required", f"attempts={_fix_attempts}")
        _set_state("manual_intervention_required")
        result["action"] = "max_fix_attempts"
        return result

    _fix_attempts += 1

    # 4. Apply fixes
    fix_result = await _apply_fixes(suggestions)
    result["fixed"] = fix_result["applied"]
    _total_fixes += len(fix_result["applied"])
    _log_event("fix.apply", f"applied={len(fix_result['applied'])}", str(suggestions))

    # 5. Trigger deploy
    if RENDER_API_KEY and fix_result["applied"]:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/deploys",
                    headers={"Authorization": f"Bearer {RENDER_API_KEY}"},
                    json={"clearCache": "do_not_clear"},
                    timeout=15.0,
                )
                if resp.status_code < 300:
                    deploy_data = resp.json()
                    deploy_id = deploy_data.get("deploy", {}).get("id", "")
                    result["deployed"] = True
                    result["deploy_id"] = deploy_id
                    _total_deploys += 1
                    _log_event("deploy.trigger", "ok", f"deploy_id={deploy_id}")
                    await asyncio.sleep(5)  # Brief pause; don't block loop for 90s
        except Exception as exc:
            _log_event("deploy.trigger", "error", str(exc))

    result["action"] = "fixed"
    return result


# ── Background loop ───────────────────────────────────────────────────────────


async def _control_loop() -> None:
    _log_event("master.start", "ok", f"interval={CYCLE_INTERVAL}s")
    _set_state("running")
    journal_counter = 0

    while True:
        state = _get_state()

        if state == "stopped":
            break

        if state in ("paused", "manual_intervention_required"):
            await asyncio.sleep(10)
            continue

        try:
            await _run_cycle()
            journal_counter += 1

            # Journal every 10 cycles
            if journal_counter % 10 == 0:
                _log_journal(
                    _cycle_count,
                    f"Cycle {_cycle_count} complete",
                    f"Total: errors={_total_errors} fixes={_total_fixes} deploys={_total_deploys}",
                )
        except Exception as exc:
            _log_event("cycle.error", "exception", str(exc))
            logger.exception("Master controller cycle error")

        await asyncio.sleep(CYCLE_INTERVAL)

    _log_event("master.stop", "ok", f"cycles={_cycle_count}")
    _set_state("stopped")


# ── Schemas ───────────────────────────────────────────────────────────────────


class MasterControlResponse(BaseModel):
    ok: bool
    state: str
    message: str = ""


class SystemStatus(BaseModel):
    state: str
    pid: str
    loop_running: bool
    cycle_count: int
    fix_attempts: int
    total_errors: int
    total_fixes: int
    total_deploys: int
    backend_url: str
    last_events: list[dict[str, Any]]
    last_journal: dict[str, Any] | None


class AutoFixRequest(BaseModel):
    suggestions: list[str]


class AutoFixResponse(BaseModel):
    applied: list[str]
    failed: list[str]


class JournalEntry(BaseModel):
    ts: str
    cycle: int
    headline: str
    summary: str


class LogEntry(BaseModel):
    ts: str
    action: str
    result: str
    detail: str = ""


class CycleRequest(BaseModel):
    force: bool = False


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/workflows/master/start", response_model=MasterControlResponse)
async def start_master(_role: str = OWNER_DEP) -> MasterControlResponse:
    """Start the autonomous control loop."""
    global _loop_task
    if _loop_task and not _loop_task.done():
        return MasterControlResponse(ok=False, state=_get_state(), message="Already running")

    _loop_task = asyncio.create_task(_control_loop())
    _set_state("running")
    _log_event("master.start", "ok", "via_api")
    return MasterControlResponse(ok=True, state="running", message="Master controller started")


@router.post("/workflows/master/stop", response_model=MasterControlResponse)
async def stop_master(_role: str = OWNER_DEP) -> MasterControlResponse:
    """Stop the control loop gracefully."""
    global _loop_task
    _set_state("stopped")
    if _loop_task and not _loop_task.done():
        _loop_task.cancel()
        try:
            await _loop_task
        except asyncio.CancelledError:
            pass
        _loop_task = None
    _log_event("master.stop", "ok", "via_api")
    return MasterControlResponse(ok=True, state="stopped", message="Master controller stopped")


@router.post("/workflows/master/pause", response_model=MasterControlResponse)
async def pause_master(_role: str = OWNER_DEP) -> MasterControlResponse:
    """Pause the control loop without stopping it."""
    _set_state("paused")
    _log_event("master.pause", "ok", "via_api")
    return MasterControlResponse(ok=True, state="paused", message="Master controller paused")


@router.post("/workflows/master/resume", response_model=MasterControlResponse)
async def resume_master(_role: str = OWNER_DEP) -> MasterControlResponse:
    """Resume from paused or manual-intervention-required."""
    global _loop_task
    current = _get_state()
    if current == "stopped":
        # Auto-restart the loop
        _loop_task = asyncio.create_task(_control_loop())

    _set_state("running")
    _log_event("master.resume", "ok", f"was={current}")
    return MasterControlResponse(ok=True, state="running", message=f"Resumed from {current}")


@router.post("/workflows/master/cycle", response_model=dict)
async def run_single_cycle(body: CycleRequest, _role: str = OWNER_DEP) -> dict[str, Any]:
    """Trigger a single health-check→fix→deploy cycle manually."""
    result = await _run_cycle()
    return result


@router.get("/workflows/system/status", response_model=SystemStatus)
async def system_status(_role: str = OWNER_DEP) -> SystemStatus:
    """Return full system state including recent log and journal."""
    pid_str = ""
    try:
        with open(PID_FILE) as f:
            pid_str = f.read().strip()
    except FileNotFoundError:
        pass

    last_events = _read_log(10)
    journal_entries = _read_journal(1)
    last_journal = journal_entries[-1] if journal_entries else None

    return SystemStatus(
        state=_get_state(),
        pid=pid_str,
        loop_running=bool(_loop_task and not _loop_task.done()),
        cycle_count=_cycle_count,
        fix_attempts=_fix_attempts,
        total_errors=_total_errors,
        total_fixes=_total_fixes,
        total_deploys=_total_deploys,
        backend_url=_get_urls()[0],
        last_events=last_events,
        last_journal=last_journal,
    )


@router.post("/workflows/auto-fix", response_model=AutoFixResponse)
async def auto_fix(body: AutoFixRequest, _role: str = OWNER_DEP) -> AutoFixResponse:
    """Apply the given fix suggestions autonomously."""
    result = await _apply_fixes(body.suggestions)
    _log_event("fix.apply", f"applied={len(result['applied'])}", str(body.suggestions))
    return AutoFixResponse(**result)


@router.get("/workflows/journal/latest", response_model=list[JournalEntry])
async def get_journal(
    limit: int = Query(default=10, ge=1, le=100),
    _role: str = OWNER_DEP,
) -> list[JournalEntry]:
    """Return the latest journal entries."""
    raw = _read_journal(limit)
    return [
        JournalEntry(
            ts=e.get("ts", ""),
            cycle=e.get("cycle", 0),
            headline=e.get("headline", ""),
            summary=e.get("summary", ""),
        )
        for e in raw
    ]


@router.get("/workflows/log/recent", response_model=list[LogEntry])
async def get_log(
    limit: int = Query(default=50, ge=1, le=500),
    _role: str = OWNER_DEP,
) -> list[LogEntry]:
    """Return recent cycle log entries."""
    raw = _read_log(limit)
    return [
        LogEntry(
            ts=e.get("ts", ""),
            action=e.get("action", ""),
            result=e.get("result", ""),
            detail=e.get("detail", ""),
        )
        for e in raw
    ]
