"""Operator System — AI planning, routing, and sequential step execution."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal, cast

from anthropic.types import TextBlock
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth import AuthContext, get_auth_context
from app.core.config import settings
from app.core.logging import get_logger
from app.core.secrets_store import get_api_key
from app.core.time import utcnow
from app.db.session import get_session
from app.services.usage.logger import (
    current_environment,
    extract_provider_usage,
    record_usage_event,
)

router = APIRouter(prefix="/operator", tags=["operator"])
AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)
logger = get_logger(__name__)


_TRIGGER = "operator"


async def _record(
    session: AsyncSession,
    *,
    provider: str,
    model: str,
    feature: str,
    started_at: datetime,
    response: object | None = None,
    error: BaseException | None = None,
) -> None:
    if error is not None:
        await record_usage_event(
            session,
            provider=provider,
            model=model,
            feature=feature,
            trigger_source=_TRIGGER,
            environment=current_environment(),
            status="error",
            error=type(error).__name__,
            started_at=started_at,
            ended_at=utcnow(),
        )
        return
    in_tok, out_tok = extract_provider_usage(provider, response)
    await record_usage_event(
        session,
        provider=provider,
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        feature=feature,
        trigger_source=_TRIGGER,
        environment=current_environment(),
        started_at=started_at,
        ended_at=utcnow(),
    )


StepType = Literal["research", "write", "analyze", "decide"]
ProviderType = Literal["claude", "chatgpt", "gemini"]

# ── Schemas ───────────────────────────────────────────────────────────────────


class PlanRequest(BaseModel):
    objective: str
    memory_context: str = ""


class PlanStep(BaseModel):
    id: int
    task: str
    type: StepType


class PlanResponse(BaseModel):
    goal: str
    steps: list[PlanStep]


class ExecuteRequest(BaseModel):
    task: str
    provider: ProviderType
    context: str = ""
    memory_context: str = ""


class ExecuteResponse(BaseModel):
    result: str
    provider: str


class ExtractInsightsRequest(BaseModel):
    goal: str
    step_task: str
    step_result: str


class Insight(BaseModel):
    type: Literal["context", "decision", "insight"]
    content: str


class ExtractInsightsResponse(BaseModel):
    insights: list[Insight]


# ── Prompts ───────────────────────────────────────────────────────────────────

PLANNING_SYSTEM = (
    "You are an expert AI operator. Given an objective, create a precise, minimal execution plan.\n"
    "Return ONLY valid JSON — no markdown, no explanation, nothing else.\n\n"
    'Schema: {"goal": "concise goal statement", "steps": [{"id": 1, "task": "specific actionable task", "type": "research|write|analyze|decide"}]}\n\n'
    "Rules:\n"
    "- 2 to 6 steps maximum — be efficient\n"
    "- research: gathering facts, data, or existing knowledge\n"
    "- analyze: evaluation, comparison, or synthesis of information\n"
    "- write: producing formatted content, documents, or summaries\n"
    "- decide: making recommendations or final judgments\n"
    "- Each task must be specific and self-contained\n"
    "- Return ONLY the JSON object"
)

EXECUTION_SYSTEM = (
    "You are an expert AI assistant executing a specific task as part of a larger plan. "
    "Be thorough, precise, and actionable. Stay focused on exactly what is asked."
)

INSIGHT_SYSTEM = (
    "You extract concise, reusable insights from completed AI work.\n"
    "Return ONLY valid JSON — no markdown, nothing else.\n\n"
    'Schema: {"insights": [{"type": "context|decision|insight", "content": "one sentence, specific and actionable"}]}\n\n'
    "Rules:\n"
    "- 1 to 3 insights maximum\n"
    "- context: background facts useful for future reference\n"
    "- decision: choices made or recommendations given\n"
    "- insight: non-obvious observations or conclusions\n"
    "- Each insight must be a single sentence, under 100 words\n"
    "- Return ONLY the JSON object"
)


# ── JSON extraction ───────────────────────────────────────────────────────────


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return cast(dict[str, Any], json.loads(text))
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return cast(dict[str, Any], json.loads(match.group(1).strip()))
        except json.JSONDecodeError:
            pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return cast(dict[str, Any], json.loads(match.group(0)))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"No valid JSON found in: {text[:300]}")


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/plan", response_model=PlanResponse)
async def create_plan(
    request: PlanRequest,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> PlanResponse:
    """Generate a structured execution plan for an objective."""
    anthropic_key = await get_api_key("anthropic", session, settings.anthropic_api_key)
    if not anthropic_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Anthropic API key required for Operator planning. Add it in Settings.",
        )

    prompt_parts: list[str] = []
    if request.memory_context:
        prompt_parts.append(f"User Memory Context:\n{request.memory_context}")
    prompt_parts.append(f"Objective: {request.objective}")
    prompt = "\n\n".join(prompt_parts)

    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=anthropic_key.strip())
    model = settings.anthropic_synthesis_model
    started_at = utcnow()

    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=1024,
            system=PLANNING_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        await _record(
            session,
            provider="anthropic",
            model=model,
            feature="operator.plan",
            started_at=started_at,
            error=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Planning error: {exc}",
        ) from exc

    await _record(
        session,
        provider="anthropic",
        model=model,
        feature="operator.plan",
        started_at=started_at,
        response=resp,
    )
    text = resp.content[0].text if resp.content and isinstance(resp.content[0], TextBlock) else ""
    logger.info("[operator/plan] raw: %s", text[:400])

    try:
        data = _extract_json(text)
        plan = PlanResponse(
            goal=str(data.get("goal", request.objective)),
            steps=[PlanStep(**s) for s in data.get("steps", [])],
        )
        logger.info("[operator/plan] goal=%r steps=%d", plan.goal, len(plan.steps))
        return plan
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Invalid plan JSON: {exc} | Raw: {text[:300]}",
        ) from exc


@router.post("/execute", response_model=ExecuteResponse)
async def execute_step(
    request: ExecuteRequest,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ExecuteResponse:
    """Execute a single operator step with the specified provider."""
    parts: list[str] = []
    if request.context:
        parts.append(f"Context from previous steps:\n{request.context}")
    parts.append(f"Task: {request.task}")
    user_message = "\n\n".join(parts)

    system = EXECUTION_SYSTEM
    if request.memory_context:
        system = f"{EXECUTION_SYSTEM}\n\nUser Memory:\n{request.memory_context}"

    logger.info("[operator/execute] provider=%s task=%r", request.provider, request.task[:80])

    if request.provider == "claude":
        anthropic_key = await get_api_key("anthropic", session, settings.anthropic_api_key)
        if not anthropic_key.strip():
            raise HTTPException(status_code=400, detail="Anthropic API key not configured.")
        return await _run_claude(anthropic_key.strip(), user_message, system, session)

    if request.provider == "chatgpt":
        openai_key = await get_api_key("openai", session, settings.openai_api_key)
        if not openai_key.strip():
            raise HTTPException(status_code=400, detail="OpenAI API key not configured.")
        return await _run_openai(openai_key.strip(), user_message, system, session)

    if request.provider == "gemini":
        gemini_key = await get_api_key("gemini", session, settings.gemini_api_key)
        if not gemini_key.strip():
            raise HTTPException(status_code=400, detail="Gemini API key not configured.")
        return await _run_gemini(gemini_key.strip(), user_message, system, session)

    raise HTTPException(status_code=400, detail=f"Unknown provider: {request.provider}")


@router.post("/extract-insights", response_model=ExtractInsightsResponse)
async def extract_insights(
    request: ExtractInsightsRequest,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> ExtractInsightsResponse:
    """Extract memory insights from a completed step result."""
    anthropic_key = await get_api_key("anthropic", session, settings.anthropic_api_key)
    if not anthropic_key.strip():
        return ExtractInsightsResponse(insights=[])

    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=anthropic_key.strip())
    model = settings.anthropic_synthesis_model

    prompt = (
        f"Goal: {request.goal}\n"
        f"Task: {request.step_task}\n"
        f"Result:\n{request.step_result[:1500]}"
    )

    started_at = utcnow()
    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=512,
            system=INSIGHT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        await _record(
            session,
            provider="anthropic",
            model=model,
            feature="operator.extract_insights",
            started_at=started_at,
            error=exc,
        )
        logger.warning("[operator/extract-insights] failed: %s", exc)
        return ExtractInsightsResponse(insights=[])

    await _record(
        session,
        provider="anthropic",
        model=model,
        feature="operator.extract_insights",
        started_at=started_at,
        response=resp,
    )
    try:
        text = (
            resp.content[0].text
            if resp.content and isinstance(resp.content[0], TextBlock)
            else "{}"
        )
        data = _extract_json(text)
        insights = [Insight(**i) for i in data.get("insights", [])]
        logger.info("[operator/extract-insights] %d insights", len(insights))
        return ExtractInsightsResponse(insights=insights)
    except Exception as exc:
        logger.warning("[operator/extract-insights] parse failed: %s", exc)
        return ExtractInsightsResponse(insights=[])


# ── Provider runners ──────────────────────────────────────────────────────────


async def _run_claude(
    api_key: str, user_message: str, system: str, session: AsyncSession
) -> ExecuteResponse:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    model = settings.anthropic_synthesis_model
    started_at = utcnow()
    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:
        await _record(
            session,
            provider="anthropic",
            model=model,
            feature="operator.execute",
            started_at=started_at,
            error=exc,
        )
        raise HTTPException(status_code=502, detail=f"Claude error: {exc}") from exc
    await _record(
        session,
        provider="anthropic",
        model=model,
        feature="operator.execute",
        started_at=started_at,
        response=resp,
    )
    text = (
        resp.content[0].text if resp.content and isinstance(resp.content[0], TextBlock) else ""
    ).strip()
    logger.info("[operator/execute] claude/%s done (%d chars)", model, len(text))
    return ExecuteResponse(result=text, provider=f"claude/{model}")


async def _run_openai(
    api_key: str, user_message: str, system: str, session: AsyncSession
) -> ExecuteResponse:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    model = "gpt-4o"
    started_at = utcnow()
    try:
        resp = await client.chat.completions.create(
            model=model,
            max_tokens=2048,
            temperature=0.4,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        )
    except Exception as exc:
        await _record(
            session,
            provider="openai",
            model=model,
            feature="operator.execute",
            started_at=started_at,
            error=exc,
        )
        raise HTTPException(status_code=502, detail=f"OpenAI error: {exc}") from exc
    await _record(
        session,
        provider="openai",
        model=model,
        feature="operator.execute",
        started_at=started_at,
        response=resp,
    )
    text = (resp.choices[0].message.content or "").strip()
    logger.info("[operator/execute] openai/%s done (%d chars)", model, len(text))
    return ExecuteResponse(result=text, provider=f"openai/{model}")


async def _run_gemini(
    api_key: str, user_message: str, system: str, session: AsyncSession
) -> ExecuteResponse:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    model = settings.gemini_model
    started_at = utcnow()
    try:
        resp = client.models.generate_content(
            model=model,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.4,
            ),
        )
    except Exception as exc:
        await _record(
            session,
            provider="gemini",
            model=model,
            feature="operator.execute",
            started_at=started_at,
            error=exc,
        )
        raise HTTPException(status_code=502, detail=f"Gemini error: {exc}") from exc
    await _record(
        session,
        provider="gemini",
        model=model,
        feature="operator.execute",
        started_at=started_at,
        response=resp,
    )
    text = (resp.text or "").strip()
    logger.info("[operator/execute] gemini/%s done (%d chars)", model, len(text))
    return ExecuteResponse(result=text, provider=f"gemini/{model}")
