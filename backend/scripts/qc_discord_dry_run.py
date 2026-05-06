"""Operator dry-run for the OF Intelligence QC Discord publisher.

Renders and (optionally) sends a curated set of canned alerts so an operator
can verify formatting + delivery against a private Discord channel without
touching real OF data.

This script is the *only* way QC alerts should reach Discord until
production wiring (Step 3+) lands.  It uses fake account, chatter, and
finding strings — no fan handles, no message bodies, no raw API responses.

Usage (private channel webhook only):

    cd backend
    export MC_OF_QC_DISCORD_ENABLED=1
    export MC_OF_QC_DISCORD_WEBHOOK_URL="$(pbpaste)"   # paste from Discord
    uv run python scripts/qc_discord_dry_run.py

Flags:
    --category <code>   send only the named scenario (default: all)
    --print-only        render to stdout, do not POST to Discord
    --list              list available scenarios and exit

Webhook resolution: the publisher reads the encrypted DB secret
``discord.qc.webhook_url`` first; if absent, it falls back to the env var
above.  This script does not write to the DB and does not log the URL.

The kill switch ``MC_OF_QC_DISCORD_ENABLED`` defaults to off — you must opt
in for each shell session.  No webhook is persisted by this script.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

# Allow running as `python scripts/qc_discord_dry_run.py` from backend/.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# Heavy app config defaults so the script can run outside a configured
# backend.  Real env values (if exported) take precedence.
os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault(
    "LOCAL_AUTH_TOKEN",
    "qc-dry-run-token-0123456789-0123456789-0123456789x",
)
os.environ.setdefault("BASE_URL", "http://localhost:8000")

from app.core.logging import configure_logging  # noqa: E402
from app.services.of_intelligence.qc import (  # noqa: E402
    AlertPayload,
    PublishResult,
    RolledUpPayload,
    Severity,
    format_alert,
    format_rollup,
    publish,
)

# ── Canned scenarios ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Scenario:
    code: str
    severity: Severity
    description: str
    rendered: str  # pre-rendered, privacy-safe message


def _build_scenarios() -> list[Scenario]:
    return [
        Scenario(
            code="account_blocked",
            severity=Severity.CRITICAL,
            description="Account access lost — immediate action.",
            rendered=format_alert(
                AlertPayload(
                    severity=Severity.CRITICAL,
                    code="account_blocked",
                    title="example_account may have lost access",
                    account_username="example_account",
                    facts=(
                        ("Status", "blocked"),
                        ("Last sync", "2h ago"),
                        ("Source", "dry-run (no real data)"),
                    ),
                    action="Re-auth in OF Intelligence → Accounts.",
                    ref="qc/dry-run/account_blocked",
                )
            ),
        ),
        Scenario(
            code="account_stale",
            severity=Severity.HIGH,
            description="Account has not synced inside the threshold.",
            rendered=format_alert(
                AlertPayload(
                    severity=Severity.HIGH,
                    code="account_stale",
                    title="example_account hasn't synced in 6h+",
                    account_username="example_account",
                    facts=(
                        ("Hours since sync", "8"),
                        ("Source", "dry-run (no real data)"),
                    ),
                    action="Investigate sync — possible access issue.",
                    ref="qc/dry-run/account_stale",
                )
            ),
        ),
        Scenario(
            code="sync_failure",
            severity=Severity.HIGH,
            description="A sync_log row errored within the last 24h.",
            rendered=format_alert(
                AlertPayload(
                    severity=Severity.HIGH,
                    code="sync_failure",
                    title="Sync failed: messages",
                    facts=(
                        ("Entity", "messages"),
                        ("Source", "dry-run (no real data)"),
                    ),
                    action="Re-run manual sync from Mission Control.",
                    ref="qc/dry-run/sync_failure",
                )
            ),
        ),
        Scenario(
            code="api_disconnected",
            severity=Severity.CRITICAL,
            description="No successful sync in 24h.",
            rendered=format_alert(
                AlertPayload(
                    severity=Severity.CRITICAL,
                    code="api_disconnected",
                    title="OnlyMonster API hasn't returned a successful sync in 24h",
                    facts=(("Source", "dry-run (no real data)"),),
                    action="Check Settings → Integrations → OnlyMonster.",
                    ref="qc/dry-run/api_disconnected",
                )
            ),
        ),
        Scenario(
            code="refund_risk",
            severity=Severity.CRITICAL,
            description="Fan messaging surfaces refund / chargeback intent.",
            rendered=format_alert(
                AlertPayload(
                    severity=Severity.CRITICAL,
                    code="refund_risk",
                    title="Refund / chargeback signal on example_account",
                    account_username="example_account",
                    chatter_name="Test Chatter",
                    facts=(
                        ("Signal", "refund-language detected"),
                        ("Source", "dry-run (no real data)"),
                    ),
                    action="Review last 30 minutes in dashboard before responding.",
                    ref="qc/dry-run/refund_risk",
                )
            ),
        ),
        Scenario(
            code="banned_content_risk",
            severity=Severity.CRITICAL,
            description="Outbound message hit a policy-term category.",
            rendered=format_alert(
                AlertPayload(
                    severity=Severity.CRITICAL,
                    code="banned_content_risk",
                    title="Policy-term category hit on example_account",
                    account_username="example_account",
                    chatter_name="Test Chatter",
                    facts=(
                        ("Category", "policy-term-category-A"),
                        ("Source", "dry-run (no real data)"),
                    ),
                    action="Open the dashboard ref to review the offending message.",
                    ref="qc/dry-run/banned_content_risk",
                )
            ),
        ),
        Scenario(
            code="rude_reply",
            severity=Severity.HIGH,
            description="Outbound reply flagged as rude / harsh tone.",
            rendered=format_alert(
                AlertPayload(
                    severity=Severity.HIGH,
                    code="rude_reply",
                    title="Rude reply flagged on example_account",
                    account_username="example_account",
                    chatter_name="Test Chatter",
                    facts=(("Source", "dry-run (no real data)"),),
                    action="Coach chatter; check refund risk on this conversation.",
                    ref="qc/dry-run/rude_reply",
                )
            ),
        ),
        Scenario(
            code="chatter_rollup",
            severity=Severity.MEDIUM,
            description="Windowed rollup of medium-severity chatter findings.",
            rendered=format_rollup(
                RolledUpPayload(
                    severity=Severity.MEDIUM,
                    window_label="last 30 min",
                    total_findings=12,
                    chatter_count=3,
                    account_count=2,
                    lines=(
                        "example_account / Test Chatter A: 4× lazy_reply, 1× missed_buying_signal",
                        "example_account / Test Chatter B: 3× slow_response (median 9 min)",
                        "second_account / Test Chatter C: 2× low_effort_chatting",
                    ),
                    action="Review Test Chatter A's last hour first.",
                    refs=("qc/dry-run/rollup-1", "qc/dry-run/rollup-2"),
                )
            ),
        ),
        Scenario(
            code="daily_scorecard",
            severity=Severity.MEDIUM,
            description="Morning summary of overnight criticals + worst chatters.",
            rendered=format_rollup(
                RolledUpPayload(
                    severity=Severity.MEDIUM,
                    window_label="overnight + last 24h",
                    total_findings=27,
                    chatter_count=5,
                    account_count=3,
                    lines=(
                        "Overnight criticals: 0",
                        "Worst chatter: Test Chatter A (8 issues)",
                        "Account health: 1 stale, 0 blocked",
                    ),
                    action="Open dashboard for full scorecard.",
                    refs=("qc/dry-run/scorecard",),
                    title="Daily QC scorecard",
                )
            ),
        ),
    ]


# ── Run loop ─────────────────────────────────────────────────────────────────


def _capture_publisher_logs() -> tuple[logging.Handler, StringIO]:
    """Attach a buffer to the publisher logger so we can scan for URL leaks."""
    buf = StringIO()
    handler = logging.StreamHandler(buf)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger_name = "app.services.of_intelligence.qc.publisher"
    logging.getLogger(logger_name).addHandler(handler)
    logging.getLogger(logger_name).setLevel(logging.DEBUG)
    return handler, buf


async def _run(
    scenarios: list[Scenario],
    *,
    print_only: bool,
) -> int:
    handler, log_buf = _capture_publisher_logs()
    publisher_logger = logging.getLogger("app.services.of_intelligence.qc.publisher")

    enabled = (os.environ.get("MC_OF_QC_DISCORD_ENABLED") or "").strip()
    has_url_env = bool((os.environ.get("MC_OF_QC_DISCORD_WEBHOOK_URL") or "").strip())
    print(f"MC_OF_QC_DISCORD_ENABLED={enabled or '(unset → disabled)'}")
    print(f"MC_OF_QC_DISCORD_WEBHOOK_URL set: {'yes' if has_url_env else 'no'}")
    print("Webhook resolution: DB-first, env fallback (DB lookup is silent on failure).\n")

    failures = 0
    for scenario in scenarios:
        glyph_line = scenario.rendered.splitlines()[0] if scenario.rendered else "(empty)"
        print(f"━━ {scenario.code} ({scenario.severity.value}) ━━")
        print(scenario.description)
        print(f"  preview: {glyph_line}")

        if print_only:
            print("  (print-only — not sent)\n")
            continue

        result: PublishResult = await publish(
            scenario.rendered,
            code=scenario.code,
            severity=scenario.severity.value,
            log_extra={"dry_run": True, "scenario": scenario.code},
        )
        print(
            f"  PublishResult: ok={result.ok} status={result.status} "
            f"attempts={result.attempts} reason={result.reason} "
            f"elapsed_ms={result.elapsed_ms}"
        )
        if not result.ok and result.reason not in ("disabled", "no_webhook"):
            failures += 1
        print()

    publisher_logger.removeHandler(handler)
    captured = log_buf.getvalue()

    # No-leak invariant — webhook URL must never appear in any captured line.
    env_url = (os.environ.get("MC_OF_QC_DISCORD_WEBHOOK_URL") or "").strip()
    leaked = bool(env_url) and env_url in captured
    if leaked:
        print("❌ FAIL: webhook URL appeared in publisher logs.", file=sys.stderr)
        return 2

    print("✅ Webhook URL did not appear in any publisher log line.")
    if failures:
        print(f"⚠️  {failures} scenario(s) failed unexpectedly.", file=sys.stderr)
        return 1
    return 0


async def main() -> int:
    scenarios = _build_scenarios()
    parser = argparse.ArgumentParser(description="QC Discord dry-run.")
    parser.add_argument(
        "--category",
        default=None,
        help="Send only the scenario with this code (default: all).",
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Render scenarios to stdout but skip the Discord POST.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available scenarios and exit.",
    )
    args = parser.parse_args()

    if args.list:
        for s in scenarios:
            print(f"  {s.code:24s} {s.severity.value:8s} — {s.description}")
        return 0

    configure_logging()

    if args.category:
        match = [s for s in scenarios if s.code == args.category]
        if not match:
            print(
                f"unknown category: {args.category!r}.  --list shows valid codes.",
                file=sys.stderr,
            )
            return 2
        scenarios = match

    return await _run(scenarios, print_only=args.print_only)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
