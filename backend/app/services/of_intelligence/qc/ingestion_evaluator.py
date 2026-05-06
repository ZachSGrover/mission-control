"""Ingestion-aware QC evaluator — produces safe findings from
``IngestionResult`` snapshots without ever touching message bodies or
fan data.

Outputs ``IngestionFinding`` rows the scheduler tick can persist + the
dashboard can render.  Each finding carries:
  • ``code``           — short kebab id (``revenue_drop``, ``stale_data``…)
  • ``severity``       — ``info`` | ``low`` | ``medium`` | ``high`` | ``critical``
  • ``account_id``     — optional internal id (never rendered alone)
  • ``account_label``  — optional display-safe label
  • ``operator_id``    — optional internal chatter id (never rendered)
  • ``signal``         — short generic phrase (no keywords, no PII)
  • ``source``         — copy of source_mode for audit
  • ``source_confidence``

Codes added in this slice (additive — existing detector codes are not
replaced):
  • ``revenue_drop``         — current 24h < 60% of prior daily avg
  • ``zero_revenue_24h``     — exactly 0 with prior history
  • ``stale_data``           — last_synced_at older than threshold
  • ``missing_data``         — message_count is None / 0 with prior activity
  • ``account_needs_review`` — composite signal from multiple yellows
  • ``data_source_disconnected`` — propagated from
                                   ``IngestionResult.skipped_reason``
  • ``low_paid_message_activity`` — paid_message_count drops vs window
  • ``unusually_low_volume``      — message_count well below baseline
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from app.core.logging import get_logger
from app.core.time import utcnow
from app.services.of_intelligence.qc.ingestion.base import (
    AccountMetrics,
    IngestionResult,
)

logger = get_logger(__name__)

REVENUE_DROP_THRESHOLD = 0.6
STALE_SYNC_HOURS = 6
LOW_VOLUME_RATIO = 0.3
LOW_PAID_RATIO = 0.4


@dataclass(frozen=True)
class IngestionFinding:
    code: str
    severity: str  # info|low|medium|high|critical
    account_id: str | None
    account_label: str | None
    operator_id: str | None
    signal: str  # generic, no PII, no keywords
    source: str
    source_confidence: str


@dataclass(frozen=True)
class EvaluationOutput:
    findings: list[IngestionFinding] = field(default_factory=list)
    accounts_checked: int = 0
    safe_mode: bool = True


# ── Detectors ────────────────────────────────────────────────────────────────


def _maybe_revenue_findings(m: AccountMetrics) -> list[IngestionFinding]:
    out: list[IngestionFinding] = []
    if m.previous_revenue_cents <= 0:
        return out
    if m.revenue_cents == 0:
        out.append(
            IngestionFinding(
                code="zero_revenue_24h",
                severity="medium",
                account_id=m.account_id,
                account_label=m.account_label,
                operator_id=m.operator_id,
                signal="zero 24h revenue with prior history",
                source=m.source,
                source_confidence=m.source_confidence,
            )
        )
    elif m.revenue_cents < int(m.previous_revenue_cents * REVENUE_DROP_THRESHOLD):
        out.append(
            IngestionFinding(
                code="revenue_drop",
                severity="high",
                account_id=m.account_id,
                account_label=m.account_label,
                operator_id=m.operator_id,
                signal=(
                    f"24h revenue below {int(REVENUE_DROP_THRESHOLD * 100)}% " "of recent daily avg"
                ),
                source=m.source,
                source_confidence=m.source_confidence,
            )
        )
    return out


def _maybe_stale_data_finding(m: AccountMetrics) -> IngestionFinding | None:
    if m.last_synced_at is None:
        return None
    age = utcnow() - m.last_synced_at
    if age >= timedelta(hours=STALE_SYNC_HOURS):
        return IngestionFinding(
            code="stale_data",
            severity="high",
            account_id=m.account_id,
            account_label=m.account_label,
            operator_id=m.operator_id,
            signal=f"no sync in {STALE_SYNC_HOURS}h+",
            source=m.source,
            source_confidence=m.source_confidence,
        )
    return None


def _maybe_missing_data_finding(m: AccountMetrics) -> IngestionFinding | None:
    """When message volume disappeared but prior revenue exists, flag."""
    if m.previous_revenue_cents > 0 and (m.message_count is None or m.message_count == 0):
        return IngestionFinding(
            code="missing_data",
            severity="medium",
            account_id=m.account_id,
            account_label=m.account_label,
            operator_id=m.operator_id,
            signal="prior activity exists but no messages in window",
            source=m.source,
            source_confidence=m.source_confidence,
        )
    return None


def _maybe_low_paid_finding(m: AccountMetrics) -> IngestionFinding | None:
    """Paid-message count fell below ratio of total."""
    if m.paid_message_count is None or m.message_count is None or m.message_count == 0:
        return None
    if m.paid_message_count == 0:
        return None  # zero is captured by zero_revenue_24h
    ratio = m.paid_message_count / m.message_count
    if ratio < LOW_PAID_RATIO:
        return IngestionFinding(
            code="low_paid_message_activity",
            severity="medium",
            account_id=m.account_id,
            account_label=m.account_label,
            operator_id=m.operator_id,
            signal="paid-message ratio below threshold",
            source=m.source,
            source_confidence=m.source_confidence,
        )
    return None


def _maybe_low_volume_finding(
    m: AccountMetrics, baseline_message_count: int
) -> IngestionFinding | None:
    """Today's volume is far below the cohort baseline."""
    if m.message_count is None or baseline_message_count <= 0:
        return None
    if m.message_count < int(baseline_message_count * LOW_VOLUME_RATIO):
        return IngestionFinding(
            code="unusually_low_volume",
            severity="medium",
            account_id=m.account_id,
            account_label=m.account_label,
            operator_id=m.operator_id,
            signal="message volume below cohort baseline",
            source=m.source,
            source_confidence=m.source_confidence,
        )
    return None


# ── Public entry point ──────────────────────────────────────────────────────


def evaluate_ingestion(result: IngestionResult) -> EvaluationOutput:
    """Walk an ``IngestionResult`` → produce ``IngestionFinding`` list."""
    findings: list[IngestionFinding] = []

    if result.skipped_reason:
        findings.append(
            IngestionFinding(
                code="data_source_disconnected",
                severity="medium",
                account_id=None,
                account_label=None,
                operator_id=None,
                signal=f"ingestion skipped: {result.skipped_reason}",
                source=result.source_mode.value,
                source_confidence=result.source_confidence,
            )
        )

    if not result.accounts:
        return EvaluationOutput(findings=findings, accounts_checked=0, safe_mode=result.safe_mode)

    # Cohort baseline for volume comparison.
    msg_counts = [a.message_count for a in result.accounts if a.message_count is not None]
    baseline_msg = int(sum(msg_counts) / len(msg_counts)) if msg_counts else 0

    for m in result.accounts:
        findings.extend(_maybe_revenue_findings(m))
        if stale := _maybe_stale_data_finding(m):
            findings.append(stale)
        if missing := _maybe_missing_data_finding(m):
            findings.append(missing)
        if low_paid := _maybe_low_paid_finding(m):
            findings.append(low_paid)
        if low_vol := _maybe_low_volume_finding(m, baseline_msg):
            findings.append(low_vol)

    # Composite "needs review" — flag accounts with 2+ medium/high findings.
    findings_per_account: dict[str, int] = {}
    for f in findings:
        if f.account_id and f.severity in ("medium", "high", "critical"):
            findings_per_account[f.account_id] = findings_per_account.get(f.account_id, 0) + 1
    by_id = {a.account_id: a for a in result.accounts}
    for acct_id, n in findings_per_account.items():
        if n >= 2:
            acct = by_id.get(acct_id)
            if acct is None:
                continue
            findings.append(
                IngestionFinding(
                    code="account_needs_review",
                    severity="high",
                    account_id=acct.account_id,
                    account_label=acct.account_label,
                    operator_id=acct.operator_id,
                    signal=f"{n} concurrent yellow/red findings",
                    source=acct.source,
                    source_confidence=acct.source_confidence,
                )
            )

    logger.info(
        "of_qc.ingestion.evaluator findings=%s accounts=%s",
        len(findings),
        len(result.accounts),
    )
    return EvaluationOutput(
        findings=findings,
        accounts_checked=len(result.accounts),
        safe_mode=result.safe_mode,
    )
