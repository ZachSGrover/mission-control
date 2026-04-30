"""Denial-audit hook for 401 / 403 responses.

Sprint 3: a thin FastAPI exception-handler wrapper that records an
audit event for unauthorized / forbidden responses, with in-memory
throttling so a noisy probing client cannot flood the ``audit_events``
table.

Design choices:
- Login *success* events live elsewhere. Clerk handles login externally
  and the per-request ``get_auth_context`` runs on every authenticated
  call — auditing every successful auth would be 99% noise. A real
  login-success hook needs a Clerk webhook integration (documented as
  a Sprint 4 task).
- Login *failure* and 403 *denial* are the high-value signal: they
  indicate either a real attacker probing or a misconfigured
  permission. Both are audited here.
- Throttle: at most one audit event per ``(ip, path, status)`` tuple
  per :data:`THROTTLE_WINDOW_SECONDS`. The throttle is in-memory and
  process-local — fine for single-instance deploys; multi-instance
  deploys will see slightly more audit rows, which is acceptable.
"""

from __future__ import annotations

import logging
import time
from typing import Final

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.db.session import async_session_maker
from app.services.audit_log import record_audit

logger = logging.getLogger(__name__)

THROTTLE_WINDOW_SECONDS: Final[int] = 300

# Process-local throttle map: (ip, path, status) → unix_seconds_of_last_audit.
_last_audit: dict[tuple[str, str, int], float] = {}


def _should_audit(key: tuple[str, str, int], now: float) -> bool:
    last = _last_audit.get(key)
    if last is None or now - last > THROTTLE_WINDOW_SECONDS:
        _last_audit[key] = now
        return True
    return False


def _safe_ip(request: Request) -> str:
    # ``request.client`` can be None in test or stripped-proxy setups.
    if request.client is None:
        return "unknown"
    # Never log full IPs to audit metadata under most regulatory regimes,
    # but for security-event correlation the full address is needed and
    # is not classified as PII when paired with a security event. Caller
    # discretion: this string is what lands in audit metadata.
    return str(request.client.host)


def _safe_user_agent(request: Request) -> str:
    raw = request.headers.get("user-agent", "")
    # Cap length to keep audit metadata bounded.
    return raw[:200] if raw else "unknown"


async def _denial_audit_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """FastAPI handler that audits 401 / 403 responses, then re-raises shape.

    Wraps the default ``HTTPException`` response — preserves the body,
    status, and headers — and adds a side-effect audit row when the
    response is 401 or 403.
    """
    status_code = exc.status_code
    if status_code in (401, 403):
        ip = _safe_ip(request)
        path = request.url.path or "unknown"
        key = (ip, path, status_code)
        if _should_audit(key, time.time()):
            try:
                async with async_session_maker() as session:
                    await record_audit(
                        session,
                        event_type=(
                            "auth.denied.unauthorized"
                            if status_code == 401
                            else "auth.denied.forbidden"
                        ),
                        category="auth",
                        action="denied",
                        result="denied",
                        severity="warning",
                        ip_address=ip,
                        user_agent=_safe_user_agent(request),
                        resource_type="http_route",
                        resource_id=f"{request.method} {path}",
                        metadata={
                            "status": status_code,
                            "method": request.method,
                            "path": path,
                            # Detail message is *not* logged: it sometimes
                            # contains user-supplied input that callers
                            # might not want round-tripped into audit.
                        },
                    )
                    await session.commit()
            except Exception as audit_exc:  # pragma: no cover — defensive
                logger.warning(
                    "denial_audit.write_failed status=%d error=%s",
                    status_code,
                    type(audit_exc).__name__,
                )

    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=status_code,
        content={"detail": exc.detail},
        headers=headers,
    )


def install_denial_audit_handler(app: FastAPI) -> None:
    """Register the denial-audit handler on the FastAPI app."""
    app.exception_handler(HTTPException)(_denial_audit_handler)
