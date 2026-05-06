"""Sandbox runner — synthetic Daily QC dry-run.

Produces a deterministic ``DailySummary``-shaped payload from hand-built
synthetic rows.  Used by ``POST /qc/scheduler/run-now?source=sandbox``
when the operator wants to verify the dashboard's wiring without
touching the real synced data.

Hard rules:
  • Never reads the DB.  Never writes the DB.
  • Never publishes to Discord or Telegram (no publisher call at all).
  • Never includes fan handles, message bodies, or raw API responses.
  • Returns a `DailySummary` + a synthetic counters dict so the manual
    run can be inspected end-to-end.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger
from app.core.time import utcnow
from app.services.of_intelligence.qc.daily_summary import DailySummary

logger = get_logger(__name__)


@dataclass(frozen=True)
class SandboxRunResult:
    summary: DailySummary
    accounts_checked: int
    findings_simulated: int


def run_sandbox_summary() -> SandboxRunResult:
    """Build a deterministic sandbox `DailySummary`."""
    summary = DailySummary(
        generated_at=utcnow(),
        accounts_reviewed=2,
        chats_reviewed=4,
        total_findings=5,
        critical_alert_count=1,
        worst_accounts=[("luna_demo", 3), ("indigo_demo", 2)],
        worst_chatters=[("Mia (sandbox)", 4), ("Sam (sandbox)", 1)],
        repeat_offenders=["Mia (sandbox)"],
        missed_sales_signals=2,
        slow_responses=2,
        follow_ups_needed=1,
        layer1_open_alerts=["account_stale"],
        layer2_open_alerts=["chatter_qc_rollup"],
        actions=[
            "Sandbox run — synthetic data only.",
            "Coach repeat offenders: Mia (sandbox)",
            "Review missed buying-signal conversations in dashboard.",
        ],
    )
    logger.info(
        "of_qc.sandbox.run accounts=%s findings=%s",
        summary.accounts_reviewed,
        summary.total_findings,
    )
    return SandboxRunResult(
        summary=summary,
        accounts_checked=summary.accounts_reviewed,
        findings_simulated=summary.total_findings,
    )
