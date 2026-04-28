"""Chat QC v1 — chatter findings derived from `of_intelligence_user_metrics`.

Single source of truth for the 8 rules in `chat-qc-agent-plan.md` §5.
Both consumers — the QC report renderer and the alerts engine — call
`evaluate_chatter_findings()` and operate on the same `ChatterQcResult`
list, so the report and the alert table never drift apart.

This module is **read-only**: it queries `of_intelligence_user_metrics`
and `of_intelligence_chatters` and returns structured findings.  It
does not write to any table — the alert engine and QC bot decide what
to persist.

Per-message-level findings (bad grammar, tone, missed upsells,
personalization, etc.) are explicitly out of scope until chat
discovery / message ingest lands.  The chatter-level placeholder is
emitted once per report so the gap is visible to the operator rather
than implicit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.of_intelligence import (
    OfIntelligenceChatter,
    OfIntelligenceUserMetrics,
)

logger = logging.getLogger(__name__)


# ── Thresholds (exposed as constants so the QC report can cite them) ─────────


SLOW_REPLY_WARN_S = 600  # 10 min → warn
SLOW_REPLY_CRITICAL_S = 1800  # 30 min → critical (supersedes warn)
HIGH_COPY_PASTE_PCT = 30.0  # ≥30% copied of total messages → warn
HIGH_AI_USAGE_PCT = 50.0  # ≥50% AI of total messages → info (review, not bad)
MIN_VOLUME_FOR_RATE_RULES = 50  # don't flag rates on small samples
MIN_VOLUME_FOR_PERF_RULES = 500  # paid-perf / tips-vs-peers rules
LOW_PAID_CONVERSION_PCT = 0.5  # paid_messages / messages < 0.5% → warn
TIPS_PEER_RATIO_THRESHOLD = 0.25  # chatter tips < 25% of peer median → warn
WORK_TIME_ANOMALY_MIN_MSGS = 50  # 50+ msgs but 0 work_time → info (data quality)
CHARGEBACK_RATE_CRITICAL = 0.05  # ≥5% chargeback rate on ≥10 sold → critical
CHARGEBACK_MIN_SOLD = 10


# ── Data containers ──────────────────────────────────────────────────────────


@dataclass
class ChatterFinding:
    """A single QC finding against a single chatter."""

    rule_id: str
    severity: str  # "info" | "warn" | "critical"
    title: str
    metric: dict[str, Any]
    why_it_matters: str
    recommended_action: str
    needs_immediate_review: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "title": self.title,
            "metric": self.metric,
            "why_it_matters": self.why_it_matters,
            "recommended_action": self.recommended_action,
            "needs_immediate_review": self.needs_immediate_review,
        }


@dataclass
class ChatterQcResult:
    """Per-chatter QC roll-up: latest metrics + findings."""

    chatter_source_id: str
    name: str | None
    email: str | None
    active: bool | None
    metrics_available: bool
    findings: list[ChatterFinding] = field(default_factory=list)
    period_start: datetime | None = None
    period_end: datetime | None = None
    # Display-friendly metrics (passed through for the QC report renderer).
    messages_count: int | None = None
    paid_messages_count: int | None = None
    sold_messages_count: int | None = None
    paid_messages_price_sum_cents: int | None = None
    tips_amount_sum_cents: int | None = None
    work_time_seconds: int | None = None
    reply_time_avg_seconds: int | None = None
    template_pct: float | None = None
    ai_pct: float | None = None
    copied_pct: float | None = None
    chargedback_messages_count: int | None = None
    chargedback_messages_price_sum_cents: int | None = None

    @property
    def severity_max(self) -> str:
        """Highest severity in this chatter's findings, or 'none'."""
        if any(f.severity == "critical" for f in self.findings):
            return "critical"
        if any(f.severity == "warn" for f in self.findings):
            return "warn"
        if any(f.severity == "info" for f in self.findings):
            return "info"
        return "none"

    @property
    def needs_immediate_review(self) -> bool:
        return any(f.needs_immediate_review for f in self.findings)


# ── Public limitation note ───────────────────────────────────────────────────


CHATTER_QC_LIMITATIONS_NOTE = (
    "Chat QC v1 runs on per-chatter aggregate metrics from "
    "`of_intelligence_user_metrics`.  Two classes of finding are deliberately "
    "out of scope until chat discovery / message ingest lands: "
    "(1) message-level QC (grammar, tone, wording, personalization, missed "
    "upsells per reply); "
    "(2) stale-fan / missed-fan detection (which fans went un-replied for N "
    "days).  See `docs/onlyfans-intelligence/chat-qc-agent-plan.md` §5–§7."
)


# ── Public entrypoint ────────────────────────────────────────────────────────


async def evaluate_chatter_findings(session: AsyncSession) -> list[ChatterQcResult]:
    """Compute per-chatter QC findings from the latest user_metrics row per chatter.

    Returns one `ChatterQcResult` per known chatter (whether or not metrics
    exist for them).  Order is stable: chatters with critical findings
    first, then warn, then info, then no-findings, sorted by name within
    each group.
    """
    chatters = (await session.exec(select(OfIntelligenceChatter))).all()
    metrics_rows = (
        await session.exec(
            select(OfIntelligenceUserMetrics).order_by(
                col(OfIntelligenceUserMetrics.period_end).desc()
            )
        )
    ).all()

    # Latest user_metrics row per user_id (one row per UTC day).
    latest_by_user: dict[str, OfIntelligenceUserMetrics] = {}
    for row in metrics_rows:
        if row.user_id not in latest_by_user:
            latest_by_user[row.user_id] = row

    # Peer-median for the tips_weakness rule.  Only consider chatters with
    # enough volume so quiet chatters don't drag the median down.
    tips_pool = sorted(
        (
            (m.tips_amount_sum_cents or 0)
            for m in latest_by_user.values()
            if (m.messages_count or 0) >= MIN_VOLUME_FOR_PERF_RULES
        )
    )
    peer_median_tips_cents = tips_pool[len(tips_pool) // 2] if tips_pool else 0

    results: list[ChatterQcResult] = []
    for chatter in chatters:
        m = latest_by_user.get(chatter.source_id)
        result = ChatterQcResult(
            chatter_source_id=chatter.source_id,
            name=chatter.name,
            email=chatter.email,
            active=chatter.active,
            metrics_available=m is not None,
        )
        if m is None:
            results.append(result)
            continue

        result.period_start = m.period_start
        result.period_end = m.period_end
        result.messages_count = m.messages_count
        result.paid_messages_count = m.paid_messages_count
        result.sold_messages_count = m.sold_messages_count
        result.paid_messages_price_sum_cents = m.paid_messages_price_sum_cents
        result.tips_amount_sum_cents = m.tips_amount_sum_cents
        result.work_time_seconds = m.work_time_seconds
        result.reply_time_avg_seconds = m.reply_time_avg_seconds
        result.chargedback_messages_count = m.chargedback_messages_count
        result.chargedback_messages_price_sum_cents = m.chargedback_messages_price_sum_cents

        msgs = m.messages_count or 0
        if msgs > 0:
            result.template_pct = round(100.0 * (m.template_messages_count or 0) / msgs, 1)
            result.ai_pct = round(100.0 * (m.ai_generated_messages_count or 0) / msgs, 1)
            result.copied_pct = round(100.0 * (m.copied_messages_count or 0) / msgs, 1)

        result.findings.extend(_evaluate_one(chatter, m, peer_median_tips_cents))
        results.append(result)

    # Sort: criticals first, then warns, then info, then clean — stable by name within each.
    severity_order = {"critical": 0, "warn": 1, "info": 2, "none": 3}
    results.sort(
        key=lambda r: (
            severity_order.get(r.severity_max, 99),
            (r.name or r.chatter_source_id).lower(),
        )
    )
    return results


# ── Single-chatter rule evaluation ───────────────────────────────────────────


def _evaluate_one(
    chatter: OfIntelligenceChatter,
    m: OfIntelligenceUserMetrics,
    peer_median_tips_cents: int,
) -> list[ChatterFinding]:
    findings: list[ChatterFinding] = []
    msgs = m.messages_count or 0
    paid_count = m.paid_messages_count or 0
    sold_count = m.sold_messages_count or 0
    reply = m.reply_time_avg_seconds or 0
    work = m.work_time_seconds or 0
    tips = m.tips_amount_sum_cents or 0
    cb_count = m.chargedback_messages_count or 0

    # Rule 1 — Slow reply (10min warn / 30min critical, supersedes warn)
    if reply >= SLOW_REPLY_CRITICAL_S:
        findings.append(
            ChatterFinding(
                rule_id="slow_reply_critical",
                severity="critical",
                title="Reply time avg ≥ 30 min",
                metric={
                    "reply_time_avg_seconds": reply,
                    "threshold_seconds": SLOW_REPLY_CRITICAL_S,
                },
                why_it_matters=(
                    "Replies above 30 min lose hot fans almost every time — the fan moves on, "
                    "comes back cold, or is poached by another creator."
                ),
                recommended_action=(
                    "Pause this chatter from new conversations for the next shift, "
                    "review their last 24 h of threads, and check whether they were "
                    "double-booked across too many accounts."
                ),
                needs_immediate_review=True,
            )
        )
    elif reply >= SLOW_REPLY_WARN_S:
        findings.append(
            ChatterFinding(
                rule_id="slow_reply_warn",
                severity="warn",
                title="Reply time avg ≥ 10 min",
                metric={
                    "reply_time_avg_seconds": reply,
                    "threshold_seconds": SLOW_REPLY_WARN_S,
                },
                why_it_matters=(
                    "Replies between 10 and 30 min noticeably reduce conversion — fans expect "
                    "near-realtime conversation when they're warm."
                ),
                recommended_action=(
                    "Spot-check 3–5 of this chatter's threads from the last 24 h. "
                    "If load looks fine, talk to them about pacing."
                ),
                needs_immediate_review=False,
            )
        )

    # Rule 2 — High copy/paste rate (≥30%, with min sample of MIN_VOLUME_FOR_RATE_RULES)
    if msgs >= MIN_VOLUME_FOR_RATE_RULES and m.copied_messages_count is not None:
        copied_pct = 100.0 * (m.copied_messages_count or 0) / msgs
        if copied_pct >= HIGH_COPY_PASTE_PCT:
            findings.append(
                ChatterFinding(
                    rule_id="high_copy_paste",
                    severity="warn",
                    title=f"Copy/paste rate {copied_pct:.0f}%",
                    metric={
                        "copied_messages_count": m.copied_messages_count,
                        "messages_count": msgs,
                        "copied_pct": round(copied_pct, 1),
                        "threshold_pct": HIGH_COPY_PASTE_PCT,
                    },
                    why_it_matters=(
                        "Fans notice repeated lines and disengage. Copy/paste at this rate "
                        "is a strong predictor of falling tip and PPV revenue."
                    ),
                    recommended_action=(
                        "Spot-check 5 random outbound messages from this chatter; ask them "
                        "to paraphrase rather than paste."
                    ),
                    needs_immediate_review=False,
                )
            )

    # Rule 3 — High AI usage (≥50%, with min sample). Info severity — not bad, but review.
    if msgs >= MIN_VOLUME_FOR_RATE_RULES and m.ai_generated_messages_count is not None:
        ai_pct = 100.0 * (m.ai_generated_messages_count or 0) / msgs
        if ai_pct >= HIGH_AI_USAGE_PCT:
            findings.append(
                ChatterFinding(
                    rule_id="high_ai_usage",
                    severity="info",
                    title=f"AI-generated messages {ai_pct:.0f}%",
                    metric={
                        "ai_generated_messages_count": m.ai_generated_messages_count,
                        "messages_count": msgs,
                        "ai_pct": round(ai_pct, 1),
                        "threshold_pct": HIGH_AI_USAGE_PCT,
                    },
                    why_it_matters=(
                        "AI usage is not automatically bad, but at this rate it's worth "
                        "checking that the fan-side experience still feels personal."
                    ),
                    recommended_action=(
                        "Read 5 of this chatter's recent AI-generated replies. Confirm they "
                        "match the creator's voice and refer to the fan's actual context."
                    ),
                    needs_immediate_review=False,
                )
            )

    # Rule 4 — Low / Zero output for active chatters
    if (chatter.active is True) and msgs == 0:
        findings.append(
            ChatterFinding(
                rule_id="zero_output_active",
                severity="warn",
                title="Active chatter with 0 messages in window",
                metric={
                    "messages_count": 0,
                    "active": chatter.active,
                    "period_start": m.period_start.isoformat() if m.period_start else None,
                    "period_end": m.period_end.isoformat() if m.period_end else None,
                },
                why_it_matters=(
                    "An active chatter producing zero output is either off-rotation, off-platform, "
                    "or the data pipeline missed them. Either way the agency is paying for nothing."
                ),
                recommended_action=(
                    "Confirm whether this chatter was actually scheduled in this window. "
                    "If yes, ask why no output was produced."
                ),
                needs_immediate_review=False,
            )
        )

    # Rule 4b — Active chatter with significant volume but 0 paid messages.
    if (chatter.active is True) and msgs >= 100 and paid_count == 0:
        findings.append(
            ChatterFinding(
                rule_id="zero_paid_active",
                severity="warn",
                title="100+ messages, 0 paid messages",
                metric={
                    "messages_count": msgs,
                    "paid_messages_count": 0,
                },
                why_it_matters=(
                    "Significant chatting volume with zero monetization is a clear sign of "
                    "missing or weak upsell behaviour."
                ),
                recommended_action=(
                    "Review this chatter's last 50 outbound messages for monetization opportunities "
                    "they didn't take. Coach or rotate accordingly."
                ),
                needs_immediate_review=False,
            )
        )

    # Rule 5 — Low paid-message conversion at significant volume
    if msgs >= MIN_VOLUME_FOR_PERF_RULES and paid_count > 0:
        paid_conv_pct = 100.0 * paid_count / msgs
        if paid_conv_pct < LOW_PAID_CONVERSION_PCT:
            findings.append(
                ChatterFinding(
                    rule_id="low_paid_conversion",
                    severity="warn",
                    title=f"Paid conversion {paid_conv_pct:.2f}% on {msgs}+ msgs",
                    metric={
                        "paid_messages_count": paid_count,
                        "messages_count": msgs,
                        "paid_conversion_pct": round(paid_conv_pct, 2),
                        "threshold_pct": LOW_PAID_CONVERSION_PCT,
                    },
                    why_it_matters=(
                        "At this volume, fewer than 0.5% paid messages means the chatter is "
                        "letting paid opportunities pass."
                    ),
                    recommended_action=(
                        "Pair this chatter with a top performer for a shift; review which "
                        "cues they're missing."
                    ),
                    needs_immediate_review=False,
                )
            )

    # Rule 6 — Tips weakness vs peer median (peer = chatters with ≥500 msgs)
    if (
        msgs >= MIN_VOLUME_FOR_PERF_RULES
        and peer_median_tips_cents > 0
        and tips < int(peer_median_tips_cents * TIPS_PEER_RATIO_THRESHOLD)
    ):
        findings.append(
            ChatterFinding(
                rule_id="tips_weakness_vs_peers",
                severity="warn",
                title=(
                    f"Tips ${tips / 100:.2f} — bottom quartile vs peers "
                    f"(peer median ${peer_median_tips_cents / 100:.2f})"
                ),
                metric={
                    "tips_amount_sum_cents": tips,
                    "peer_median_tips_cents": peer_median_tips_cents,
                    "ratio_to_median": round(tips / max(peer_median_tips_cents, 1), 2),
                    "threshold_ratio": TIPS_PEER_RATIO_THRESHOLD,
                },
                why_it_matters=(
                    "Tips weakness at high message volume usually means the chatter isn't asking, "
                    "or is asking poorly."
                ),
                recommended_action=(
                    "Listen-in / read-along on this chatter's next shift; flag whether tip "
                    "asks happen at all and whether they feel earned."
                ),
                needs_immediate_review=False,
            )
        )

    # Rule 7 — Work time anomaly (≥50 msgs but 0 work_time → data quality)
    if msgs >= WORK_TIME_ANOMALY_MIN_MSGS and work == 0:
        findings.append(
            ChatterFinding(
                rule_id="work_time_anomaly",
                severity="info",
                title=f"{msgs} msgs but work_time = 0",
                metric={
                    "messages_count": msgs,
                    "work_time_seconds": 0,
                },
                why_it_matters=(
                    "Either this chatter is bypassing the OnlyMonster work-time clock, or the "
                    "data pipeline missed their session. Both worth investigating."
                ),
                recommended_action=(
                    "Confirm chatter is logging in through OnlyMonster; if yes, escalate as "
                    "an OnlyMonster data-quality issue."
                ),
                needs_immediate_review=False,
            )
        )

    # Rule 8 — Chargeback rate (≥5% on ≥10 sold → critical)
    if sold_count >= CHARGEBACK_MIN_SOLD:
        cb_rate = cb_count / sold_count
        if cb_rate >= CHARGEBACK_RATE_CRITICAL:
            findings.append(
                ChatterFinding(
                    rule_id="chargeback_rate_critical",
                    severity="critical",
                    title=f"Chargeback rate {cb_rate * 100:.0f}% on {sold_count} sold",
                    metric={
                        "chargedback_messages_count": cb_count,
                        "sold_messages_count": sold_count,
                        "chargeback_rate": round(cb_rate, 3),
                        "threshold_rate": CHARGEBACK_RATE_CRITICAL,
                    },
                    why_it_matters=(
                        "Sustained chargebacks at this rate hurt the account's overall payment "
                        "processor standing — risk extends to every other chatter on that account."
                    ),
                    recommended_action=(
                        "Pull the last 7 days of paid messages from this chatter; look for "
                        "refund-trigger language (overpromising, missing media, hostile tone). "
                        "Coach or remove from paid sales until resolved."
                    ),
                    needs_immediate_review=True,
                )
            )

    return findings
