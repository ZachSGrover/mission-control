"""Cross-row sequence detectors — slow_response + missed_follow_up.

Both detectors look at message *sequences* on the same chat.  They emit
``ChatterFindingCandidate`` rows (Layer 2) so the rollup engine deduplicates,
groups by (chatter, code, account), and ships ONE Discord digest.

slow_response
  Fan inbound on a chat with no outbound on the same chat in the configured
  response window (default 30 min).  Only triggers once the response window
  has *closed* — we never flag an inbound that still has time to be answered.

missed_follow_up
  Narrower than slow_response.  Only fan inbound that contains a buying
  signal or sales objection AND no outbound on the same chat in a longer
  follow-up window (default 60 min).  Captures conversations that went
  cold after a high-intent moment.

Privacy: detectors read message bodies for the missed_follow_up regex, but
emit only privacy-safe fields (chat is identified by an internal source id
that is *never* rendered in Discord — only the chatter and account display
names + generic detection phrase reach Discord through the rollup).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.of_intelligence import OfIntelligenceMessage
from app.services.of_intelligence.qc.chatter_findings import ChatterFindingCandidate
from app.services.of_intelligence.qc.detectors import (
    _matches_buying_signal,
    _matches_weak_sales,
)

logger = get_logger(__name__)

DEFAULT_SLOW_RESPONSE_WINDOW_MINUTES = 30
DEFAULT_MISSED_FOLLOW_UP_WINDOW_MINUTES = 60
# Look back this far for inbound candidates — bounded so the scan stays cheap.
DEFAULT_LOOKBACK_HOURS = 4


# ── Shared chat-grouping helper ─────────────────────────────────────────────


async def _load_chat_messages(
    session: AsyncSession,
    *,
    lookback_hours: int,
) -> dict[str, list[OfIntelligenceMessage]]:
    """Return ``{chat_source_id: [messages sorted by sent_at asc]}``.

    Filters: messages with chat_source_id + sent_at in lookback window.
    """
    cutoff = utcnow() - timedelta(hours=lookback_hours)
    rows = (
        await session.exec(
            select(OfIntelligenceMessage)
            .where(col(OfIntelligenceMessage.sent_at) >= cutoff)
            .where(col(OfIntelligenceMessage.chat_source_id).is_not(None))
        )
    ).all()
    by_chat: dict[str, list[OfIntelligenceMessage]] = defaultdict(list)
    for r in rows:
        if r.chat_source_id is None or r.sent_at is None:
            continue
        by_chat[r.chat_source_id].append(r)
    for chat in by_chat.values():
        chat.sort(key=_sent_at_key)
    return by_chat


def _sent_at_key(m: OfIntelligenceMessage) -> datetime:
    return m.sent_at or datetime.min


def _resolve_prior_chatter(
    chat_msgs: list[OfIntelligenceMessage],
    cutoff_index: int,
) -> str | None:
    """Look back from ``cutoff_index`` for the most recent outbound chatter.

    Returns None if no prior outbound has a chatter assigned — finding rollups
    fall back to a placeholder for those.
    """
    for prior in reversed(chat_msgs[:cutoff_index]):
        if prior.direction == "out" and prior.chatter_source_id:
            return prior.chatter_source_id
    return None


def _existing_finding_message_ids_filter(
    candidates: list[ChatterFindingCandidate],
    seen: set[str],
) -> list[ChatterFindingCandidate]:
    return [c for c in candidates if not c.message_source_id or c.message_source_id not in seen]


# ── slow_response ───────────────────────────────────────────────────────────


async def scan_slow_response(
    session: AsyncSession,
    *,
    response_window_minutes: int = DEFAULT_SLOW_RESPONSE_WINDOW_MINUTES,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    seen_message_ids: set[str] | None = None,
) -> list[ChatterFindingCandidate]:
    """Inbound with no outbound reply on same chat within the response window."""
    by_chat = await _load_chat_messages(session, lookback_hours=lookback_hours)
    cutoff_for_closed_window = utcnow() - timedelta(minutes=response_window_minutes)

    candidates: list[ChatterFindingCandidate] = []
    for chat_msgs in by_chat.values():
        for i, m in enumerate(chat_msgs):
            if m.direction != "in" or m.sent_at is None:
                continue
            # Only flag when the response window has closed.  An inbound
            # received a minute ago still has time to be answered.
            if m.sent_at > cutoff_for_closed_window:
                continue
            response_deadline = m.sent_at + timedelta(minutes=response_window_minutes)
            has_reply = any(
                later.direction == "out"
                and later.sent_at is not None
                and m.sent_at < later.sent_at <= response_deadline
                for later in chat_msgs[i + 1 :]
            )
            if has_reply:
                continue
            chatter = _resolve_prior_chatter(chat_msgs, i)
            candidates.append(
                ChatterFindingCandidate(
                    code="slow_response",
                    severity="medium",
                    account_source_id=m.account_source_id,
                    chatter_source_id=chatter,
                    message_source_id=m.source_id,
                    detection_phrase=f"no reply within {response_window_minutes} min",
                )
            )

    if seen_message_ids:
        candidates = _existing_finding_message_ids_filter(candidates, seen_message_ids)

    if candidates:
        logger.info(
            "of_qc.sequence.slow_response window_min=%s candidates=%s",
            response_window_minutes,
            len(candidates),
        )
    return candidates


# ── missed_follow_up ────────────────────────────────────────────────────────


def _is_high_intent_inbound(body: str | None) -> bool:
    if not body:
        return False
    return _matches_buying_signal(body) or _matches_weak_sales(body)


async def scan_missed_follow_up(
    session: AsyncSession,
    *,
    follow_up_window_minutes: int = DEFAULT_MISSED_FOLLOW_UP_WINDOW_MINUTES,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    seen_message_ids: set[str] | None = None,
) -> list[ChatterFindingCandidate]:
    """High-intent inbound with no outbound on same chat within follow-up window."""
    by_chat = await _load_chat_messages(session, lookback_hours=lookback_hours)
    cutoff_for_closed_window = utcnow() - timedelta(minutes=follow_up_window_minutes)

    candidates: list[ChatterFindingCandidate] = []
    for chat_msgs in by_chat.values():
        for i, m in enumerate(chat_msgs):
            if m.direction != "in" or m.sent_at is None:
                continue
            if m.sent_at > cutoff_for_closed_window:
                continue
            if not _is_high_intent_inbound(m.body):
                continue
            response_deadline = m.sent_at + timedelta(minutes=follow_up_window_minutes)
            has_follow_up = any(
                later.direction == "out"
                and later.sent_at is not None
                and m.sent_at < later.sent_at <= response_deadline
                for later in chat_msgs[i + 1 :]
            )
            if has_follow_up:
                continue
            chatter = _resolve_prior_chatter(chat_msgs, i)
            candidates.append(
                ChatterFindingCandidate(
                    code="missed_follow_up",
                    severity="high",
                    account_source_id=m.account_source_id,
                    chatter_source_id=chatter,
                    message_source_id=m.source_id,
                    detection_phrase=f"no follow-up within {follow_up_window_minutes} min on high-intent inbound",
                )
            )

    if seen_message_ids:
        candidates = _existing_finding_message_ids_filter(candidates, seen_message_ids)

    if candidates:
        logger.info(
            "of_qc.sequence.missed_follow_up window_min=%s candidates=%s",
            follow_up_window_minutes,
            len(candidates),
        )
    return candidates
