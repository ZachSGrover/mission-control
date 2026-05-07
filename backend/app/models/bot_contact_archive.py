"""Mission Control bot contact archive — one row per (bot, profile, handle).

Used by sandbox-mode duplicate-prevention checks and by the operator
contact-archive view.  In the X DM Bot RTxRT MVP this table is *only*
populated by sandbox dry-runs (mock contacts) — there is no live
send path, so ``sent_count`` and ``last_sent_at`` are not advanced by
real platform writes.

Privacy contract:
  • ``handle`` is a short profile handle (e.g. ``mock_contact_001`` in
    sandbox).  Real fan PII must never be stored here in MVP.
  • ``conversation_url`` is gated on the API surface: operator views
    return only counts, not URLs; only owner-tier consumers may receive
    the full URL.  In sandbox mode, URLs are redacted placeholders
    (``redacted://x-message/<handle>``).
  • No tokens, cookies, AdsPower keys, or session data may appear in
    any column.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Column, String
from sqlmodel import Field, SQLModel

from app.core.time import utcnow


class BotContactArchive(SQLModel, table=True):
    """A contact ever messaged or queued for a given bot/profile combo."""

    __tablename__ = "bot_contact_archive"  # pyright: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    bot_id: UUID = Field(index=True, foreign_key="bot_registry.id")
    profile_id: str = Field(index=True, max_length=64)
    handle: str = Field(index=True, max_length=128)
    conversation_url: str = Field(
        sa_column=Column("conversation_url", String(512), nullable=False),
    )
    last_sent_at: datetime | None = Field(default=None)
    sent_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


__all__ = ["BotContactArchive"]
