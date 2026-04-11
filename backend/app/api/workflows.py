"""
Workflow trigger API — callable by n8n, claw agents, or webhooks.

Endpoints:
  POST /api/v1/workflows/health-check   → run system health check
  POST /api/v1/workflows/deploy         → trigger Render redeploy
  POST /api/v1/workflows/error-detect   → run error detection
  GET  /api/v1/workflows/status         → last known system status (cached)

All endpoints require owner role.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.mc_roles import require_owner
from app.core.auth import AuthContext, get_auth_context

router = APIRouter(prefix="/workflows", tags=["workflows"])
logger = logging.getLogger(__name__)

AUTH_DEP = Depends(get_auth_context)
OWNER_DEP = Depends(require_owner)

# ── Config from environment ───────────────────────────────────────────────────
RENDER_API_KEY = os.getenv("RENDER_API_KEY", "")
RENDER_SERVICE_ID = os.getenv("RENDER_SERVICE_ID", "srv-d7cq41q8qa3s73bbke00")
BACKEND_URL = os.getenv("BASE_URL", "https://mission-control-jbx8.onrender.com")
FRONTEND_URL = "https://app.digidle.com"

# Simple in-memory cache for last health status
_last_health: dict[str, Any] = {}
_last_health_ts: float = 0.0
HEALTH_CACHE_TTL = 30  # seconds


# ── Schemas ───────────────────────────────────────────────────────────────────

class CheckResult(BaseModel):
    name: str
    status: str       # "pass" | "fail" | "warn"
    detail: str = ""


class HealthReport(BaseModel):
    overall: str      # "healthy" | "degraded" | "down"
    pass_count: int
    fail_count: int
    checks: list[CheckResult]
    timestamp: str


class DeployRequest(BaseModel):
    clear_cache: bool = False
    message: str = ""


class DeployResponse(BaseModel):
    triggered: bool
    deploy_id: str = ""
    method: str       # "render_api" | "not_configured"
    message: str = ""


class ErrorReport(BaseModel):
    status: str       # "clean" | "errors_detected"
    errors: list[str]
    warnings: list[str]
    fix_suggestions: list[str]


# ── Health check logic ────────────────────────────────────────────────────────

async def _check(
    client: httpx.AsyncClient,
    name: str,
    url: str,
    method: str = "GET",
    origin: str = "",
    expected_status: int = 200,
    extra_headers: dict[str, str] | None = None,
) -> CheckResult:
    headers = {}
    if origin:
        headers["Origin"] = origin
    if method == "OPTIONS":
        headers["Access-Control-Request-Method"] = "GET"
        headers["Access-Control-Request-Headers"] = "authorization"
    if extra_headers:
        headers.update(extra_headers)

    try:
        resp = await client.request(method, url, headers=headers, timeout=10.0)
        if resp.status_code == expected_status:
            return CheckResult(name=name, status="pass", detail=str(resp.status_code))
        return CheckResult(
            name=name,
            status="fail",
            detail=f"expected {expected_status}, got {resp.status_code}",
        )
    except Exception as exc:
        return CheckResult(name=name, status="fail", detail=f"error: {exc}")


async def run_health_check() -> HealthReport:
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).isoformat()
    checks: list[CheckResult] = []

    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [
            # Backend
            _check(client, "backend.health",        f"{BACKEND_URL}/health",                  expected_status=200),
            _check(client, "backend.readyz",         f"{BACKEND_URL}/readyz",                  expected_status=200),
            # CORS
            _check(client, "cors.settings",          f"{BACKEND_URL}/api/v1/settings/api-keys", "OPTIONS", FRONTEND_URL, 200),
            _check(client, "cors.roles_me",           f"{BACKEND_URL}/api/v1/roles/me",          "OPTIONS", FRONTEND_URL, 200),
            # Auth (expect 401 without token)
            _check(client, "auth.settings",           f"{BACKEND_URL}/api/v1/settings/api-keys", expected_status=401),
            _check(client, "auth.roles_me",           f"{BACKEND_URL}/api/v1/roles/me",          expected_status=401),
            _check(client, "auth.openai",             f"{BACKEND_URL}/api/v1/openai/status",     expected_status=401),
            _check(client, "auth.gemini",             f"{BACKEND_URL}/api/v1/gemini/status",     expected_status=401),
            # Frontend
            _check(client, "frontend.root",           FRONTEND_URL,                              expected_status=200),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        if isinstance(r, CheckResult):
            checks.append(r)
        else:
            checks.append(CheckResult(name="unknown", status="fail", detail=str(r)))

    passes = sum(1 for c in checks if c.status == "pass")
    fails  = sum(1 for c in checks if c.status == "fail")
    overall = "healthy" if fails == 0 else ("down" if passes == 0 else "degraded")

    return HealthReport(
        overall=overall,
        pass_count=passes,
        fail_count=fails,
        checks=checks,
        timestamp=ts,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/health-check", response_model=HealthReport)
async def trigger_health_check(_role: str = OWNER_DEP) -> HealthReport:
    """Run a full system health check and return a structured report."""
    global _last_health, _last_health_ts

    report = await run_health_check()

    _last_health = report.model_dump()
    _last_health_ts = time.time()

    logger.info(
        "workflows.health_check overall=%s pass=%d fail=%d",
        report.overall, report.pass_count, report.fail_count,
    )
    return report


@router.get("/status", response_model=HealthReport | None)
async def get_last_status(_role: str = OWNER_DEP) -> dict[str, Any] | None:
    """Return the last cached health check result (up to 30s old), or None."""
    if not _last_health or (time.time() - _last_health_ts) > HEALTH_CACHE_TTL:
        return None  # type: ignore[return-value]
    return _last_health  # type: ignore[return-value]


@router.post("/deploy", response_model=DeployResponse)
async def trigger_deploy(body: DeployRequest, _role: str = OWNER_DEP) -> DeployResponse:
    """
    Trigger a Render redeploy via the Render API.
    Requires RENDER_API_KEY env var. Falls back to instructions if not set.
    """
    if not RENDER_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="RENDER_API_KEY not configured. Add it to Render environment variables.",
        )

    clear = "clear" if body.clear_cache else "do_not_clear"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/deploys",
                headers={"Authorization": f"Bearer {RENDER_API_KEY}"},
                json={"clearCache": clear},
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()

        deploy_id = data.get("deploy", {}).get("id", "")
        logger.info("workflows.deploy triggered deploy_id=%s", deploy_id)
        return DeployResponse(
            triggered=True,
            deploy_id=deploy_id,
            method="render_api",
            message=body.message or "Deploy triggered successfully",
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Render API error: {exc.response.status_code} {exc.response.text}",
        ) from exc


@router.post("/error-detect", response_model=ErrorReport)
async def trigger_error_detect(_role: str = OWNER_DEP) -> ErrorReport:
    """Run error detection and return actionable error/fix report."""
    errors: list[str] = []
    warnings: list[str] = []

    report = await run_health_check()

    for check in report.checks:
        if check.status == "fail":
            errors.append(f"{check.name}: {check.detail}")

    # Map errors → fix suggestions
    fix_map = {
        "cors":     ["cors.settings", "cors.roles_me"],
        "auth":     ["auth.settings", "auth.roles_me", "auth.openai"],
        "backend":  ["backend.health", "backend.readyz"],
        "frontend": ["frontend.root"],
    }
    suggestions: set[str] = set()
    for category, check_names in fix_map.items():
        for c in report.checks:
            if c.status == "fail" and c.name in check_names:
                suggestions.add(f"fix:{category}")

    if errors:
        suggestions.add("fix:redeploy")

    logger.info(
        "workflows.error_detect errors=%d warnings=%d suggestions=%s",
        len(errors), len(warnings), list(suggestions),
    )

    return ErrorReport(
        status="clean" if not errors else "errors_detected",
        errors=errors,
        warnings=warnings,
        fix_suggestions=sorted(suggestions),
    )
