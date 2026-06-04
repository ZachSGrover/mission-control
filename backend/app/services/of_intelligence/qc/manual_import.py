"""Manual / sanitized Daily-QC import — offline, read-only, no live connectors.

This module lets an operator run the *existing* Daily-QC detectors against
**sanitized sample data** (CSV or JSON fixtures) without connecting any real
OnlyFans or OnlyMonster account.  It exists so the agency can get QC value
*today* while live read-only connectors are still being prepared.

What it does
------------
1. Parse a sanitized batch (JSON or CSV) of message-level records that use
   *aliases only* — no real handles, names, cookies, sessions, or tokens.
2. Load those records into the **existing** OF-Intelligence tables
   (``of_intelligence_*``) in whatever ``AsyncSession`` it's handed — in
   practice an in-memory SQLite DB for the dry-run script and tests.
3. Run the **existing** message detectors (``scan_critical_qc``) and the
   **existing** aggregate evaluator (``evaluate_ingestion``) over the loaded
   data, plus two lightweight report-only passes (whale/VIP rollup and
   content-request detection) that don't warrant their own DB detector yet.
4. Assemble a single privacy-safe ``DailyQcReport`` dict the dashboard/API
   can render and a human can read fast.

Hard safety rules baked in
--------------------------
  • NEVER opens a network connection.  NEVER calls an external API.
  • NEVER reads or writes real-account credentials.  A guard rejects any
    record that carries credential-like keys (password/cookie/token/...).
  • Message excerpts are capped (``EXCERPT_CAP``) on load, and any excerpt
    that reaches the report is re-capped to ``REPORT_EXCERPT_CAP``.
  • The report is the only thing meant for human eyes; it carries aliases,
    counts, generic signal phrases, and short capped excerpts — never a raw
    body, never a real identifier.
  • Re-running the same batch is idempotent: message ``source_id`` is
    deterministic, and existing rows are skipped instead of duplicated.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.logging import get_logger
from app.core.time import utcnow
from app.models.of_intelligence import (
    OfIntelligenceAccount,
    OfIntelligenceChat,
    OfIntelligenceChatter,
    OfIntelligenceFan,
    OfIntelligenceMessage,
)
from app.services.of_intelligence.qc.detectors import scan_critical_qc
from app.services.of_intelligence.qc.ingestion.base import (
    AccountMetrics,
    IngestionResult,
    SourceMode,
)
from app.services.of_intelligence.qc.ingestion_evaluator import evaluate_ingestion

logger = get_logger(__name__)

# Manual imports are tagged with their own ``source`` so they are trivially
# distinguishable from (and never confused with) real connector data.
SOURCE_MANUAL = "manual_import"

# Excerpt caps — bodies are truncated on load; report excerpts are shorter.
EXCERPT_CAP = 280
REPORT_EXCERPT_CAP = 100

# Whale/VIP: a fan whose spend within the batch meets this bar is flagged.
WHALE_BATCH_SPEND_CENTS = 10_000  # $100
WHALE_TOP_N = 5

# Lookback used when scanning loaded fixture messages.  Fixtures stamp recent
# timestamps; 72h is generous so a whole sample day is always in-window.
SCAN_LOOKBACK_HOURS = 72

# Credential-like keys that must NEVER appear in a sanitized import.  Their
# presence means someone pasted real account data — we refuse the whole batch.
_FORBIDDEN_KEYS = {
    "password",
    "passwd",
    "secret",
    "cookie",
    "cookies",
    "session",
    "session_id",
    "token",
    "access_token",
    "auth",
    "authorization",
    "credential",
    "credentials",
    "api_key",
    "apikey",
    "private_key",
}

# Content-request detection — fan asking for specific/custom content.  This is
# report-only (not a DB alert) and deliberately targeted to limit false hits.
_CONTENT_REQUEST_TERMS = [
    r"can\s+you\s+(?:make|do|send|record|film)",
    r"could\s+you\s+(?:make|do|send|record|film)",
    r"custom(?:\s+(?:content|video|vid|clip|pic|photo|set|request))?",
    r"voice\s+(?:note|message|memo)",
    r"video\s+of",
    r"vid\s+of",
    r"pic(?:ture)?s?\s+of",
    r"photos?\s+of",
    r"do\s+you\s+(?:have|sell|offer)\s+(?:any\s+)?(?:content|vids?|videos?|pics?|customs?)",
    r"(?:your|the)\s+menu",
    r"go\s+live",
]
_CONTENT_REQUEST_RX = re.compile(r"\b(?:" + "|".join(_CONTENT_REQUEST_TERMS) + r")", re.IGNORECASE)

# How detector codes map into human-facing report sections.
_CHATTER_QUALITY_CODES = {"rude_reply"}
_MISSED_SALES_CODES = {"missed_buying_signal", "weak_sales_handling"}
_SAFETY_PRIVACY_CODES = {
    "refund_risk",
    "banned_content_risk",
    "serious_escalation_risk",
}


# ── Parsing ──────────────────────────────────────────────────────────────────


class ManualImportError(ValueError):
    """Raised when a batch is malformed or contains forbidden data."""


@dataclass(frozen=True)
class ManualMessageRecord:
    """One sanitized message row.  Aliases only — never real identifiers."""

    creator_alias: str
    direction: str  # "in" (fan→chatter) | "out" (chatter→fan)
    fan_alias: str | None = None
    chatter_alias: str | None = None
    timestamp: datetime | None = None
    text: str | None = None  # sanitized excerpt, capped on load
    price_cents: int = 0
    tip_cents: int = 0
    purchase_cents: int = 0
    reply_minutes: int | None = None
    notes: str | None = None
    tags: tuple[str, ...] = ()

    @property
    def revenue_cents(self) -> int:
        return int(self.price_cents) + int(self.tip_cents) + int(self.purchase_cents)


@dataclass(frozen=True)
class ManualImportBatch:
    """A parsed batch: records plus optional per-creator revenue baselines."""

    records: tuple[ManualMessageRecord, ...]
    account_baselines_cents: Mapping[str, int] = field(default_factory=dict)


def _cap(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = str(text).replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _assert_no_forbidden_keys(obj: Mapping[str, Any]) -> None:
    lowered = {str(k).strip().lower() for k in obj}
    bad = lowered & _FORBIDDEN_KEYS
    if bad:
        # Do NOT echo the offending values — only the key names.
        raise ManualImportError(
            "refusing import: credential-like field(s) present "
            f"({', '.join(sorted(bad))}); imports must be sanitized aliases only"
        )


def _coerce_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, bool):  # guard against True→1 surprises
        return 0
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _coerce_direction(value: Any) -> str:
    v = str(value or "").strip().lower()
    if v in {"in", "inbound", "fan", "fan_to_chatter", "received"}:
        return "in"
    if v in {"out", "outbound", "chatter", "chatter_to_fan", "sent"}:
        return "out"
    raise ManualImportError(f"invalid direction: {value!r} (use 'in' or 'out')")


def _coerce_ts(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    # Normalize to naive-UTC to match the existing models' utcnow() usage.
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz=None).replace(tzinfo=None)
    return dt


def _coerce_tags(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        parts = re.split(r"[;,|]", value)
    elif isinstance(value, Iterable):
        parts = list(value)
    else:
        return ()
    return tuple(p for p in (str(x).strip() for x in parts) if p)


def _record_from_dict(obj: Mapping[str, Any]) -> ManualMessageRecord:
    _assert_no_forbidden_keys(obj)
    creator = str(
        obj.get("creator_alias")
        or obj.get("creator")
        or obj.get("model")
        or obj.get("account")
        or ""
    ).strip()
    if not creator:
        raise ManualImportError("each record needs a creator_alias/model alias")
    return ManualMessageRecord(
        creator_alias=creator,
        direction=_coerce_direction(obj.get("direction")),
        fan_alias=(str(obj.get("fan_alias") or obj.get("fan") or "").strip() or None),
        chatter_alias=(str(obj.get("chatter_alias") or obj.get("chatter") or "").strip() or None),
        timestamp=_coerce_ts(obj.get("timestamp") or obj.get("sent_at") or obj.get("time")),
        text=_cap(obj.get("text") or obj.get("message") or obj.get("excerpt") or obj.get("body"),
                  EXCERPT_CAP),
        price_cents=_coerce_int(obj.get("price_cents", obj.get("price"))),
        tip_cents=_coerce_int(obj.get("tip_cents", obj.get("tip"))),
        purchase_cents=_coerce_int(obj.get("purchase_cents", obj.get("purchase"))),
        reply_minutes=(
            None if obj.get("reply_minutes") in (None, "") else _coerce_int(obj.get("reply_minutes"))
        ),
        notes=_cap(obj.get("notes"), EXCERPT_CAP),
        tags=_coerce_tags(obj.get("tags")),
    )


def parse_records(rows: Iterable[Mapping[str, Any]]) -> list[ManualMessageRecord]:
    return [_record_from_dict(r) for r in rows]


def parse_json(text: str) -> ManualImportBatch:
    """Parse a JSON batch.

    Accepts either a bare list of records or an object of the form::

        {"records": [...], "account_baselines_cents": {"luna_demo": 22000}}
    """
    data = json.loads(text)
    baselines: dict[str, int] = {}
    if isinstance(data, Mapping):
        rows = data.get("records", [])
        raw_baselines = data.get("account_baselines_cents", {}) or {}
        baselines = {str(k): _coerce_int(v) for k, v in raw_baselines.items()}
    elif isinstance(data, list):
        rows = data
    else:
        raise ManualImportError("JSON batch must be a list or an object with 'records'")
    return ManualImportBatch(records=tuple(parse_records(rows)), account_baselines_cents=baselines)


def parse_csv(text: str) -> ManualImportBatch:
    """Parse a CSV batch.  Header row defines field names (see _record_from_dict)."""
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(r) for r in reader]
    return ManualImportBatch(records=tuple(parse_records(rows)))


# ── Loading into the existing models ─────────────────────────────────────────


@dataclass(frozen=True)
class LoadSummary:
    messages_loaded: int
    messages_skipped_duplicate: int
    accounts: int
    chatters: int
    fans: int


def _alias_source_id(prefix: str, alias: str) -> str:
    return f"{prefix}:{alias}"


def _message_source_id(rec: ManualMessageRecord, ts: datetime) -> str:
    """Deterministic id so re-importing the same row dedupes."""
    basis = "|".join(
        [
            rec.creator_alias,
            rec.fan_alias or "",
            rec.chatter_alias or "",
            rec.direction,
            ts.isoformat(),
            rec.text or "",
            str(rec.revenue_cents),
        ]
    )
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    return f"manual:{digest}"


async def load_batch(session: AsyncSession, batch: ManualImportBatch) -> LoadSummary:
    """Upsert aliases and append messages into the existing OFI tables.

    Idempotent: messages with an already-present ``source_id`` are skipped.
    """
    seen_accounts: set[str] = set()
    seen_chatters: set[str] = set()
    seen_fans: set[str] = set()
    seen_chats: set[str] = set()

    loaded = 0
    skipped = 0
    base_ts = utcnow()

    for idx, rec in enumerate(batch.records):
        ts = rec.timestamp or (base_ts - timedelta(minutes=len(batch.records) - idx))

        acct_sid = _alias_source_id("creator", rec.creator_alias)
        if acct_sid not in seen_accounts:
            if not await _exists(session, OfIntelligenceAccount, acct_sid):
                session.add(
                    OfIntelligenceAccount(
                        source=SOURCE_MANUAL,
                        source_id=acct_sid,
                        username=rec.creator_alias,
                        display_name=rec.creator_alias,
                        access_status="active",
                    )
                )
            seen_accounts.add(acct_sid)

        chatter_sid = None
        if rec.chatter_alias:
            chatter_sid = _alias_source_id("chatter", rec.chatter_alias)
            if chatter_sid not in seen_chatters:
                if not await _exists(session, OfIntelligenceChatter, chatter_sid):
                    session.add(
                        OfIntelligenceChatter(
                            source=SOURCE_MANUAL,
                            source_id=chatter_sid,
                            name=rec.chatter_alias,
                            active=True,
                        )
                    )
                seen_chatters.add(chatter_sid)

        fan_sid = None
        if rec.fan_alias:
            fan_sid = _alias_source_id("fan", rec.fan_alias)
            if fan_sid not in seen_fans:
                if not await _exists(session, OfIntelligenceFan, fan_sid):
                    session.add(
                        OfIntelligenceFan(
                            source=SOURCE_MANUAL,
                            source_id=fan_sid,
                            account_source_id=acct_sid,
                            username=rec.fan_alias,
                        )
                    )
                seen_fans.add(fan_sid)

        chat_sid = None
        if fan_sid:
            chat_sid = f"chat:{rec.creator_alias}:{rec.fan_alias}"
            if chat_sid not in seen_chats:
                if not await _exists(session, OfIntelligenceChat, chat_sid):
                    session.add(
                        OfIntelligenceChat(
                            source=SOURCE_MANUAL,
                            source_id=chat_sid,
                            account_source_id=acct_sid,
                            fan_source_id=fan_sid,
                        )
                    )
                seen_chats.add(chat_sid)

        msg_sid = _message_source_id(rec, ts)
        if await _exists(session, OfIntelligenceMessage, msg_sid):
            skipped += 1
            continue
        session.add(
            OfIntelligenceMessage(
                source=SOURCE_MANUAL,
                source_id=msg_sid,
                chat_source_id=chat_sid,
                account_source_id=acct_sid,
                fan_source_id=fan_sid,
                chatter_source_id=chatter_sid,
                direction=rec.direction,
                sent_at=ts,
                body=rec.text,
                revenue_cents=rec.revenue_cents or None,
            )
        )
        loaded += 1

    await session.commit()
    summary = LoadSummary(
        messages_loaded=loaded,
        messages_skipped_duplicate=skipped,
        accounts=len(seen_accounts),
        chatters=len(seen_chatters),
        fans=len(seen_fans),
    )
    logger.info(
        "of_qc.manual_import.load loaded=%s skipped_dup=%s accounts=%s",
        loaded,
        skipped,
        len(seen_accounts),
    )
    return summary


async def _exists(session: AsyncSession, model: Any, source_id: str) -> bool:
    found = (
        await session.exec(
            select(model).where(
                col(model.source) == SOURCE_MANUAL,
                col(model.source_id) == source_id,
            )
        )
    ).first()
    return found is not None


# ── Report assembly ──────────────────────────────────────────────────────────


async def _build_account_metrics(session: AsyncSession, batch: ManualImportBatch) -> IngestionResult:
    """Aggregate loaded messages into per-account ``AccountMetrics``."""
    rows = (
        await session.exec(
            select(OfIntelligenceMessage).where(col(OfIntelligenceMessage.source) == SOURCE_MANUAL)
        )
    ).all()

    by_acct: dict[str, list[OfIntelligenceMessage]] = defaultdict(list)
    for r in rows:
        if r.account_source_id:
            by_acct[r.account_source_id].append(r)

    label_by_sid = await _account_labels(session, list(by_acct))
    now = utcnow()
    accounts: list[AccountMetrics] = []
    for acct_sid, msgs in by_acct.items():
        label = label_by_sid.get(acct_sid) or acct_sid
        revenue = sum(m.revenue_cents or 0 for m in msgs)
        paid = sum(1 for m in msgs if (m.revenue_cents or 0) > 0)
        baseline = int(batch.account_baselines_cents.get(label, 0))
        accounts.append(
            AccountMetrics(
                account_id=acct_sid,
                account_label=label,
                period_start=now - timedelta(hours=24),
                period_end=now,
                revenue_cents=revenue,
                previous_revenue_cents=baseline,
                message_count=len(msgs),
                paid_message_count=paid,
                purchase_count=paid,
                operator_id=None,
                source=SourceMode.SYNTHETIC.value,  # safe label; manual is synthetic-class
                source_confidence="medium",
                last_synced_at=now,
                has_recent_sync_failure=False,
            )
        )
    return IngestionResult(
        source_mode=SourceMode.SYNTHETIC,
        source_confidence="medium",
        safe_mode=True,
        accounts=accounts,
        skipped_reason=None,
        notes=["manual sanitized import; no real data"],
    )


async def _account_labels(session: AsyncSession, source_ids: list[str]) -> dict[str, str | None]:
    if not source_ids:
        return {}
    rows = (
        await session.exec(
            select(OfIntelligenceAccount).where(
                col(OfIntelligenceAccount.source) == SOURCE_MANUAL,
                col(OfIntelligenceAccount.source_id).in_(set(source_ids)),
            )
        )
    ).all()
    return {r.source_id: r.username for r in rows}


async def _whale_rollup(session: AsyncSession) -> list[dict[str, Any]]:
    """Report-only whale/VIP rollup from per-fan spend within the batch."""
    rows = (
        await session.exec(
            select(OfIntelligenceMessage).where(col(OfIntelligenceMessage.source) == SOURCE_MANUAL)
        )
    ).all()
    spend: dict[tuple[str | None, str | None], int] = defaultdict(int)
    msgs: dict[tuple[str | None, str | None], int] = defaultdict(int)
    for r in rows:
        if not r.fan_source_id:
            continue
        key = (r.account_source_id, r.fan_source_id)
        spend[key] += r.revenue_cents or 0
        msgs[key] += 1

    fan_labels = await _fan_labels(session, [f for (_, f) in spend])
    acct_labels = await _account_labels(session, [a for (a, _) in spend if a])

    ranked = sorted(spend.items(), key=lambda kv: kv[1], reverse=True)
    out: list[dict[str, Any]] = []
    for i, ((acct_sid, fan_sid), cents) in enumerate(ranked):
        is_whale = cents >= WHALE_BATCH_SPEND_CENTS
        if not is_whale and i >= WHALE_TOP_N:
            break
        out.append(
            {
                "fan_alias": fan_labels.get(fan_sid) or "fan",
                "creator": acct_labels.get(acct_sid) or acct_sid,
                "batch_spend_cents": cents,
                "messages": msgs[(acct_sid, fan_sid)],
                "tier": "whale" if is_whale else "watch",
            }
        )
    return out


async def _fan_labels(session: AsyncSession, source_ids: list[str | None]) -> dict[str, str | None]:
    ids = [s for s in source_ids if s]
    if not ids:
        return {}
    rows = (
        await session.exec(
            select(OfIntelligenceFan).where(
                col(OfIntelligenceFan.source) == SOURCE_MANUAL,
                col(OfIntelligenceFan.source_id).in_(set(ids)),
            )
        )
    ).all()
    return {r.source_id: r.username for r in rows}


async def _content_requests(session: AsyncSession) -> list[dict[str, Any]]:
    """Report-only content-request detection over inbound messages."""
    rows = (
        await session.exec(
            select(OfIntelligenceMessage).where(
                col(OfIntelligenceMessage.source) == SOURCE_MANUAL,
                col(OfIntelligenceMessage.direction) == "in",
                col(OfIntelligenceMessage.body).is_not(None),
            )
        )
    ).all()
    acct_labels = await _account_labels(session, [r.account_source_id for r in rows if r.account_source_id])
    fan_labels = await _fan_labels(session, [r.fan_source_id for r in rows])
    out: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for r in rows:
        body = r.body or ""
        if not _CONTENT_REQUEST_RX.search(body):
            continue
        key = (r.account_source_id, r.fan_source_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "creator": acct_labels.get(r.account_source_id) or r.account_source_id,
                "fan_alias": fan_labels.get(r.fan_source_id) or "fan",
                "signal": "fan requested specific/custom content",
                "safe_excerpt": _cap(body, REPORT_EXCERPT_CAP),
            }
        )
    return out


def _summarize(report: dict[str, Any]) -> str:
    c = report["counts"]
    return (
        f"{c['messages_processed']} messages • {c['findings_total']} findings across "
        f"{c['accounts']} creator(s) and {c['chatters']} chatter(s): "
        f"{len(report['chatter_quality'])} chatter-quality, "
        f"{len(report['missed_sales'])} missed-sales, "
        f"{len(report['whale_vip'])} VIP/whale, "
        f"{len(report['content_requests'])} content-requests, "
        f"{len(report['revenue_warnings'])} revenue, "
        f"{len(report['safety_privacy'])} safety/privacy."
    )


def _recommended_actions(report: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if report["safety_privacy"]:
        actions.append("Review safety/privacy flags first — refund, policy, or escalation risk.")
    if report["missed_sales"]:
        actions.append("Coach chatters on the flagged missed-sales conversations.")
    if report["whale_vip"]:
        actions.append("Assign your best chatter to the VIP/whale watchlist.")
    if report["content_requests"]:
        actions.append("Route content requests to the creator content queue.")
    if report["revenue_warnings"]:
        actions.append("Investigate revenue drops against the prior baseline.")
    if not actions:
        actions.append("No action needed — all sampled accounts look healthy.")
    return actions


async def build_manual_qc_report(session: AsyncSession, batch: ManualImportBatch) -> dict[str, Any]:
    """Run existing detectors over loaded manual data → privacy-safe report dict."""
    candidates = await scan_critical_qc(session, lookback_hours=SCAN_LOOKBACK_HOURS)
    ingestion = await _build_account_metrics(session, batch)
    evaluation = evaluate_ingestion(ingestion)

    chatter_quality: list[dict[str, Any]] = []
    missed_sales: list[dict[str, Any]] = []
    safety_privacy: list[dict[str, Any]] = []
    by_creator: dict[str, int] = defaultdict(int)
    by_chatter: dict[str, int] = defaultdict(int)

    for cand in candidates:
        item = {
            "creator": cand.account_username or cand.account_source_id,
            "chatter": cand.chatter_name,
            "code": cand.code,
            "severity": cand.severity,
            "signal": cand.detection_phrase,
        }
        if cand.account_username:
            by_creator[cand.account_username] += 1
        if cand.chatter_name:
            by_chatter[cand.chatter_name] += 1
        if cand.code in _CHATTER_QUALITY_CODES:
            chatter_quality.append(item)
        elif cand.code in _MISSED_SALES_CODES:
            missed_sales.append(item)
        elif cand.code in _SAFETY_PRIVACY_CODES:
            safety_privacy.append(item)

    revenue_warnings = [
        {
            "creator": f.account_label or f.account_id,
            "code": f.code,
            "severity": f.severity,
            "signal": f.signal,
        }
        for f in evaluation.findings
    ]

    whale_vip = await _whale_rollup(session)
    content_requests = await _content_requests(session)

    findings_total = (
        len(chatter_quality)
        + len(missed_sales)
        + len(safety_privacy)
        + len(revenue_warnings)
        + len(content_requests)
    )

    report: dict[str, Any] = {
        "generated_for": "manual_import",
        "safe_mode": True,
        "live_connection": False,
        "window": {
            "start": ingestion.accounts[0].period_start.isoformat() if ingestion.accounts else None,
            "end": ingestion.accounts[0].period_end.isoformat() if ingestion.accounts else None,
        },
        "counts": {
            "messages_processed": len(batch.records),
            "accounts": evaluation.accounts_checked,
            "chatters": len({r.chatter_alias for r in batch.records if r.chatter_alias}),
            "findings_total": findings_total,
        },
        "chatter_quality": chatter_quality,
        "missed_sales": missed_sales,
        "whale_vip": whale_vip,
        "content_requests": content_requests,
        "revenue_warnings": revenue_warnings,
        "safety_privacy": safety_privacy,
        "by_creator": dict(by_creator),
        "by_chatter": dict(by_chatter),
    }
    report["summary"] = _summarize(report)
    report["recommended_actions"] = _recommended_actions(report)
    return report


async def run_manual_import(session: AsyncSession, batch: ManualImportBatch) -> dict[str, Any]:
    """Convenience: load a batch then build its report.  Returns the report dict
    with a ``load`` block describing what was ingested."""
    summary = await load_batch(session, batch)
    report = await build_manual_qc_report(session, batch)
    report["load"] = {
        "messages_loaded": summary.messages_loaded,
        "messages_skipped_duplicate": summary.messages_skipped_duplicate,
        "accounts": summary.accounts,
        "chatters": summary.chatters,
        "fans": summary.fans,
    }
    return report
