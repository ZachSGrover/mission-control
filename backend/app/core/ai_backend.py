"""
ai_backend — one-shot "ask the model" helper used by the messaging speed layer.

Prefers Anthropic (Claude) if a key is configured; falls back to OpenAI; else
returns a plain-text notice so the messenger always gets *something* to send.

Only called on the AI path — the fast/greeting path never reaches this module.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from typing import Final

from anthropic.types import TextBlock
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.secrets_store import get_api_key
from app.core.time import utcnow
from app.services.audit_log import record_audit
from app.services.usage.logger import (
    current_environment,
    extract_provider_usage,
    record_usage_event,
)

# ── Provider order (cloud-only; no OpenClaw / localhost path) ────────────────
# Controlled by MC_AI_PROVIDER_ORDER env var.  Default: openai first, anthropic
# optional fallback — matches the cloud-first directive.
_DEFAULT_ORDER = "openai,anthropic"
_PROVIDER_ORDER: tuple[str, ...] = tuple(
    p.strip().lower()
    for p in (os.getenv("MC_AI_PROVIDER_ORDER") or _DEFAULT_ORDER).split(",")
    if p.strip()
)

__all__ = ["ask_ai", "ask_ai_detailed"]

logger = get_logger(__name__)

# ── Retry policy (exponential backoff) ───────────────────────────────────────
_MAX_ATTEMPTS: "Final[int]" = 3
_BASE_DELAY_S: "Final[float]" = 0.6


def _is_transient(exc: BaseException) -> bool:
    """Best-effort classifier for retryable errors."""
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()
    if isinstance(exc, asyncio.TimeoutError):
        return True
    if any(
        tag in name
        for tag in ("timeout", "connection", "apiconnection", "ratelimit", "serviceunavailable")
    ):
        return True
    if any(tag in msg for tag in ("502", "503", "504", "429", "temporarily", "overloaded")):
        return True
    return False


async def _attempt_with_retry(
    coro_factory: Callable[[], Awaitable[str]],
    provider: str,
    timeout_s: float,
) -> tuple[str, int]:
    """Run coro_factory() with up to _MAX_ATTEMPTS retries on transient errors.
    Returns (reply, attempts_used).  Raises last exception on final failure."""
    last_exc: BaseException | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            reply = await asyncio.wait_for(coro_factory(), timeout=timeout_s)
            if attempt > 1:
                logger.info("ai_backend.%s.retry.success attempt=%d", provider, attempt)
            return reply, attempt
        except BaseException as exc:  # noqa: BLE001 — we classify below
            last_exc = exc
            if attempt >= _MAX_ATTEMPTS or not _is_transient(exc):
                raise
            delay = _BASE_DELAY_S * (2 ** (attempt - 1))
            logger.warning(
                "ai_backend.%s.retry attempt=%d delay=%.2fs error=%s",
                provider,
                attempt,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    # Unreachable but keeps mypy happy
    if last_exc:
        raise last_exc
    raise RuntimeError("ai_backend: exhausted retries without exception")


_NO_KEY_MSG: Final = (
    "AI responses aren't configured yet. Add an Anthropic or OpenAI API key in "
    "Settings → API Keys, then try again."
)

_SYSTEM_PROMPT: Final = (
    "You are the Mission Control assistant replying over a chat bot "
    "(Telegram or Discord). Keep replies under 400 characters unless the user "
    "asks for detail. Be direct and operator-focused."
)

_MAX_TIMEOUT_S: Final = 12.0


async def ask_ai(
    prompt: str,
    session: AsyncSession,
    *,
    trigger_source: str = "backend",
) -> tuple[str, str]:
    """
    Return (reply_text, provider_used).  Thin wrapper over ask_ai_detailed for
    backwards compatibility with Phase 2 callers.
    """
    reply, provider, _attempts, _err = await ask_ai_detailed(
        prompt, session, trigger_source=trigger_source
    )
    return reply, provider


async def _run_provider(
    provider: str,
    prompt: str,
    session: AsyncSession,
    trigger_source: str,
) -> tuple[str, int]:
    """Resolve the key for `provider`, call it, return (reply, attempts)."""
    if provider == "openai":
        key = await get_api_key("openai", session, settings.openai_api_key)
        if not key.strip():
            raise RuntimeError("openai: no api key configured")
        return await _attempt_with_retry(
            lambda: _call_openai(prompt, key.strip(), session, trigger_source),
            provider="openai",
            timeout_s=_MAX_TIMEOUT_S,
        )
    if provider == "anthropic":
        key = await get_api_key("anthropic", session, settings.anthropic_api_key)
        if not key.strip():
            raise RuntimeError("anthropic: no api key configured")
        return await _attempt_with_retry(
            lambda: _call_anthropic(prompt, key.strip(), session, trigger_source),
            provider="anthropic",
            timeout_s=_MAX_TIMEOUT_S,
        )
    raise RuntimeError(f"unknown provider: {provider}")


async def ask_ai_detailed(
    prompt: str,
    session: AsyncSession,
    *,
    trigger_source: str = "backend",
) -> tuple[str, str, int, str | None]:
    """
    Return (reply_text, provider_used, total_attempts, error_or_none).

    Tries providers in `_PROVIDER_ORDER` (default: openai, then anthropic).
    All calls go directly to the hosted cloud APIs — no OpenClaw / localhost
    gateway is involved.  Each provider retries transient errors with
    exponential backoff before the next in the chain is tried.

    Sprint 3 hardening: the prompt is run through
    :func:`app.core.pii_redact.redact_for_llm` before being handed to
    the provider client. The redactor strips obvious credentials,
    emails, phone numbers, and JWT-shaped strings. The original
    ``prompt`` is never logged.
    """
    from app.core.pii_redact import redact_for_llm

    redacted_prompt, was_redacted, redaction_counts = redact_for_llm(prompt)
    total_attempts = 0
    last_error: str | None = None
    prompt_len = len(redacted_prompt)

    for provider in _PROVIDER_ORDER:
        try:
            reply, attempts = await _run_provider(
                provider, redacted_prompt, session, trigger_source
            )
            total_attempts += attempts
            await _audit_llm_call(
                session,
                provider=provider,
                result="success",
                attempts=total_attempts,
                prompt_len=prompt_len,
                reply_len=len(reply),
                error=None,
                redaction_applied=was_redacted,
                redaction_counts=redaction_counts,
            )
            return reply, provider, total_attempts, last_error
        except Exception as exc:
            total_attempts += _MAX_ATTEMPTS
            last_error = f"{last_error + '; ' if last_error else ''}{provider}: {exc}"
            logger.warning("ai_backend.%s.unavailable error=%s", provider, exc)
            await _audit_llm_call(
                session,
                provider=provider,
                result="failed",
                attempts=total_attempts,
                prompt_len=prompt_len,
                reply_len=0,
                error=type(exc).__name__,
                redaction_applied=was_redacted,
                redaction_counts=redaction_counts,
            )

    return _NO_KEY_MSG, "none", total_attempts, last_error


async def _audit_llm_call(
    session: AsyncSession,
    *,
    provider: str,
    result: str,
    attempts: int,
    prompt_len: int,
    reply_len: int,
    error: str | None,
    redaction_applied: bool = False,
    redaction_counts: dict[str, int] | None = None,
) -> None:
    """Audit a single LLM provider attempt without ever touching prompt/reply text.

    By design we log only sizes and the exception class — never prompt body,
    reply body, or any hash that could re-identify content. The audit row is
    added to the caller's session and committed so each call is durable even
    if the request handler later rolls back.
    """
    # Late imports to avoid a hard-coupled module-level dependency for a
    # belt-and-braces type narrowing. The ``AuditResult`` / ``AuditSeverity``
    # aliases live in ``app.services.audit_log`` so the vocabulary stays
    # single-sourced; using them here (instead of inline ``Literal[...]``
    # subscripts) also sidesteps a pyflakes false-positive that misreads
    # aliased ``Literal`` subscript args as bare names.
    from typing import cast

    from app.services.audit_log import AuditResult, AuditSeverity

    safe_result: AuditResult = cast(
        AuditResult,
        result if result in {"success", "denied", "failed", "blocked", "skipped"} else "failed",
    )
    severity: AuditSeverity = "info" if safe_result == "success" else "warning"
    await record_audit(
        session,
        event_type="llm.call",
        category="llm",
        action="invoke",
        result=safe_result,
        severity=severity,
        resource_type="llm_provider",
        resource_id=provider,
        metadata={
            "provider": provider,
            "attempts": attempts,
            "prompt_chars": prompt_len,
            "reply_chars": reply_len,
            "error_class": error,
            "pii_redaction_applied": redaction_applied,
            "pii_redaction_counts": redaction_counts or {},
        },
    )
    try:
        await session.commit()
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("ai_backend.audit_commit_failed error=%s", type(exc).__name__)


_AI_BACKEND_FEATURE: Final = "messaging"


async def _call_anthropic(
    prompt: str,
    api_key: str,
    session: AsyncSession,
    trigger_source: str,
) -> str:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)
    model = "claude-haiku-4-5-20251001"
    started_at = utcnow()
    try:
        message = await client.messages.create(
            model=model,
            max_tokens=400,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        await record_usage_event(
            session,
            provider="anthropic",
            model=model,
            feature=_AI_BACKEND_FEATURE,
            trigger_source=trigger_source,
            environment=current_environment(),
            status="error",
            error=type(exc).__name__,
            started_at=started_at,
            ended_at=utcnow(),
        )
        raise
    in_tok, out_tok = extract_provider_usage("anthropic", message)
    await record_usage_event(
        session,
        provider="anthropic",
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        feature=_AI_BACKEND_FEATURE,
        trigger_source=trigger_source,
        environment=current_environment(),
        started_at=started_at,
        ended_at=utcnow(),
    )
    parts = [block.text for block in message.content if isinstance(block, TextBlock)]
    return "".join(parts).strip() or "(empty reply)"


async def _call_openai(
    prompt: str,
    api_key: str,
    session: AsyncSession,
    trigger_source: str,
) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    model = settings.openai_model or "gpt-4o-mini"
    started_at = utcnow()
    try:
        completion = await client.chat.completions.create(
            model=model,
            max_tokens=400,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as exc:
        await record_usage_event(
            session,
            provider="openai",
            model=model,
            feature=_AI_BACKEND_FEATURE,
            trigger_source=trigger_source,
            environment=current_environment(),
            status="error",
            error=type(exc).__name__,
            started_at=started_at,
            ended_at=utcnow(),
        )
        raise
    in_tok, out_tok = extract_provider_usage("openai", completion)
    await record_usage_event(
        session,
        provider="openai",
        model=model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        feature=_AI_BACKEND_FEATURE,
        trigger_source=trigger_source,
        environment=current_environment(),
        started_at=started_at,
        ended_at=utcnow(),
    )
    choice = completion.choices[0] if completion.choices else None
    reply = (choice.message.content if choice and choice.message else "") or ""
    return reply.strip() or "(empty reply)"
