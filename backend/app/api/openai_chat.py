"""OpenAI chat streaming endpoint for Mission Control."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth import AuthContext, get_auth_context
from app.core.config import settings
from app.core.secrets_store import get_api_key
from app.db.session import get_session

router = APIRouter(prefix="/openai", tags=["openai"])
AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)


class ChatMessageIn(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessageIn]
    model: str | None = None


@router.get("/status")
async def openai_status(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> dict[str, bool]:
    """Return whether the OpenAI API key is configured (DB or .env)."""
    api_key = await get_api_key("openai", session, settings.openai_api_key)
    return {"configured": bool(api_key.strip())}


@router.post("/chat/stream")
async def stream_chat(
    request: ChatRequest,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> StreamingResponse:
    """Stream a ChatGPT response using SSE."""
    api_key = await get_api_key("openai", session, settings.openai_api_key)
    if not api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OPENAI_API_KEY is not configured. Add it in Settings.",
        )

    model = (request.model or settings.openai_model).strip()
    messages = [{"role": m.role, "content": m.content} for m in request.messages]

    async def generate() -> AsyncIterator[str]:
        from openai import APIError as OpenAIAPIError
        from openai import AsyncOpenAI, AsyncStream
        from openai.types.chat import ChatCompletionChunk

        # TODO(usage-logging-streaming): wire record_usage_event() on stream
        # completion. Token counts only arrive in the terminal chunk (or not at
        # all), so this needs an end-of-stream hook rather than the inline wrap
        # used elsewhere. Out of scope for the initial usage-logging slice.
        client = AsyncOpenAI(api_key=api_key)
        try:
            stream = cast(
                AsyncStream[ChatCompletionChunk],
                await client.chat.completions.create(
                    model=model,
                    messages=messages,  # type: ignore[arg-type]
                    stream=True,
                ),
            )
            async for chunk in stream:
                choice = chunk.choices[0] if chunk.choices else None
                delta_content = choice.delta.content if choice and choice.delta else None
                if delta_content:
                    yield f"data: {json.dumps({'delta': delta_content})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except OpenAIAPIError as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': f'Unexpected error: {exc}'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
