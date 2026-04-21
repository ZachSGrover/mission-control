"""
agent_executions — append-only execution record for complex-bot runs.

Each invoke of an agent writes one JSON object per line to
  ~/.mission-control/executions.jsonl

Records are small and persistent — survive backend restarts.  File rotates at
~5 MB (lazy; checked on append).  Queries walk the file backwards for recent
records and stop early once `limit` is reached, so this scales to tens of
thousands of records without any DB overhead.

If you later want Postgres-backed history, swap _append/_tail and keep the
public API unchanged.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock

__all__ = ["ExecutionRecord", "record", "recent", "by_agent"]

_DATA_DIR = Path(os.getenv("MC_DATA_DIR", str(Path.home() / ".mission-control")))
_LOG_PATH = _DATA_DIR / "executions.jsonl"
_ROTATE_AT_BYTES = 5 * 1024 * 1024
_lock = Lock()


@dataclass
class ExecutionRecord:
    id:           str
    agent_id:     str
    agent_name:   str
    source:       str                  # "telegram" | "discord" | "ui" | "task" | …
    prompt:       str
    reply:        str
    provider:     str                  # "anthropic" | "openai" | "none"
    status:       str                  # "ok" | "error" | "timeout"
    error:        str | None
    response_ms:  float
    attempts:     int
    correlation_id: str | None
    tokens_in:    int | None
    tokens_out:   int | None
    timestamp:    float
    node_id:      str = ""             # which Mission Control node handled it


def _ensure_path() -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _LOG_PATH.exists():
        _LOG_PATH.touch()


def _rotate_if_large() -> None:
    try:
        if _LOG_PATH.stat().st_size > _ROTATE_AT_BYTES:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            _LOG_PATH.rename(_LOG_PATH.with_name(f"executions.{stamp}.jsonl"))
            _LOG_PATH.touch()
    except FileNotFoundError:
        _LOG_PATH.touch()


def record(
    agent_id: str,
    agent_name: str,
    source: str,
    prompt: str,
    reply: str,
    provider: str,
    status: str = "ok",
    error: str | None = None,
    response_ms: float = 0.0,
    attempts: int = 1,
    correlation_id: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> ExecutionRecord:
    # Lazy import to avoid a hard cycle if node_identity is missing in tests.
    try:
        from app.core.node_identity import node_id as _nid
        node = _nid()
    except Exception:
        node = ""
    rec = ExecutionRecord(
        id=uuid.uuid4().hex[:16],
        agent_id=agent_id,
        agent_name=agent_name,
        source=source,
        prompt=prompt[:4000],
        reply=reply[:4000],
        provider=provider,
        status=status,
        error=(error[:500] if error else None),
        response_ms=float(response_ms),
        attempts=int(attempts),
        correlation_id=correlation_id,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        timestamp=time.time(),
        node_id=node,
    )
    with _lock:
        _ensure_path()
        _rotate_if_large()
        with _LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
    return rec


def _iter_reverse() -> list[ExecutionRecord]:
    """Load all current-file records in reverse chronological order."""
    _ensure_path()
    with _LOG_PATH.open("r", encoding="utf-8") as fh:
        lines = fh.readlines()
    out: list[ExecutionRecord] = []
    valid = {f for f in ExecutionRecord.__dataclass_fields__}
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
            if not isinstance(parsed, dict):
                continue
            clean = {k: v for k, v in parsed.items() if k in valid}
            clean.setdefault("node_id", "")
            out.append(ExecutionRecord(**clean))
        except Exception:
            continue
    return out


def recent(limit: int = 50) -> list[ExecutionRecord]:
    return _iter_reverse()[:limit]


def by_agent(agent_id: str, limit: int = 50) -> list[ExecutionRecord]:
    out: list[ExecutionRecord] = []
    for r in _iter_reverse():
        if r.agent_id == agent_id:
            out.append(r)
            if len(out) >= limit:
                break
    return out
