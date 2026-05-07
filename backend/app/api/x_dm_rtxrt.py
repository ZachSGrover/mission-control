"""X DM Bot RTxRT API surface — sandbox-only, MVP.

This module wires the Mission Control bot dashboard endpoints for the
RT BOT.  Every path here is gated by the existing role system from
PR #21:

  • ``operator`` and ``owner`` may read all RT BOT surfaces and may
    pause / reject sandbox runs.
  • ``owner`` may additionally create draft runs, start sandbox runs,
    read settings, and activate the kill switch.

Hard MVP rules enforced here (cross-checked against
``app.services.x_dm_rtxrt``):
  • ``live_writes_enabled`` is locked off.  Any PATCH that would set it
    to ``True`` returns 403 ``{"error":"live_writes_disabled_in_MVP"}``.
  • ``sandbox_mode`` is locked on.  Any PATCH that would set it ``False``
    returns 403 ``{"error":"live_writes_disabled_in_MVP"}``.
  • There is no AdsPower / Playwright / X.com / Windows-Scheduler code
    path anywhere in this file.  The "send" verb does not exist.
  • Responses NEVER include API keys, cookies, passwords, tokens,
    session data, or full message bodies.  Only the 80-char
    ``message_preview`` is ever returned.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from pydantic import Field as PField
from sqlmodel import select

from app.api.mc_roles import require_operator, require_owner
from app.core.auth import AuthContext, get_auth_context
from app.core.logging import get_logger
from app.db.session import get_session
from app.models.audit_event import AuditEvent
from app.models.bot_contact_archive import BotContactArchive
from app.models.bot_registry import BotRegistryEntry
from app.models.bot_runs import (
    OUTPUT_TYPE_RUN_LOG,
    BotRun,
    BotRunOutput,
)
from app.services.audit_log import actor_from_auth, record_audit
from app.services.bot_registry import parse_permitted_roles
from app.services.x_dm_rtxrt import (
    MAX_MESSAGE_PREVIEW_CHARS,
    X_DM_RTXRT_SLUG,
    activate_kill_switch,
    contacts_to_csv,
    create_draft_run,
    log_safety_event,
    pause_run,
    reject_run,
    runs_to_csv,
)
from app.services.x_dm_rtxrt import start_sandbox_run as _start_sandbox_run_service
from app.services.x_dm_rtxrt import (
    truncate_message_preview,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(tags=["x-dm-rtxrt"])
logger = get_logger(__name__)

AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)
OPERATOR_DEP = Depends(require_operator)
OWNER_DEP = Depends(require_owner)

# Coded error string used for every blocked live-write attempt.
LIVE_WRITES_DISABLED_ERROR = "live_writes_disabled_in_MVP"


# ── Response schemas (no secrets, no message body) ──────────────────────────


class BotRunResponse(BaseModel):
    """Public-safe view of a bot run row."""

    id: str
    bot_slug: str
    status: str
    mode: str
    profile_id: str
    profile_name: str
    message_preview: str | None
    target_count: int
    sent_count: int
    scan_count: int
    readonly_count: int
    elapsed_seconds: int | None
    started_at: datetime | None
    completed_at: datetime | None
    created_by: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class BotRunOutputResponse(BaseModel):
    id: str
    output_type: str
    content: dict[str, Any] | list[Any] | str
    created_at: datetime


class RunCreateRequest(BaseModel):
    profile_id: str = PField(min_length=1, max_length=64)
    profile_name: str = PField(min_length=1, max_length=128)
    message: str = PField(min_length=1)
    target_count: int = PField(gt=0, le=10_000)


class RunDetailResponse(BotRunResponse):
    outputs: list[BotRunOutputResponse]


class ContactArchiveSummary(BaseModel):
    profile_id: str
    profile_name: str | None = None
    contact_count: int
    last_sent_at: datetime | None = None


class BotSettingsResponse(BaseModel):
    """Owner-only settings view.  No API keys ever, only presence flags."""

    slug: str
    name: str
    version: str | None
    sandbox_mode: bool
    live_writes_enabled: bool
    kill_switch_active: bool
    api_key_present: bool


class SettingsUpdateRequest(BaseModel):
    sandbox_mode: bool | None = None
    live_writes_enabled: bool | None = None


class KillSwitchResponse(BaseModel):
    slug: str
    kill_switch_active: bool
    cancelled_runs: int
    paused_runs: int


class AuditEventResponse(BaseModel):
    id: str
    actor_clerk_user_id: str
    actor_email: str | None
    actor_role: str | None
    action: str
    target_type: str | None
    target_id: str | None
    outcome: str
    safe_summary: str | None
    payload_hash: str | None
    ip_address: str | None
    created_at: datetime


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _get_bot_or_404(slug: str, session: "AsyncSession") -> BotRegistryEntry:
    result = await session.exec(select(BotRegistryEntry).where(BotRegistryEntry.slug == slug))
    entry = result.first()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bot '{slug}' not found.",
        )
    return entry


def _live_writes_disabled() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error": LIVE_WRITES_DISABLED_ERROR},
    )


def _ensure_rtxrt_slug(slug: str) -> None:
    """RT BOT-scoped run/contacts endpoints only respond for the RT BOT.

    Other bot slugs in the registry might not have run-lifecycle support
    at all, so we surface a clean 404 rather than silently accept.
    """
    if slug != X_DM_RTXRT_SLUG:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bot '{slug}' has no run lifecycle in this MVP.",
        )


def _can_view(role: str, entry: BotRegistryEntry) -> bool:
    """Operator or owner may view RT BOT surfaces; others denied."""
    if role == "owner":
        return True
    if role == "operator":
        permitted = parse_permitted_roles(entry.permitted_roles_json)
        return "operator" in permitted
    return False


def _to_run_response(run: BotRun, slug: str) -> BotRunResponse:
    return BotRunResponse(
        id=str(run.id),
        bot_slug=slug,
        status=run.status,
        mode=run.mode,
        profile_id=run.profile_id,
        profile_name=run.profile_name,
        message_preview=run.message_preview,
        target_count=run.target_count,
        sent_count=run.sent_count,
        scan_count=run.scan_count,
        readonly_count=run.readonly_count,
        elapsed_seconds=run.elapsed_seconds,
        started_at=run.started_at,
        completed_at=run.completed_at,
        created_by=run.created_by,
        error_message=run.error_message,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _decode_output_content(raw: str) -> dict[str, Any] | list[Any] | str:
    try:
        return json.loads(raw)  # type: ignore[no-any-return]
    except (TypeError, ValueError):
        return raw


def _to_output_response(output: BotRunOutput) -> BotRunOutputResponse:
    return BotRunOutputResponse(
        id=str(output.id),
        output_type=output.output_type,
        content=_decode_output_content(output.content_json),
        created_at=output.created_at,
    )


async def _list_runs_for_bot(
    session: "AsyncSession",
    bot_id: UUID,
    *,
    limit: int = 50,
) -> list[BotRun]:
    result = await session.exec(
        select(BotRun)
        .where(BotRun.bot_id == bot_id)
        .order_by(BotRun.created_at.desc())  # type: ignore[attr-defined]
        .limit(limit)
    )
    return list(result.all())


async def _get_run_or_404(session: "AsyncSession", run_id_str: str, bot_id: UUID) -> BotRun:
    try:
        run_uuid = UUID(run_id_str)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id_str}' not found.",
        ) from exc
    result = await session.exec(
        select(BotRun).where(BotRun.id == run_uuid, BotRun.bot_id == bot_id)
    )
    run = result.first()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{run_id_str}' not found.",
        )
    return run


# ── Run endpoints ───────────────────────────────────────────────────────────


@router.get("/bots/{slug}/runs", response_model=list[BotRunResponse])
async def list_runs(
    slug: str,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> list[BotRunResponse]:
    """List run history for the RT BOT.  Operator or owner."""
    _ensure_rtxrt_slug(slug)
    entry = await _get_bot_or_404(slug, session)
    if not _can_view(role, entry):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    runs = await _list_runs_for_bot(session, entry.id)
    return [_to_run_response(r, slug) for r in runs]


@router.post(
    "/bots/{slug}/runs",
    response_model=BotRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_run(
    slug: str,
    body: RunCreateRequest,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotRunResponse:
    """Create a draft sandbox run.  Owner only."""
    _ensure_rtxrt_slug(slug)
    entry = await _get_bot_or_404(slug, session)

    actor_id, actor_email = actor_from_auth(auth)

    # Service-level safety + duplicate check.
    result = await create_draft_run(
        session,
        entry=entry,
        profile_id=body.profile_id,
        profile_name=body.profile_name,
        target_count=body.target_count,
        message=body.message,
        created_by=actor_id,
    )
    if not result.ok or result.run is None:
        # Distinguish between live-disabled, kill-switch, duplicate, validation.
        await record_audit(
            session,
            actor_clerk_user_id=actor_id,
            actor_email=actor_email,
            actor_role=role,
            action="bot_run.create",
            target_type="bot",
            target_id=slug,
            outcome="denied",
            safe_summary=f"create denied: {result.error_code}",
            request=request,
        )
        await session.commit()
        if result.error_code == LIVE_WRITES_DISABLED_ERROR:
            raise _live_writes_disabled()
        if result.error_code == "kill_switch_active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "kill_switch_active"},
            )
        if result.error_code == "duplicate_run":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "duplicate_run"},
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": result.error_code or "invalid_request",
                "detail": result.error_detail,
            },
        )

    run = result.run

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="bot_run.create",
        target_type="bot_run",
        target_id=str(run.id),
        outcome="success",
        safe_summary=(
            f"sandbox draft created profile={run.profile_id} "
            f"target={run.target_count} preview_len="
            f"{len(run.message_preview or '')}"
        ),
        request=request,
    )
    await session.commit()
    await session.refresh(run)
    return _to_run_response(run, slug)


@router.get("/bots/{slug}/runs/{run_id}", response_model=RunDetailResponse)
async def get_run_detail(
    slug: str,
    run_id: str,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> RunDetailResponse:
    """Return one run plus its outputs.  Operator or owner."""
    _ensure_rtxrt_slug(slug)
    entry = await _get_bot_or_404(slug, session)
    if not _can_view(role, entry):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    run = await _get_run_or_404(session, run_id, entry.id)
    outputs_result = await session.exec(select(BotRunOutput).where(BotRunOutput.run_id == run.id))
    outputs = [_to_output_response(o) for o in outputs_result.all()]
    base = _to_run_response(run, slug).model_dump()
    return RunDetailResponse(**base, outputs=outputs)


@router.post("/bots/{slug}/runs/{run_id}/start", response_model=BotRunResponse)
async def start_run(
    slug: str,
    run_id: str,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotRunResponse:
    """Start a draft sandbox run.  Owner only."""
    _ensure_rtxrt_slug(slug)
    entry = await _get_bot_or_404(slug, session)
    run = await _get_run_or_404(session, run_id, entry.id)
    actor_id, actor_email = actor_from_auth(auth)

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="bot_run.start",
        target_type="bot_run",
        target_id=str(run.id),
        outcome="success",
        safe_summary=f"sandbox start requested profile={run.profile_id}",
        request=request,
    )

    result = await _start_sandbox_run_service(session, entry=entry, run=run)
    if not result.ok:
        await record_audit(
            session,
            actor_clerk_user_id=actor_id,
            actor_email=actor_email,
            actor_role=role,
            action="bot_run.failed",
            target_type="bot_run",
            target_id=str(run.id),
            outcome="error",
            safe_summary=f"start failed: {result.error_code}",
            request=request,
        )
        await session.commit()
        if result.error_code == LIVE_WRITES_DISABLED_ERROR:
            raise _live_writes_disabled()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": result.error_code, "detail": result.error_detail},
        )

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="bot_run.completed",
        target_type="bot_run",
        target_id=str(run.id),
        outcome="success",
        safe_summary=(
            f"sandbox run completed scan={run.scan_count} "
            f"readonly={run.readonly_count} sent={run.sent_count}"
        ),
        request=request,
    )
    await session.commit()
    await session.refresh(run)
    return _to_run_response(run, slug)


@router.post("/bots/{slug}/runs/{run_id}/pause", response_model=BotRunResponse)
async def pause_run_endpoint(
    slug: str,
    run_id: str,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotRunResponse:
    """Pause a queued/running sandbox run.  Owner or operator."""
    _ensure_rtxrt_slug(slug)
    entry = await _get_bot_or_404(slug, session)
    if not _can_view(role, entry):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    run = await _get_run_or_404(session, run_id, entry.id)
    actor_id, actor_email = actor_from_auth(auth)
    mutated = await pause_run(session, run=run)
    outcome = "success" if mutated else "denied"
    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="bot_run.pause",
        target_type="bot_run",
        target_id=str(run.id),
        outcome=outcome,
        safe_summary=f"pause requested status_after={run.status}",
        request=request,
    )
    await session.commit()
    if not mutated:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "invalid_state"},
        )
    await session.refresh(run)
    return _to_run_response(run, slug)


@router.post("/bots/{slug}/runs/{run_id}/reject", response_model=BotRunResponse)
async def reject_run_endpoint(
    slug: str,
    run_id: str,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotRunResponse:
    """Reject a draft / queued / paused run.  Owner or operator."""
    _ensure_rtxrt_slug(slug)
    entry = await _get_bot_or_404(slug, session)
    if not _can_view(role, entry):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    run = await _get_run_or_404(session, run_id, entry.id)
    actor_id, actor_email = actor_from_auth(auth)
    mutated = await reject_run(session, run=run)
    outcome = "success" if mutated else "denied"
    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="bot_run.reject",
        target_type="bot_run",
        target_id=str(run.id),
        outcome=outcome,
        safe_summary=f"reject requested status_after={run.status}",
        request=request,
    )
    await session.commit()
    if not mutated:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "invalid_state"},
        )
    await session.refresh(run)
    return _to_run_response(run, slug)


@router.get("/bots/{slug}/runs/{run_id}/log", response_model=BotRunOutputResponse | None)
async def get_run_log(
    slug: str,
    run_id: str,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotRunOutputResponse | None:
    """Return the run_log output for a run.  Operator or owner."""
    _ensure_rtxrt_slug(slug)
    entry = await _get_bot_or_404(slug, session)
    if not _can_view(role, entry):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    run = await _get_run_or_404(session, run_id, entry.id)
    result = await session.exec(
        select(BotRunOutput).where(
            BotRunOutput.run_id == run.id,
            BotRunOutput.output_type == OUTPUT_TYPE_RUN_LOG,
        )
    )
    log_row = result.first()
    if log_row is None:
        return None
    return _to_output_response(log_row)


@router.get("/bots/{slug}/runs/{run_id}/export")
async def export_run_csv(
    slug: str,
    run_id: str,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> Response:
    """Export one run as CSV.  Operator or owner.  No secrets, no full body."""
    _ensure_rtxrt_slug(slug)
    entry = await _get_bot_or_404(slug, session)
    if not _can_view(role, entry):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    run = await _get_run_or_404(session, run_id, entry.id)
    csv_text = runs_to_csv([run])
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=run-{run.id}.csv"},
    )


# ── Contacts archive ────────────────────────────────────────────────────────


@router.get("/bots/{slug}/contacts", response_model=list[ContactArchiveSummary])
async def list_contacts(
    slug: str,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> list[ContactArchiveSummary]:
    """Operator-safe summary of the contact archive — counts only.

    URLs are intentionally NOT returned on this endpoint regardless of
    role; owner can hit ``/contacts/export`` to get the (URL-less) CSV.
    """
    _ensure_rtxrt_slug(slug)
    entry = await _get_bot_or_404(slug, session)
    if not _can_view(role, entry):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    result = await session.exec(
        select(BotContactArchive).where(BotContactArchive.bot_id == entry.id)
    )
    rows = list(result.all())
    by_profile: dict[str, ContactArchiveSummary] = {}
    for r in rows:
        existing = by_profile.get(r.profile_id)
        if existing is None:
            by_profile[r.profile_id] = ContactArchiveSummary(
                profile_id=r.profile_id,
                profile_name=None,
                contact_count=1,
                last_sent_at=r.last_sent_at,
            )
        else:
            existing.contact_count += 1
            if r.last_sent_at and (
                existing.last_sent_at is None or r.last_sent_at > existing.last_sent_at
            ):
                existing.last_sent_at = r.last_sent_at
    return sorted(by_profile.values(), key=lambda s: s.profile_id)


@router.get("/bots/{slug}/contacts/export")
async def export_contacts_csv(
    slug: str,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> Response:
    """Export operator-safe contact archive CSV (no URLs, no secrets)."""
    _ensure_rtxrt_slug(slug)
    entry = await _get_bot_or_404(slug, session)
    if not _can_view(role, entry):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    result = await session.exec(
        select(BotContactArchive).where(BotContactArchive.bot_id == entry.id)
    )
    rows = list(result.all())
    csv_rows = [
        (
            r.profile_id,  # profile_name placeholder (we don't store it on the archive row)
            r.profile_id,
            r.handle,
            r.last_sent_at,
            r.sent_count,
        )
        for r in rows
    ]
    csv_text = contacts_to_csv(csv_rows, include_handle=role == "owner")
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=contacts-{slug}.csv",
        },
    )


# ── Settings ────────────────────────────────────────────────────────────────


@router.get("/bots/{slug}/settings", response_model=BotSettingsResponse)
async def get_settings(
    slug: str,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotSettingsResponse:
    """Owner-only settings view.  Never returns API key values."""
    _ensure_rtxrt_slug(slug)
    entry = await _get_bot_or_404(slug, session)
    return BotSettingsResponse(
        slug=entry.slug,
        name=entry.name,
        version=entry.version,
        sandbox_mode=entry.sandbox_mode,
        live_writes_enabled=entry.live_writes_enabled,
        kill_switch_active=entry.kill_switch_active,
        # MVP has no AdsPower / x.com / Anthropic key wired into RT BOT.
        # Always False; the owner UI can show "no integrations configured".
        api_key_present=False,
    )


@router.patch("/bots/{slug}/settings", response_model=BotSettingsResponse)
async def patch_settings(
    slug: str,
    body: SettingsUpdateRequest,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotSettingsResponse:
    """Update safe settings.  Owner only.

    MVP rules:
      • ``sandbox_mode`` cannot be set to ``False``.
      • ``live_writes_enabled`` cannot be set to ``True``.
      • Either attempt returns 403 ``{"error":"live_writes_disabled_in_MVP"}``
        and writes a denied audit row + a safety event.
    """
    _ensure_rtxrt_slug(slug)
    entry = await _get_bot_or_404(slug, session)
    actor_id, actor_email = actor_from_auth(auth)

    if body.live_writes_enabled is True or body.sandbox_mode is False:
        await record_audit(
            session,
            actor_clerk_user_id=actor_id,
            actor_email=actor_email,
            actor_role=role,
            action="bot_settings.patch",
            target_type="bot",
            target_id=slug,
            outcome="denied",
            safe_summary=(
                f"live writes attempt blocked sandbox_mode={body.sandbox_mode} "
                f"live_writes_enabled={body.live_writes_enabled}"
            ),
            request=request,
        )
        log_safety_event(
            session,
            event_type="live_writes_attempt_blocked",
            description=(
                f"actor attempted to enable live writes for {slug}; "
                f"requested sandbox={body.sandbox_mode} live={body.live_writes_enabled}"
            ),
            severity="critical",
        )
        await session.commit()
        raise _live_writes_disabled()

    # No safe settings to apply in MVP — accept the no-op write so the
    # endpoint stays usable, but do not mutate anything.
    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="bot_settings.patch",
        target_type="bot",
        target_id=slug,
        outcome="success",
        safe_summary="no-op settings patch",
        request=request,
    )
    await session.commit()
    return BotSettingsResponse(
        slug=entry.slug,
        name=entry.name,
        version=entry.version,
        sandbox_mode=entry.sandbox_mode,
        live_writes_enabled=entry.live_writes_enabled,
        kill_switch_active=entry.kill_switch_active,
        api_key_present=False,
    )


# ── Kill switch ─────────────────────────────────────────────────────────────


@router.post("/bots/{slug}/kill", response_model=KillSwitchResponse)
async def kill_switch_endpoint(
    slug: str,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> KillSwitchResponse:
    """Activate the kill switch.  Owner only.

    Sets ``kill_switch_active=True``, cancels every queued run, and
    pauses every running scan.  Writes both an audit row and a
    safety_event row.
    """
    _ensure_rtxrt_slug(slug)
    entry = await _get_bot_or_404(slug, session)
    actor_id, actor_email = actor_from_auth(auth)
    cancelled, paused = await activate_kill_switch(session, entry=entry)
    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="kill_switch.activated",
        target_type="bot",
        target_id=slug,
        outcome="success",
        safe_summary=f"kill switch activated cancelled={cancelled} paused={paused}",
        request=request,
    )
    await session.commit()
    await session.refresh(entry)
    return KillSwitchResponse(
        slug=slug,
        kill_switch_active=entry.kill_switch_active,
        cancelled_runs=cancelled,
        paused_runs=paused,
    )


# ── Audit log ───────────────────────────────────────────────────────────────


@router.get("/audit-log/{slug}", response_model=list[AuditEventResponse])
async def get_bot_audit_log(
    slug: str,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> list[AuditEventResponse]:
    """Return audit events scoped to this bot or its runs.  Operator or owner.

    Filters by ``target_type in ('bot', 'bot_run')`` and matches either
    ``target_id == slug`` (for bot-scoped actions) or
    ``actor took action on a bot_run that belongs to this bot``.
    """
    entry = await _get_bot_or_404(slug, session)
    if not _can_view(role, entry):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    bot_targeted = await session.exec(
        select(AuditEvent).where(
            AuditEvent.target_type == "bot",
            AuditEvent.target_id == slug,
        )
    )
    bot_rows = list(bot_targeted.all())

    run_ids_result = await session.exec(select(BotRun.id).where(BotRun.bot_id == entry.id))
    run_ids = {str(rid) for rid in run_ids_result.all()}
    run_targeted: list[AuditEvent] = []
    if run_ids:
        run_target_result = await session.exec(
            select(AuditEvent).where(AuditEvent.target_type == "bot_run")
        )
        run_targeted = [r for r in run_target_result.all() if r.target_id in run_ids]

    combined = sorted(
        bot_rows + run_targeted,
        key=lambda e: e.created_at,
        reverse=True,
    )

    return [
        AuditEventResponse(
            id=str(e.id),
            actor_clerk_user_id=e.actor_clerk_user_id,
            actor_email=e.actor_email,
            actor_role=e.actor_role,
            action=e.action,
            target_type=e.target_type,
            target_id=e.target_id,
            outcome=e.outcome,
            safe_summary=e.safe_summary,
            payload_hash=e.payload_hash,
            ip_address=e.ip_address,
            created_at=e.created_at,
        )
        for e in combined
    ]


# ── Sandbox convenience endpoint ────────────────────────────────────────────


class SandboxRunRequest(BaseModel):
    bot_slug: str
    profile_id: str
    profile_name: str
    message: str
    target_count: int = PField(gt=0, le=10_000)


@router.post("/sandbox/run", response_model=BotRunResponse)
async def sandbox_run(
    body: SandboxRunRequest,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotRunResponse:
    """Convenience endpoint: create + start a sandbox run in one call.

    Owner only.  Same safety semantics as the per-bot endpoints —
    everything goes through the same gates.
    """
    _ensure_rtxrt_slug(body.bot_slug)
    entry = await _get_bot_or_404(body.bot_slug, session)
    actor_id, actor_email = actor_from_auth(auth)

    create_result = await create_draft_run(
        session,
        entry=entry,
        profile_id=body.profile_id,
        profile_name=body.profile_name,
        target_count=body.target_count,
        message=body.message,
        created_by=actor_id,
    )
    if not create_result.ok or create_result.run is None:
        await record_audit(
            session,
            actor_clerk_user_id=actor_id,
            actor_email=actor_email,
            actor_role=role,
            action="sandbox.run.denied",
            target_type="bot",
            target_id=body.bot_slug,
            outcome="denied",
            safe_summary=f"sandbox run denied: {create_result.error_code}",
            request=request,
        )
        await session.commit()
        if create_result.error_code == LIVE_WRITES_DISABLED_ERROR:
            raise _live_writes_disabled()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": create_result.error_code,
                "detail": create_result.error_detail,
            },
        )

    run = create_result.run
    start_result = await _start_sandbox_run_service(session, entry=entry, run=run)
    if not start_result.ok:
        await session.commit()
        if start_result.error_code == LIVE_WRITES_DISABLED_ERROR:
            raise _live_writes_disabled()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": start_result.error_code},
        )

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="sandbox.run.completed",
        target_type="bot_run",
        target_id=str(run.id),
        outcome="success",
        safe_summary=(
            f"sandbox run completed scan={run.scan_count} "
            f"readonly={run.readonly_count} sent={run.sent_count}"
        ),
        request=request,
    )
    await session.commit()
    await session.refresh(run)
    return _to_run_response(run, body.bot_slug)


# Re-export so test modules can import the router directly.
__all__ = [
    "LIVE_WRITES_DISABLED_ERROR",
    "MAX_MESSAGE_PREVIEW_CHARS",
    "router",
    "truncate_message_preview",
]
