"""
platform_routing — resolve which agent should handle an inbound message
from a given platform (telegram / discord / ui / task / …).

Priority:
  1. An active agent with `platform in agent.platforms` and is_default=True
  2. An active agent with `platform in agent.platforms`
  3. An active agent tagged "default"
  4. None   (caller falls back to generic speed_layer handling)
"""

from __future__ import annotations

from app.core import agents_registry
from app.core.agents_registry import Agent

__all__ = ["resolve_agent_for_platform"]


def resolve_agent_for_platform(platform: str) -> Agent | None:
    platform = (platform or "").strip().lower()
    if not platform:
        return None

    active = [a for a in agents_registry.list_agents() if a.active]

    # Priority 1 — declared default for this platform
    for a in active:
        if a.is_default and platform in [p.lower() for p in a.platforms]:
            return a

    # Priority 2 — declared handler for this platform
    for a in active:
        if platform in [p.lower() for p in a.platforms]:
            return a

    # Priority 3 — tagged "default"
    for a in active:
        if "default" in [t.lower() for t in a.tags]:
            return a

    return None
