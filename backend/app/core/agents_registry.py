"""
agents_registry — simple file-backed registry of Mission Control agents.

Each agent has: id, name, purpose, system_prompt, model, provider, active.
Persisted as JSON so configs survive restart without touching the main DB.

NOTE: This is a *config* registry only.  API keys are never stored here —
they stay in the encrypted secrets_store and are resolved server-side when
an agent is invoked via ai_backend.ask_ai().
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock
from typing import Literal

__all__ = [
    "Agent",
    "list_agents",
    "get_agent",
    "create_agent",
    "update_agent",
    "delete_agent",
]

Provider = Literal["anthropic", "openai", "auto"]

_DATA_DIR = Path(os.getenv("MC_DATA_DIR", str(Path.home() / ".mission-control")))
_REGISTRY_PATH = _DATA_DIR / "agents.json"

_lock = RLock()


@dataclass
class Agent:
    id:            str
    name:          str
    purpose:       str
    system_prompt: str
    model:         str = ""                  # empty → provider default
    provider:      Provider = "auto"         # "auto" = try anthropic → openai
    active:        bool = True
    tags:          list[str] = field(default_factory=list)
    platforms:     list[str] = field(default_factory=list)   # ["telegram","discord","ui",…]
    is_default:    bool = False              # default-handler for platforms in `platforms`

    @classmethod
    def new(
        cls,
        name: str,
        purpose: str,
        system_prompt: str,
        model: str = "",
        provider: Provider = "auto",
        active: bool = True,
        tags: list[str] | None = None,
        platforms: list[str] | None = None,
        is_default: bool = False,
    ) -> "Agent":
        return cls(
            id=uuid.uuid4().hex[:12],
            name=name.strip(),
            purpose=purpose.strip(),
            system_prompt=system_prompt,
            model=model.strip(),
            provider=provider,
            active=active,
            tags=tags or [],
            platforms=platforms or [],
            is_default=is_default,
        )


# ── Persistence ───────────────────────────────────────────────────────────────

_DEFAULT_AGENTS: list[Agent] = [
    Agent.new(
        name="Chat Agent",
        purpose="General-purpose conversational agent. Default fallback.",
        system_prompt=(
            "You are the Mission Control chat agent. Be concise, direct, and "
            "operator-focused. Reply in under 400 characters unless asked."
        ),
        tags=["default", "chat"],
    ),
    Agent.new(
        name="Hiring Agent",
        purpose="Drafts outreach, screens applicants, tracks interview pipeline.",
        system_prompt=(
            "You are the Mission Control hiring assistant. Draft concise, "
            "respectful outreach. When given applicant info, rank fit 1-10 "
            "with a one-line rationale. Always end with a next-step suggestion."
        ),
        tags=["ops", "hiring"],
    ),
    Agent.new(
        name="Content Agent",
        purpose="Drafts posts, replies, and marketing copy in Zach's voice.",
        system_prompt=(
            "You write in a direct, confident, first-person voice. Short "
            "sentences. No fluff. Match the tone of a founder-operator."
        ),
        tags=["content"],
    ),
]


_VALID_FIELDS = {f for f in Agent.__dataclass_fields__}


def _coerce_entry(entry: dict) -> Agent:
    # Drop unknown fields, fill defaults for any missing ones → forward-compat.
    clean = {k: v for k, v in entry.items() if k in _VALID_FIELDS}
    clean.setdefault("platforms", [])
    clean.setdefault("is_default", False)
    clean.setdefault("tags", [])
    return Agent(**clean)


def _ensure_loaded() -> list[Agent]:
    if _REGISTRY_PATH.exists():
        try:
            raw = json.loads(_REGISTRY_PATH.read_text())
            return [_coerce_entry(entry) for entry in raw]
        except Exception:
            # Corrupt file — back it up, seed defaults
            try:
                _REGISTRY_PATH.rename(_REGISTRY_PATH.with_suffix(".corrupt.json"))
            except Exception:
                pass
    # First-run: seed defaults
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _persist(_DEFAULT_AGENTS)
    return list(_DEFAULT_AGENTS)


def _persist(agents: list[Agent]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _REGISTRY_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(a) for a in agents], indent=2))
    tmp.replace(_REGISTRY_PATH)


# ── Public API ────────────────────────────────────────────────────────────────

def list_agents() -> list[Agent]:
    with _lock:
        return list(_ensure_loaded())


def get_agent(agent_id: str) -> Agent | None:
    with _lock:
        for a in _ensure_loaded():
            if a.id == agent_id:
                return a
        return None


def create_agent(
    name: str,
    purpose: str,
    system_prompt: str,
    model: str = "",
    provider: Provider = "auto",
    active: bool = True,
    tags: list[str] | None = None,
    platforms: list[str] | None = None,
    is_default: bool = False,
) -> Agent:
    agent = Agent.new(
        name, purpose, system_prompt, model, provider,
        active, tags, platforms, is_default,
    )
    with _lock:
        agents = _ensure_loaded()
        agents.append(agent)
        _persist(agents)
    return agent


def update_agent(agent_id: str, **updates: object) -> Agent | None:
    allowed = {
        "name", "purpose", "system_prompt", "model", "provider",
        "active", "tags", "platforms", "is_default",
    }
    with _lock:
        agents = _ensure_loaded()
        for i, a in enumerate(agents):
            if a.id == agent_id:
                for key, value in updates.items():
                    if key in allowed and value is not None:
                        setattr(a, key, value)
                agents[i] = a
                _persist(agents)
                return a
        return None


def delete_agent(agent_id: str) -> bool:
    with _lock:
        agents = _ensure_loaded()
        kept = [a for a in agents if a.id != agent_id]
        if len(kept) == len(agents):
            return False
        _persist(kept)
        return True
