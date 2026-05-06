"""
control_devices — CLAW node registry (heartbeat + list).

Endpoints (prefix /api/v1/control/devices):
  POST /heartbeat   → CLAW node check-in (device_id, name, capabilities, current_task)
  GET  /            → list all known devices with online/offline status
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core import device_registry
from app.core.auth import AuthContext, get_auth_context

router = APIRouter(prefix="/control/devices", tags=["control-devices"])
AUTH_DEP = Depends(get_auth_context)


class HeartbeatRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=80)
    capabilities: list[str] = []
    current_task: str | None = None
    meta: dict[str, Any] = {}


class DeviceOut(BaseModel):
    device_id: str
    name: str
    capabilities: list[str]
    current_task: str | None
    last_seen: float
    age_s: float
    online: bool
    meta: dict[str, Any]


def _to_out(dev: device_registry.Device) -> DeviceOut:
    age = max(0.0, time.time() - dev.last_seen)
    return DeviceOut(
        device_id=dev.device_id,
        name=dev.name,
        capabilities=dev.capabilities,
        current_task=dev.current_task,
        last_seen=dev.last_seen,
        age_s=round(age, 1),
        online=age < 120.0,
        meta=dev.meta,
    )


@router.post("/heartbeat", response_model=DeviceOut)
async def heartbeat(body: HeartbeatRequest, _: AuthContext = AUTH_DEP) -> DeviceOut:
    dev = device_registry.record_heartbeat(
        device_id=body.device_id,
        name=body.name,
        capabilities=body.capabilities,
        current_task=body.current_task,
        meta=body.meta,
    )
    return _to_out(dev)


@router.get("", response_model=list[DeviceOut])
async def list_all(_: AuthContext = AUTH_DEP) -> list[DeviceOut]:
    return [_to_out(d) for d in device_registry.list_devices()]
