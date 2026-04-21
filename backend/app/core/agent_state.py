"""
agent_state — per-agent persistent KV scratchpad.

Purpose: complex bots need to remember small facts across invocations
(current goal, last_processed_id, rate-limit counters, campaign handle, etc.)
without spinning up the full ActivityEvent / board-memory pipeline.

State lives at ~/.mission-control/agent_state/<agent_id>.json.  Reads and
writes are atomic; concurrent writes are serialized per agent.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

__all__ = ["get_state", "set_state", "merge_state", "clear_state"]

_DATA_DIR = Path(os.getenv("MC_DATA_DIR", str(Path.home() / ".mission-control")))
_STATE_DIR = _DATA_DIR / "agent_state"
_MAX_SIZE_BYTES = 64 * 1024      # 64 KB per agent — enough for many bots, caps blow-ups

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock_for(agent_id: str) -> threading.RLock:
    with _locks_guard:
        lock = _locks.get(agent_id)
        if lock is None:
            lock = threading.RLock()
            _locks[agent_id] = lock
        return lock


def _path_for(agent_id: str) -> Path:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Basic sanitization — agent IDs are 12-hex from uuid already, but belt-and-braces.
    safe = "".join(c for c in agent_id if c.isalnum() or c in ("-", "_"))[:64]
    return _STATE_DIR / f"{safe}.json"


def get_state(agent_id: str) -> dict[str, Any]:
    path = _path_for(agent_id)
    if not path.exists():
        return {}
    with _lock_for(agent_id):
        try:
            return json.loads(path.read_text()) or {}
        except Exception:
            return {}


def set_state(agent_id: str, state: dict[str, Any]) -> dict[str, Any]:
    """Replace the full state dict."""
    serialized = json.dumps(state, ensure_ascii=False, indent=2)
    if len(serialized.encode("utf-8")) > _MAX_SIZE_BYTES:
        raise ValueError(f"agent state exceeds {_MAX_SIZE_BYTES} bytes")
    path = _path_for(agent_id)
    with _lock_for(agent_id):
        tmp = path.with_suffix(".tmp")
        tmp.write_text(serialized)
        tmp.replace(path)
    return state


def merge_state(agent_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge patch into existing state."""
    with _lock_for(agent_id):
        current = get_state(agent_id)
        current.update(patch)
        return set_state(agent_id, current)


def clear_state(agent_id: str) -> None:
    path = _path_for(agent_id)
    with _lock_for(agent_id):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
