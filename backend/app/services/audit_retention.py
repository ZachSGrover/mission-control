"""Audit-event retention helpers.

Sprint 3 foundation. **No row is deleted by default in this sprint.**
The helpers here identify rows older than the configured retention
window so an operator (or a future scheduled job) can review them
before any actual purge.

Retention policy is per-category — e.g. `security` events are kept
much longer than routine `auth` events. Per the security plan §7.2 the
default retention for `audit_events` is **730 days**.

Operational usage::

    # In a CLI / RQ job:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.services.audit_retention import preview_purge, purge_old_audit_events

    async def run() -> None:
        async with async_session_maker() as session:
            preview = await preview_purge(session)
            print(preview)
            # When you're ready (and only then):
            # deleted = await purge_old_audit_events(session, dry_run=False)
            # await session.commit()
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.audit_events import AuditEvent

# Per-category retention in days. Anything not explicitly listed falls
# back to ``DEFAULT_RETENTION_DAYS``. Numbers chosen to match security
# plan §7.2 with reasonable per-category exceptions.
RETENTION_DAYS_BY_CATEGORY: Final[dict[str, int]] = {
    "auth": 90,  # noisier, low-value individually; aggregates suffice after 90d
    "credential": 730,
    "role": 730,
    "permission": 730,
    "export": 730,
    "connector": 730,
    "llm": 365,
    "creator_data": 730,
    "fan_data": 730,
    "system": 365,
    "security": 1825,  # 5y — deepest retention for the most consequential events
    "integration": 730,
}
DEFAULT_RETENTION_DAYS: Final[int] = 730


def cutoff_for_category(category: str, *, now: datetime | None = None) -> datetime:
    """Return the timestamp at-or-before which rows of ``category`` are eligible
    for purge. Anything ``created_at <= cutoff`` is in scope.
    """
    moment = now or utcnow()
    days = RETENTION_DAYS_BY_CATEGORY.get(category, DEFAULT_RETENTION_DAYS)
    return moment - timedelta(days=days)


async def preview_purge(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Count how many rows per category are older than that category's cutoff.

    Pure read — never deletes. Returns ``{category: row_count}`` for
    every distinct category present in the table; categories with zero
    eligible rows are omitted from the result.
    """
    moment = now or utcnow()
    counts: dict[str, int] = {}

    # Pull the distinct category list once. Cheap because the column
    # is indexed.
    cat_stmt = select(AuditEvent.category).distinct()
    cat_result = await session.exec(cat_stmt)
    categories = [c for c in cat_result.all() if c]

    for category in categories:
        cutoff = cutoff_for_category(category, now=moment)
        count_stmt = (
            select(AuditEvent)
            .where(AuditEvent.category == category)
            .where(AuditEvent.created_at <= cutoff)
        )
        rows = (await session.exec(count_stmt)).all()
        if rows:
            counts[category] = len(rows)

    return counts


async def purge_old_audit_events(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    dry_run: bool = True,
) -> dict[str, int]:
    """Delete audit rows older than each category's retention cutoff.

    Defaults to ``dry_run=True`` — returns the count that *would* be
    deleted without actually deleting. Set ``dry_run=False`` to
    perform the delete; caller commits.

    The deletion is per-category, so a misconfigured cutoff in one
    category cannot wipe rows in another.
    """
    moment = now or utcnow()
    if dry_run:
        return await preview_purge(session, now=moment)

    deleted_per_category: dict[str, int] = {}
    cat_stmt = select(AuditEvent.category).distinct()
    cat_result = await session.exec(cat_stmt)
    categories = [c for c in cat_result.all() if c]

    for category in categories:
        cutoff = cutoff_for_category(category, now=moment)
        select_stmt = (
            select(AuditEvent)
            .where(AuditEvent.category == category)
            .where(AuditEvent.created_at <= cutoff)
        )
        rows = (await session.exec(select_stmt)).all()
        if not rows:
            continue
        for row in rows:
            await session.delete(row)
        deleted_per_category[category] = len(rows)

    return deleted_per_category
