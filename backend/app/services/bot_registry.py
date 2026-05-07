"""Bot registry helpers: seed data, permission checks, safe-actuator stubs.

The registry is a *reference* table — it does not orchestrate processes.
For v1:

  • ``bootstrap_seed`` upserts a known set of bot rows on backend startup.
    Existing rows are NOT overwritten (so an owner's permission edits
    survive restarts).
  • ``can_role_operate`` resolves whether a role string is allowed to
    start/stop a given bot.
  • ``actuate_start`` / ``actuate_stop`` are deliberate stubs:
       – If the bot is ``read_only_external``, both reject with a coded
         ``managed_externally`` outcome.  This protects launchd-managed
         bots (Hermes, Radar, cloudflared) from being touched via the
         API.
       – Otherwise they flip ``enabled`` on the registry row and write a
         status update.  v1 does not start real OS-level processes from
         here; the registry's ``enabled`` flag is the operator's intent
         and downstream loops can poll it later.

Privacy: nothing in this module touches secrets, fan PII, message
bodies, or webhook URLs.  Seed metadata is hand-curated, public-facing
copy.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlmodel import select

from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.bot_registry import (
    BOT_KIND_CONTROL_LOOP,
    BOT_KIND_PUBLISHER,
    BOT_KIND_READ_ONLY_EXTERNAL,
    BOT_KIND_SCHEDULER,
    BOT_STATUS_DISABLED,
    BOT_STATUS_IDLE,
    BOT_STATUS_UNKNOWN,
    VALID_BOT_KINDS,
    BotRegistryEntry,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = get_logger(__name__)


# ── Seed data ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BotSeed:
    """Static seed metadata for a known Mission Control bot."""

    slug: str
    name: str
    kind: str
    description: str
    permitted_roles: tuple[str, ...]
    safe_mode: bool = True


# IMPORTANT: keep this list non-sensitive.  No webhook URLs, no tokens,
# no env-var values, no fan PII.  Just slugs + display copy.
#
# For Daily QC bots the start/stop endpoints in /api/v1/bots are
# intentionally a no-op + audit-log only.  Real start/stop continues to
# happen via the existing /api/v1/of-qc-scheduler/enabled and
# /api/v1/of-qc-discord/enabled owner-only endpoints — this lane does
# not duplicate or override that surface.
SEED_BOTS: tuple[BotSeed, ...] = (
    BotSeed(
        slug="of_daily_qc_scheduler",
        name="OF Daily QC Scheduler",
        kind=BOT_KIND_SCHEDULER,
        description=(
            "Daily QC tick loop.  Operates in synthetic-data sandbox by "
            "default.  Real start/stop is gated by the existing Daily QC "
            "scheduler toggles."
        ),
        permitted_roles=("owner",),
    ),
    BotSeed(
        slug="of_qc_discord_publisher",
        name="OF QC Discord Publisher",
        kind=BOT_KIND_PUBLISHER,
        description=(
            "Publishes Daily QC alerts to Discord via webhook when both "
            "the master toggle and the live-send gate are on."
        ),
        permitted_roles=("owner",),
    ),
    BotSeed(
        slug="of_qc_telegram_publisher",
        name="OF QC Telegram Publisher",
        kind=BOT_KIND_PUBLISHER,
        description=(
            "Publishes Daily QC summaries to Telegram when explicitly "
            "enabled.  Defaults off; obeys the same kill switches as "
            "the Discord publisher."
        ),
        permitted_roles=("owner",),
    ),
    BotSeed(
        slug="master_control_loop",
        name="Master Control Loop",
        kind=BOT_KIND_CONTROL_LOOP,
        description=(
            "Mission Control's master orchestration loop.  Owner-only "
            "start/stop today; reflects the existing /workflows/master "
            "endpoints."
        ),
        permitted_roles=("owner",),
    ),
    BotSeed(
        slug="hermes",
        name="Hermes (External)",
        kind=BOT_KIND_READ_ONLY_EXTERNAL,
        description=(
            "Hermes guardian process.  Managed by launchd outside "
            "Mission Control.  Status is reflected here for visibility "
            "only — start/stop is intentionally not exposed via this API."
        ),
        permitted_roles=("owner",),
    ),
    BotSeed(
        slug="ai_radar",
        name="AI Radar (External)",
        kind=BOT_KIND_READ_ONLY_EXTERNAL,
        description=(
            "AI Radar Discord posting bot.  Managed by launchd outside "
            "Mission Control.  Read-only entry."
        ),
        permitted_roles=("owner",),
    ),
    BotSeed(
        slug="social_radar",
        name="Social Radar (External)",
        kind=BOT_KIND_READ_ONLY_EXTERNAL,
        description=(
            "Social Radar Discord posting bot.  Managed by launchd "
            "outside Mission Control.  Read-only entry."
        ),
        permitted_roles=("owner",),
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def parse_permitted_roles(json_text: str | None) -> list[str]:
    """Decode the ``permitted_roles_json`` string into a list of role names."""
    if not json_text:
        return ["owner"]
    try:
        decoded = json.loads(json_text)
    except (TypeError, ValueError):
        return ["owner"]
    if not isinstance(decoded, list):
        return ["owner"]
    return [str(r) for r in decoded if isinstance(r, str)]


def encode_permitted_roles(roles: Sequence[str]) -> str:
    """JSON-encode a permitted-roles list with stable ordering."""
    cleaned = sorted({r for r in roles if isinstance(r, str)})
    if not cleaned:
        cleaned = ["owner"]
    if "owner" not in cleaned:
        cleaned = ["owner", *cleaned]
        cleaned = sorted(set(cleaned))
    return json.dumps(cleaned)


def can_role_operate(role: str | None, entry: BotRegistryEntry) -> bool:
    """Return True iff *role* is allowed to start/stop *entry*.

    External-managed bots ALWAYS reject — even owners cannot actuate
    launchd / cloudflared / Hermes / Radar processes through this API.
    Owner can still edit ``permitted_roles`` (different endpoint) and
    of course retains DB access.
    """
    if role is None:
        return False
    if entry.kind == BOT_KIND_READ_ONLY_EXTERNAL:
        return False
    if role == "owner":
        return True
    permitted = parse_permitted_roles(entry.permitted_roles_json)
    return role in permitted


def is_read_only_external(entry: BotRegistryEntry) -> bool:
    return entry.kind == BOT_KIND_READ_ONLY_EXTERNAL


# ── Seeding ──────────────────────────────────────────────────────────────────


async def bootstrap_seed(session: "AsyncSession") -> int:
    """Idempotently insert seed rows for every known bot.

    Returns the number of newly inserted rows.  Existing rows are
    untouched so owner edits to ``permitted_roles_json`` survive
    restarts.
    """
    result = await session.exec(select(BotRegistryEntry))
    existing = {row.slug: row for row in result.all()}

    inserted = 0
    for seed in SEED_BOTS:
        if seed.slug in existing:
            continue
        if seed.kind not in VALID_BOT_KINDS:  # pragma: no cover — defensive
            logger.warning("[bot_registry] seed has invalid kind=%s slug=%s", seed.kind, seed.slug)
            continue
        row = BotRegistryEntry(
            slug=seed.slug,
            name=seed.name,
            kind=seed.kind,
            description=seed.description,
            enabled=False,
            safe_mode=seed.safe_mode,
            status=(
                BOT_STATUS_DISABLED
                if seed.kind == BOT_KIND_READ_ONLY_EXTERNAL
                else BOT_STATUS_UNKNOWN
            ),
            permitted_roles_json=encode_permitted_roles(seed.permitted_roles),
        )
        session.add(row)
        inserted += 1

    if inserted:
        await session.commit()
        logger.info("[bot_registry] bootstrap_seed inserted=%s", inserted)
    return inserted


# ── Actuator stubs ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ActuationResult:
    ok: bool
    status: str
    detail: str


async def actuate_start(
    session: "AsyncSession",
    entry: BotRegistryEntry,
) -> ActuationResult:
    """Mark a bot as enabled.  Returns a coded result.

    For ``read_only_external`` bots this rejects with
    ``managed_externally``.  For every other kind it flips the
    registry's intent flag — downstream supervisors / schedulers can
    poll the row to learn the operator's intent.
    """
    if is_read_only_external(entry):
        return ActuationResult(
            ok=False,
            status="blocked",
            detail="managed_externally",
        )
    entry.enabled = True
    entry.status = BOT_STATUS_IDLE
    entry.last_status_detail = "start_requested"
    entry.last_run_at = utcnow()
    entry.updated_at = utcnow()
    session.add(entry)
    return ActuationResult(ok=True, status=BOT_STATUS_IDLE, detail="start_requested")


async def actuate_stop(
    session: "AsyncSession",
    entry: BotRegistryEntry,
) -> ActuationResult:
    """Mark a bot as disabled.  Returns a coded result."""
    if is_read_only_external(entry):
        return ActuationResult(
            ok=False,
            status="blocked",
            detail="managed_externally",
        )
    entry.enabled = False
    entry.status = BOT_STATUS_DISABLED
    entry.last_status_detail = "stop_requested"
    entry.last_run_at = utcnow()
    entry.updated_at = utcnow()
    session.add(entry)
    return ActuationResult(ok=True, status=BOT_STATUS_DISABLED, detail="stop_requested")
