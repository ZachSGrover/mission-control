"""AI Synthesis endpoint — combines multi-provider responses into a superior answer."""

from __future__ import annotations

import logging
from datetime import datetime

from anthropic.types import TextBlock
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

logger = logging.getLogger(__name__)

_FEATURE = "synthesize"
_TRIGGER = "synthesize"

router = APIRouter(prefix="/synthesize", tags=["synthesize"])
AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)


class SynthesisResponses(BaseModel):
    claude: str = ""
    chatgpt: str = ""
    gemini: str = ""


class SynthesisRequest(BaseModel):
    question: str
    responses: SynthesisResponses
    memory_context: str = ""


class SynthesisResult(BaseModel):
    synthesis: str
    model_used: str


def _build_synthesis_prompt(request: SynthesisRequest) -> str:
    """Build the synthesis prompt combining all provider responses."""
    lines: list[str] = []

    if request.memory_context:
        lines.append(f"User Memory Context:\n{request.memory_context}\n")

    lines.append(f'User Question:\n"""\n{request.question}\n"""\n')

    providers = {
        "Claude": request.responses.claude,
        "ChatGPT": request.responses.chatgpt,
        "Gemini": request.responses.gemini,
    }

    has_any = False
    for name, text in providers.items():
        if text.strip():
            lines.append(f'{name} Response:\n"""\n{text.strip()}\n"""\n')
            has_any = True

    if not has_any:
        raise ValueError("No provider responses to synthesize.")

    lines.append(
        "You are an expert synthesis engine. Your task:\n\n"
        "1. Carefully read all AI responses above\n"
        "2. Extract the strongest, most accurate insights from each\n"
        "3. Identify and correct any weak, incomplete, or incorrect information\n"
        "4. Eliminate redundancy — say each thing once, perfectly\n"
        "5. Produce ONE definitive, comprehensive answer that is better than any individual response\n\n"
        "Requirements for your synthesis:\n"
        "- Be authoritative and direct\n"
        "- Preserve concrete details, code examples, and specific recommendations from the responses\n"
        "- If responses contradict each other, use your knowledge to resolve the contradiction\n"
        "- Structure the answer clearly (use paragraphs, lists, or code blocks as appropriate)\n"
        "- Do NOT mention that you are synthesizing other AI responses — write as if this is your own answer\n"
        "- Do NOT include phrases like 'Based on the responses above' or 'The models agree that'\n\n"
        "Write the final synthesized answer now:"
    )

    return "\n".join(lines)


def _count_responses(responses: SynthesisResponses) -> int:
    return sum(1 for r in [responses.claude, responses.chatgpt, responses.gemini] if r.strip())


@router.post("/generate", response_model=SynthesisResult)
async def generate_synthesis(
    request: SynthesisRequest,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> SynthesisResult:
    """Synthesize multiple AI responses into a single superior answer."""
    response_count = _count_responses(request.responses)

    # If only one model responded, return it directly — nothing to synthesize
    if response_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No provider responses to synthesize.",
        )

    if response_count == 1:
        # Return the single available response as-is
        single = request.responses.claude or request.responses.chatgpt or request.responses.gemini
        return SynthesisResult(synthesis=single.strip(), model_used="passthrough")

    prompt = _build_synthesis_prompt(request)

    # Priority: Anthropic Claude → OpenAI GPT-4o → Gemini
    logger.info("[synthesize] %d provider(s) responded — selecting synthesis model", response_count)

    anthropic_key = await get_api_key("anthropic", session, settings.anthropic_api_key)
    if anthropic_key.strip():
        logger.info(
            "[synthesize] anthropic key present — using Claude (%s)",
            settings.anthropic_synthesis_model,
        )
        return await _synthesize_with_anthropic(anthropic_key.strip(), prompt, session)

    logger.info("[synthesize] no anthropic key — falling back to OpenAI GPT-4o")
    openai_key = await get_api_key("openai", session, settings.openai_api_key)
    if openai_key.strip():
        logger.info("[synthesize] openai key present — using GPT-4o")
        return await _synthesize_with_openai(openai_key.strip(), prompt, session)

    logger.info("[synthesize] no openai key — falling back to Gemini")
    gemini_key = await get_api_key("gemini", session, settings.gemini_api_key)
    if gemini_key.strip():
        logger.info("[synthesize] gemini key present — using %s", settings.gemini_model)
        return await _synthesize_with_gemini(gemini_key.strip(), prompt, session)

    logger.error("[synthesize] no API keys configured — synthesis unavailable")
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No AI API key configured for synthesis. Add Anthropic, OpenAI, or Gemini key in Settings.",
    )


async def _record(
    session: AsyncSession,
    *,
    provider: str,
    model: str,
    started_at: datetime,
    response: object | None = None,
    error: BaseException | None = None,
) -> None:
    """Record one usage event for a synthesize call.  Best-effort."""
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


async def _synthesize_with_anthropic(
    api_key: str, prompt: str, session: AsyncSession
) -> SynthesisResult:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    model = settings.anthropic_synthesis_model
    started_at = utcnow()
    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=(
                "You are an expert synthesis engine. You combine insights from multiple AI responses "
                "into a single definitive, superior answer. Be authoritative, precise, and comprehensive."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        await _record(session, provider="anthropic", model=model, started_at=started_at, error=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Anthropic synthesis error: {exc}",
        ) from exc

    await _record(session, provider="anthropic", model=model, started_at=started_at, response=resp)
    text = resp.content[0].text if resp.content and isinstance(resp.content[0], TextBlock) else ""
    logger.info("[synthesize] ✓ completed via claude/%s (%d chars)", model, len(text.strip()))
    return SynthesisResult(synthesis=text.strip(), model_used=f"claude/{model}")


async def _synthesize_with_openai(
    api_key: str, prompt: str, session: AsyncSession
) -> SynthesisResult:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    # Use gpt-4o for synthesis — higher quality than gpt-4o-mini
    model = "gpt-4o"
    started_at = utcnow()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert synthesis engine. You combine insights from multiple AI responses "
                        "into a single definitive, superior answer. Be authoritative, precise, and comprehensive."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=4096,
        )
    except Exception as exc:
        await _record(session, provider="openai", model=model, started_at=started_at, error=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI synthesis error: {exc}",
        ) from exc

    await _record(session, provider="openai", model=model, started_at=started_at, response=resp)
    text = resp.choices[0].message.content or ""
    logger.info("[synthesize] ✓ completed via openai/%s (%d chars)", model, len(text.strip()))
    return SynthesisResult(synthesis=text.strip(), model_used=f"openai/{model}")


async def _synthesize_with_gemini(
    api_key: str, prompt: str, session: AsyncSession
) -> SynthesisResult:
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
                    "You are an expert synthesis engine. You combine insights from multiple AI responses "
                    "into a single definitive, superior answer. Be authoritative, precise, and comprehensive."
                ),
                temperature=0.3,
            ),
        )
    except Exception as exc:
        await _record(session, provider="gemini", model=model, started_at=started_at, error=exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gemini synthesis error: {exc}",
        ) from exc

    await _record(session, provider="gemini", model=model, started_at=started_at, response=resp)
    text = resp.text or ""
    logger.info("[synthesize] ✓ completed via gemini/%s (%d chars)", model, len(text.strip()))
    return SynthesisResult(synthesis=text.strip(), model_used=f"gemini/{model}")
