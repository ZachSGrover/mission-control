"""X DM Bot RTxRT — sandbox-only run/orchestration helpers.

This module is the *only* place that knows how to advance a run for
the X DM Bot RTxRT.  It is deliberately narrow:

  • No AdsPower client.  No Playwright.  No HTTP requests to x.com.
  • No Windows Task Scheduler integration, no cron, no scheduled live
    runs.  ``start_sandbox_run`` is the only entry point and it
    produces dry-run output synchronously.
  • No secrets, cookies, tokens, or platform credentials are read,
    written, logged, or returned anywhere on this code path.

The word "send" appears nowhere in this module's runtime behavior —
the MVP literally has no live-send code path.  The API layer enforces
that ``live_writes_enabled=False`` and rejects any path that would
attempt one with a 403 ``live_writes_disabled_in_MVP``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlmodel import select

from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.bot_registry import BotRegistryEntry
from app.models.bot_runs import (
    OUTPUT_TYPE_DRY_RUN_LIST,
    OUTPUT_TYPE_RUN_LOG,
    OUTPUT_TYPE_SCAN_SUMMARY,
    RUN_MODE_SANDBOX,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_DRAFT,
    RUN_STATUS_PAUSED,
    RUN_STATUS_QUEUED,
    RUN_STATUS_REJECTED,
    RUN_STATUS_RUNNING_SCAN,
    BotRun,
    BotRunOutput,
)
from app.models.safety_events import (
    SAFETY_SEVERITY_CRITICAL,
    SAFETY_SEVERITY_INFO,
    SafetyEvent,
)

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = get_logger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

X_DM_RTXRT_SLUG = "x-dm-rtxrt"
X_DM_RTXRT_VERSION = "1.0.0"

# Runs which a duplicate-prevention check must consider "in flight".
ACTIVE_RUN_STATUSES = frozenset({RUN_STATUS_QUEUED, RUN_STATUS_RUNNING_SCAN, RUN_STATUS_DRAFT})

# Hard caps applied to user-supplied input.
MAX_MESSAGE_PREVIEW_CHARS = 80
MAX_TARGET_COUNT = 10_000


# ── Result types ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RunCreationResult:
    ok: bool
    run: BotRun | None
    error_code: str | None = None
    error_detail: str | None = None


@dataclass(frozen=True)
class RunStartResult:
    ok: bool
    run: BotRun | None
    error_code: str | None = None
    error_detail: str | None = None


# ── Validation helpers ───────────────────────────────────────────────────────


def truncate_message_preview(message: str | None) -> str | None:
    """Return at most ``MAX_MESSAGE_PREVIEW_CHARS`` of *message*.

    Empty / whitespace-only input becomes ``None``.  This is the *only*
    function in MVP that reads the user-supplied message body — the
    full message is dropped on the floor after this call returns.
    """
    if message is None:
        return None
    cleaned = message.strip()
    if not cleaned:
        return None
    return cleaned[:MAX_MESSAGE_PREVIEW_CHARS]


def validate_sandbox_gates(entry: BotRegistryEntry) -> str | None:
    """Return an error code if the bot's sandbox/live state is not safe.

    Returns ``None`` when the bot is in MVP-safe state, otherwise one
    of the coded errors used by the API layer.
    """
    if entry.live_writes_enabled:
        return "live_writes_disabled_in_MVP"
    if not entry.sandbox_mode:
        return "live_writes_disabled_in_MVP"
    if entry.kill_switch_active:
        return "kill_switch_active"
    return None


# ── Mock dry-run output ──────────────────────────────────────────────────────


def _mock_handles(target_count: int) -> list[str]:
    """Generate stable mock contact handles, never any real X handles."""
    n = max(0, min(target_count, MAX_TARGET_COUNT))
    return [f"mock_contact_{i:03d}" for i in range(1, n + 1)]


def _redacted_url(handle: str) -> str:
    """Return a redacted placeholder URL.

    The ``redacted://`` scheme is intentionally non-resolvable.  Real
    X.com URLs must never appear in MVP output.
    """
    return f"redacted://x-message/{handle}"


def _scan_summary(target_count: int) -> dict[str, int]:
    """Build the deterministic scan summary the spec asks for.

    Numbers are derived from ``target_count`` so the dry-run is fully
    reproducible without any external calls.
    """
    contacts_found = max(0, target_count)
    filtered_24h = contacts_found // 10
    readonly_count = contacts_found // 20
    would_message = max(0, contacts_found - filtered_24h - readonly_count)
    return {
        "contacts_found": contacts_found,
        "filtered_24h": filtered_24h,
        "readonly_count": readonly_count,
        "would_message_count": would_message,
    }


def build_dry_run_output(
    *,
    profile_id: str,
    profile_name: str,
    target_count: int,
    message_preview: str | None,
) -> tuple[dict[str, int], list[dict[str, str | bool]]]:
    """Return ``(scan_summary, dry_run_contacts)`` for a sandbox run.

    No external services are contacted.  Output is deterministic given
    the inputs and contains zero real platform data.
    """
    summary = _scan_summary(target_count)
    handles = _mock_handles(target_count)
    contacts: list[dict[str, str | bool]] = [
        {
            "handle": h,
            "conversation_url": _redacted_url(h),
            "profile_id": profile_id,
            "profile_name": profile_name,
            "message_preview": message_preview or "",
            "would_send": False,
        }
        for h in handles
    ]
    return summary, contacts


# ── Duplicate-run prevention ─────────────────────────────────────────────────


async def has_active_run_for_profile(
    session: "AsyncSession",
    *,
    bot_id: UUID,
    profile_id: str,
) -> bool:
    """True iff a queued/draft/running run already exists for this profile."""
    result = await session.exec(
        select(BotRun).where(BotRun.bot_id == bot_id, BotRun.profile_id == profile_id),
    )
    rows = result.all()
    for row in rows:
        if row.status in ACTIVE_RUN_STATUSES:
            return True
    return False


# ── Run creation / start (sandbox-only) ──────────────────────────────────────


async def create_draft_run(
    session: "AsyncSession",
    *,
    entry: BotRegistryEntry,
    profile_id: str,
    profile_name: str,
    target_count: int,
    message: str | None,
    created_by: str | None,
) -> RunCreationResult:
    """Create a draft sandbox run row.  The caller commits.

    Refuses if the bot is not in MVP-safe state (live writes flagged
    on, sandbox off, or kill switch active), or if a queued/running
    run already exists for the same profile.
    """
    gate_error = validate_sandbox_gates(entry)
    if gate_error is not None:
        return RunCreationResult(ok=False, run=None, error_code=gate_error)

    if target_count <= 0:
        return RunCreationResult(
            ok=False,
            run=None,
            error_code="invalid_target_count",
            error_detail="target_count must be positive",
        )
    if target_count > MAX_TARGET_COUNT:
        return RunCreationResult(
            ok=False,
            run=None,
            error_code="invalid_target_count",
            error_detail=f"target_count must be <= {MAX_TARGET_COUNT}",
        )

    if await has_active_run_for_profile(
        session,
        bot_id=entry.id,
        profile_id=profile_id,
    ):
        return RunCreationResult(
            ok=False,
            run=None,
            error_code="duplicate_run",
            error_detail="another run is already queued or running for this profile",
        )

    preview = truncate_message_preview(message)
    run = BotRun(
        bot_id=entry.id,
        status=RUN_STATUS_DRAFT,
        mode=RUN_MODE_SANDBOX,
        profile_id=profile_id[:64],
        profile_name=profile_name[:128],
        message_preview=preview,
        target_count=target_count,
        created_by=created_by,
    )
    session.add(run)
    return RunCreationResult(ok=True, run=run)


async def start_sandbox_run(
    session: "AsyncSession",
    *,
    entry: BotRegistryEntry,
    run: BotRun,
) -> RunStartResult:
    """Advance a draft run through scan → completed using mock data.

    The whole "execution" happens in-process and produces redacted
    dry-run output.  No external services are contacted.  The caller
    commits.
    """
    gate_error = validate_sandbox_gates(entry)
    if gate_error is not None:
        return RunStartResult(ok=False, run=run, error_code=gate_error)

    if run.status != RUN_STATUS_DRAFT:
        return RunStartResult(
            ok=False,
            run=run,
            error_code="invalid_state",
            error_detail=f"run cannot be started from status={run.status}",
        )

    if run.mode != RUN_MODE_SANDBOX:
        return RunStartResult(
            ok=False,
            run=run,
            error_code="live_writes_disabled_in_MVP",
        )

    started = utcnow()
    run.status = RUN_STATUS_RUNNING_SCAN
    run.started_at = started
    run.updated_at = started
    session.add(run)

    summary, contacts = build_dry_run_output(
        profile_id=run.profile_id,
        profile_name=run.profile_name,
        target_count=run.target_count,
        message_preview=run.message_preview,
    )

    scan_output = BotRunOutput(
        run_id=run.id,
        output_type=OUTPUT_TYPE_SCAN_SUMMARY,
        content_json=json.dumps(summary, sort_keys=True),
    )
    list_output = BotRunOutput(
        run_id=run.id,
        output_type=OUTPUT_TYPE_DRY_RUN_LIST,
        content_json=json.dumps({"contacts": contacts}),
    )
    log_output = BotRunOutput(
        run_id=run.id,
        output_type=OUTPUT_TYPE_RUN_LOG,
        content_json=json.dumps(
            {
                "events": [
                    {"event": "run_created", "ts": started.isoformat()},
                    {"event": "scan_started", "ts": started.isoformat()},
                    {
                        "event": "scan_completed",
                        "ts": started.isoformat(),
                        "summary": summary,
                    },
                    {"event": "run_completed", "ts": started.isoformat()},
                ],
                "mode": RUN_MODE_SANDBOX,
                "live_writes": False,
            },
            sort_keys=True,
        ),
    )
    session.add(scan_output)
    session.add(list_output)
    session.add(log_output)

    completed = utcnow()
    run.status = RUN_STATUS_COMPLETED
    run.scan_count = summary["contacts_found"]
    run.readonly_count = summary["readonly_count"]
    run.sent_count = 0
    run.completed_at = completed
    run.updated_at = completed
    elapsed = (completed - started).total_seconds()
    run.elapsed_seconds = max(0, int(elapsed))
    session.add(run)

    return RunStartResult(ok=True, run=run)


# ── Pause / reject / kill ────────────────────────────────────────────────────


async def pause_run(session: "AsyncSession", *, run: BotRun) -> bool:
    """Pause a queued/running sandbox run.  Returns True if mutated."""
    if run.status not in {RUN_STATUS_QUEUED, RUN_STATUS_RUNNING_SCAN}:
        return False
    run.status = RUN_STATUS_PAUSED
    run.updated_at = utcnow()
    session.add(run)
    return True


async def reject_run(session: "AsyncSession", *, run: BotRun) -> bool:
    """Reject a draft/queued/paused run.  Returns True if mutated."""
    if run.status not in {
        RUN_STATUS_DRAFT,
        RUN_STATUS_QUEUED,
        RUN_STATUS_PAUSED,
    }:
        return False
    run.status = RUN_STATUS_REJECTED
    run.updated_at = utcnow()
    session.add(run)
    return True


async def activate_kill_switch(
    session: "AsyncSession",
    *,
    entry: BotRegistryEntry,
) -> tuple[int, int]:
    """Set ``kill_switch_active`` and cancel queued / running sandbox runs.

    Returns ``(cancelled_count, paused_count)``.  Append-only safety
    event row is written by this function; the caller commits.
    """
    entry.kill_switch_active = True
    entry.updated_at = utcnow()
    session.add(entry)

    result = await session.exec(
        select(BotRun).where(
            BotRun.bot_id == entry.id,
            BotRun.status.in_(  # type: ignore[attr-defined]
                [RUN_STATUS_QUEUED, RUN_STATUS_RUNNING_SCAN]
            ),
        )
    )
    affected = list(result.all())
    cancelled = 0
    paused = 0
    now = utcnow()
    for r in affected:
        if r.status == RUN_STATUS_QUEUED:
            r.status = RUN_STATUS_REJECTED
            cancelled += 1
        else:
            r.status = RUN_STATUS_PAUSED
            paused += 1
        r.updated_at = now
        session.add(r)

    session.add(
        SafetyEvent(
            run_id=None,
            event_type="kill_switch.activated",
            severity=SAFETY_SEVERITY_CRITICAL,
            description=(
                f"kill switch activated for {entry.slug}; " f"cancelled={cancelled} paused={paused}"
            ),
            resolved=False,
        )
    )
    return cancelled, paused


# ── CSV redaction helpers ────────────────────────────────────────────────────


def csv_safe_value(value: str | int | datetime | None) -> str:
    """Render a value for CSV without leaking newlines or quoting issues."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).replace("\n", " ").replace("\r", " ")
    if any(ch in text for ch in (",", '"', "\n")):
        return '"' + text.replace('"', '""') + '"'
    return text


def runs_to_csv(runs: Sequence[BotRun]) -> str:
    """Serialize a list of runs to CSV.  No secrets, no full message body."""
    header = (
        "id,status,mode,profile_id,profile_name,message_preview,"
        "target_count,scan_count,readonly_count,sent_count,elapsed_seconds,"
        "started_at,completed_at,created_by"
    )
    lines = [header]
    for r in runs:
        lines.append(
            ",".join(
                csv_safe_value(v)
                for v in (
                    str(r.id),
                    r.status,
                    r.mode,
                    r.profile_id,
                    r.profile_name,
                    r.message_preview,
                    r.target_count,
                    r.scan_count,
                    r.readonly_count,
                    r.sent_count,
                    r.elapsed_seconds,
                    r.started_at,
                    r.completed_at,
                    r.created_by,
                )
            )
        )
    return "\n".join(lines) + "\n"


def contacts_to_csv(
    rows: Sequence[tuple[str, str, str | None, datetime | None, int]],
    *,
    include_handle: bool = True,
) -> str:
    """Serialize the operator-safe contact archive view.

    Columns: ``profile_name,profile_id,handle,last_sent_at,sent_count``.
    Conversation URLs and any sensitive fields are intentionally absent.
    """
    if include_handle:
        header = "profile_name,profile_id,handle,last_sent_at,sent_count"
    else:
        header = "profile_name,profile_id,last_sent_at,sent_count"
    lines = [header]
    for profile_name, profile_id, handle, last_sent_at, sent_count in rows:
        cells = [csv_safe_value(profile_name), csv_safe_value(profile_id)]
        if include_handle:
            cells.append(csv_safe_value(handle))
        cells.extend([csv_safe_value(last_sent_at), csv_safe_value(sent_count)])
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"


# ── Logger sentinel ──────────────────────────────────────────────────────────


def log_safety_event(
    session: "AsyncSession",
    *,
    event_type: str,
    description: str,
    severity: str = SAFETY_SEVERITY_INFO,
    run_id: UUID | None = None,
) -> SafetyEvent:
    """Append a safety event row.  Caller commits."""
    event = SafetyEvent(
        run_id=run_id,
        event_type=event_type,
        severity=severity,
        description=description[:512],
        resolved=False,
    )
    session.add(event)
    return event
