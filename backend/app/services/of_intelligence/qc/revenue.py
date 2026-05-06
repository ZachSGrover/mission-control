"""Revenue-drop detector — per-account 24h vs 7d-avg comparison.

Operates on the existing ``OfIntelligenceRevenue`` table (read-only).  No
mutation of revenue rows.  No external IO.

Severity ladder (configurable):
  • ``high``    — 24h revenue is < ``threshold`` × 7d-avg AND prior-7d
                  total > 0  (i.e. account had history and dropped)
  • ``medium``  — 24h revenue is exactly 0 AND prior-7d total > 0
                  (special-cased: a hard zero gets flagged even if the
                  ratio rule wouldn't fire because of integer math)

Brand-new accounts with zero prior-7d history are intentionally skipped —
we cannot tell whether a fresh account is healthy or quietly broken yet.

Privacy: returns only ``account_source_id`` + display name + cents totals
+ severity.  No fan / message / API-payload data anywhere.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.of_intelligence import OfIntelligenceAccount, OfIntelligenceRevenue

logger = get_logger(__name__)

DEFAULT_THRESHOLD = 0.6  # 24h must be < 60% of 7d avg
ACCOUNT_REVENUE_DROP_CODE = "account_revenue_drop"

Severity = Literal["medium", "high"]


@dataclass
class RevenueDropWarning:
    account_source_id: str
    username: str | None
    revenue_24h_cents: int
    revenue_7d_avg_cents: int
    severity: Severity
    reason: str  # short, privacy-safe — never includes raw API content


# ── Public detector ─────────────────────────────────────────────────────────


async def detect_revenue_drops(
    session: AsyncSession,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    now: datetime | None = None,
) -> list[RevenueDropWarning]:
    """Compare 24h revenue against the 7-day daily average per account.

    Args:
        session: DB session.
        threshold: 24h-vs-avg ratio below which we flag.  ``0.6`` means
            "fire when 24h < 60% of 7d daily average".
        now: clock injection (tests).
    """
    now = now or utcnow()
    today_cutoff = now - timedelta(hours=24)
    week_cutoff = now - timedelta(days=7)

    # Fetch all revenue rows in the last 7 days in one query.
    rows = (
        await session.exec(
            select(OfIntelligenceRevenue)
            .where(col(OfIntelligenceRevenue.account_source_id).is_not(None))
            .where(col(OfIntelligenceRevenue.period_start).is_not(None))
            .where(OfIntelligenceRevenue.period_start >= week_cutoff)
        )
    ).all()

    if not rows:
        return []

    last_24h: defaultdict[str, int] = defaultdict(int)
    prior_6d: defaultdict[str, int] = defaultdict(int)
    for r in rows:
        if r.account_source_id is None or r.period_start is None:
            continue
        if r.period_start >= today_cutoff:
            last_24h[r.account_source_id] += r.revenue_cents
        else:
            prior_6d[r.account_source_id] += r.revenue_cents

    if not prior_6d and not last_24h:
        return []

    # Resolve display names once.
    account_ids = set(last_24h) | set(prior_6d)
    accounts = (
        await session.exec(
            select(OfIntelligenceAccount).where(
                col(OfIntelligenceAccount.source_id).in_(account_ids)
            )
        )
    ).all()
    name_by_id = {a.source_id: a.username for a in accounts}

    warnings: list[RevenueDropWarning] = []
    for source_id in account_ids:
        prior_total = prior_6d.get(source_id, 0)
        # Brand-new account: no prior history → skip (cannot judge).
        if prior_total <= 0:
            continue
        avg_daily = prior_total / 6.0  # average over the 6 days before today
        rev_24h = last_24h.get(source_id, 0)

        if rev_24h == 0:
            warnings.append(
                RevenueDropWarning(
                    account_source_id=source_id,
                    username=name_by_id.get(source_id),
                    revenue_24h_cents=0,
                    revenue_7d_avg_cents=int(avg_daily),
                    severity="medium",
                    reason="zero 24h revenue with prior history",
                )
            )
            continue

        if rev_24h < avg_daily * threshold:
            warnings.append(
                RevenueDropWarning(
                    account_source_id=source_id,
                    username=name_by_id.get(source_id),
                    revenue_24h_cents=rev_24h,
                    revenue_7d_avg_cents=int(avg_daily),
                    severity="high",
                    reason=(f"24h revenue below {int(threshold * 100)}% of 7d daily avg"),
                )
            )

    if warnings:
        logger.info(
            "of_qc.revenue.drops detected=%s threshold=%s",
            len(warnings),
            threshold,
        )
    return warnings
