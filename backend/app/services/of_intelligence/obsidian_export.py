"""OnlyFans Intelligence — Obsidian-style memory export skeleton.

Renders a daily note + per-section subfolder layout that mirrors:

    Business Memory/
        OnlyMonster/
            Accounts/
            Chatters/
            Fans/
            Revenue/
            QC Reports/
            Alerts/
            Mass Messages/
            Posting Insights/

The default behaviour is to render the markdown in-memory and return the
files to the caller — no filesystem writes — so the API endpoint can stream
a zip back to the user.  When an `export_path` is provided (configurable in
the OFI settings page), files are written to disk relative to that root.

Markdown is intentionally Obsidian-friendly: front-matter for metadata,
double-bracket links for cross-references, and YAML-tag-compatible tag lists.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.of_intelligence import (
    BusinessMemoryEntry,
    OfIntelligenceAccount,
    OfIntelligenceAlert,
    OfIntelligenceMassMessage,
    OfIntelligenceQcReport,
)

logger = logging.getLogger(__name__)

OBSIDIAN_ROOT = "Business Memory/OnlyMonster"


@dataclass
class ExportedFile:
    relative_path: str
    content: str


@dataclass
class ExportResult:
    generated_at: datetime
    files: list[ExportedFile] = field(default_factory=list)
    written_to_disk: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


# ── Public entrypoint ────────────────────────────────────────────────────────


async def export_memory(
    session: AsyncSession,
    *,
    target_date: datetime | None = None,
    export_path: str | None = None,
) -> ExportResult:
    """Generate an Obsidian-friendly snapshot of the OFI memory layer.

    When `export_path` is set and the directory exists (or can be created),
    files are also written to disk.  Otherwise files are returned in memory
    so the API can stream them.
    """
    when = target_date or utcnow()
    files: list[ExportedFile] = []

    files.append(_render_daily_note(when, await _gather_daily_summary(session, when)))
    files.extend(await _render_accounts(session))
    files.extend(await _render_qc_reports(session))
    files.extend(await _render_alerts(session))
    files.extend(await _render_mass_messages(session))

    written: list[str] = []
    skipped: list[str] = []
    if export_path:
        root = Path(export_path).expanduser()
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning("of_intelligence.export.mkdir_failed path=%s err=%s", root, exc)
            skipped.append(str(root))
        else:
            for f in files:
                full = root / f.relative_path
                full.parent.mkdir(parents=True, exist_ok=True)
                try:
                    full.write_text(f.content, encoding="utf-8")
                    written.append(str(full))
                except OSError as exc:
                    logger.warning("of_intelligence.export.write_failed path=%s err=%s", full, exc)
                    skipped.append(str(full))

    logger.info(
        "of_intelligence.export.done files=%s written=%s skipped=%s",
        len(files),
        len(written),
        len(skipped),
    )
    return ExportResult(
        generated_at=utcnow(),
        files=files,
        written_to_disk=written,
        skipped=skipped,
    )


# ── Daily note ───────────────────────────────────────────────────────────────


async def _gather_daily_summary(session: AsyncSession, when: datetime) -> dict[str, Any]:
    qc = (
        await session.exec(
            select(OfIntelligenceQcReport)
            .order_by(OfIntelligenceQcReport.generated_at.desc())
            .limit(1)
        )
    ).first()
    accounts = (await session.exec(select(OfIntelligenceAccount))).all()
    alerts = (
        await session.exec(select(OfIntelligenceAlert).where(OfIntelligenceAlert.status == "open"))
    ).all()
    return {
        "qc": qc,
        "accounts": list(accounts),
        "open_alerts": list(alerts),
    }


def _render_daily_note(when: datetime, summary: dict[str, Any]) -> ExportedFile:
    date_str = when.date().isoformat()
    qc: OfIntelligenceQcReport | None = summary.get("qc")
    accounts: list[OfIntelligenceAccount] = summary.get("accounts") or []
    open_alerts: list[OfIntelligenceAlert] = summary.get("open_alerts") or []

    lines = [
        "---",
        f"date: {date_str}",
        "type: of-intelligence-daily",
        "tags: [of-intelligence, daily-note]",
        "---",
        "",
        f"# OnlyFans Intelligence — {date_str}",
        "",
        "## Accounts reviewed",
        f"- Total: {len(accounts)}",
    ]
    for a in accounts[:10]:
        lines.append(f"  - [[Accounts/{(a.username or a.source_id)}]] (status={a.status})")

    lines.extend(
        [
            "",
            "## Revenue summary",
            "_Skeleton — wire up daily revenue rollups here once the OnlyMonster revenue endpoint is connected._",
            "",
            "## Best performing accounts",
            "_Skeleton._",
            "",
            "## Worst performing accounts",
            "_Skeleton._",
            "",
            "## Chatter issues",
            "_Skeleton._",
            "",
            "## Fan issues",
            "_Skeleton._",
            "",
            "## Mass message performance",
            "_Skeleton._",
            "",
            "## Posting performance",
            "_Skeleton._",
            "",
            "## Access issues",
        ]
    )
    for a in accounts:
        if a.access_status and a.access_status.lower() in {"lost", "blocked", "expired"}:
            lines.append(f"- [[Accounts/{a.username or a.source_id}]] — {a.access_status}")
    if not any(
        a.access_status and a.access_status.lower() in {"lost", "blocked", "expired"}
        for a in accounts
    ):
        lines.append("- None")

    lines.extend(["", "## Important alerts"])
    if not open_alerts:
        lines.append("- None")
    for alert in open_alerts[:20]:
        lines.append(f"- ({alert.severity}) [[Alerts/{alert.code}]] — {alert.title}")

    lines.extend(["", "## Recommended actions"])
    if qc and qc.payload.get("action_list"):
        for idx, action in enumerate(qc.payload["action_list"], 1):
            lines.append(f"{idx}. {action}")
    else:
        lines.append("- None")

    lines.extend(["", "## Raw data references"])
    if qc:
        lines.append(f"- QC report id: `{qc.id}`")
    lines.append("- See `of_intelligence_sync_logs` for full sync history.")

    return ExportedFile(
        relative_path=f"{OBSIDIAN_ROOT}/Daily/{date_str}.md",
        content="\n".join(lines),
    )


# ── Sub-folder renderers ─────────────────────────────────────────────────────


async def _render_accounts(session: AsyncSession) -> list[ExportedFile]:
    accounts = (await session.exec(select(OfIntelligenceAccount))).all()
    files: list[ExportedFile] = []
    for a in accounts:
        slug = _safe_filename(a.username or a.source_id)
        body = "\n".join(
            [
                "---",
                f"id: {a.source_id}",
                f"source: {a.source}",
                f"username: {a.username or ''}",
                f"status: {a.status or ''}",
                f"access_status: {a.access_status or ''}",
                f"last_synced_at: {a.last_synced_at.isoformat()}",
                "tags: [of-intelligence, account]",
                "---",
                "",
                f"# {a.username or a.source_id}",
                "",
                f"- **Status:** {a.status or 'unknown'}",
                f"- **Access:** {a.access_status or 'unknown'}",
                f"- **Last synced:** {a.last_synced_at.isoformat()}",
            ]
        )
        files.append(
            ExportedFile(
                relative_path=f"{OBSIDIAN_ROOT}/Accounts/{slug}.md",
                content=body,
            )
        )
    return files


async def _render_qc_reports(session: AsyncSession) -> list[ExportedFile]:
    rows = (
        await session.exec(
            select(OfIntelligenceQcReport)
            .order_by(OfIntelligenceQcReport.generated_at.desc())
            .limit(30)
        )
    ).all()
    return [
        ExportedFile(
            relative_path=f"{OBSIDIAN_ROOT}/QC Reports/{r.report_date.date().isoformat()}.md",
            content=(
                r.markdown
                or f"# QC Report — {r.report_date.date().isoformat()}\n\n_No markdown rendered._"
            ),
        )
        for r in rows
    ]


async def _render_alerts(session: AsyncSession) -> list[ExportedFile]:
    rows = (
        await session.exec(
            select(OfIntelligenceAlert).order_by(OfIntelligenceAlert.created_at.desc()).limit(100)
        )
    ).all()
    files: list[ExportedFile] = []
    grouped: dict[str, list[OfIntelligenceAlert]] = {}
    for r in rows:
        grouped.setdefault(r.code, []).append(r)
    for code, alerts in grouped.items():
        slug = _safe_filename(code)
        lines = [
            "---",
            f"code: {code}",
            "tags: [of-intelligence, alert]",
            "---",
            "",
            f"# Alert: {code}",
            "",
        ]
        for a in alerts:
            lines.append(f"- **{a.created_at.isoformat()}** ({a.severity}/{a.status}) — {a.title}")
        files.append(
            ExportedFile(
                relative_path=f"{OBSIDIAN_ROOT}/Alerts/{slug}.md",
                content="\n".join(lines),
            )
        )
    return files


async def _render_mass_messages(session: AsyncSession) -> list[ExportedFile]:
    rows = (
        await session.exec(
            select(OfIntelligenceMassMessage)
            .order_by(OfIntelligenceMassMessage.snapshot_at.desc())
            .limit(50)
        )
    ).all()
    if not rows:
        return []
    lines = [
        "---",
        "tags: [of-intelligence, mass-messages]",
        "---",
        "",
        "# Mass Messages — recent snapshots",
        "",
    ]
    for r in rows:
        lines.append(
            f"- **{r.sent_at.isoformat() if r.sent_at else 'unknown'}** "
            f"acct=`{r.account_source_id or '?'}` "
            f"recipients={r.recipients_count} purchases={r.purchases_count} "
            f"revenue=${(r.revenue_cents or 0) / 100:.2f}"
        )
    return [
        ExportedFile(
            relative_path=f"{OBSIDIAN_ROOT}/Mass Messages/recent.md",
            content="\n".join(lines),
        )
    ]


# ── Memory mirror (writes BusinessMemoryEntry rows for each export) ──────────


async def mirror_export_to_memory(session: AsyncSession, result: ExportResult) -> int:
    """Write a BusinessMemoryEntry per exported file so AI can search it."""
    written = 0
    for f in result.files:
        session.add(
            BusinessMemoryEntry(
                product="of_intelligence",
                kind="obsidian_export",
                title=os.path.basename(f.relative_path),
                body=f.content,
                tags=["obsidian", "export"],
                obsidian_path=f.relative_path,
            )
        )
        written += 1
    if written:
        await session.commit()
    return written


# ── Helpers ──────────────────────────────────────────────────────────────────


def _safe_filename(value: str) -> str:
    keep = "-_."
    cleaned = "".join(c if (c.isalnum() or c in keep) else "-" for c in value).strip("-")
    return cleaned or "untitled"
