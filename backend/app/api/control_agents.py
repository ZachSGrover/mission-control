"""
control_agents — CRUD + invoke endpoints for Mission Control agent configs.

Endpoints (prefix /api/v1/control/agents):
  GET    /                 → list all agents
  POST   /                 → create agent
  GET    /{agent_id}       → fetch one
  PATCH  /{agent_id}       → partial update
  DELETE /{agent_id}       → remove
  POST   /{agent_id}/invoke → run a prompt through the agent (AI happens BACKEND-ONLY)
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

import uuid
from typing import Any

from app.api.mc_roles import require_owner
from app.core import agent_executions, agent_state, agents_registry, message_metrics
from app.core.agents_registry import Agent
from app.core.ai_backend import ask_ai_detailed
from app.core.auth import AuthContext, get_auth_context
from app.db.session import get_session

router = APIRouter(prefix="/control/agents", tags=["control-agents"])
logger = logging.getLogger(__name__)

AUTH_DEP = Depends(get_auth_context)
OWNER_DEP = Depends(require_owner)
SESSION_DEP = Depends(get_session)


class AgentOut(BaseModel):
    id:            str
    name:          str
    purpose:       str
    system_prompt: str
    model:         str
    provider:      str
    active:        bool
    tags:          list[str]
    platforms:     list[str]
    is_default:    bool

    @classmethod
    def from_core(cls, a: Agent) -> "AgentOut":
        return cls(
            id=a.id, name=a.name, purpose=a.purpose,
            system_prompt=a.system_prompt, model=a.model,
            provider=a.provider, active=a.active, tags=a.tags,
            platforms=a.platforms, is_default=a.is_default,
        )


class AgentCreate(BaseModel):
    name:          str = Field(..., min_length=1, max_length=80)
    purpose:       str = Field(..., max_length=400)
    system_prompt: str = Field(..., max_length=4000)
    model:         str = ""
    provider:      str = "auto"
    active:        bool = True
    tags:          list[str] = []
    platforms:     list[str] = []
    is_default:    bool = False


class AgentPatch(BaseModel):
    name:          str | None = None
    purpose:       str | None = None
    system_prompt: str | None = None
    model:         str | None = None
    provider:      str | None = None
    active:        bool | None = None
    tags:          list[str] | None = None
    platforms:     list[str] | None = None
    is_default:    bool | None = None


class InvokeRequest(BaseModel):
    prompt: str = Field(..., max_length=8000)
    source: str = "ui"
    correlation_id: str | None = None


class InvokeResponse(BaseModel):
    agent_id:     str
    reply:        str
    provider:     str
    response_ms:  float
    attempts:     int
    status:       str
    correlation_id: str
    error:        str | None = None


class ExecutionOut(BaseModel):
    id:             str
    agent_id:       str
    agent_name:     str
    source:         str
    prompt:         str
    reply:          str
    provider:       str
    status:         str
    error:          str | None
    response_ms:    float
    attempts:       int
    correlation_id: str | None
    tokens_in:      int | None
    tokens_out:     int | None
    timestamp:      float


class StateResponse(BaseModel):
    agent_id: str
    state:    dict[str, Any]


class StatePut(BaseModel):
    state: dict[str, Any]


class StatePatch(BaseModel):
    patch: dict[str, Any]


@router.get("", response_model=list[AgentOut])
async def list_all(_: AuthContext = AUTH_DEP) -> list[AgentOut]:
    return [AgentOut.from_core(a) for a in agents_registry.list_agents()]


@router.post("", response_model=AgentOut, status_code=status.HTTP_201_CREATED)
async def create(
    body: AgentCreate,
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
) -> AgentOut:
    agent = agents_registry.create_agent(
        name=body.name,
        purpose=body.purpose,
        system_prompt=body.system_prompt,
        model=body.model,
        provider=body.provider,  # type: ignore[arg-type]
        active=body.active,
        tags=body.tags,
        platforms=body.platforms,
        is_default=body.is_default,
    )
    return AgentOut.from_core(agent)


@router.get("/{agent_id}", response_model=AgentOut)
async def get_one(agent_id: str, _: AuthContext = AUTH_DEP) -> AgentOut:
    agent = agents_registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentOut.from_core(agent)


@router.patch("/{agent_id}", response_model=AgentOut)
async def patch(
    agent_id: str,
    body: AgentPatch,
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
) -> AgentOut:
    agent = agents_registry.update_agent(
        agent_id, **body.model_dump(exclude_unset=True, exclude_none=True)
    )
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentOut.from_core(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    agent_id: str,
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
) -> None:
    if not agents_registry.delete_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")


@router.post("/{agent_id}/invoke", response_model=InvokeResponse)
async def invoke(
    agent_id: str,
    body: InvokeRequest,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> InvokeResponse:
    """
    Run the given agent's system_prompt against the user prompt. AI calls stay
    backend-only (keys resolved via secrets_store, never sent to the client).
    Automatically retries transient errors with exponential backoff and records
    a persistent execution entry for the agent.
    """
    agent = agents_registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not agent.active:
        raise HTTPException(status_code=409, detail="Agent is not active")

    corr_id = (body.correlation_id or uuid.uuid4().hex[:12]).strip()
    start = time.perf_counter()
    composed = f"{agent.system_prompt.strip()}\n\nUser:\n{body.prompt}"

    status_label = "ok"
    error: str | None = None
    try:
        reply, provider, attempts, err = await ask_ai_detailed(composed, session)
        error = err
        if provider == "none":
            status_label = "error"
    except Exception as exc:                             # noqa: BLE001
        reply, provider, attempts = "", "none", 1
        status_label, error = "error", str(exc)

    elapsed_ms = (time.perf_counter() - start) * 1000.0

    # In-memory messaging metrics (Phase 2 ring buffer — unchanged)
    message_metrics.record(
        source="other",
        response_ms=elapsed_ms,
        used_ai=True,
        reason=f"agent:{agent.name}",
    )
    # Persistent execution record (Phase 4)
    agent_executions.record(
        agent_id=agent.id,
        agent_name=agent.name,
        source=body.source,
        prompt=body.prompt,
        reply=reply,
        provider=provider,
        status=status_label,
        error=error,
        response_ms=elapsed_ms,
        attempts=attempts,
        correlation_id=corr_id,
    )
    logger.info(
        "control.agent.invoked agent=%s provider=%s ms=%.1f attempts=%d status=%s corr=%s",
        agent.name, provider, elapsed_ms, attempts, status_label, corr_id,
    )
    return InvokeResponse(
        agent_id=agent.id,
        reply=reply,
        provider=provider,
        response_ms=round(elapsed_ms, 2),
        attempts=attempts,
        status=status_label,
        correlation_id=corr_id,
        error=error,
    )


# ── Executions (persistent history) ──────────────────────────────────────────

@router.get("/{agent_id}/executions", response_model=list[ExecutionOut])
async def get_executions(
    agent_id: str,
    limit: int = 50,
    _: AuthContext = AUTH_DEP,
) -> list[ExecutionOut]:
    if not agents_registry.get_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    records = agent_executions.by_agent(agent_id, limit=min(limit, 200))
    return [ExecutionOut(**r.__dict__) for r in records]


# ── Per-agent state (KV scratchpad) ──────────────────────────────────────────

@router.get("/{agent_id}/state", response_model=StateResponse)
async def get_agent_state(agent_id: str, _: AuthContext = AUTH_DEP) -> StateResponse:
    if not agents_registry.get_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return StateResponse(agent_id=agent_id, state=agent_state.get_state(agent_id))


@router.put("/{agent_id}/state", response_model=StateResponse)
async def put_agent_state(
    agent_id: str,
    body: StatePut,
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
) -> StateResponse:
    if not agents_registry.get_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        state = agent_state.set_state(agent_id, body.state)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    return StateResponse(agent_id=agent_id, state=state)


@router.patch("/{agent_id}/state", response_model=StateResponse)
async def patch_agent_state(
    agent_id: str,
    body: StatePatch,
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
) -> StateResponse:
    if not agents_registry.get_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        state = agent_state.merge_state(agent_id, body.patch)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc))
    return StateResponse(agent_id=agent_id, state=state)


@router.delete("/{agent_id}/state", status_code=status.HTTP_204_NO_CONTENT)
async def clear_agent_state(
    agent_id: str,
    _: AuthContext = AUTH_DEP,
    _role: str = OWNER_DEP,
) -> None:
    if not agents_registry.get_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    agent_state.clear_state(agent_id)


# ── Global execution feed ────────────────────────────────────────────────────

@router.get("/_/executions", response_model=list[ExecutionOut])
async def all_recent_executions(
    limit: int = 50,
    _: AuthContext = AUTH_DEP,
) -> list[ExecutionOut]:
    records = agent_executions.recent(limit=min(limit, 200))
    return [ExecutionOut(**r.__dict__) for r in records]
