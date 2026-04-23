"""Gemini chat streaming endpoint for Mission Control."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth import AuthContext, get_auth_context
from app.core.config import settings
from app.core.secrets_store import get_api_key
from app.db.session import get_session

router = APIRouter(prefix="/gemini", tags=["gemini"])
AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)


class ChatMessageIn(BaseModel):
    role: str  # "user" | "assistant" | "system"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessageIn]
    model: str | None = None


@router.get("/status")
async def gemini_status(
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> dict[str, bool]:
    """Return whether the Gemini API key is configured (DB or .env)."""
    api_key = await get_api_key("gemini", session, settings.gemini_api_key)
    return {"configured": bool(api_key.strip())}


@router.post("/chat/stream")
async def stream_chat(
    request: ChatRequest,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> StreamingResponse:
    """Stream a Gemini response using SSE."""
    api_key = await get_api_key("gemini", session, settings.gemini_api_key)
    if not api_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GEMINI_API_KEY is not configured. Add it in Settings.",
        )

    model = (request.model or settings.gemini_model).strip()

    # Separate system instructions from conversation turns
    system_parts = [m.content for m in request.messages if m.role == "system"]
    system_instruction = {"parts": [{"text": "\n\n".join(system_parts)}]} if system_parts else None

    contents = []
    for m in request.messages:
        if m.role == "system":
            continue
        gemini_role = "model" if m.role == "assistant" else "user"
        contents.append({"role": gemini_role, "parts": [{"text": m.content}]})

    async def generate() -> object:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        generate_kwargs: dict = {"model": model, "contents": contents}
        if system_instruction:
            generate_kwargs["config"] = types.GenerateContentConfig(
                system_instruction=system_instruction["parts"][0]["text"]
            )
        try:
            async for chunk in await client.aio.models.generate_content_stream(**generate_kwargs):
                text = chunk.text
                if text:
                    yield f"data: {json.dumps({'delta': text})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
