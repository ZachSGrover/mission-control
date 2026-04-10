"""Auto-generated daily journal endpoint for Mission Control."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.auth import AuthContext, get_auth_context
from app.core.config import settings
from app.core.secrets_store import get_api_key
from app.db.session import get_session

router = APIRouter(prefix="/journal", tags=["journal"])
AUTH_DEP = Depends(get_auth_context)
SESSION_DEP = Depends(get_session)


class JournalMessageIn(BaseModel):
    role: str       # "user" | "assistant"
    text: str
    provider: str   # "claude" | "chatgpt" | "gemini"
    createdAt: str  # ISO timestamp


class MemoryEntryIn(BaseModel):
    type: str       # "context" | "decision" | "note"
    content: str


class JournalGenerateRequest(BaseModel):
    date: str                           # "YYYY-MM-DD"
    messages: list[JournalMessageIn]
    memory: list[MemoryEntryIn] = []


class JournalCategories(BaseModel):
    actions: list[str] = []
    decisions: list[str] = []
    insights: list[str] = []
    themes: list[str] = []


class JournalGenerateResponse(BaseModel):
    date: str
    headline: str
    summary: str
    categories: JournalCategories
    messageCount: int


def _build_prompt(date: str, messages: list[JournalMessageIn], memory: list[MemoryEntryIn]) -> str:
    lines: list[str] = []

    lines.append(f"Date: {date}")
    lines.append("")

    if memory:
        lines.append("Persistent Memory Context:")
        for m in memory:
            lines.append(f"  [{m.type.upper()}] {m.content}")
        lines.append("")

    if messages:
        lines.append("Today's AI Conversations:")
        for msg in messages:
            prefix = "User" if msg.role == "user" else f"AI ({msg.provider})"
            lines.append(f"  [{prefix}] {msg.text}")
        lines.append("")

    lines.append(
        "Generate a concise daily journal entry for the date above based on the conversation activity.\n"
        "Respond with ONLY valid JSON matching this exact schema:\n"
        '{\n'
        '  "headline": "<1 sentence, ≤80 chars — what today was really about>",\n'
        '  "summary": "<2-4 sentences — narrative of the day\'s work and thinking>",\n'
        '  "categories": {\n'
        '    "actions": ["<thing built/done/shipped>", ...],\n'
        '    "decisions": ["<choice made and why>", ...],\n'
        '    "insights": ["<learning or realization>", ...],\n'
        '    "themes": ["<recurring topic or focus area>", ...]\n'
        '  }\n'
        '}\n'
        "Keep each item concise (one sentence). Use empty arrays for categories with nothing relevant.\n"
        "Focus on substance — extract what actually matters from the activity above."
    )

    return "\n".join(lines)


def _parse_response(raw: str, date: str, message_count: int) -> JournalGenerateResponse:
    """Parse the LLM response, stripping markdown fences if present."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text[: text.rfind("```")]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI returned invalid JSON: {exc}",
        ) from exc

    cats = data.get("categories", {})
    return JournalGenerateResponse(
        date=date,
        headline=data.get("headline", ""),
        summary=data.get("summary", ""),
        categories=JournalCategories(
            actions=cats.get("actions", []),
            decisions=cats.get("decisions", []),
            insights=cats.get("insights", []),
            themes=cats.get("themes", []),
        ),
        messageCount=message_count,
    )


@router.post("/generate", response_model=JournalGenerateResponse)
async def generate_journal(
    request: JournalGenerateRequest,
    _: AuthContext = AUTH_DEP,
    session: AsyncSession = SESSION_DEP,
) -> JournalGenerateResponse:
    """Generate a structured daily journal entry from today's AI chat activity."""
    if not request.messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No messages provided. Have at least one AI conversation today first.",
        )

    prompt = _build_prompt(request.date, request.messages, request.memory)

    # Try OpenAI first, fall back to Gemini
    openai_key = await get_api_key("openai", session, settings.openai_api_key)
    if openai_key.strip():
        return await _generate_with_openai(openai_key.strip(), prompt, request.date, len(request.messages))

    gemini_key = await get_api_key("gemini", session, settings.gemini_api_key)
    if gemini_key.strip():
        return await _generate_with_gemini(gemini_key.strip(), prompt, request.date, len(request.messages))

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="No AI API key configured. Add OpenAI or Gemini key in Settings.",
    )


async def _generate_with_openai(
    api_key: str, prompt: str, date: str, message_count: int
) -> JournalGenerateResponse:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    try:
        resp = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a personal journal assistant. Always respond with valid JSON only — no markdown, no prose outside the JSON object.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
        )
        raw = resp.choices[0].message.content or ""
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenAI error: {exc}",
        ) from exc

    return _parse_response(raw, date, message_count)


async def _generate_with_gemini(
    api_key: str, prompt: str, date: str, message_count: int
) -> JournalGenerateResponse:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    try:
        resp = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction="You are a personal journal assistant. Always respond with valid JSON only — no markdown, no prose outside the JSON object.",
                temperature=0.4,
            ),
        )
        raw = resp.text or ""
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gemini error: {exc}",
        ) from exc

    return _parse_response(raw, date, message_count)
