"""Thin API wrappers for gateway CRUD and template synchronization."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from sqlmodel import col

from app.api.deps import require_org_admin
from app.core.auth import AuthContext, get_auth_context
from app.db import crud
from app.db.pagination import paginate
from app.db.session import get_session
from app.models.agents import Agent
from app.models.gateways import Gateway
from app.models.skills import GatewayInstalledSkill
from app.schemas.common import OkResponse
from app.schemas.gateways import (
    GatewayCreate,
    GatewayRead,
    GatewayTemplatesSyncResult,
    GatewayUpdate,
)
from app.schemas.pagination import DefaultLimitOffsetPage
from app.services.gateway_tokens import set_token as set_gateway_token
from app.services.openclaw.admin_service import GatewayAdminLifecycleService
from app.services.openclaw.session_service import GatewayTemplateSyncQuery

if TYPE_CHECKING:
    from fastapi_pagination.limit_offset import LimitOffsetPage
    from sqlmodel.ext.asyncio.session import AsyncSession

    from app.services.organizations import OrganizationContext


router = APIRouter(prefix="/gateways", tags=["gateways"])
SESSION_DEP = Depends(get_session)
AUTH_DEP = Depends(get_auth_context)
ORG_ADMIN_DEP = Depends(require_org_admin)
INCLUDE_MAIN_QUERY = Query(default=True)
RESET_SESSIONS_QUERY = Query(default=False)
ROTATE_TOKENS_QUERY = Query(default=False)
FORCE_BOOTSTRAP_QUERY = Query(default=False)
OVERWRITE_QUERY = Query(default=False)
LEAD_ONLY_QUERY = Query(default=False)
BOARD_ID_QUERY = Query(default=None)
_RUNTIME_TYPE_REFERENCES = (UUID,)


def _template_sync_query(
    *,
    include_main: bool = INCLUDE_MAIN_QUERY,
    lead_only: bool = LEAD_ONLY_QUERY,
    reset_sessions: bool = RESET_SESSIONS_QUERY,
    rotate_tokens: bool = ROTATE_TOKENS_QUERY,
    force_bootstrap: bool = FORCE_BOOTSTRAP_QUERY,
    overwrite: bool = OVERWRITE_QUERY,
    board_id: UUID | None = BOARD_ID_QUERY,
) -> GatewayTemplateSyncQuery:
    return GatewayTemplateSyncQuery(
        include_main=include_main,
        lead_only=lead_only,
        reset_sessions=reset_sessions,
        rotate_tokens=rotate_tokens,
        force_bootstrap=force_bootstrap,
        overwrite=overwrite,
        board_id=board_id,
    )


SYNC_QUERY_DEP = Depends(_template_sync_query)


def _mask_gateway_token(gateway: Gateway) -> Gateway:
    """Return a defensive copy of ``gateway`` with the legacy ``token``
    field nulled. Used by every read path that doesn't explicitly opt
    into raw-token disclosure.
    """
    from copy import copy as _copy

    masked = _copy(gateway)
    masked.token = None
    return masked


@router.get("", response_model=DefaultLimitOffsetPage[GatewayRead])
async def list_gateways(
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> LimitOffsetPage[GatewayRead]:
    """List gateways for the caller's organization.

    Sprint 5 cutover: every row's legacy ``token`` field is masked.
    Use ``GET /{gateway_id}?include_token=1`` for the legitimate
    edit-page disclosure path.
    """
    statement = (
        Gateway.objects.filter_by(organization_id=ctx.organization.id)
        .order_by(col(Gateway.created_at).desc())
        .statement
    )

    page: LimitOffsetPage[GatewayRead] = await paginate(session, statement)
    # Mask each row's legacy plaintext token. ``token_configured`` on
    # GatewayRead is derived in the schema validator and is unaffected.
    masked_items: list[GatewayRead] = []
    for g in page.items:
        gr = g.model_copy(update={"token": None})
        masked_items.append(gr)
    page.items = masked_items
    return page


@router.post("", response_model=GatewayRead)
async def create_gateway(
    payload: GatewayCreate,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> Gateway:
    """Create a gateway and provision or refresh its main agent.

    Sprint 3: the plaintext ``payload.token`` is encrypted via
    :func:`app.services.gateway_tokens.set_token` immediately after the
    row is created, so the legacy ``token`` column is never written to.
    """
    service = GatewayAdminLifecycleService(session)
    await service.assert_gateway_runtime_compatible(
        url=payload.url,
        token=payload.token,
        allow_insecure_tls=payload.allow_insecure_tls,
        disable_device_pairing=payload.disable_device_pairing,
    )
    data = payload.model_dump()
    plaintext_token = data.pop("token", None)
    gateway_id = uuid4()
    data["id"] = gateway_id
    data["organization_id"] = ctx.organization.id
    gateway = await crud.create(session, Gateway, **data)
    if plaintext_token:
        await set_gateway_token(
            session,
            gateway,
            plaintext_token,
            actor_user_id=auth.user.id if auth.user else None,
            actor_email=auth.user.email if auth.user else None,
        )
        await session.commit()
    await service.ensure_main_agent(gateway, auth, action="provision")
    return _mask_gateway_token(gateway)


@router.get("/{gateway_id}", response_model=GatewayRead)
async def get_gateway(
    gateway_id: UUID,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
    auth: AuthContext = AUTH_DEP,
    include_token: bool = False,
) -> Gateway:
    """Return one gateway by id for the caller's organization.

    Sprint 5 cutover: by default the response masks the legacy ``token``
    field to ``None`` even when a legacy plaintext value still exists on
    disk. Pass ``?include_token=1`` to receive it (e.g. for the gateway
    edit page); this path audits ``gateway.token.exposed`` so every
    plaintext disclosure is visible in the trail. ``token_configured``
    on the response is always populated truthfully.
    """
    service = GatewayAdminLifecycleService(session)
    gateway = await service.require_gateway(
        gateway_id=gateway_id,
        organization_id=ctx.organization.id,
    )
    if not include_token:
        # Don't mutate the ORM row; build a defensive read-only copy
        # for serialisation. ``token_configured`` is derived in the
        # schema's model_validator.
        from copy import copy as _copy

        masked = _copy(gateway)
        masked.token = None
        return masked

    # Owner-or-admin already gated by ORG_ADMIN_DEP. Audit the explicit
    # opt-in so any plaintext disclosure is on the record.
    from app.services.audit_log import record_audit

    await record_audit(
        session,
        event_type="gateway.token.exposed",
        category="credential",
        action="read",
        result="success",
        severity="warning",
        actor_user_id=auth.user.id if auth.user else None,
        actor_email=auth.user.email if auth.user else None,
        organization_id=gateway.organization_id,
        resource_type="gateway",
        resource_id=str(gateway.id),
        metadata={"reason": "include_token=1"},
    )
    await session.commit()
    return gateway


@router.patch("/{gateway_id}", response_model=GatewayRead)
async def update_gateway(
    gateway_id: UUID,
    payload: GatewayUpdate,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> Gateway:
    """Patch a gateway and refresh the main-agent provisioning state."""
    service = GatewayAdminLifecycleService(session)
    gateway = await service.require_gateway(
        gateway_id=gateway_id,
        organization_id=ctx.organization.id,
    )
    updates = payload.model_dump(exclude_unset=True)
    # Sprint 3: extract token from the patch payload so it goes through
    # ``set_gateway_token`` and lands in ``encrypted_token``, never the
    # legacy plaintext column.
    token_change_requested = "token" in updates
    plaintext_token = updates.pop("token", None)
    if (
        "url" in updates
        or token_change_requested
        or "allow_insecure_tls" in updates
        or "disable_device_pairing" in updates
    ):
        raw_next_url = updates.get("url", gateway.url)
        next_url = raw_next_url.strip() if isinstance(raw_next_url, str) else ""
        next_token = (
            plaintext_token
            if token_change_requested
            else (gateway.encrypted_token and "")  # don't leak plaintext to compat check
            or gateway.token
        )
        next_allow_insecure_tls = bool(
            updates.get("allow_insecure_tls", gateway.allow_insecure_tls),
        )
        next_disable_device_pairing = bool(
            updates.get("disable_device_pairing", gateway.disable_device_pairing),
        )
        if next_url:
            await service.assert_gateway_runtime_compatible(
                url=next_url,
                token=next_token,
                allow_insecure_tls=next_allow_insecure_tls,
                disable_device_pairing=next_disable_device_pairing,
            )
    await crud.patch(session, gateway, updates)
    if token_change_requested:
        await set_gateway_token(
            session,
            gateway,
            plaintext_token,
            actor_user_id=auth.user.id if auth.user else None,
            actor_email=auth.user.email if auth.user else None,
        )
        await session.commit()
    await service.ensure_main_agent(gateway, auth, action="update")
    return _mask_gateway_token(gateway)


@router.post("/{gateway_id}/templates/sync", response_model=GatewayTemplatesSyncResult)
async def sync_gateway_templates(
    gateway_id: UUID,
    sync_query: GatewayTemplateSyncQuery = SYNC_QUERY_DEP,
    session: AsyncSession = SESSION_DEP,
    auth: AuthContext = AUTH_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> GatewayTemplatesSyncResult:
    """Sync templates for a gateway and optionally rotate runtime settings."""
    service = GatewayAdminLifecycleService(session)
    gateway = await service.require_gateway(
        gateway_id=gateway_id,
        organization_id=ctx.organization.id,
    )
    return await service.sync_templates(gateway, query=sync_query, auth=auth)


@router.delete("/{gateway_id}", response_model=OkResponse)
async def delete_gateway(
    gateway_id: UUID,
    session: AsyncSession = SESSION_DEP,
    ctx: OrganizationContext = ORG_ADMIN_DEP,
) -> OkResponse:
    """Delete a gateway in the caller's organization."""
    service = GatewayAdminLifecycleService(session)
    gateway = await service.require_gateway(
        gateway_id=gateway_id,
        organization_id=ctx.organization.id,
    )
    main_agent = await service.find_main_agent(gateway)
    if main_agent is not None:
        await service.clear_agent_foreign_keys(agent_id=main_agent.id)
        await session.delete(main_agent)

    duplicate_main_agents = await Agent.objects.filter_by(
        gateway_id=gateway.id,
        board_id=None,
    ).all(session)
    for agent in duplicate_main_agents:
        if main_agent is not None and agent.id == main_agent.id:
            continue
        await service.clear_agent_foreign_keys(agent_id=agent.id)
        await session.delete(agent)

    # NOTE: The migration declares `ondelete="CASCADE"` for gateway_installed_skills.gateway_id,
    # but some backends/test environments (e.g. SQLite without FK pragma) may not
    # enforce cascades. Delete rows explicitly to guarantee cleanup semantics.
    installed_skills = await GatewayInstalledSkill.objects.filter_by(
        gateway_id=gateway.id,
    ).all(session)
    for installed_skill in installed_skills:
        await session.delete(installed_skill)

    await session.delete(gateway)
    await session.commit()
    return OkResponse()
