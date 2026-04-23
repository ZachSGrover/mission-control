"""
device_registry — in-memory registry of connected CLAW nodes.

Each node POSTs a heartbeat every ~30 s.  Any node silent for >120 s is
considered offline (still listed but marked inactive).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import RLock

__all__ = ["Device", "record_heartbeat", "list_devices", "is_online"]

_STALE_AFTER_S = 120.0
_lock = RLock()


@dataclass
class Device:
    device_id: str
    name: str
    capabilities: list[str] = field(default_factory=list)
    current_task: str | None = None
    last_seen: float = 0.0
    meta: dict = field(default_factory=dict)


_devices: dict[str, Device] = {}


def record_heartbeat(
    device_id: str,
    name: str,
    capabilities: list[str] | None = None,
    current_task: str | None = None,
    meta: dict | None = None,
) -> Device:
    with _lock:
        existing = _devices.get(device_id)
        dev = Device(
            device_id=device_id,
            name=name or device_id,
            capabilities=(
                capabilities
                if capabilities is not None
                else (existing.capabilities if existing else [])
            ),
            current_task=(
                current_task
                if current_task is not None
                else (existing.current_task if existing else None)
            ),
            last_seen=time.time(),
            meta=meta if meta is not None else (existing.meta if existing else {}),
        )
        _devices[device_id] = dev
        return dev


def list_devices() -> list[Device]:
    with _lock:
        return sorted(_devices.values(), key=lambda d: d.last_seen, reverse=True)


def is_online(device_id: str) -> bool:
    with _lock:
        dev = _devices.get(device_id)
        if not dev:
            return False
        return (time.time() - dev.last_seen) < _STALE_AFTER_S
