"""Build Requests API — structured COO/operator change-request workflow.

Endpoints (all under ``/api/v1/build-requests``):

  GET    /                              list (role-filtered visibility)
  POST   /                              create  (operator+; owner ok)
  GET    /{id}                          single  (visibility-checked)
  PATCH  /{id}                          edit    (author or owner; status-gated)
  POST   /{id}/submit                   draft|needs_changes -> submitted
  POST   /{id}/approve                  owner-only (submitted|needs_changes -> approved)
  POST   /{id}/reject                   owner-only (-> rejected, terminal)
  POST   /{id}/request-changes          owner-only (submitted -> needs_changes)
  POST   /{id}/cancel                   author or owner (-> cancelled, terminal)
  POST   /{id}/mark-building            owner-only (approved -> building)
  POST   /{id}/mark-completed           owner-only (building|approved -> completed)

Hard rules enforced here:
  • No git commands run.  No gh commands run.  No subprocess calls.
  • No branch is created.  ``requested_branch_name`` is metadata only.
  • No deploy is triggered.  No Claude Code worker is started.
  • Free-text fields are scrubbed for secret-looking substrings via
    ``app.services.build_requests.validate_no_secrets``.
  • ``safe_mode_required`` is sticky-ON — caller cannot set it False
    via create or update in v1.
  • Audit rows are written for every mutating endpoint.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlmodel import select

from app.api.mc_roles import (
    get_mc_role,
    require_operator,
    require_owner,
)
from app.core.auth import AuthContext, get_auth_context
from app.core.logging import get_logger
from app.core.time import utcnow
from app.db.session import get_session
from app.models.build_request import (
    STATUS_APPROVED,
    STATUS_BUILDING,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_NEEDS_CHANGES,
    STATUS_REJECTED,
    STATUS_SUBMITTED,
    VALID_STATUSES,
    BuildRequest,
)
from app.services.audit_log import actor_from_auth, record_audit
from app.services.build_requests import (
    BuildRequestFields,
    SecretLikeFieldError,
    can_view,
    is_operator_editable,
    is_owner_role,
    normalize_slug,
    validate_no_secrets,
    validate_priority,
    validate_request_type,
    validate_risk_level,
    validate_string_list,
    validate_transition,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/build-requests", tags=["build-requests"])
logger = get_logger(__name__)

AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)
ROLE_DEP = Depends(get_mc_role)
OPERATOR_DEP = Depends(require_operator)
OWNER_DEP = Depends(require_owner)


# ── Response schemas (privacy-reviewed) ────────────────────────────────────


class BuildRequestResponse(BaseModel):
    """Public-safe view of a ``BuildRequest``.

    Adding a field requires re-confirming it does NOT carry secrets,
    webhook URLs, cookies, fan PII, or message bodies.
    """

    id: UUID
    title: str
    slug: str
    request_type: str
    summary: str
    description: str | None
    business_reason: str | None
    requested_by_user_id: str
    requested_by_email: str | None
    requested_by_role: str | None
    status: str
    priority: str
    risk_level: str
    target_area: str | None
    related_bot_draft_id: UUID | None
    related_agent_id: UUID | None
    requested_branch_name: str | None
    approved_by_user_id: str | None
    approved_at: datetime | None
    rejected_by_user_id: str | None
    rejected_at: datetime | None
    rejection_reason: str | None
    owner_notes: str | None
    safe_mode_required: bool
    external_actions_requested: bool
    secrets_required: bool
    platforms_requested: list[str] | None
    acceptance_criteria: list[str] | None
    created_at: datetime
    updated_at: datetime


class BuildRequestCreateRequest(BaseModel):
    title: str
    request_type: str
    summary: str
    slug: str | None = None
    description: str | None = None
    business_reason: str | None = None
    priority: str = "normal"
    risk_level: str = "low"
    target_area: str | None = None
    related_bot_draft_id: UUID | None = None
    related_agent_id: UUID | None = None
    requested_branch_name: str | None = None
    external_actions_requested: bool = False
    secrets_required: bool = False
    platforms_requested: list[str] | None = None
    acceptance_criteria: list[str] | None = None


class BuildRequestUpdateRequest(BaseModel):
    title: str | None = None
    request_type: str | None = None
    summary: str | None = None
    description: str | None = None
    business_reason: str | None = None
    priority: str | None = None
    risk_level: str | None = None
    target_area: str | None = None
    related_bot_draft_id: UUID | None = None
    related_agent_id: UUID | None = None
    requested_branch_name: str | None = None
    external_actions_requested: bool | None = None
    secrets_required: bool | None = None
    platforms_requested: list[str] | None = None
    acceptance_criteria: list[str] | None = None


class OwnerNoteBody(BaseModel):
    notes: str | None = None


class RejectBody(BaseModel):
    reason: str


class RequestChangesBody(BaseModel):
    notes: str


class CancelBody(BaseModel):
    notes: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────────


def _to_response(row: BuildRequest) -> BuildRequestResponse:
    return BuildRequestResponse(
        id=row.id,
        title=row.title,
        slug=row.slug,
        request_type=row.request_type,
        summary=row.summary,
        description=row.description,
        business_reason=row.business_reason,
        requested_by_user_id=row.requested_by_user_id,
        requested_by_email=row.requested_by_email,
        requested_by_role=row.requested_by_role,
        status=row.status,
        priority=row.priority,
        risk_level=row.risk_level,
        target_area=row.target_area,
        related_bot_draft_id=row.related_bot_draft_id,
        related_agent_id=row.related_agent_id,
        requested_branch_name=row.requested_branch_name,
        approved_by_user_id=row.approved_by_user_id,
        approved_at=row.approved_at,
        rejected_by_user_id=row.rejected_by_user_id,
        rejected_at=row.rejected_at,
        rejection_reason=row.rejection_reason,
        owner_notes=row.owner_notes,
        safe_mode_required=row.safe_mode_required,
        external_actions_requested=row.external_actions_requested,
        secrets_required=row.secrets_required,
        platforms_requested=row.platforms_requested,
        acceptance_criteria=row.acceptance_criteria,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _get_or_404(req_id: UUID, session: "AsyncSession") -> BuildRequest:
    row = (await session.exec(select(BuildRequest).where(BuildRequest.id == req_id))).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Build request '{req_id}' not found.",
        )
    return row


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _check_visibility(role: str, actor_id: str, row: BuildRequest) -> None:
    if not can_view(role, actor_id, row):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Build request not found.",
        )


def _validate_create(
    body: BuildRequestCreateRequest,
) -> tuple[str, list[str] | None, list[str] | None]:
    try:
        validate_request_type(body.request_type)
        validate_priority(body.priority)
        validate_risk_level(body.risk_level)
        slug = normalize_slug(body.slug, fallback_from=body.title)
        platforms = validate_string_list(body.platforms_requested, field="platforms_requested")
        acs = validate_string_list(body.acceptance_criteria, field="acceptance_criteria")
    except ValueError as exc:
        raise _bad(str(exc)) from exc

    try:
        validate_no_secrets(
            BuildRequestFields(
                title=body.title,
                summary=body.summary,
                description=body.description,
                business_reason=body.business_reason,
                target_area=body.target_area,
                requested_branch_name=body.requested_branch_name,
                platforms_requested=platforms,
                acceptance_criteria=acs,
            ),
        )
    except SecretLikeFieldError as exc:
        raise _bad(str(exc)) from exc

    return slug, platforms, acs


def _validate_update(body: BuildRequestUpdateRequest) -> tuple[list[str] | None, list[str] | None]:
    try:
        if body.request_type is not None:
            validate_request_type(body.request_type)
        if body.priority is not None:
            validate_priority(body.priority)
        if body.risk_level is not None:
            validate_risk_level(body.risk_level)
        platforms = validate_string_list(body.platforms_requested, field="platforms_requested")
        acs = validate_string_list(body.acceptance_criteria, field="acceptance_criteria")
    except ValueError as exc:
        raise _bad(str(exc)) from exc

    try:
        validate_no_secrets(
            BuildRequestFields(
                title=body.title,
                summary=body.summary,
                description=body.description,
                business_reason=body.business_reason,
                target_area=body.target_area,
                requested_branch_name=body.requested_branch_name,
                platforms_requested=platforms if body.platforms_requested is not None else None,
                acceptance_criteria=acs if body.acceptance_criteria is not None else None,
            ),
        )
    except SecretLikeFieldError as exc:
        raise _bad(str(exc)) from exc
    return platforms, acs


def _apply_transition(row: BuildRequest, action: str) -> None:
    try:
        validate_transition(action, row.status)
    except ValueError as exc:
        raise _conflict(str(exc)) from exc


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("", response_model=list[BuildRequestResponse])
async def list_build_requests(
    auth: AuthContext = AUTH_DEP,
    role: str = ROLE_DEP,
    session: "AsyncSession" = SESSION_DEP,
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[BuildRequestResponse]:
    """List build requests visible to the current user.

    Owner sees all rows; everyone else sees only their own.  Optional
    ``?status=`` filter narrows the list.
    """
    if status_filter is not None and status_filter not in VALID_STATUSES:
        raise _bad(
            f"Invalid status '{status_filter}'. Valid: {sorted(VALID_STATUSES)}",
        )
    actor_id, _ = actor_from_auth(auth)
    rows = (await session.exec(select(BuildRequest))).all()
    visible = [r for r in rows if can_view(role, actor_id, r)]
    if status_filter is not None:
        visible = [r for r in visible if r.status == status_filter]
    visible.sort(key=lambda r: r.created_at, reverse=True)
    return [_to_response(r) for r in visible]


@router.post(
    "",
    response_model=BuildRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_build_request(
    body: BuildRequestCreateRequest,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BuildRequestResponse:
    """Create a new build request.  Operator or owner only.

    Always starts in ``draft`` status.  ``safe_mode_required`` is forced
    True regardless of body input — there is no path through the API to
    create a build request that opts out of safe mode in v1.
    """
    slug, platforms, acs = _validate_create(body)

    existing = (await session.exec(select(BuildRequest).where(BuildRequest.slug == slug))).first()
    if existing is not None:
        raise _conflict(f"Slug '{slug}' is already used by another build request.")

    actor_id, actor_email = actor_from_auth(auth)
    now = utcnow()
    row = BuildRequest(
        title=body.title.strip(),
        slug=slug,
        request_type=body.request_type,
        summary=body.summary.strip(),
        description=(body.description.strip() if body.description else None),
        business_reason=(body.business_reason.strip() if body.business_reason else None),
        requested_by_user_id=actor_id,
        requested_by_email=actor_email,
        requested_by_role=role,
        status="draft",
        priority=body.priority,
        risk_level=body.risk_level,
        target_area=(body.target_area.strip() if body.target_area else None),
        related_bot_draft_id=body.related_bot_draft_id,
        related_agent_id=body.related_agent_id,
        requested_branch_name=(
            body.requested_branch_name.strip() if body.requested_branch_name else None
        ),
        # Sticky-on regardless of caller input.
        safe_mode_required=True,
        external_actions_requested=body.external_actions_requested,
        secrets_required=body.secrets_required,
        platforms_requested=platforms,
        acceptance_criteria=acs,
        created_at=now,
        updated_at=now,
    )
    session.add(row)

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="build_request.create",
        target_type="build_request",
        target_id=slug,
        outcome="success",
        safe_summary=(
            f"created slug={slug} type={body.request_type} "
            f"risk={body.risk_level} priority={body.priority}"
        ),
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.get("/{req_id}", response_model=BuildRequestResponse)
async def get_build_request(
    req_id: UUID,
    auth: AuthContext = AUTH_DEP,
    role: str = ROLE_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BuildRequestResponse:
    actor_id, _ = actor_from_auth(auth)
    row = await _get_or_404(req_id, session)
    _check_visibility(role, actor_id, row)
    return _to_response(row)


@router.patch("/{req_id}", response_model=BuildRequestResponse)
async def update_build_request(
    req_id: UUID,
    body: BuildRequestUpdateRequest,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = ROLE_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BuildRequestResponse:
    """Edit an existing build request.

    • Owner may edit any non-terminal row.
    • Author may edit only while the row is in ``draft`` or
      ``needs_changes``.
    • Other operators cannot edit someone else's request.
    """
    actor_id, actor_email = actor_from_auth(auth)
    row = await _get_or_404(req_id, session)
    _check_visibility(role, actor_id, row)

    if row.status in {STATUS_REJECTED, STATUS_CANCELLED, STATUS_COMPLETED}:
        raise _conflict(
            f"Build request is in terminal state '{row.status}' and cannot be edited.",
        )

    is_owner = is_owner_role(role)
    is_author = row.requested_by_user_id == actor_id

    if not is_owner:
        if not is_author:
            raise _forbidden("You can only edit build requests you created.")
        if not is_operator_editable(row.status):
            raise _conflict(
                f"Build request status '{row.status}' is not editable by the requester. "
                "Wait for owner action or ask for changes.",
            )

    platforms, acs = _validate_update(body)

    if body.title is not None:
        row.title = body.title.strip()
    if body.request_type is not None:
        row.request_type = body.request_type
    if body.summary is not None:
        row.summary = body.summary.strip()
    if body.description is not None:
        row.description = body.description.strip() or None
    if body.business_reason is not None:
        row.business_reason = body.business_reason.strip() or None
    if body.priority is not None:
        row.priority = body.priority
    if body.risk_level is not None:
        row.risk_level = body.risk_level
    if body.target_area is not None:
        row.target_area = body.target_area.strip() or None
    if body.related_bot_draft_id is not None:
        row.related_bot_draft_id = body.related_bot_draft_id
    if body.related_agent_id is not None:
        row.related_agent_id = body.related_agent_id
    if body.requested_branch_name is not None:
        row.requested_branch_name = body.requested_branch_name.strip() or None
    if body.external_actions_requested is not None:
        row.external_actions_requested = body.external_actions_requested
    if body.secrets_required is not None:
        row.secrets_required = body.secrets_required
    if body.platforms_requested is not None:
        row.platforms_requested = platforms
    if body.acceptance_criteria is not None:
        row.acceptance_criteria = acs

    # Sticky-on regardless of body input.
    row.safe_mode_required = True

    row.updated_at = utcnow()
    session.add(row)

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="build_request.update",
        target_type="build_request",
        target_id=row.slug,
        outcome="success",
        safe_summary=f"updated slug={row.slug} status={row.status}",
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.post("/{req_id}/submit", response_model=BuildRequestResponse)
async def submit_build_request(
    req_id: UUID,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = ROLE_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BuildRequestResponse:
    """Author submits their request for owner review.

    Operators may only submit requests they themselves authored.  Owners
    may submit any.
    """
    actor_id, actor_email = actor_from_auth(auth)
    row = await _get_or_404(req_id, session)
    _check_visibility(role, actor_id, row)

    if not is_owner_role(role) and row.requested_by_user_id != actor_id:
        raise _forbidden("You can only submit build requests you created.")

    _apply_transition(row, "submit")
    row.status = STATUS_SUBMITTED
    row.updated_at = utcnow()
    session.add(row)

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="build_request.submit",
        target_type="build_request",
        target_id=row.slug,
        outcome="success",
        safe_summary=f"submitted slug={row.slug}",
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.post("/{req_id}/approve", response_model=BuildRequestResponse)
async def approve_build_request(
    req_id: UUID,
    request: Request,
    body: OwnerNoteBody = OwnerNoteBody(),
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BuildRequestResponse:
    """Owner-only: approve a submitted/needs-changes request.

    Approval is a *spec sign-off only* — no code generation runs, no
    branch is created, no deploy is triggered.
    """
    actor_id, actor_email = actor_from_auth(auth)
    row = await _get_or_404(req_id, session)
    _apply_transition(row, "approve")

    if body.notes:
        try:
            validate_no_secrets(BuildRequestFields(owner_notes=body.notes))
        except SecretLikeFieldError as exc:
            raise _bad(str(exc)) from exc
        row.owner_notes = body.notes.strip() or None

    now = utcnow()
    row.status = STATUS_APPROVED
    row.approved_by_user_id = actor_id
    row.approved_at = now
    row.updated_at = now
    session.add(row)

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="build_request.approve",
        target_type="build_request",
        target_id=row.slug,
        outcome="success",
        safe_summary=(f"approved slug={row.slug} (spec sign-off only — no build runs in v1)"),
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.post("/{req_id}/reject", response_model=BuildRequestResponse)
async def reject_build_request(
    req_id: UUID,
    body: RejectBody,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BuildRequestResponse:
    """Owner-only: reject a submitted/needs-changes request (terminal)."""
    if not body.reason or not body.reason.strip():
        raise _bad("Rejection requires a reason.")
    try:
        validate_no_secrets(BuildRequestFields(rejection_reason=body.reason))
    except SecretLikeFieldError as exc:
        raise _bad(str(exc)) from exc

    actor_id, actor_email = actor_from_auth(auth)
    row = await _get_or_404(req_id, session)
    _apply_transition(row, "reject")

    now = utcnow()
    row.status = STATUS_REJECTED
    row.rejected_by_user_id = actor_id
    row.rejected_at = now
    row.rejection_reason = body.reason.strip()
    row.updated_at = now
    session.add(row)

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="build_request.reject",
        target_type="build_request",
        target_id=row.slug,
        outcome="success",
        safe_summary=f"rejected slug={row.slug}",
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.post("/{req_id}/request-changes", response_model=BuildRequestResponse)
async def request_changes_build_request(
    req_id: UUID,
    body: RequestChangesBody,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BuildRequestResponse:
    """Owner-only: send a submitted request back for revision."""
    if not body.notes or not body.notes.strip():
        raise _bad("Change request requires notes.")
    try:
        validate_no_secrets(BuildRequestFields(owner_notes=body.notes))
    except SecretLikeFieldError as exc:
        raise _bad(str(exc)) from exc

    actor_id, actor_email = actor_from_auth(auth)
    row = await _get_or_404(req_id, session)
    _apply_transition(row, "request_changes")

    row.status = STATUS_NEEDS_CHANGES
    row.owner_notes = body.notes.strip()
    row.updated_at = utcnow()
    session.add(row)

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="build_request.request_changes",
        target_type="build_request",
        target_id=row.slug,
        outcome="success",
        safe_summary=f"changes requested slug={row.slug}",
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.post("/{req_id}/cancel", response_model=BuildRequestResponse)
async def cancel_build_request(
    req_id: UUID,
    request: Request,
    body: CancelBody = CancelBody(),
    auth: AuthContext = AUTH_DEP,
    role: str = ROLE_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BuildRequestResponse:
    """Cancel a build request (terminal).

    • Author may cancel while in draft / submitted / needs_changes.
    • Owner may additionally cancel approved or building requests.
    """
    actor_id, actor_email = actor_from_auth(auth)
    row = await _get_or_404(req_id, session)
    _check_visibility(role, actor_id, row)

    is_owner = is_owner_role(role)
    is_author = row.requested_by_user_id == actor_id

    if not is_owner and not is_author:
        raise _forbidden("You can only cancel build requests you created.")

    action = "cancel_owner" if is_owner else "cancel_operator"
    _apply_transition(row, action)

    if body.notes:
        try:
            validate_no_secrets(BuildRequestFields(owner_notes=body.notes))
        except SecretLikeFieldError as exc:
            raise _bad(str(exc)) from exc
        row.owner_notes = body.notes.strip() or None

    row.status = STATUS_CANCELLED
    row.updated_at = utcnow()
    session.add(row)

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="build_request.cancel",
        target_type="build_request",
        target_id=row.slug,
        outcome="success",
        safe_summary=f"cancelled slug={row.slug} by={'owner' if is_owner else 'author'}",
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.post("/{req_id}/mark-building", response_model=BuildRequestResponse)
async def mark_building_build_request(
    req_id: UUID,
    request: Request,
    body: OwnerNoteBody = OwnerNoteBody(),
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BuildRequestResponse:
    """Owner-only: mark an approved request as actively being built.

    This is metadata only.  v1 does not start a builder, run a worker,
    or invoke any code generation.  The owner sets this flag manually
    when they pick the request up for work elsewhere.
    """
    actor_id, actor_email = actor_from_auth(auth)
    row = await _get_or_404(req_id, session)
    _apply_transition(row, "mark_building")

    if body.notes:
        try:
            validate_no_secrets(BuildRequestFields(owner_notes=body.notes))
        except SecretLikeFieldError as exc:
            raise _bad(str(exc)) from exc
        row.owner_notes = body.notes.strip() or None

    row.status = STATUS_BUILDING
    row.updated_at = utcnow()
    session.add(row)

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="build_request.mark_building",
        target_type="build_request",
        target_id=row.slug,
        outcome="success",
        safe_summary=(f"marked building slug={row.slug} (no worker started — metadata only)"),
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.post("/{req_id}/mark-completed", response_model=BuildRequestResponse)
async def mark_completed_build_request(
    req_id: UUID,
    request: Request,
    body: OwnerNoteBody = OwnerNoteBody(),
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BuildRequestResponse:
    """Owner-only: mark a building/approved request as completed (terminal)."""
    actor_id, actor_email = actor_from_auth(auth)
    row = await _get_or_404(req_id, session)
    _apply_transition(row, "mark_completed")

    if body.notes:
        try:
            validate_no_secrets(BuildRequestFields(owner_notes=body.notes))
        except SecretLikeFieldError as exc:
            raise _bad(str(exc)) from exc
        row.owner_notes = body.notes.strip() or None

    row.status = STATUS_COMPLETED
    row.updated_at = utcnow()
    session.add(row)

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="build_request.mark_completed",
        target_type="build_request",
        target_id=row.slug,
        outcome="success",
        safe_summary=f"marked completed slug={row.slug}",
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _to_response(row)
