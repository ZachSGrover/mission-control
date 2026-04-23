"""
speed_layer — classify inbound messages as FAST (predefined reply) or AI.

Rules (Phase 2 spec):
  • FAST  → under 5 words AND not a question AND no command prefix
  • FAST  → simple greeting (hi / hey / hello / …)
  • AI    → message > 5 words OR contains a question mark

Everything here is pure (no I/O) so it stays microsecond-cheap on the hot path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["classify", "fast_response_for", "Route"]

# ── Greeting / small-talk table ───────────────────────────────────────────────

_GREETINGS: dict[str, str] = {
    "hi": "Hey! 👋  I'm live.  Send a question or type a command to dig in.",
    "hey": "Hey! 👋  I'm listening — what's up?",
    "hello": "Hello!  Mission Control is online.  Ask me anything.",
    "yo": "Yo.  Ready when you are.",
    "sup": "Not much — operator standing by.",
    "gm": "Good morning ☀️",
    "gn": "Good night 🌙",
    "thanks": "Anytime.",
    "thank you": "Anytime.",
    "ty": "👍",
    "ok": "👍",
    "cool": "👍",
    "ping": "pong",
    "test": "✅ receiving you",
}

_GENERIC_FAST = "👍 got it — if you need a detailed answer, end with '?' or give me more context."

# Normalize punctuation/whitespace, keep it cheap.
_WORD_SPLIT = re.compile(r"\s+")


@dataclass(frozen=True)
class Route:
    use_ai: bool
    reason: str  # "greeting" | "short" | "question" | "long" | "command"
    fast_reply: str | None  # populated iff use_ai is False


def _normalize(text: str) -> str:
    return text.strip().lower().rstrip(".!,;:")


def classify(text: str) -> Route:
    """Decide whether a message needs AI or can get an instant fast reply."""
    raw = (text or "").strip()
    if not raw:
        return Route(use_ai=False, reason="empty", fast_reply="(empty)")

    # Commands are handled elsewhere — never touch AI
    if raw.startswith("/"):
        return Route(use_ai=False, reason="command", fast_reply=None)

    has_question = "?" in raw
    normalized = _normalize(raw)
    words = [w for w in _WORD_SPLIT.split(normalized) if w]
    word_count = len(words)

    # Greetings / small-talk dictionary (case-insensitive, punctuation-stripped)
    if normalized in _GREETINGS:
        return Route(use_ai=False, reason="greeting", fast_reply=_GREETINGS[normalized])

    # Two-word combos like "hi there", "hey bot"
    if word_count <= 2 and words and words[0] in _GREETINGS:
        return Route(use_ai=False, reason="greeting", fast_reply=_GREETINGS[words[0]])

    # Questions always go to AI regardless of length
    if has_question:
        return Route(use_ai=True, reason="question", fast_reply=None)

    # Short non-question: predefined ack
    if word_count < 5:
        return Route(use_ai=False, reason="short", fast_reply=_GENERIC_FAST)

    # Long declarative → AI
    return Route(use_ai=True, reason="long", fast_reply=None)


def fast_response_for(text: str) -> str | None:
    """Convenience wrapper — returns the fast reply string or None if AI is needed."""
    route = classify(text)
    return route.fast_reply if not route.use_ai else None
