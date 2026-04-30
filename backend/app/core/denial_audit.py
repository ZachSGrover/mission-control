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


def _route_pattern(request: Request) -> str:
    """Return the parameterised route pattern (e.g. ``/items/{id}``) when
    available, falling back to the raw path. Lets denial-audit metadata
    aggregate by route shape rather than blowing up the cardinality with
    every concrete id.
    """
    route = request.scope.get("route")
    pattern = getattr(route, "path", None) if route is not None else None
    return pattern or (request.url.path or "unknown")


def _reason_category(status_code: int, exc: HTTPException) -> str:
    """Bucket a denial into a coarse, dashboard-friendly reason.

    Pure-text only — no user-supplied data flows into the audit metadata
    via the message body. Detail strings can carry input we don't want
    to round-trip, so we infer a category from the status + a short fixed
    keyword scan.

    Sprint 6 enrichment: dependency code (e.g. ``require_owner``) can
    attach a typed denial-detail dict to the exception via
    :func:`attach_denial_detail` to bypass the keyword inference.
    """
    # Sprint 6: prefer explicit detail attached by the dependency.
    explicit = getattr(exc, "_mc_denial_detail", None)
    if isinstance(explicit, dict):
        category = explicit.get("reason_category")
        if isinstance(category, str):
            return category

    detail = ""
    raw_detail = getattr(exc, "detail", None)
    if isinstance(raw_detail, str):
        detail = raw_detail.lower()

    if status_code == 401:
        return "unauthenticated"
    if status_code == 403:
        if "owner" in detail:
            return "role_required_owner"
        if "admin" in detail:
            return "role_required_admin"
        if "allowlist" in detail:
            return "allowlist"
        if "disabled" in detail:
            return "user_disabled"
        return "forbidden"
    return "denied"


def attach_denial_detail(
    exc: HTTPException,
    *,
    dependency: str,
    reason_category: str,
    required_role: str | None = None,
    required_permission: str | None = None,
) -> HTTPException:
    """Attach typed denial-detail to an ``HTTPException`` for audit.

    Sprint 6 helper. Dependencies (``require_owner``, ``require_org_admin``,
    permission-checks) call this just before raising so the
    denial-audit handler can record the *exact* reason instead of
    inferring from the message body.

    The dict is stashed on a private ``_mc_denial_detail`` attribute
    so it never leaks into the HTTP response body. The handler reads
    it explicitly via :func:`getattr`.

    Never include: tokens, cookies, request body, fan data, creator
    private data. The caller is responsible for passing only the
    safe-to-audit fields.
    """
    setattr(
        exc,
        "_mc_denial_detail",
        {
            "dependency": dependency,
            "reason_category": reason_category,
            "required_role": required_role,
            "required_permission": required_permission,
        },
    )
    return exc


def _safe_actor(request: Request) -> tuple[str | None, str | None]:
    """Best-effort extraction of (actor_id, actor_email) from request state.

    Many FastAPI deps stash the resolved auth context on ``request.state``
    via the dependency's side-effect. We read that here without re-running
    auth (which would itself raise on a 401 path). If nothing is on state,
    the fields stay ``None`` and the audit row reflects "unknown actor".
    """
    state = getattr(request, "state", None)
    user = None
    if state is not None:
        for attr in ("auth", "auth_context", "current_user"):
            obj = getattr(state, attr, None)
            user = getattr(obj, "user", obj) if obj is not None else None
            if user is not None:
                break
    actor_id = None
    actor_email = None
    if user is not None:
        uid = getattr(user, "id", None)
        if uid is not None:
            actor_id = str(uid)
        email = getattr(user, "email", None)
        if isinstance(email, str):
            actor_email = email
    return actor_id, actor_email


async def _denial_audit_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """FastAPI handler that audits 401 / 403 responses, then re-raises shape.

    Wraps the default ``HTTPException`` response — preserves the body,
    status, and headers — and adds a side-effect audit row when the
    response is 401 or 403.

    Sprint 4 enrichment:
    - Adds parameterised ``route_pattern`` so dashboards can aggregate
      cleanly without exploding cardinality.
    - Adds a coarse ``reason_category`` bucketed from the denial type.
    - Best-effort populates the actor id/email from ``request.state``
      when a dependency happened to resolve it before raising.
    - Never logs the ``detail`` body, the request body, cookies, or any
      header value.
    """
    status_code = exc.status_code
    if status_code in (401, 403):
        ip = _safe_ip(request)
        path = request.url.path or "unknown"
        route_pattern = _route_pattern(request)
        reason_category = _reason_category(status_code, exc)
        actor_id, actor_email = _safe_actor(request)
        key = (ip, route_pattern, status_code)
        if _should_audit(key, time.time()):
            try:
                async with async_session_maker() as session:
                    from uuid import UUID

                    actor_uuid: UUID | None = None
                    try:
                        actor_uuid = UUID(actor_id) if actor_id else None
                    except (ValueError, TypeError):
                        actor_uuid = None

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
                        actor_user_id=actor_uuid,
                        actor_email=actor_email,
                        ip_address=ip,
                        user_agent=_safe_user_agent(request),
                        resource_type="http_route",
                        resource_id=f"{request.method} {route_pattern}",
                        metadata={
                            "status": status_code,
                            "method": request.method,
                            "path": path,
                            "route_pattern": route_pattern,
                            "reason_category": reason_category,
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
