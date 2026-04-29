"""Chat Data Import Bridge — parse + persist sample chat data into OFI.

This is the **manual import** path for chat/message text.  It does
**not** call OnlyFans, OnlyMonster, or any external service.  Every
import is operator-initiated, comes from a file or paste-buffer, and
writes only to the local Mission Control database.

Hard guarantees enforced here:
  • No external network calls — module imports nothing that does I/O
    against an external service.
  • No outbound write actions to OnlyFans / OnlyMonster.
  • Message bodies are persisted to `of_intelligence_messages.body` but
    are **never** logged to stdout, file logs, or error responses.
    The logger only emits counts and (where useful) sha256 fingerprints
    of the upload payload.
  • Every persisted row is dedup-keyed by `(source, source_id)` —
    re-uploading the same file leaves the table unchanged.

Supported input formats:
  • `manual_json`  — top-level list of objects, OR object with a
    `messages` key and (optionally) a `chats` key
  • `manual_csv`   — header row + one row per message
  • `paste`        — same shape as `manual_json` (preserved as a separate
    `source_kind` so we can audit how data arrived)
  • `fixture`      — same shape as `manual_json`; used by the in-tree
    test fixture endpoint

Field mapping (input → DB column):

  account_id         → message.account_source_id
  creator_profile_id → (carried in raw_payload only — not enforced)
  fan_id             → message.fan_source_id
  fan_username       → carried into raw_payload
  chatter_id         → message.chatter_source_id
  chatter_name       → carried into raw_payload
  chat_id            → message.chat_source_id
  message_id         → message.source_id (when present)
                       fallback: deterministic SHA-256 of
                       (chat_id, sender_type, timestamp, body)
  sender_type        → message.direction:
                         "fan" / "in"        → "in"
                         "chatter" / "out"   → "out"
                         "creator" / "model" → "out"
  sender_name        → carried into raw_payload
  message_text       → message.body
  timestamp          → message.sent_at  (ISO-8601 or unix seconds)
  price              → message.revenue_cents (when status=purchased)
  purchased / unlocked → carried into raw_payload
  source             → message.source (default `manual_import`)
  raw_payload        → message.raw

Persistence details:
  • A new `of_intelligence_chat_imports` row is created at the start of
    the run and updated with the final counts.
  • Messages are persisted with `import_id` set to the import row's id
    so we can attribute / re-run / delete a batch later.
  • `of_intelligence_chats` rows are upserted (one row per chat_id seen
    in the batch).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable
from uuid import UUID, uuid4

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.time import utcnow
from app.models.of_intelligence import (
    OfIntelligenceChat,
    OfIntelligenceChatImport,
    OfIntelligenceMessage,
)

logger = logging.getLogger(__name__)

# Defensive cap so a runaway upload can't OOM the backend.
MAX_PAYLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_MESSAGES_PER_BATCH = 50_000

DEFAULT_SOURCE = "manual_import"

VALID_SOURCE_KINDS = {"manual_json", "manual_csv", "paste", "fixture"}


# ── Dataclasses returned to API callers ──────────────────────────────────────


@dataclass
class ParsedMessage:
    """Normalised, ready-to-persist representation of one input row."""

    source: str
    source_id: str
    chat_source_id: str | None
    account_source_id: str | None
    fan_source_id: str | None
    chatter_source_id: str | None
    direction: str | None  # "in" | "out" | None
    sent_at: datetime | None
    body: str | None
    revenue_cents: int | None
    raw: dict[str, Any]


@dataclass
class ImportResult:
    import_id: UUID
    label: str | None
    source_kind: str
    status: str
    total_messages_seen: int
    total_chats_seen: int
    messages_inserted: int
    messages_skipped_dup: int
    parse_errors: list[str] = field(default_factory=list)


# ── Public API ───────────────────────────────────────────────────────────────


async def import_chat_payload(
    session: AsyncSession,
    *,
    payload_text: str,
    source_kind: str,
    label: str | None = None,
    triggered_by: str | None = None,
) -> ImportResult:
    """Parse → persist → return summary.  Never raises on parse errors;
    individual bad rows go into `parse_errors`.

    Empty or oversized payloads raise `ValueError` (the API layer
    translates that into a 400/413).
    """
    if source_kind not in VALID_SOURCE_KINDS:
        raise ValueError(f"unknown source_kind: {source_kind}")

    raw_bytes = payload_text.encode("utf-8")
    if not raw_bytes:
        raise ValueError("payload is empty")
    if len(raw_bytes) > MAX_PAYLOAD_BYTES:
        raise ValueError(
            f"payload exceeds {MAX_PAYLOAD_BYTES} bytes " f"({len(raw_bytes)} bytes provided)"
        )
    sha = hashlib.sha256(raw_bytes).hexdigest()

    # Create the import row up front.  Even if parsing blows up halfway
    # through we'll have a record of the attempt.
    import_row = OfIntelligenceChatImport(
        label=label,
        source_kind=source_kind,
        status="running",
        payload_sha256=sha,
        payload_size_bytes=len(raw_bytes),
        started_at=utcnow(),
        triggered_by=triggered_by,
    )
    session.add(import_row)
    await session.commit()
    await session.refresh(import_row)

    parse_errors: list[str] = []
    try:
        if source_kind == "manual_csv":
            parsed = list(_parse_csv(payload_text, parse_errors))
        else:
            parsed = list(_parse_json(payload_text, parse_errors))
    except Exception as exc:  # truly unparseable input
        import_row.status = "error"
        import_row.error = f"parse failed: {type(exc).__name__}"
        import_row.completed_at = utcnow()
        session.add(import_row)
        await session.commit()
        # Deliberately do NOT echo the underlying exception body — could
        # contain raw message text from the upload.
        logger.warning(
            "of_intelligence.chat_import.parse_failed import_id=%s sha=%s err=%s",
            import_row.id,
            sha,
            type(exc).__name__,
        )
        return ImportResult(
            import_id=import_row.id,
            label=label,
            source_kind=source_kind,
            status="error",
            total_messages_seen=0,
            total_chats_seen=0,
            messages_inserted=0,
            messages_skipped_dup=0,
            parse_errors=[type(exc).__name__],
        )

    if len(parsed) > MAX_MESSAGES_PER_BATCH:
        import_row.status = "error"
        import_row.error = (
            f"batch exceeds {MAX_MESSAGES_PER_BATCH} messages ({len(parsed)} provided)"
        )
        import_row.completed_at = utcnow()
        session.add(import_row)
        await session.commit()
        raise ValueError(import_row.error)

    inserted, skipped_dup, chats_seen = await _persist(session, parsed, import_id=import_row.id)

    import_row.total_messages = len(parsed)
    import_row.total_chats = chats_seen
    import_row.messages_inserted = inserted
    import_row.messages_skipped_dup = skipped_dup
    import_row.status = "success" if not parse_errors else "partial" if inserted > 0 else "error"
    if parse_errors:
        # Keep error messages high-level — reasons, not message bodies.
        import_row.error = "; ".join(parse_errors[:10])
    import_row.completed_at = utcnow()
    session.add(import_row)
    await session.commit()
    await session.refresh(import_row)

    logger.info(
        "of_intelligence.chat_import.done import_id=%s sha=%s rows_seen=%s "
        "inserted=%s skipped_dup=%s parse_errors=%s status=%s",
        import_row.id,
        sha,
        len(parsed),
        inserted,
        skipped_dup,
        len(parse_errors),
        import_row.status,
    )

    return ImportResult(
        import_id=import_row.id,
        label=label,
        source_kind=source_kind,
        status=import_row.status,
        total_messages_seen=len(parsed),
        total_chats_seen=chats_seen,
        messages_inserted=inserted,
        messages_skipped_dup=skipped_dup,
        parse_errors=parse_errors,
    )


async def list_imports(
    session: AsyncSession,
    *,
    limit: int = 50,
) -> list[OfIntelligenceChatImport]:
    rows = (
        await session.exec(
            select(OfIntelligenceChatImport)
            .order_by(col(OfIntelligenceChatImport.started_at).desc())
            .limit(limit)
        )
    ).all()
    return list(rows)


async def get_import(session: AsyncSession, import_id: UUID) -> OfIntelligenceChatImport | None:
    return (
        await session.exec(
            select(OfIntelligenceChatImport).where(OfIntelligenceChatImport.id == import_id)
        )
    ).first()


# ── JSON parsing ─────────────────────────────────────────────────────────────


def _parse_json(text: str, parse_errors: list[str]) -> Iterable[ParsedMessage]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        parse_errors.append(f"json: {exc.msg} at line {exc.lineno}")
        return []

    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("messages") or []
        if not isinstance(rows, list):
            parse_errors.append("json: 'messages' must be a list")
            return []
    else:
        parse_errors.append("json: top-level must be a list or object")
        return []

    out: list[ParsedMessage] = []
    for i, raw in enumerate(rows):
        if not isinstance(raw, dict):
            parse_errors.append(f"row {i}: not an object")
            continue
        try:
            out.append(_normalise(raw))
        except _RowParseError as e:
            parse_errors.append(f"row {i}: {e}")
    return out


# ── CSV parsing ──────────────────────────────────────────────────────────────


def _parse_csv(text: str, parse_errors: list[str]) -> Iterable[ParsedMessage]:
    reader = csv.DictReader(io.StringIO(text))
    out: list[ParsedMessage] = []
    for i, row in enumerate(reader):
        if not row:
            continue
        try:
            # Strip empty strings to None so downstream treats them as missing.
            cleaned = {k: (v if v not in ("", None) else None) for k, v in row.items()}
            out.append(_normalise(cleaned))
        except _RowParseError as e:
            parse_errors.append(f"row {i}: {e}")
    return out


# ── Normalisation (one input row → ParsedMessage) ────────────────────────────


class _RowParseError(ValueError):
    pass


_DIRECTION_MAP = {
    "in": "in",
    "fan": "in",
    "subscriber": "in",
    "user": "in",
    "out": "out",
    "chatter": "out",
    "creator": "out",
    "model": "out",
    "agent": "out",
}


def _normalise(raw: dict[str, Any]) -> ParsedMessage:
    body = _coerce_str(raw.get("message_text") or raw.get("body") or raw.get("text"))
    if body is None:
        raise _RowParseError("missing message_text")

    chat_id = _coerce_str(raw.get("chat_id") or raw.get("chat"))
    sender_type = _coerce_str(raw.get("sender_type") or raw.get("direction") or raw.get("from"))
    direction: str | None = None
    if sender_type:
        direction = _DIRECTION_MAP.get(sender_type.lower())

    sent_at = _coerce_dt(raw.get("timestamp") or raw.get("sent_at") or raw.get("ts"))
    price_cents = _coerce_price_cents(raw.get("price") or raw.get("price_cents"))
    purchased_or_unlocked = _coerce_bool(
        raw.get("purchased") or raw.get("unlocked") or raw.get("paid")
    )

    message_id = _coerce_str(raw.get("message_id") or raw.get("id"))
    if not message_id:
        # Deterministic dedup key: same chat + sender + timestamp + body
        # always hashes to the same source_id, so re-imports collapse.
        h = hashlib.sha256()
        h.update((chat_id or "").encode("utf-8"))
        h.update(b"|")
        h.update((sender_type or "").encode("utf-8"))
        h.update(b"|")
        h.update((sent_at.isoformat() if sent_at else "").encode("utf-8"))
        h.update(b"|")
        h.update(body.encode("utf-8"))
        message_id = "manual:" + h.hexdigest()[:24]

    source = _coerce_str(raw.get("source")) or DEFAULT_SOURCE

    # Anything we don't have a column for travels via raw — never logged.
    raw_payload = {k: v for k, v in raw.items() if v is not None}
    if purchased_or_unlocked is not None:
        raw_payload["purchased_or_unlocked"] = purchased_or_unlocked

    return ParsedMessage(
        source=source,
        source_id=message_id,
        chat_source_id=chat_id,
        account_source_id=_coerce_str(raw.get("account_id") or raw.get("account_source_id")),
        fan_source_id=_coerce_str(raw.get("fan_id") or raw.get("fan_source_id")),
        chatter_source_id=_coerce_str(raw.get("chatter_id") or raw.get("chatter_source_id")),
        direction=direction,
        sent_at=sent_at,
        body=body,
        revenue_cents=(
            price_cents
            if purchased_or_unlocked
            else (price_cents if price_cents is not None and price_cents > 0 else None)
        ),
        raw=raw_payload,
    )


# ── Persistence ──────────────────────────────────────────────────────────────


async def _persist(
    session: AsyncSession,
    parsed: list[ParsedMessage],
    *,
    import_id: UUID,
) -> tuple[int, int, int]:
    """Insert parsed messages, dedup by `(source, source_id)`.

    Returns `(messages_inserted, messages_skipped_dup, distinct_chats_seen)`.
    """
    if not parsed:
        return 0, 0, 0

    # Snapshot existing source_ids for each `source` we're touching so the
    # dedup is one query per source instead of N.
    sources = {m.source for m in parsed}
    existing: set[tuple[str, str]] = set()
    for src in sources:
        rows = (
            await session.exec(
                select(OfIntelligenceMessage.source, OfIntelligenceMessage.source_id).where(
                    OfIntelligenceMessage.source == src
                )
            )
        ).all()
        for row in rows:
            existing.add((row[0], row[1]))

    inserted = skipped = 0
    chats_seen: set[str] = set()
    chat_account_ids: dict[str, str | None] = {}
    chat_fan_ids: dict[str, str | None] = {}
    chat_last_msg_ts: dict[str, datetime] = {}

    for m in parsed:
        if m.chat_source_id:
            chats_seen.add(m.chat_source_id)
            chat_account_ids.setdefault(m.chat_source_id, m.account_source_id)
            chat_fan_ids.setdefault(m.chat_source_id, m.fan_source_id)
            if m.sent_at and (
                m.chat_source_id not in chat_last_msg_ts
                or m.sent_at > chat_last_msg_ts[m.chat_source_id]
            ):
                chat_last_msg_ts[m.chat_source_id] = m.sent_at
        key = (m.source, m.source_id)
        if key in existing:
            skipped += 1
            continue
        existing.add(key)
        session.add(
            OfIntelligenceMessage(
                source=m.source,
                source_id=m.source_id,
                chat_source_id=m.chat_source_id,
                account_source_id=m.account_source_id,
                fan_source_id=m.fan_source_id,
                chatter_source_id=m.chatter_source_id,
                direction=m.direction,
                sent_at=m.sent_at,
                body=m.body,
                revenue_cents=m.revenue_cents,
                raw=m.raw,
                import_id=import_id,
            )
        )
        inserted += 1

    # Upsert chat rows so the chats table reflects whatever we just imported.
    if chats_seen:
        await _upsert_chats(
            session,
            sources=sources,
            chat_ids=chats_seen,
            account_for_chat=chat_account_ids,
            fan_for_chat=chat_fan_ids,
            last_msg_ts=chat_last_msg_ts,
        )

    await session.commit()
    return inserted, skipped, len(chats_seen)


async def _upsert_chats(
    session: AsyncSession,
    *,
    sources: set[str],
    chat_ids: set[str],
    account_for_chat: dict[str, str | None],
    fan_for_chat: dict[str, str | None],
    last_msg_ts: dict[str, datetime],
) -> None:
    """One-shot upsert of `(source, source_id)` chat rows we touched."""
    # We could use INSERT ... ON CONFLICT here, but keeping it
    # source-agnostic by going through the ORM lookup-then-update path
    # so SQLite tests work too.
    for source in sources:
        existing = {
            row.source_id: row
            for row in (
                await session.exec(
                    select(OfIntelligenceChat).where(OfIntelligenceChat.source == source)
                )
            ).all()
        }
        for chat_id in chat_ids:
            row = existing.get(chat_id)
            if row is None:
                session.add(
                    OfIntelligenceChat(
                        source=source,
                        source_id=chat_id,
                        account_source_id=account_for_chat.get(chat_id),
                        fan_source_id=fan_for_chat.get(chat_id),
                        last_message_at=last_msg_ts.get(chat_id),
                    )
                )
            else:
                # Patch only fields we have new data for.
                if row.account_source_id is None and account_for_chat.get(chat_id):
                    row.account_source_id = account_for_chat[chat_id]
                if row.fan_source_id is None and fan_for_chat.get(chat_id):
                    row.fan_source_id = fan_for_chat[chat_id]
                ts = last_msg_ts.get(chat_id)
                if ts and (row.last_message_at is None or ts > row.last_message_at):
                    row.last_message_at = ts
                row.last_synced_at = utcnow()
                session.add(row)


# ── Coercion helpers (mirror sync._coerce_* but kept local) ──────────────────


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    if isinstance(value, (int, float)):
        try:
            return datetime.utcfromtimestamp(float(value))
        except (OverflowError, ValueError, OSError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # Try ISO-8601 first (with or without trailing Z).
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            # Fallback: integer-seconds-as-string.
            try:
                return datetime.utcfromtimestamp(float(text))
            except (ValueError, OverflowError):
                return None
        return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed
    return None


def _coerce_price_cents(value: Any) -> int | None:
    """Accept dollars ('5.00', 5.0) or cents ('500', 500) — assumes
    anything ≤ 1000 with a decimal point is dollars; otherwise cents.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            return int(round(value * 100))
        return int(value)
    if isinstance(value, str):
        text = value.strip().lstrip("$")
        if not text:
            return None
        try:
            if "." in text:
                return int(round(float(text) * 100))
            return int(text)
        except ValueError:
            return None
    return None


def _coerce_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "purchased", "unlocked", "paid"}:
            return True
        if text in {"0", "false", "no", "n", ""}:
            return False
    return None


# ── Generate a uniquish import id helper (imported by tests) ─────────────────


def new_import_id() -> UUID:
    return uuid4()
