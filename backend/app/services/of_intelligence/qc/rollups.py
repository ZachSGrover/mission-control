"""Layer 2 rollup engine.

Groups un-rolled-up ``OfIntelligenceQcFinding`` rows by (chatter, code,
account) and ships ONE Discord digest per evaluation cycle when the total
crosses a threshold.  Findings that participated in a rollup get
``rolled_up_at`` stamped so the next run doesn't re-include them.

Repeat-offender escalation: if any (chatter, code) pair shows up at or
above ``_ESCALATION_THRESHOLD`` matches in the window, that line is
flagged in the digest and the rollup severity bumps to HIGH.

Privacy: the digest uses account display name + chatter name only.  Body,
fan handle, raw payload — never.  Internal source ids are mapped to
display names; if no display name exists, the line uses ``"<account>"``
placeholder rather than leaking the source_id.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Tuple
from uuid import UUID, uuid4

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.of_intelligence import (
    OfIntelligenceAccount,
    OfIntelligenceAlert,
    OfIntelligenceChatter,
)
from app.models.of_qc_finding import OfIntelligenceQcFinding
from app.services.of_intelligence.qc.formatters import (
    RolledUpPayload,
    format_rollup,
)
from app.services.of_intelligence.qc.publisher import PublishResult, publish
from app.services.of_intelligence.qc.severity import Severity

logger = get_logger(__name__)

DEFAULT_ROLLUP_WINDOW_MINUTES = 30
_MIN_FINDINGS_TO_ROLLUP = 2  # below this, skip the digest
_ESCALATION_THRESHOLD = 3
_MAX_LINES_IN_DIGEST = 8  # cap to keep messages under format_rollup's char budget
ROLLUP_ALERT_CODE = "chatter_qc_rollup"


# (chatter_source_id, code) → count
_GroupKey = Tuple[str | None, str]


@dataclass
class _GroupAgg:
    chatter_source_id: str | None
    account_source_id: str | None
    code: str
    count: int = 0
    severity: str = "low"
    finding_ids: list[UUID] = field(default_factory=list)


@dataclass
class RollupResult:
    alert_id: UUID | None
    findings_rolled: int
    chatter_count: int
    account_count: int
    publish_result: PublishResult | None


# ── Public entrypoint ───────────────────────────────────────────────────────


async def fire_rollup_if_due(
    session: AsyncSession,
    *,
    window_minutes: int = DEFAULT_ROLLUP_WINDOW_MINUTES,
) -> RollupResult:
    """Group recent un-rolled-up chatter findings and ship one digest.

    Returns a ``RollupResult`` even when nothing was shipped (caller can
    audit).  Marks every included finding ``rolled_up_at = now`` so the
    next call doesn't re-include them.
    """
    cutoff = utcnow() - timedelta(minutes=window_minutes)
    findings = (
        await session.exec(
            select(OfIntelligenceQcFinding)
            .where(OfIntelligenceQcFinding.rolled_up_at.is_(None))  # type: ignore[union-attr]
            .where(OfIntelligenceQcFinding.created_at >= cutoff)
        )
    ).all()

    if len(findings) < _MIN_FINDINGS_TO_ROLLUP:
        return RollupResult(None, 0, 0, 0, None)

    # Group by (chatter, code) and track per-account.
    groups: dict[_GroupKey, _GroupAgg] = {}
    accounts_seen: set[str] = set()
    chatters_seen: set[str] = set()
    for f in findings:
        key: _GroupKey = (f.chatter_source_id, f.code)
        agg = groups.get(key)
        if agg is None:
            agg = _GroupAgg(
                chatter_source_id=f.chatter_source_id,
                account_source_id=f.account_source_id,
                code=f.code,
            )
            groups[key] = agg
        agg.count += 1
        agg.finding_ids.append(f.id)
        agg.severity = _max_sev(agg.severity, f.severity)
        if f.account_source_id:
            accounts_seen.add(f.account_source_id)
        if f.chatter_source_id:
            chatters_seen.add(f.chatter_source_id)

    # Resolve display names once.
    chatter_names = await _chatter_names(session, list(chatters_seen))
    account_names = await _account_usernames(session, list(accounts_seen))

    # Collapse to per-(account, chatter) lines for readability.
    by_pair: dict[tuple[str | None, str | None], list[_GroupAgg]] = defaultdict(list)
    for agg in groups.values():
        by_pair[(agg.account_source_id, agg.chatter_source_id)].append(agg)

    # Ranking: pairs with the highest single-code count (= worst offenders) first.
    ranked = sorted(
        by_pair.items(),
        key=lambda kv: max((a.count for a in kv[1]), default=0),
        reverse=True,
    )

    has_repeat_offender = any(a.count >= _ESCALATION_THRESHOLD for a in groups.values())
    digest_severity = Severity.HIGH if has_repeat_offender else Severity.MEDIUM

    lines: list[str] = []
    for (acct_id, ch_id), aggs in ranked[:_MAX_LINES_IN_DIGEST]:
        acct_name = account_names.get(acct_id) if acct_id else None
        ch_name = chatter_names.get(ch_id) if ch_id else None
        lines.append(_format_line(acct_name, ch_name, aggs))

    total = len(findings)
    refs: list[str] = []  # rollup-level alert ref attached after we create the row

    # Persist a rollup alert row so the dashboard has a stable handle.
    rollup_alert = OfIntelligenceAlert(
        code=ROLLUP_ALERT_CODE,
        severity=digest_severity.value,
        status="open",
        title="Chatter QC rollup",
        message=f"{total} findings across {len(chatters_seen)} chatter(s), {len(accounts_seen)} account(s)",
        context={
            "window_minutes": window_minutes,
            "groups": [
                {
                    "code": agg.code,
                    "chatter_source_id": agg.chatter_source_id,
                    "account_source_id": agg.account_source_id,
                    "count": agg.count,
                }
                for agg in groups.values()
            ],
            "has_repeat_offender": has_repeat_offender,
        },
    )
    session.add(rollup_alert)
    await session.flush()
    refs.append(f"qc/alert/{rollup_alert.id}")

    # Stamp findings as rolled up.
    now = utcnow()
    for f in findings:
        f.rolled_up_at = now
        session.add(f)
    await session.commit()
    await session.refresh(rollup_alert)

    payload = RolledUpPayload(
        severity=digest_severity,
        window_label=f"last {window_minutes} min",
        total_findings=total,
        chatter_count=len(chatters_seen),
        account_count=len(accounts_seen),
        lines=tuple(lines),
        action=(
            "Review repeat offenders first."
            if has_repeat_offender
            else "Open dashboard for full details."
        ),
        refs=tuple(refs),
    )
    rendered = format_rollup(payload)
    publish_result = await publish(
        rendered,
        code=ROLLUP_ALERT_CODE,
        severity=digest_severity.value,
        log_extra={"alert_id": str(rollup_alert.id), "findings": total},
    )

    return RollupResult(
        alert_id=rollup_alert.id,
        findings_rolled=total,
        chatter_count=len(chatters_seen),
        account_count=len(accounts_seen),
        publish_result=publish_result,
    )


# ── Helpers ────────────────────────────────────────────────────────────────


_SEV_RANK = {"info": 0, "low": 1, "medium": 2, "warn": 2, "high": 3, "critical": 4}


def _max_sev(a: str, b: str) -> str:
    return a if _SEV_RANK.get(a, 0) >= _SEV_RANK.get(b, 0) else b


def _format_line(
    acct_name: str | None,
    chatter_name: str | None,
    aggs: list[_GroupAgg],
) -> str:
    """Single rollup-line format.

    Account / chatter labels: only display names.  No source_ids leak.
    """
    acct_label = acct_name or "<account>"
    ch_label = chatter_name or "<chatter>"
    repeat = sorted(aggs, key=lambda a: a.count, reverse=True)
    code_summary = ", ".join(f"{a.count}× {a.code}" for a in repeat)
    is_repeat = any(a.count >= _ESCALATION_THRESHOLD for a in aggs)
    suffix = " — repeat offender" if is_repeat else ""
    return f"{acct_label} / {ch_label}: {code_summary}{suffix}"


async def _chatter_names(session: AsyncSession, ids: list[str]) -> dict[str, str | None]:
    if not ids:
        return {}
    rows = (
        await session.exec(
            select(OfIntelligenceChatter).where(
                col(OfIntelligenceChatter.source_id).in_(set(ids))
            )
        )
    ).all()
    return {r.source_id: r.name for r in rows}


async def _account_usernames(session: AsyncSession, ids: list[str]) -> dict[str, str | None]:
    if not ids:
        return {}
    rows = (
        await session.exec(
            select(OfIntelligenceAccount).where(
                col(OfIntelligenceAccount.source_id).in_(set(ids))
            )
        )
    ).all()
    return {r.source_id: r.username for r in rows}


# uuid4 imported only to satisfy older tests — actual creation uses default
# factory on the model.
_ = uuid4
