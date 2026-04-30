"""AI Judge endpoint — evaluates and ranks parallel provider responses."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth import AuthContext, get_auth_context
from app.core.config import settings
from app.core.secrets_store import get_api_key
from app.core.time import utcnow
from app.db.session import get_session
from app.services.usage.logger import (
    current_environment,
    extract_provider_usage,
    record_usage_event,
)

router = APIRouter(prefix="/judge", tags=["judge"])
AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)

_FEATURE = "judge"
_TRIGGER = "judge"


async def _record(
    session: AsyncSession,
    *,
    provider: str,
    model: str,
    started_at: datetime,
    response: object | None = None,
    error: BaseException | None = None,
) -> None:
    if error is not None:
        await record_usage_event(
            session,
            provider=provider,
            model=model,
            feature=_FEATURE,
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
        feature=_FEATURE,
        trigger_source=_TRIGGER,
        environment=current_environment(),
        started_at=started_at,
        ended_at=utcnow(),
    )


class JudgeResponses(BaseModel):
    claude: str = ""
    chatgpt: str = ""
    gemini: str = ""


class JudgeRequest(BaseModel):
    question: str
    responses: JudgeResponses
    memory_context: str = ""


class JudgeScores(BaseModel):
    claude: float = 0
    chatgpt: float = 0
    gemini: float = 0


class JudgeResult(BaseModel):
    best: str  # "claude" | "chatgpt" | "gemini"
    reasoning: str
    scores: JudgeScores


def _build_judge_prompt(request: JudgeRequest) -> str:
    lines: list[str] = []

    if request.memory_context:
        lines.append(f"User Memory Context:\n{request.memory_context}\n")

    lines.append(f'User Question:\n"""\n{request.question}\n"""\n')

    providers = {
        "claude": request.responses.claude,
        "chatgpt": request.responses.chatgpt,
        "gemini": request.responses.gemini,
    }

    for name, text in providers.items():
        if text.strip():
            lines.append(f'{name.capitalize()} Response:\n"""\n{text.strip()}\n"""\n')
        else:
            lines.append(f"{name.capitalize()} Response: [No response / failed]\n")

    lines.append(
        "Evaluate each response on:\n"
        "1. Accuracy and correctness (avoids hallucinations)\n"
        "2. Completeness (fully addresses the question)\n"
        "3. Practical usefulness (actionable and concrete)\n"
        "4. Clarity (well-structured and concise)\n\n"
        "Respond with ONLY valid JSON matching this exact schema:\n"
        "{\n"
        '  "best": "claude" | "chatgpt" | "gemini",\n'
        '  "reasoning": "<1-2 sentences explaining why this answer is best>",\n'
        '  "scores": {\n'
        '    "claude": <0-10>,\n'
        '    "chatgpt": <0-10>,\n'
        '    "gemini": <0-10>\n'
        "  }\n"
        "}\n\n"
        "If a provider had no response, give it a score of 0.\n"
        'The "best" must be the provider with the highest score.\n'
        "If scores are tied, prefer whichever response is more complete."
    )

    return "\n".join(lines)


def _parse_judge_response(raw: str) -> dict[str, Any]:
    text = raw.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: text.rstrip().rfind("```")]
    return cast(dict[str, Any], json.loads(text))


@router.post("/evaluate", response_model=JudgeResult)
async def evaluate(
    request: JudgeRequest,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> JudgeResult:
    """Evaluate three AI responses and select the best answer."""
    # Need at least one non-empty response
    responses = request.responses
    if not any([responses.claude.strip(), responses.chatgpt.strip(), responses.gemini.strip()]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="All provider responses are empty.",
        )

    prompt = _build_judge_prompt(request)

    # Try OpenAI first (most reliable JSON output), fall back to Gemini
    openai_key = await get_api_key("openai", session, settings.openai_api_key)
    if openai_key.strip():
        return await _judge_with_openai(openai_key.strip(), prompt, session)

    gemini_key = await get_api_key("gemini", session, settings.gemini_api_key)
    if gemini_key.strip():
        return await _judge_with_gemini(gemini_key.strip(), prompt, session)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No AI API key configured. Add OpenAI or Gemini key in Settings.",
    )


async def _judge_with_openai(api_key: str, prompt: str, session: AsyncSession) -> JudgeResult:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    model = settings.openai_model
    started_at = utcnow()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an impartial AI response evaluator. "
                        "You compare responses from different AI assistants and select the best one. "
                        "Always respond with valid JSON only — no markdown, no explanations outside the JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
    except Exception as exc:
        await _record(session, provider="openai", model=model, started_at=started_at, error=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI judge error: {exc}",
        ) from exc

    await _record(session, provider="openai", model=model, started_at=started_at, response=resp)
    raw = resp.choices[0].message.content or ""
    return _build_result(raw)


async def _judge_with_gemini(api_key: str, prompt: str, session: AsyncSession) -> JudgeResult:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    model = settings.gemini_model
    started_at = utcnow()
    try:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are an impartial AI response evaluator. "
                    "Always respond with valid JSON only."
                ),
                temperature=0.1,
            ),
        )
    except Exception as exc:
        await _record(session, provider="gemini", model=model, started_at=started_at, error=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gemini judge error: {exc}",
        ) from exc

    await _record(session, provider="gemini", model=model, started_at=started_at, response=resp)
    raw = resp.text or ""
    return _build_result(raw)


def _build_result(raw: str) -> JudgeResult:
    try:
        data = _parse_judge_response(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Judge returned invalid JSON: {exc}",
        ) from exc

    best = str(data.get("best", "")).lower()
    if best not in {"claude", "chatgpt", "gemini"}:
        # Pick highest score as fallback
        scores_raw = data.get("scores", {})
        best = max(
            ["claude", "chatgpt", "gemini"],
            key=lambda p: float(scores_raw.get(p, 0)),
        )

    scores_raw = data.get("scores", {})
    return JudgeResult(
        best=best,
        reasoning=str(data.get("reasoning", "Best overall response.")),
        scores=JudgeScores(
            claude=float(scores_raw.get("claude", 0)),
            chatgpt=float(scores_raw.get("chatgpt", 0)),
            gemini=float(scores_raw.get("gemini", 0)),
        ),
    )
