"""
node_identity — stable identifier for this Mission Control node.

Reads ~/.mission-control/node_id (created once; never changed by the backend).
Falls back to the MC_NODE_ID env var, then to the hostname.

Also exposes process start time for uptime reporting.
"""

from __future__ import annotations

import os
import socket
import time
from pathlib import Path

__all__ = ["node_id", "start_time", "uptime_seconds"]

_START_TIME = time.time()
_NODE_ID_PATH = Path.home() / ".mission-control" / "node_id"
_cached_node_id: str | None = None


def node_id() -> str:
    global _cached_node_id
    if _cached_node_id:
        return _cached_node_id

    # 1. File-based (most durable, user-edited)
    try:
        if _NODE_ID_PATH.exists():
            value = _NODE_ID_PATH.read_text().strip()
            if value:
                _cached_node_id = value
                return value
    except Exception:
        pass

    # 2. Env override
    env_value = os.getenv("MC_NODE_ID", "").strip()
    if env_value:
        _cached_node_id = env_value
        return env_value

    # 3. Hostname fallback
    try:
        host = socket.gethostname().strip() or "unknown-node"
    except Exception:
        host = "unknown-node"
    _cached_node_id = f"claw-{host.lower()}"
    return _cached_node_id


def start_time() -> float:
    return _START_TIME


def uptime_seconds() -> float:
    return max(0.0, time.time() - _START_TIME)
