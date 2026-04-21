"""
network_monitor — async probe that tracks internet reachability transitions.

Every _PROBE_INTERVAL_S we attempt a TCP connect to a well-known DNS host
(1.1.1.1:53 by default) with a short timeout.  Transitions from online→offline
and offline→online are timestamped and logged.

The module is safe to import before the probe loop is started; snapshot() will
return is_online=None until the first probe completes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from dataclasses import dataclass
from threading import RLock

__all__ = ["snapshot", "NetworkSnapshot", "run_forever", "mark_online", "mark_offline"]

logger = logging.getLogger(__name__)

_PROBE_HOST = os.getenv("MC_PROBE_HOST", "1.1.1.1")
_PROBE_PORT = int(os.getenv("MC_PROBE_PORT", "53"))
_PROBE_TIMEOUT_S = 3.0
_PROBE_INTERVAL_S = 15.0
_FAIL_THRESHOLD = 2           # require N consecutive failures before flipping to offline


@dataclass
class NetworkSnapshot:
    is_online:            bool | None
    last_online_at:       float | None
    last_offline_at:      float | None
    consecutive_failures: int
    consecutive_successes:int
    last_checked_at:      float | None
    probe_target:         str


_lock = RLock()
_state = NetworkSnapshot(
    is_online=None,
    last_online_at=None,
    last_offline_at=None,
    consecutive_failures=0,
    consecutive_successes=0,
    last_checked_at=None,
    probe_target=f"{_PROBE_HOST}:{_PROBE_PORT}",
)


def snapshot() -> NetworkSnapshot:
    with _lock:
        return NetworkSnapshot(**_state.__dict__)


async def _probe_once() -> bool:
    """Return True if the probe TCP connect succeeded."""
    loop = asyncio.get_running_loop()

    def _connect() -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(_PROBE_TIMEOUT_S)
        try:
            s.connect((_PROBE_HOST, _PROBE_PORT))
            return True
        except OSError:
            return False
        finally:
            try:
                s.close()
            except Exception:
                pass

    return await loop.run_in_executor(None, _connect)


def mark_online() -> None:
    with _lock:
        was_offline = _state.is_online is False
        _state.is_online = True
        _state.last_online_at = time.time()
        _state.consecutive_failures = 0
        _state.consecutive_successes += 1
        _state.last_checked_at = _state.last_online_at
    if was_offline:
        logger.warning("network_monitor.online_recovered at=%s", _state.last_online_at)


def mark_offline() -> None:
    with _lock:
        was_online = _state.is_online is True
        _state.is_online = False
        _state.last_offline_at = time.time()
        _state.consecutive_successes = 0
        _state.consecutive_failures += 1
        _state.last_checked_at = _state.last_offline_at
    if was_online:
        logger.warning("network_monitor.went_offline at=%s", _state.last_offline_at)


async def run_forever(stop_event: asyncio.Event | None = None) -> None:
    """Long-running probe loop.  Started from the FastAPI lifespan hook."""
    logger.info("network_monitor.start target=%s interval=%.0fs",
                f"{_PROBE_HOST}:{_PROBE_PORT}", _PROBE_INTERVAL_S)
    while True:
        if stop_event is not None and stop_event.is_set():
            logger.info("network_monitor.stop")
            return
        try:
            success = await _probe_once()
        except Exception as exc:
            logger.warning("network_monitor.probe_error: %s", exc)
            success = False

        with _lock:
            _state.last_checked_at = time.time()
            if success:
                _state.consecutive_successes += 1
                _state.consecutive_failures = 0
            else:
                _state.consecutive_failures += 1
                _state.consecutive_successes = 0
            prev = _state.is_online
            if success:
                new_online: bool | None = True
            elif _state.consecutive_failures >= _FAIL_THRESHOLD:
                new_online = False
            else:
                new_online = prev

        if new_online is True and prev is not True:
            mark_online()
        elif new_online is False and prev is not False:
            mark_offline()

        try:
            await asyncio.sleep(_PROBE_INTERVAL_S)
        except asyncio.CancelledError:
            logger.info("network_monitor.cancelled")
            return
