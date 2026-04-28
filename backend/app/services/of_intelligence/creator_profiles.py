"""OnlyFans Intelligence — Creator Account Intelligence Profiles.

Permanent profile-per-creator layer.  Each `(source, source_account_id)`
combination has at most one row in `of_intelligence_creator_profiles`.

Two flavours of fields:
  • Auto fields (identity, status, subscription) — sourced from the synced
    `of_intelligence_accounts.raw` payload.  Reconcile rewrites them on
    every read so a re-sync is reflected without a manual edit.
  • Operator fields (brand, voice, vault, strategy, social URLs, notes) —
    only ever changed via `update_profile`.  Reconcile never touches them.

Consumers:
  • `list_profiles` → frontend list page (Account Intelligence index).
  • `get_profile`   → frontend detail page.
  • `update_profile`→ frontend detail page (operator edits).
  • `generate_account_audit` → "Generate Account Audit" button.

The audit is intentionally a deterministic, read-only roll-up of what we
already have synced.  No external scraping, no AI calls, no writes back
to OnlyMonster.  Today's accounts get a usable summary; we can layer an
LLM-backed enrichment on top later without changing the call sites.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.of_intelligence import (
    SOURCE_ONLYMONSTER,
    OfIntelligenceAccount,
    OfIntelligenceAlert,
    OfIntelligenceCreatorProfile,
    OfIntelligenceFan,
    OfIntelligenceMessage,
    OfIntelligencePost,
    OfIntelligenceRevenue,
    OfIntelligenceUserMetrics,
)

logger = logging.getLogger(__name__)


# Operator-managed columns.  `update_profile` only accepts these — everything
# else is auto-populated and would be clobbered on the next reconcile.
EDITABLE_FIELDS: tuple[str, ...] = (
    "brand_persona",
    "content_pillars",
    "voice_tone",
    "audience_summary",
    "monetization_focus",
    "posting_cadence",
    "strategy_summary",
    "off_limits",
    "vault_notes",
    "agency_notes",
    "onlyfans_url",
    "instagram_url",
    "twitter_url",
    "tiktok_url",
    "threads_url",
    "reddit_url",
)


# ── Public dataclasses ───────────────────────────────────────────────────────


@dataclass
class CreatorProfileStats:
    """Live counts joined onto a profile row for the list/detail views."""

    fans_count: int = 0
    messages_count: int = 0
    posts_count: int = 0
    revenue_30d_cents: int = 0
    revenue_total_cents: int = 0
    open_alert_count: int = 0
    last_message_at: datetime | None = None


@dataclass
class CreatorProfileWithStats:
    profile: OfIntelligenceCreatorProfile
    stats: CreatorProfileStats


@dataclass
class AccountAuditSection:
    title: str
    body: str


@dataclass
class AccountAudit:
    profile_id: UUID
    source: str
    source_account_id: str
    generated_at: datetime
    summary: str
    sections: list[AccountAuditSection] = field(default_factory=list)
    markdown: str = ""


# ── Reconcile / read ─────────────────────────────────────────────────────────


def _coerce_dt(value: Any) -> datetime | None:
    """Naive-UTC coercion mirroring sync._coerce_dt.

    Local copy avoids importing the entire onlymonster.sync module just for
    a coercion helper.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        cleaned = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(cleaned)
        except ValueError:
            return None
        return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed
    if isinstance(value, (int, float)):
        try:
            return datetime.utcfromtimestamp(float(value))
        except (OverflowError, ValueError, OSError):
            return None
    return None


def _account_payload(account: OfIntelligenceAccount) -> dict[str, Any]:
    return account.raw if isinstance(account.raw, dict) else {}


async def _all_accounts(session: AsyncSession) -> list[OfIntelligenceAccount]:
    return list(
        (
            await session.exec(
                select(OfIntelligenceAccount).order_by(
                    col(OfIntelligenceAccount.last_synced_at).desc()
                )
            )
        ).all()
    )


async def _profiles_by_key(
    session: AsyncSession,
) -> dict[tuple[str, str], OfIntelligenceCreatorProfile]:
    rows = (await session.exec(select(OfIntelligenceCreatorProfile))).all()
    return {(p.source, p.source_account_id): p for p in rows}


async def reconcile_profiles(session: AsyncSession) -> int:
    """Ensure a profile row exists per synced account; refresh auto fields.

    Operator-managed fields are never touched.  Returns the number of
    profile rows that were created or updated.
    """
    accounts = await _all_accounts(session)
    by_key = await _profiles_by_key(session)
    touched = 0
    now = utcnow()

    for account in accounts:
        payload = _account_payload(account)
        key = (account.source, account.source_id)
        profile = by_key.get(key)
        is_new = profile is None
        if profile is None:
            profile = OfIntelligenceCreatorProfile(
                source=account.source,
                source_account_id=account.source_id,
                created_at=now,
                updated_at=now,
            )

        # Auto fields — always rewrite from the latest synced account row.
        # These are derived data; never operator-managed.
        new_username = account.username or payload.get("username")
        new_display = account.display_name or payload.get("name")
        new_avatar = payload.get("avatar")
        new_platform = payload.get("platform")
        new_org = payload.get("organisation_id")
        new_price = payload.get("subscribe_price")
        new_subscribe_price_cents: int | None
        if isinstance(new_price, (int, float)):
            # OnlyMonster reports `subscribe_price` in dollars (float).
            new_subscribe_price_cents = int(round(float(new_price) * 100))
        elif isinstance(new_price, str):
            try:
                new_subscribe_price_cents = int(round(float(new_price) * 100))
            except ValueError:
                new_subscribe_price_cents = None
        else:
            new_subscribe_price_cents = None
        new_expiration = _coerce_dt(payload.get("subscription_expiration_date"))

        changed = is_new
        for attr, new_val in (
            ("username", new_username),
            ("display_name", new_display),
            ("avatar_url", new_avatar),
            ("platform", new_platform),
            ("organisation_id", new_org),
            ("subscribe_price_cents", new_subscribe_price_cents),
            ("subscription_expiration_date", new_expiration),
            ("access_status", account.access_status),
            ("status", account.status),
            ("last_account_sync_at", account.last_synced_at),
            ("raw_source_payload", payload or None),
        ):
            if getattr(profile, attr) != new_val:
                setattr(profile, attr, new_val)
                changed = True

        if changed:
            profile.updated_at = now
            session.add(profile)
            touched += 1

    if touched:
        await session.commit()
        logger.info(
            "of_intelligence.creator_profiles.reconciled touched=%s accounts=%s",
            touched,
            len(accounts),
        )
    return touched


async def _stats_for_account(
    session: AsyncSession,
    source: str,
    source_account_id: str,
) -> CreatorProfileStats:
    """Live roll-up against existing OFI tables.

    All counts are scoped by `(source, account_source_id)`.  No data is
    written here — pure read.
    """
    fans_count = (
        await session.exec(
            select(func.count())
            .select_from(OfIntelligenceFan)
            .where(OfIntelligenceFan.source == source)
            .where(OfIntelligenceFan.account_source_id == source_account_id)
        )
    ).one() or 0

    messages_count = (
        await session.exec(
            select(func.count())
            .select_from(OfIntelligenceMessage)
            .where(OfIntelligenceMessage.source == source)
            .where(OfIntelligenceMessage.account_source_id == source_account_id)
        )
    ).one() or 0

    posts_count = (
        await session.exec(
            select(func.count())
            .select_from(OfIntelligencePost)
            .where(OfIntelligencePost.source == source)
            .where(OfIntelligencePost.account_source_id == source_account_id)
        )
    ).one() or 0

    revenue_rows = (
        await session.exec(
            select(OfIntelligenceRevenue)
            .where(OfIntelligenceRevenue.source == source)
            .where(OfIntelligenceRevenue.account_source_id == source_account_id)
        )
    ).all()
    now = utcnow()
    cutoff_30 = now - timedelta(days=30)

    def _txn_time(row: OfIntelligenceRevenue) -> datetime:
        return row.period_start or row.captured_at

    revenue_total = sum(r.revenue_cents for r in revenue_rows)
    revenue_30d = sum(r.revenue_cents for r in revenue_rows if _txn_time(r) >= cutoff_30)

    open_alerts = (
        await session.exec(
            select(func.count())
            .select_from(OfIntelligenceAlert)
            .where(OfIntelligenceAlert.account_source_id == source_account_id)
            .where(OfIntelligenceAlert.status == "open")
        )
    ).one() or 0

    last_message = (
        await session.exec(
            select(OfIntelligenceMessage)
            .where(OfIntelligenceMessage.source == source)
            .where(OfIntelligenceMessage.account_source_id == source_account_id)
            .order_by(col(OfIntelligenceMessage.sent_at).desc())
            .limit(1)
        )
    ).first()

    return CreatorProfileStats(
        fans_count=int(fans_count),
        messages_count=int(messages_count),
        posts_count=int(posts_count),
        revenue_30d_cents=int(revenue_30d),
        revenue_total_cents=int(revenue_total),
        open_alert_count=int(open_alerts),
        last_message_at=last_message.sent_at if last_message else None,
    )


async def list_profiles(session: AsyncSession) -> list[CreatorProfileWithStats]:
    """Return every creator profile + live stats; reconciles first."""
    await reconcile_profiles(session)
    profiles = (
        await session.exec(
            select(OfIntelligenceCreatorProfile).order_by(
                col(OfIntelligenceCreatorProfile.username).asc()
            )
        )
    ).all()
    out: list[CreatorProfileWithStats] = []
    for profile in profiles:
        stats = await _stats_for_account(session, profile.source, profile.source_account_id)
        out.append(CreatorProfileWithStats(profile=profile, stats=stats))
    return out


async def get_profile(
    session: AsyncSession,
    profile_id: UUID,
) -> CreatorProfileWithStats | None:
    profile = (
        await session.exec(
            select(OfIntelligenceCreatorProfile).where(
                OfIntelligenceCreatorProfile.id == profile_id
            )
        )
    ).first()
    if not profile:
        return None
    stats = await _stats_for_account(session, profile.source, profile.source_account_id)
    return CreatorProfileWithStats(profile=profile, stats=stats)


async def update_profile(
    session: AsyncSession,
    profile_id: UUID,
    fields: dict[str, Any],
) -> OfIntelligenceCreatorProfile | None:
    """Apply operator edits — silently ignores any non-editable keys."""
    profile = (
        await session.exec(
            select(OfIntelligenceCreatorProfile).where(
                OfIntelligenceCreatorProfile.id == profile_id
            )
        )
    ).first()
    if not profile:
        return None

    changed = False
    for key, value in fields.items():
        if key not in EDITABLE_FIELDS:
            continue
        # Normalise empty strings to None so the DB stores NULL, not "".
        new_value = value if value not in ("", None) else None
        if getattr(profile, key) != new_value:
            setattr(profile, key, new_value)
            changed = True

    if changed:
        profile.updated_at = utcnow()
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
        logger.info(
            "of_intelligence.creator_profiles.updated profile_id=%s fields=%s",
            profile_id,
            sorted(k for k in fields if k in EDITABLE_FIELDS),
        )
    return profile


# ── Audit generation ─────────────────────────────────────────────────────────


def _format_cents(cents: int | None) -> str:
    if cents is None:
        return "—"
    return f"${cents / 100:,.2f}"


def _format_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M UTC")


async def generate_account_audit(
    session: AsyncSession,
    profile_id: UUID,
) -> AccountAudit | None:
    """Deterministic audit roll-up for a single creator profile.

    Pulls existing OFI tables only.  No external network calls, no AI.
    Used by the "Generate Account Audit" button on the detail page.
    """
    bundle = await get_profile(session, profile_id)
    if not bundle:
        return None
    profile = bundle.profile
    stats = bundle.stats
    now = utcnow()

    # ── Identity / connection
    identity_lines = [
        f"- **Username**: {profile.username or '—'}",
        f"- **Display name**: {profile.display_name or '—'}",
        f"- **Platform**: {profile.platform or '—'}",
        f"- **Subscription price**: {_format_cents(profile.subscribe_price_cents)}",
        f"- **Subscription expires**: {_format_dt(profile.subscription_expiration_date)}",
        f"- **Access status**: {profile.access_status or '—'}",
        f"- **Last account sync**: {_format_dt(profile.last_account_sync_at)}",
    ]

    # ── Operator strategy notes (whatever has been filled in)
    strategy_lines: list[str] = []
    for label, value in [
        ("Brand persona", profile.brand_persona),
        ("Content pillars", profile.content_pillars),
        ("Voice / tone", profile.voice_tone),
        ("Audience", profile.audience_summary),
        ("Monetization focus", profile.monetization_focus),
        ("Posting cadence", profile.posting_cadence),
        ("Strategy summary", profile.strategy_summary),
        ("Off limits", profile.off_limits),
        ("Vault notes", profile.vault_notes),
        ("Agency notes", profile.agency_notes),
    ]:
        if value:
            strategy_lines.append(f"**{label}**\n\n{value}\n")
    if not strategy_lines:
        strategy_lines.append(
            "_No operator notes filled in yet — open this profile and fill in the "
            "Brand, Strategy, and Vault sections to enrich future audits._"
        )

    # ── Performance roll-up
    performance_lines = [
        f"- **Fans synced**: {stats.fans_count:,}",
        f"- **Messages synced**: {stats.messages_count:,}",
        f"- **Posts synced**: {stats.posts_count:,}",
        f"- **Revenue (30d)**: {_format_cents(stats.revenue_30d_cents)}",
        f"- **Revenue (lifetime)**: {_format_cents(stats.revenue_total_cents)}",
        f"- **Last message at**: {_format_dt(stats.last_message_at)}",
        f"- **Open alerts**: {stats.open_alert_count}",
    ]

    # ── Latest user metrics window (per chatter on this account)
    metrics_rows = (
        await session.exec(
            select(OfIntelligenceUserMetrics)
            .order_by(col(OfIntelligenceUserMetrics.period_end).desc())
            .limit(50)
        )
    ).all()
    metrics_lines: list[str]
    if metrics_rows:
        metrics_lines = [
            "Latest 5 user-metric windows across all chatters (most recent first):",
        ]
        for m in metrics_rows[:5]:
            metrics_lines.append(
                f"- chatter `{m.user_id}` • {m.period_start.date()} → {m.period_end.date()}"
                f" • msgs={m.messages_count or 0:,} • paid={_format_cents(m.paid_messages_price_sum_cents)}"
                f" • tips={_format_cents(m.tips_amount_sum_cents)}"
                f" • avg reply={m.reply_time_avg_seconds or 0}s"
            )
    else:
        metrics_lines = ["No `of_intelligence_user_metrics` rows synced yet."]

    # ── Recent open alerts on this account
    alert_rows = (
        await session.exec(
            select(OfIntelligenceAlert)
            .where(OfIntelligenceAlert.account_source_id == profile.source_account_id)
            .where(OfIntelligenceAlert.status == "open")
            .order_by(col(OfIntelligenceAlert.created_at).desc())
            .limit(10)
        )
    ).all()
    alert_lines: list[str]
    if alert_rows:
        alert_lines = [
            f"- **{a.severity.upper()}** — {a.title} ({_format_dt(a.created_at)})"
            for a in alert_rows
        ]
    else:
        alert_lines = ["No open alerts attached to this account."]

    # ── External links
    link_lines: list[str] = []
    for label, url in [
        ("OnlyFans", profile.onlyfans_url),
        ("Instagram", profile.instagram_url),
        ("Twitter / X", profile.twitter_url),
        ("TikTok", profile.tiktok_url),
        ("Threads", profile.threads_url),
        ("Reddit", profile.reddit_url),
    ]:
        if url:
            link_lines.append(f"- {label}: {url}")
    if not link_lines:
        link_lines.append("_No external links recorded yet._")

    sections: list[AccountAuditSection] = [
        AccountAuditSection(title="Identity", body="\n".join(identity_lines)),
        AccountAuditSection(title="Brand & Strategy", body="\n\n".join(strategy_lines)),
        AccountAuditSection(title="Performance", body="\n".join(performance_lines)),
        AccountAuditSection(title="Recent Chatter Metrics", body="\n".join(metrics_lines)),
        AccountAuditSection(title="Open Alerts", body="\n".join(alert_lines)),
        AccountAuditSection(title="External Presence", body="\n".join(link_lines)),
    ]

    label = profile.display_name or profile.username or profile.source_account_id
    summary = (
        f"Audit for **{label}** generated {_format_dt(now)}. "
        f"{stats.fans_count:,} fans, {stats.messages_count:,} messages, "
        f"30-day revenue {_format_cents(stats.revenue_30d_cents)}, "
        f"{stats.open_alert_count} open alert(s)."
    )

    md_parts: list[str] = [f"# Account Audit — {label}", "", summary, ""]
    for s in sections:
        md_parts.append(f"## {s.title}")
        md_parts.append("")
        md_parts.append(s.body)
        md_parts.append("")
    markdown = "\n".join(md_parts)

    return AccountAudit(
        profile_id=profile.id,
        source=profile.source,
        source_account_id=profile.source_account_id,
        generated_at=now,
        summary=summary,
        sections=sections,
        markdown=markdown,
    )


# ── Default-source convenience for tests / scripts ───────────────────────────


def default_source() -> str:
    return SOURCE_ONLYMONSTER
