"""Bot Drafts API — sandbox-only authoring surface for the Bot Builder UI.

Endpoints (all under ``/api/v1/bot-drafts``):

  GET    /                          list drafts (any authenticated role)
  GET    /{id}                      single draft (any authenticated role)
  POST   /                          create  (operator+)
  PATCH  /{id}                      update  (operator+)
  POST   /{id}/archive              archive (operator+)
  POST   /{id}/request-approval     flip status to pending_approval (operator+)
  POST   /{id}/approve              flip status to approved (owner only)

Privacy contract:
  • Responses NEVER contain secrets, tokens, cookies, webhook URLs, or
    fan PII.  The shape is constrained by ``BotDraftResponse`` below
    and reviewed for sensitivity on every change.
  • Caller-supplied free-text is run through
    ``app.services.bot_drafts.validate_no_secrets`` before persistence.
    Strings that look like API keys, bearer tokens, cookie material,
    or DSN URLs are rejected with HTTP 400.
  • There is no activation endpoint in v1.  The API ends at
    ``approved`` — actual execution is intentionally out of scope.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
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
from app.models.bot_draft import (
    DRAFT_STATUS_APPROVED,
    DRAFT_STATUS_ARCHIVED,
    DRAFT_STATUS_DRAFT,
    DRAFT_STATUS_PENDING,
    VALID_RISK_LEVELS,
    BotDraft,
)
from app.services.audit_log import actor_from_auth, record_audit
from app.services.bot_drafts import (
    DraftFields,
    SecretLikeFieldError,
    encode_tools_needed,
    normalize_slug,
    parse_tools_needed,
    validate_no_secrets,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter(prefix="/bot-drafts", tags=["bot-drafts"])
logger = get_logger(__name__)

AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)
ROLE_DEP = Depends(get_mc_role)
OPERATOR_DEP = Depends(require_operator)
OWNER_DEP = Depends(require_owner)


# ── Response schemas (no secrets) ───────────────────────────────────────────


class BotDraftResponse(BaseModel):
    """Public-safe view of a ``BotDraft``.

    Adding a new field requires re-confirming it does NOT carry secrets,
    webhook URLs, cookies, fan PII, or message bodies.  Keep this
    contract tight.
    """

    id: UUID
    slug: str
    name: str
    purpose: str
    category: str
    description: str | None
    owner: str | None
    status: str
    sandbox_mode: bool
    risk_level: str
    approval_required: bool
    trigger_type: str | None
    input_requirements: str | None
    output_requirements: str | None
    prompt_template: str | None
    dashboard_notes: str | None
    tools_needed: list[str]
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime


class BotDraftCreateRequest(BaseModel):
    slug: str
    name: str
    purpose: str
    category: str
    description: str | None = None
    owner: str | None = None
    sandbox_mode: bool = True
    risk_level: str = "low"
    approval_required: bool = True
    trigger_type: str | None = None
    input_requirements: str | None = None
    output_requirements: str | None = None
    prompt_template: str | None = None
    dashboard_notes: str | None = None
    tools_needed: list[str] | None = None


class BotDraftUpdateRequest(BaseModel):
    name: str | None = None
    purpose: str | None = None
    category: str | None = None
    description: str | None = None
    owner: str | None = None
    sandbox_mode: bool | None = None
    risk_level: str | None = None
    approval_required: bool | None = None
    trigger_type: str | None = None
    input_requirements: str | None = None
    output_requirements: str | None = None
    prompt_template: str | None = None
    dashboard_notes: str | None = None
    tools_needed: list[str] | None = None


# ── Helpers ─────────────────────────────────────────────────────────────────


def _to_response(row: BotDraft) -> BotDraftResponse:
    return BotDraftResponse(
        id=row.id,
        slug=row.slug,
        name=row.name,
        purpose=row.purpose,
        category=row.category,
        description=row.description,
        owner=row.owner,
        status=row.status,
        sandbox_mode=row.sandbox_mode,
        risk_level=row.risk_level,
        approval_required=row.approval_required,
        trigger_type=row.trigger_type,
        input_requirements=row.input_requirements,
        output_requirements=row.output_requirements,
        prompt_template=row.prompt_template,
        dashboard_notes=row.dashboard_notes,
        tools_needed=parse_tools_needed(row.tools_needed_json),
        created_by=row.created_by,
        updated_by=row.updated_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _get_draft_or_404(draft_id: UUID, session: "AsyncSession") -> BotDraft:
    row = (await session.exec(select(BotDraft).where(BotDraft.id == draft_id))).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bot draft '{draft_id}' not found.",
        )
    return row


def _validate_create(body: BotDraftCreateRequest) -> str:
    """Run all create-time validations.  Returns the normalized slug."""
    try:
        slug = normalize_slug(body.slug)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if body.risk_level not in VALID_RISK_LEVELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid risk_level '{body.risk_level}'. "
            f"Valid: {sorted(VALID_RISK_LEVELS)}",
        )

    try:
        validate_no_secrets(
            DraftFields(
                name=body.name,
                purpose=body.purpose,
                category=body.category,
                description=body.description,
                owner=body.owner,
                trigger_type=body.trigger_type,
                input_requirements=body.input_requirements,
                output_requirements=body.output_requirements,
                prompt_template=body.prompt_template,
                dashboard_notes=body.dashboard_notes,
                tools_needed=tuple(body.tools_needed or ()),
            ),
        )
    except SecretLikeFieldError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return slug


def _validate_update(body: BotDraftUpdateRequest) -> None:
    if body.risk_level is not None and body.risk_level not in VALID_RISK_LEVELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid risk_level '{body.risk_level}'. "
            f"Valid: {sorted(VALID_RISK_LEVELS)}",
        )
    try:
        validate_no_secrets(
            DraftFields(
                name=body.name,
                purpose=body.purpose,
                category=body.category,
                description=body.description,
                owner=body.owner,
                trigger_type=body.trigger_type,
                input_requirements=body.input_requirements,
                output_requirements=body.output_requirements,
                prompt_template=body.prompt_template,
                dashboard_notes=body.dashboard_notes,
                tools_needed=(tuple(body.tools_needed) if body.tools_needed is not None else None),
            ),
        )
    except SecretLikeFieldError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("", response_model=list[BotDraftResponse])
async def list_bot_drafts(
    _: AuthContext = AUTH_DEP,
    _role: str = ROLE_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> list[BotDraftResponse]:
    """List all drafts.  Visible to any authenticated user; mutations are role-gated below."""
    rows = (await session.exec(select(BotDraft))).all()
    return [
        _to_response(row)
        for row in sorted(rows, key=lambda r: (r.status != DRAFT_STATUS_DRAFT, r.created_at))
    ]


@router.get("/{draft_id}", response_model=BotDraftResponse)
async def get_bot_draft(
    draft_id: UUID,
    _: AuthContext = AUTH_DEP,
    _role: str = ROLE_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotDraftResponse:
    return _to_response(await _get_draft_or_404(draft_id, session))


@router.post(
    "",
    response_model=BotDraftResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_bot_draft(
    body: BotDraftCreateRequest,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotDraftResponse:
    """Create a new draft.  Operator or owner only.

    The new row always starts in ``draft`` status with sandbox_mode=True
    enforced server-side regardless of what the caller sent.  Status
    transitions happen via the dedicated endpoints below.
    """
    slug = _validate_create(body)

    # Slug uniqueness — fail fast with a clear message instead of an
    # IntegrityError up the stack.
    existing = (await session.exec(select(BotDraft).where(BotDraft.slug == slug))).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Slug '{slug}' is already used by another bot draft.",
        )

    actor_id, actor_email = actor_from_auth(auth)
    now = utcnow()
    row = BotDraft(
        slug=slug,
        name=body.name.strip(),
        purpose=body.purpose.strip(),
        category=body.category.strip(),
        description=(body.description.strip() if body.description else None),
        owner=(body.owner.strip() if body.owner else None),
        status=DRAFT_STATUS_DRAFT,
        # Sandbox mode is sticky-on in v1.  The model already defaults it,
        # but we re-assert here so a future caller can never disable it
        # via the create flow.
        sandbox_mode=True,
        risk_level=body.risk_level,
        approval_required=body.approval_required,
        trigger_type=body.trigger_type,
        input_requirements=body.input_requirements,
        output_requirements=body.output_requirements,
        prompt_template=body.prompt_template,
        dashboard_notes=body.dashboard_notes,
        tools_needed_json=encode_tools_needed(body.tools_needed),
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="bot_draft.create",
        target_type="bot_draft",
        target_id=slug,
        outcome="success",
        safe_summary=f"created slug={slug} risk={body.risk_level}",
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.patch("/{draft_id}", response_model=BotDraftResponse)
async def update_bot_draft(
    draft_id: UUID,
    body: BotDraftUpdateRequest,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotDraftResponse:
    """Edit an existing draft.  Operator or owner only.

    Sandbox mode is forced True regardless of what the caller sends —
    no path through the API can flip a draft into non-sandbox mode in v1.
    Status transitions only via the dedicated endpoints.
    """
    _validate_update(body)
    row = await _get_draft_or_404(draft_id, session)

    if row.status == DRAFT_STATUS_ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived drafts cannot be edited.  Duplicate or restore first.",
        )

    actor_id, actor_email = actor_from_auth(auth)

    if body.name is not None:
        row.name = body.name.strip()
    if body.purpose is not None:
        row.purpose = body.purpose.strip()
    if body.category is not None:
        row.category = body.category.strip()
    if body.description is not None:
        row.description = body.description.strip() or None
    if body.owner is not None:
        row.owner = body.owner.strip() or None
    if body.risk_level is not None:
        row.risk_level = body.risk_level
    if body.approval_required is not None:
        row.approval_required = body.approval_required
    if body.trigger_type is not None:
        row.trigger_type = body.trigger_type
    if body.input_requirements is not None:
        row.input_requirements = body.input_requirements
    if body.output_requirements is not None:
        row.output_requirements = body.output_requirements
    if body.prompt_template is not None:
        row.prompt_template = body.prompt_template
    if body.dashboard_notes is not None:
        row.dashboard_notes = body.dashboard_notes
    if body.tools_needed is not None:
        row.tools_needed_json = encode_tools_needed(body.tools_needed)

    # Sandbox mode is sticky-on regardless of body input.  We accept the
    # field for forward-compatibility but never honour a False value.
    row.sandbox_mode = True

    row.updated_by = actor_id
    row.updated_at = utcnow()
    session.add(row)

    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="bot_draft.update",
        target_type="bot_draft",
        target_id=row.slug,
        outcome="success",
        safe_summary=f"updated slug={row.slug}",
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.post("/{draft_id}/archive", response_model=BotDraftResponse)
async def archive_bot_draft(
    draft_id: UUID,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotDraftResponse:
    row = await _get_draft_or_404(draft_id, session)
    actor_id, actor_email = actor_from_auth(auth)
    if row.status != DRAFT_STATUS_ARCHIVED:
        row.status = DRAFT_STATUS_ARCHIVED
        row.updated_by = actor_id
        row.updated_at = utcnow()
        session.add(row)
    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="bot_draft.archive",
        target_type="bot_draft",
        target_id=row.slug,
        outcome="success",
        safe_summary=f"archived slug={row.slug}",
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.post("/{draft_id}/request-approval", response_model=BotDraftResponse)
async def request_bot_draft_approval(
    draft_id: UUID,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OPERATOR_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotDraftResponse:
    """Move a draft from ``draft`` to ``pending_approval``."""
    row = await _get_draft_or_404(draft_id, session)
    if row.status not in (DRAFT_STATUS_DRAFT, DRAFT_STATUS_PENDING):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Draft is in '{row.status}' state and cannot be re-submitted for approval.",
        )
    actor_id, actor_email = actor_from_auth(auth)
    row.status = DRAFT_STATUS_PENDING
    row.updated_by = actor_id
    row.updated_at = utcnow()
    session.add(row)
    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="bot_draft.approval_requested",
        target_type="bot_draft",
        target_id=row.slug,
        outcome="success",
        safe_summary=f"approval requested for slug={row.slug}",
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _to_response(row)


@router.post("/{draft_id}/approve", response_model=BotDraftResponse)
async def approve_bot_draft(
    draft_id: UUID,
    request: Request,
    auth: AuthContext = AUTH_DEP,
    role: str = OWNER_DEP,
    session: "AsyncSession" = SESSION_DEP,
) -> BotDraftResponse:
    """Owner-only: flip a pending draft to ``approved``.

    Approval here is a *spec sign-off* — it does NOT activate any live
    behaviour.  Bringing an approved draft into a running bot remains a
    deliberate, separate step that is intentionally out of scope for
    this sprint.
    """
    row = await _get_draft_or_404(draft_id, session)
    if row.status not in (DRAFT_STATUS_PENDING, DRAFT_STATUS_DRAFT):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Draft is in '{row.status}' state and cannot be approved.",
        )
    actor_id, actor_email = actor_from_auth(auth)
    row.status = DRAFT_STATUS_APPROVED
    row.updated_by = actor_id
    row.updated_at = utcnow()
    session.add(row)
    await record_audit(
        session,
        actor_clerk_user_id=actor_id,
        actor_email=actor_email,
        actor_role=role,
        action="bot_draft.approval_approved",
        target_type="bot_draft",
        target_id=row.slug,
        outcome="success",
        safe_summary=(f"approved slug={row.slug} (spec sign-off only — no live activation)"),
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return _to_response(row)
