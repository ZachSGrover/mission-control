"""Layer 2 — chatter pattern detectors that write QC findings.

Each match produces an ``OfIntelligenceQcFinding`` row.  Findings are NOT
shipped to Discord directly — the rollup engine (``qc/rollups.py``) groups
them per (chatter, code, account) over a window and ships ONE digest when
thresholds are crossed.

Privacy: detectors read message bodies but emit only privacy-safe fields
(account_source_id / chatter_source_id / message_source_id / generic
detection phrase).  The matched keyword and body are never persisted on
the finding row and never reach Discord.

Detectors implemented (per-message, no sequence joins):
  • bad_english          — outbound contains common typos / shorthand
  • lazy_reply           — outbound body is too short to count as a reply
  • low_effort_chatting  — outbound is short and has no question

Deferred to a follow-up (need cross-row queries):
  • slow_response        — outbound > N min after last inbound on chat
  • missed_follow_up     — inbound > N hours with no reply
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, NamedTuple

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.of_intelligence import OfIntelligenceMessage
from app.models.of_qc_finding import OfIntelligenceQcFinding

logger = get_logger(__name__)

DEFAULT_LOOKBACK_HOURS = 1


# ── Curated keyword maps ─────────────────────────────────────────────────────


_BAD_ENGLISH_PATTERNS = [
    r"\brecieve\w*",
    r"\balot\b",
    r"\bdefinately\b",
    r"\bseperate\w*",
    r"\boccured\b",
    r"\buntill\b",
    r"\bweather\s+or\s+not\b",  # weather → whether
    r"\byour\s+welcome\b",  # missing apostrophe trip
    r"\bshould\s+of\b",
    r"\bcould\s+of\b",
    r"\bwould\s+of\b",
]
# Shorthand tokens we count for the "pile-up" heuristic — 3+ in one message
# trips bad_english even when no individual typo regex hit.
_SHORTHAND_TOKEN_RX = re.compile(r"\b(?:u|ur|r|y|n|k|ok|tho|thru|cuz|bcuz)\b", re.IGNORECASE)
_SHORTHAND_PILEUP_THRESHOLD = 3

# lazy_reply: outbound that's basically a single short token / emoji.  We
# operate on the *cleaned* body (whitespace and emoji removed) — anything
# 4 chars or shorter counts.
_LAZY_REPLY_MAX_ALPHANUM = 4

# low_effort_chatting: outbound longer than lazy but still short and lacks
# a question (chatter isn't engaging the fan to keep the convo going).
_LOW_EFFORT_MAX_ALPHANUM = 25


def _compile_any(patterns: Iterable[str]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(patterns) + r")", re.IGNORECASE)


_BAD_ENGLISH_RX = _compile_any(_BAD_ENGLISH_PATTERNS)
_ALPHANUM_RX = re.compile(r"[A-Za-z0-9]")
_QUESTION_RX = re.compile(r"\?")


def _alphanum_len(body: str) -> int:
    return len(_ALPHANUM_RX.findall(body or ""))


def _matches_bad_english(body: str) -> bool:
    if not body:
        return False
    if _BAD_ENGLISH_RX.search(body):
        return True
    # Pile-up heuristic.
    return len(_SHORTHAND_TOKEN_RX.findall(body)) >= _SHORTHAND_PILEUP_THRESHOLD


def _matches_lazy_reply(body: str) -> bool:
    if not body:
        return True  # empty outbound is the laziest possible
    return _alphanum_len(body) <= _LAZY_REPLY_MAX_ALPHANUM


def _matches_low_effort(body: str) -> bool:
    if not body:
        return False  # already covered by lazy_reply
    n = _alphanum_len(body)
    if n <= _LAZY_REPLY_MAX_ALPHANUM:
        return False  # falls under lazy_reply, not low_effort
    return n <= _LOW_EFFORT_MAX_ALPHANUM and not _QUESTION_RX.search(body)


# Per-rule config: only outbound (chatter→fan).  Severities are kept low /
# medium because these always roll up — they never ship as standalone alerts.
class _ChatterRule(NamedTuple):
    code: str
    severity: str
    matcher: callable  # type: ignore[type-arg]
    detection_phrase: str


_CHATTER_RULES: list[_ChatterRule] = [
    _ChatterRule("bad_english", "low", _matches_bad_english, "outbound English-quality flag"),
    _ChatterRule("lazy_reply", "medium", _matches_lazy_reply, "outbound too short to count as reply"),
    _ChatterRule("low_effort_chatting", "low", _matches_low_effort, "outbound short + no question"),
]


# ── Output shape ────────────────────────────────────────────────────────────


@dataclass
class ChatterFindingCandidate:
    code: str
    severity: str
    account_source_id: str | None
    chatter_source_id: str | None
    message_source_id: str | None
    detection_phrase: str


# ── Public scan + persist ───────────────────────────────────────────────────


async def scan_chatter_findings(
    session: AsyncSession,
    *,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
) -> list[ChatterFindingCandidate]:
    """Scan recent outbound messages for chatter QC patterns.

    Returns a list of candidate findings.  Caller persists them via
    ``persist_findings``.  Splitting the scan and persist keeps tests
    able to inspect findings without DB writes if needed.
    """
    cutoff = utcnow() - timedelta(hours=lookback_hours)
    rows = (
        await session.exec(
            select(OfIntelligenceMessage)
            .where(OfIntelligenceMessage.sent_at >= cutoff)
            .where(OfIntelligenceMessage.direction == "out")
            .where(col(OfIntelligenceMessage.body).is_not(None))
        )
    ).all()

    if not rows:
        return []

    # Skip messages we already have a finding for — append-only, idempotent.
    seen_message_ids = await _existing_finding_message_ids(session)

    candidates: list[ChatterFindingCandidate] = []
    for row in rows:
        if row.source_id in seen_message_ids:
            continue
        body = row.body or ""
        for rule in _CHATTER_RULES:
            if not rule.matcher(body):
                continue
            candidates.append(
                ChatterFindingCandidate(
                    code=rule.code,
                    severity=rule.severity,
                    account_source_id=row.account_source_id,
                    chatter_source_id=row.chatter_source_id,
                    message_source_id=row.source_id,
                    detection_phrase=rule.detection_phrase,
                )
            )

    if candidates:
        logger.info(
            "of_qc.chatter_scan window_h=%s rows=%s candidates=%s",
            lookback_hours,
            len(rows),
            len(candidates),
        )
    return candidates


async def persist_findings(
    session: AsyncSession,
    candidates: Iterable[ChatterFindingCandidate],
) -> int:
    """Append candidates as ``OfIntelligenceQcFinding`` rows.  Returns count."""
    n = 0
    for c in candidates:
        session.add(
            OfIntelligenceQcFinding(
                code=c.code,
                severity=c.severity,
                account_source_id=c.account_source_id,
                chatter_source_id=c.chatter_source_id,
                message_source_id=c.message_source_id,
                detection_phrase=c.detection_phrase,
            )
        )
        n += 1
    if n:
        await session.commit()
    return n


async def _existing_finding_message_ids(session: AsyncSession) -> set[str]:
    """Return message_source_ids that already have at least one finding.

    Bounded by a 24h sliding window — older findings won't block new
    detections on rare reused message ids and the query stays cheap.
    """
    cutoff = utcnow() - timedelta(hours=24)
    rows = (
        await session.exec(
            select(OfIntelligenceQcFinding.message_source_id).where(
                OfIntelligenceQcFinding.created_at >= cutoff
            )
        )
    ).all()
    return {r for r in rows if r}


async def scan_all_chatter_findings(
    session: AsyncSession,
    *,
    per_message_lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
) -> list[ChatterFindingCandidate]:
    """Combined scan: per-message detectors + sequence detectors.

    The sequence detectors (slow_response, missed_follow_up) live in
    ``sequence_detectors.py`` so this module stays focused on per-message
    matching, but callers want a single entrypoint.  Local import here
    avoids a circular reference because ``sequence_detectors`` reads
    regexes from ``detectors.py``.
    """
    from app.services.of_intelligence.qc.sequence_detectors import (
        scan_missed_follow_up,
        scan_slow_response,
    )

    seen = await _existing_finding_message_ids(session)

    per_msg = await scan_chatter_findings(session, lookback_hours=per_message_lookback_hours)
    slow = await scan_slow_response(session, seen_message_ids=seen)
    missed = await scan_missed_follow_up(session, seen_message_ids=seen)

    # Per-message detectors already filter against ``seen`` in
    # ``scan_chatter_findings``.  Combine + de-dupe by (code, message_id).
    combined: list[ChatterFindingCandidate] = []
    seen_pairs: set[tuple[str, str | None]] = set()
    for c in (*per_msg, *slow, *missed):
        key = (c.code, c.message_source_id)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        combined.append(c)
    return combined


# Re-export for callers wiring the detectors and the alert engine together.
__all__ = [
    "ChatterFindingCandidate",
    "DEFAULT_LOOKBACK_HOURS",
    "persist_findings",
    "scan_all_chatter_findings",
    "scan_chatter_findings",
]
_ = Any  # keep import-tests quiet if Any becomes unused later
