"""Critical QC risk detectors — refund / banned / rude / escalation.

Scans recent ``OfIntelligenceMessage`` rows for high-signal risk patterns
and yields ``AlertCandidate``-shaped tuples for the alert engine to
persist + ship to Discord.

Detection is intentionally simple in v1 — curated regex against a small
keyword list per category.  No ML.  The keyword lists below are
placeholders meant to be tuned against real data; the dispatcher and
privacy guards never render the matched keyword itself.

Hard rules:
  • Discord output never contains the message body, the fan handle, the
    matched keyword, or anything from the raw OnlyMonster payload.
  • Categories are described generically (e.g. ``"refund-language
    detected"``).  Operators open the dashboard via the alert ref to see
    the actual conversation.
  • Direction matters: outbound categories (banned_content_risk,
    rude_reply) only fire on chatter→fan messages; inbound categories
    (refund_risk, serious_escalation_risk) only fire on fan→chatter
    messages.  Reversed checks are explicitly skipped.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import NamedTuple

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.of_intelligence import (
    OfIntelligenceAccount,
    OfIntelligenceChatter,
    OfIntelligenceMessage,
)

logger = get_logger(__name__)

DEFAULT_LOOKBACK_HOURS = 1


# ── Curated keyword maps ─────────────────────────────────────────────────────
# Word boundaries on both sides, case-insensitive.  Each pattern is a list of
# alternation groups; we OR them together at module load to a single compiled
# regex per category.

_REFUND_TERMS = [
    r"refund",
    r"chargeback",
    r"charge[\s-]?back",
    r"dispute",
    r"cancel(?:ling|ed)?\s+(?:my\s+)?(?:sub|subscription|payment)",
    r"report\s+(?:you|him|her|this|the\s+account)",
    r"scam(?:mer|ming)?",
    r"fraud",
    r"lawyer",
    r"legal\s+action",
    r"sue\s+you",
]

_BANNED_CONTENT_TERMS = [
    # Placeholder categories.  Tune against real OF policy guidance.
    r"minor",
    r"underage",
    r"under\s*18",
    r"\bteen\b",  # paired with policy review — broad, intentionally over-flags
    r"weapon",
    r"trafficking",
]

_RUDE_TERMS = [
    r"shut\s*up",
    r"f\W*u\W*c\W*k\s*off",
    r"\bstfu\b",
    r"\bidiot\b",
    r"\bstupid\b",
    r"\bbitch\b",
    r"\bloser\b",
    r"piss\s*off",
    r"go\s*away",
]

_ESCALATION_TERMS = [
    r"calling\s+(?:the\s+)?police",
    r"\bfbi\b",
    r"kill\s+myself",
    r"harm\s+myself",
    r"\bsuicid",
    r"\btraffick",
    r"abuse",
]

# Phase-1 sales-side detectors.
# missed_buying_signal: fan asks about price / availability / value.  We flag
# it for review even if the chatter does respond — operators told us they want
# to *see every signal* and decide.  False-positive cost is low because the
# alert dedups per (account, code) until acknowledged.
_BUYING_SIGNAL_TERMS = [
    r"how\s+much",
    r"what\s+(?:does\s+|do\s+)?(?:that|it|this|the\s+(?:vid|video|content|set|pic|pics|menu))\s+cost",
    r"price",
    r"\bcost\b",
    r"\bppv\b",
    r"can\s+i\s+(?:get|buy|see)",
    r"send\s+me\s+(?:more|the|a)",
    r"how\s+do\s+i\s+(?:buy|get)",
    r"any\s+(?:menus?|specials?|deals?)",
    r"do\s+you\s+(?:have|sell|do)",
]

# weak_sales_handling: fan voicing an objection.  Flagged so operator can
# review whether the chatter recovered with a special / discount / personal
# offer.
_WEAK_SALES_TERMS = [
    r"too\s+(?:expensive|much|pricey)",
    r"can'?t\s+afford",
    r"don'?t\s+have\s+(?:money|cash|the\s+money)",
    r"not\s+(?:right\s+)?now",
    r"maybe\s+(?:later|next\s+time)",
    r"i'?ll\s+think\s+about\s+it",
    r"out\s+of\s+(?:my\s+)?budget",
    r"no\s+thanks?",
    r"too\s+steep",
]


def _compile_any(patterns: Iterable[str]) -> re.Pattern[str]:
    """Build a case-insensitive OR of patterns, anchored on a word boundary
    at the start.  We deliberately do NOT enforce a trailing word boundary
    so prefix patterns (``suicid``, ``traffick``) match their full
    family (``suicide``, ``suicidal``, ``trafficking``).  Concrete words
    that happen to share a prefix with a longer one (e.g. ``scam`` inside
    ``scammer``) get matched too — that's a deliberate over-flag for v1
    safety; tune as we collect real data.
    """
    return re.compile(r"\b(?:" + "|".join(patterns) + r")", re.IGNORECASE)


_REFUND_RX = _compile_any(_REFUND_TERMS)
_BANNED_RX = _compile_any(_BANNED_CONTENT_TERMS)
_RUDE_RX = _compile_any(_RUDE_TERMS)
_ESCALATION_RX = _compile_any(_ESCALATION_TERMS)
_BUYING_SIGNAL_RX = _compile_any(_BUYING_SIGNAL_TERMS)
_WEAK_SALES_RX = _compile_any(_WEAK_SALES_TERMS)


# ── Detector entry points ────────────────────────────────────────────────────


def _matches_refund(body: str) -> bool:
    return bool(_REFUND_RX.search(body))


def _matches_banned(body: str) -> bool:
    return bool(_BANNED_RX.search(body))


def _matches_rude(body: str) -> bool:
    return bool(_RUDE_RX.search(body))


def _matches_escalation(body: str) -> bool:
    return bool(_ESCALATION_RX.search(body))


def _matches_buying_signal(body: str) -> bool:
    return bool(_BUYING_SIGNAL_RX.search(body))


def _matches_weak_sales(body: str) -> bool:
    return bool(_WEAK_SALES_RX.search(body))


# Per-category configuration: (code, severity, direction-required, matcher,
# title-template-using-account-username, generic-detection-phrase).
class _Rule(NamedTuple):
    code: str
    severity: str
    direction: str  # "in" (fan→chatter) or "out" (chatter→fan)
    matcher: callable  # type: ignore[type-arg]
    title_template: str
    detection_phrase: str  # what ``signal`` field shows in Discord


_CRITICAL_RULES: list[_Rule] = [
    _Rule(
        code="refund_risk",
        severity="critical",
        direction="in",
        matcher=_matches_refund,
        title_template="Refund / chargeback signal on {account}",
        detection_phrase="refund-language detected",
    ),
    _Rule(
        code="banned_content_risk",
        severity="critical",
        direction="out",
        matcher=_matches_banned,
        title_template="Policy-term category hit on {account}",
        detection_phrase="policy-term category hit",
    ),
    _Rule(
        code="rude_reply",
        severity="high",
        direction="out",
        matcher=_matches_rude,
        title_template="Rude reply flagged on {account}",
        detection_phrase="harsh tone detected",
    ),
    _Rule(
        code="serious_escalation_risk",
        severity="critical",
        direction="in",
        matcher=_matches_escalation,
        title_template="Escalation risk on {account}",
        detection_phrase="escalation-language detected",
    ),
    _Rule(
        code="missed_buying_signal",
        severity="high",
        direction="in",
        matcher=_matches_buying_signal,
        title_template="Buying-signal review needed on {account}",
        detection_phrase="fan asked about price/availability",
    ),
    _Rule(
        code="weak_sales_handling",
        severity="high",
        direction="in",
        matcher=_matches_weak_sales,
        title_template="Sales-objection review needed on {account}",
        detection_phrase="fan voiced an objection",
    ),
]


# ── Output shape — kept compatible with alerts.AlertCandidate ───────────────


@dataclass
class CriticalQcCandidate:
    code: str
    severity: str
    title: str
    account_source_id: str | None
    chatter_source_id: str | None
    account_username: str | None
    chatter_name: str | None
    detection_phrase: str  # privacy-safe — never the matched keyword


# ── Public scan ─────────────────────────────────────────────────────────────


async def scan_critical_qc(
    session: AsyncSession,
    *,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
) -> list[CriticalQcCandidate]:
    """Scan recent messages for critical QC risk patterns.

    Returns one candidate per (rule, account) combination in the window —
    the alert engine's dedup gate prevents repeated Discord shipping while
    an alert is open.  Returning multiple matches per account is fine; they
    collapse downstream.
    """
    cutoff = utcnow() - timedelta(hours=lookback_hours)
    rows = (
        await session.exec(
            select(OfIntelligenceMessage)
            .where(OfIntelligenceMessage.sent_at >= cutoff)
            .where(col(OfIntelligenceMessage.body).is_not(None))
        )
    ).all()

    if not rows:
        return []

    # Resolve display names once per scan.
    account_usernames = await _account_usernames(
        session, [r.account_source_id for r in rows if r.account_source_id]
    )
    chatter_names = await _chatter_names(
        session, [r.chatter_source_id for r in rows if r.chatter_source_id]
    )

    # Track which (code, account) combos we've already emitted to avoid
    # producing duplicate candidates within a single scan — the alert
    # engine's open-alert dedup is also a safety net, but skipping here
    # keeps the candidates list short.
    seen: set[tuple[str, str | None]] = set()
    candidates: list[CriticalQcCandidate] = []

    for row in rows:
        body = row.body or ""
        if not body:
            continue
        for rule in _CRITICAL_RULES:
            if row.direction != rule.direction:
                continue
            if not rule.matcher(body):
                continue
            key = (rule.code, row.account_source_id)
            if key in seen:
                continue
            seen.add(key)

            account_name = (
                account_usernames.get(row.account_source_id)
                if row.account_source_id
                else None
            )
            chatter_name = (
                chatter_names.get(row.chatter_source_id)
                if row.chatter_source_id
                else None
            )
            candidates.append(
                CriticalQcCandidate(
                    code=rule.code,
                    severity=rule.severity,
                    title=rule.title_template.format(
                        account=account_name or row.account_source_id or "unknown"
                    ),
                    account_source_id=row.account_source_id,
                    chatter_source_id=row.chatter_source_id,
                    account_username=account_name,
                    chatter_name=chatter_name,
                    detection_phrase=rule.detection_phrase,
                )
            )

    if candidates:
        logger.info(
            "of_qc.detectors.scan window_h=%s rows=%s candidates=%s",
            lookback_hours,
            len(rows),
            len(candidates),
        )
    return candidates


async def _account_usernames(
    session: AsyncSession,
    source_ids: list[str],
) -> dict[str, str | None]:
    if not source_ids:
        return {}
    rows = (
        await session.exec(
            select(OfIntelligenceAccount).where(
                col(OfIntelligenceAccount.source_id).in_(set(source_ids))
            )
        )
    ).all()
    return {r.source_id: r.username for r in rows}


async def _chatter_names(
    session: AsyncSession,
    source_ids: list[str],
) -> dict[str, str | None]:
    if not source_ids:
        return {}
    rows = (
        await session.exec(
            select(OfIntelligenceChatter).where(
                col(OfIntelligenceChatter.source_id).in_(set(source_ids))
            )
        )
    ).all()
    return {r.source_id: r.name for r in rows}
