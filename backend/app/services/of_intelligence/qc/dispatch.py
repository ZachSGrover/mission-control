"""Bridge from OF Intelligence alert candidates to Discord QC publishing.

The OF Intelligence alert engine ``services/of_intelligence/alerts.py``
evaluates rules and writes ``OfIntelligenceAlert`` rows.  This module ships
each *newly created* alert to Discord via the QC publisher.

Hard rules upheld here:
  • Only allowlisted account-health fields render to Discord — never the
    raw ``error``/``reason`` strings from sync_log (which can contain API
    response bodies), never fan handles, never message bodies.
  • Each code maps to a curated action sentence so the Discord message is
    actionable on its own without opening the dashboard.
  • Alert dedup happens upstream in ``alerts.py``; this module is only
    invoked for newly inserted rows, so no extra cooldown is needed.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.services.of_intelligence.qc import (
    AlertPayload,
    PublishResult,
    Severity,
    format_alert,
    publish,
)

logger = get_logger(__name__)


# ── Code → human-friendly title prefix + action sentence ────────────────────

# Each entry: (severity, action sentence shown after Account/Chatter/facts).
# Title is built from the candidate's title field (already includes the
# account display name).  Severity here overrides whatever the upstream
# rule emitted — keeps the Discord ladder consistent.
_CODE_ROUTING: dict[str, tuple[Severity, str]] = {
    # Account / sync health
    "account_blocked": (
        Severity.CRITICAL,
        "Re-auth in OF Intelligence → Accounts.",
    ),
    "account_expired": (
        Severity.CRITICAL,
        "Refresh credentials in OF Intelligence → Accounts.",
    ),
    "account_disconnected": (
        Severity.CRITICAL,
        "Reconnect account in OF Intelligence → Accounts.",
    ),
    "account_stale": (
        Severity.HIGH,
        "Investigate sync — possible access issue.",
    ),
    "api_disconnected": (
        Severity.CRITICAL,
        "Check Settings → Integrations → OnlyMonster credentials.",
    ),
    # Critical QC risks (per-message detectors → dedup'd per account)
    "refund_risk": (
        Severity.CRITICAL,
        "Review last hour of conversation in dashboard before responding.",
    ),
    "banned_content_risk": (
        Severity.CRITICAL,
        "Open dashboard ref to review the offending message; coach chatter.",
    ),
    "rude_reply": (
        Severity.HIGH,
        "Coach chatter; check refund risk on this conversation.",
    ),
    "serious_escalation_risk": (
        Severity.CRITICAL,
        "Review immediately in dashboard; consider compliance escalation.",
    ),
    "missed_buying_signal": (
        Severity.HIGH,
        "Open conversation in dashboard; verify chatter offered a price/PPV.",
    ),
    "weak_sales_handling": (
        Severity.HIGH,
        "Open conversation in dashboard; check for recovery / counter-offer.",
    ),
    "account_revenue_drop": (
        Severity.HIGH,
        "Compare today vs the last 7 days in the Daily QC Dashboard.",
    ),
}

# Sync-failure codes use a ``sync_failure:{entity}`` shape.  Routing matches
# on prefix.
_SYNC_FAILURE_PREFIX = "sync_failure:"
_SYNC_FAILURE_ROUTE: tuple[Severity, str] = (
    Severity.HIGH,
    "Re-run manual sync from OF Intelligence.",
)


def _route(code: str) -> tuple[Severity, str] | None:
    if code in _CODE_ROUTING:
        return _CODE_ROUTING[code]
    if code.startswith(_SYNC_FAILURE_PREFIX):
        return _SYNC_FAILURE_ROUTE
    return None


def _facts_for(code: str, context: dict[str, Any] | None) -> tuple[tuple[str, str], ...]:
    """Return the curated, privacy-safe facts list for a given code.

    NEVER read raw ``error``/``reason`` text from sync_log here — that
    field can carry OnlyMonster API response bodies and leak user data.
    NEVER include the matched keyword for QC risk codes — only generic
    detection phrases.  Anything not listed here is dropped; callers
    that need full detail open the dashboard via the alert ref.
    """
    ctx = context or {}
    if code == "account_blocked":
        return (("Status", "blocked"),)
    if code == "account_expired":
        return (("Status", "expired"),)
    if code == "account_disconnected":
        return (("Status", "disconnected"),)
    if code == "account_stale":
        hours = ctx.get("hours_since_sync")
        return (("Hours since sync", str(hours)),) if hours is not None else ()
    if code == "api_disconnected":
        return (("Window", "last 24h"),)
    if code == "account_revenue_drop":
        rev24 = ctx.get("revenue_24h_cents")
        avg7 = ctx.get("revenue_7d_avg_cents")
        facts: list[tuple[str, str]] = []
        if rev24 is not None:
            facts.append(("24h", f"${int(rev24) / 100:,.2f}"))
        if avg7 is not None:
            facts.append(("7d daily avg", f"${int(avg7) / 100:,.2f}"))
        return tuple(facts)
    if code.startswith(_SYNC_FAILURE_PREFIX):
        entity = ctx.get("entity") or code.split(":", 1)[1]
        return (("Entity", str(entity)),)
    if code in (
        "refund_risk",
        "banned_content_risk",
        "rude_reply",
        "serious_escalation_risk",
        "missed_buying_signal",
        "weak_sales_handling",
        "slow_response",
        "missed_follow_up",
    ):
        # Allowed: ``detection_phrase`` (generic, e.g. "refund-language detected").
        # Forbidden: matched keyword, message body, fan handle, raw payload.
        phrase = ctx.get("detection_phrase")
        return (("Signal", str(phrase)),) if phrase else ()
    return ()


# ── Public entrypoint ───────────────────────────────────────────────────────


async def ship_account_or_sync_alert(
    *,
    code: str,
    title: str,
    account_username: str | None,
    alert_id: UUID,
    context: dict[str, Any] | None = None,
    chatter_name: str | None = None,
) -> PublishResult | None:
    """Render and publish one OF account/sync/QC-risk alert.

    Returns ``None`` if the code is outside this dispatcher's scope (e.g.
    a future chatter-rollup code).  Returns the publisher's ``PublishResult``
    otherwise.

    Never raises — the OF Intelligence evaluation loop must be unaffected
    by Discord outages.
    """
    route = _route(code)
    if route is None:
        return None
    severity, action = route

    payload = AlertPayload(
        severity=severity,
        code=code,
        title=title,
        account_username=account_username,
        chatter_name=chatter_name,
        facts=_facts_for(code, context),
        action=action,
        ref=f"qc/alert/{alert_id}",
    )
    rendered = format_alert(payload)
    return await publish(
        rendered,
        code=code,
        severity=severity.value,
        log_extra={"alert_id": str(alert_id)},
    )
