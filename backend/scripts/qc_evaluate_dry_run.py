"""QC evaluation + daily summary dry-run runner.

Stand-in for the eventual scheduler.  Runs the same code paths that a cron
job would, but prints the result instead of relying on a long-lived
process.  Discord ships still happen iff the operator-toggle is on and a
webhook is configured — set ``MC_OF_QC_DISCORD_ENABLED=0`` (or leave the
toggle off) for a fully offline check.

Three commands:
  evaluate       — run alert engine (Layer 1 + Layer 2 detectors + rollup)
  daily-summary  — generate + ship the daily QC scorecard
  all            — both, in that order

Why this script exists instead of a cron task:
  The other ``feat/ofi-daily-qc-scheduler`` branch owns the scheduler
  layer.  Adding a scheduler here would create a merge conflict.  When
  that branch lands, the scheduler should call:

    from app.db.session import async_session_maker
    from app.services.of_intelligence.alerts import evaluate_alerts
    from app.services.of_intelligence.qc.daily_summary import ship_daily_summary

    async with async_session_maker() as session:
        await evaluate_alerts(session)        # every 15-30 min
        await ship_daily_summary(session)     # once per day at the configured hour

  Both functions are idempotent and will not double-ship to Discord
  (alert dedup + finding ``rolled_up_at`` stamping + ``rollup_alert``
  uniqueness all enforce that).  Daily summary uses
  ``bypass_kill_switch=False`` from a scheduler — wrap the call when you
  want operator-initiated ships from cron to also bypass.

Usage:
  cd backend
  uv run python scripts/qc_evaluate_dry_run.py evaluate
  uv run python scripts/qc_evaluate_dry_run.py daily-summary
  uv run python scripts/qc_evaluate_dry_run.py all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault(
    "LOCAL_AUTH_TOKEN",
    "qc-dry-run-token-0123456789-0123456789-0123456789x",
)
os.environ.setdefault("BASE_URL", "http://localhost:8765")

from app.core.logging import configure_logging  # noqa: E402
from app.db.session import async_session_maker  # noqa: E402


def _summary_to_jsonable(value: object) -> object:
    if hasattr(value, "__dict__"):
        return {k: _summary_to_jsonable(v) for k, v in vars(value).items() if not k.startswith("_")}
    if isinstance(value, list):
        return [_summary_to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return list(_summary_to_jsonable(v) for v in value)
    if isinstance(value, dict):
        return {k: _summary_to_jsonable(v) for k, v in value.items()}
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


async def _run_evaluate() -> int:
    from app.services.of_intelligence.alerts import evaluate_alerts

    async with async_session_maker() as session:
        summary = await evaluate_alerts(session)
    print("=== evaluate_alerts ===")
    print(json.dumps(_summary_to_jsonable(summary), indent=2, default=str))
    return 0


async def _run_daily() -> int:
    from app.services.of_intelligence.qc.daily_summary import ship_daily_summary

    async with async_session_maker() as session:
        summary, result = await ship_daily_summary(session, bypass_kill_switch=False)
    print("=== daily_summary ===")
    print(json.dumps(_summary_to_jsonable(summary), indent=2, default=str))
    print("=== publish ===")
    print(json.dumps(_summary_to_jsonable(result), indent=2, default=str))
    return 0 if result.ok or result.reason in ("disabled", "no_webhook") else 1


async def main() -> int:
    parser = argparse.ArgumentParser(description="OF QC dry-run runner.")
    parser.add_argument("command", choices=["evaluate", "daily-summary", "all"])
    args = parser.parse_args()

    configure_logging()
    if args.command == "evaluate":
        return await _run_evaluate()
    if args.command == "daily-summary":
        return await _run_daily()
    rc = await _run_evaluate()
    if rc:
        return rc
    return await _run_daily()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
