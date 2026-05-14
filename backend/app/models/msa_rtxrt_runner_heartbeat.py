"""MSA RT/X runner heartbeat row.

One row per runner_id. Upserted on every ``GET /runner/poll`` with a
valid runner token. Read by the operator-facing
``GET /runner/status`` endpoint and by the frontend status pill.

Privacy contract:
    * Stores only ``runner_id`` (operator-chosen, e.g. ``"claw-1"``)
      + two timestamps + a derived state string. Never the runner
      token, never any per-claim job content, never AdsPower / X /
      OnlyFans data.
    * The runner-auth token gates the *write* (only valid tokens
      cause an upsert), but the token value itself is not stored.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.core.time import utcnow

# ── Status vocabulary ──────────────────────────────────────────────────────

RUNNER_STATUS_IDLE = "idle"
RUNNER_STATUS_BUSY = "busy"

VALID_RUNNER_STATUSES: frozenset[str] = frozenset({RUNNER_STATUS_IDLE, RUNNER_STATUS_BUSY})


# ── Freshness window ────────────────────────────────────────────────────────

# How recently the runner must have been seen to count as online. The
# frontend uses the same window. Picked at 90s to give a healthy buffer
# over the runner's default 5s poll cadence — a stalled runner becomes
# offline after roughly 18 missed polls.
ONLINE_FRESHNESS_SECONDS = 90


# ── Table ────────────────────────────────────────────────────────────────────


class MsaRtxrtRunnerHeartbeat(SQLModel, table=True):
    """One row per runner identifier (one heartbeat record)."""

    __tablename__ = "msa_rtxrt_runner_heartbeats"  # pyright: ignore[reportAssignmentType]

    runner_id: str = Field(primary_key=True, max_length=128)
    last_seen_at: datetime = Field(default_factory=utcnow)
    last_poll_at: datetime = Field(default_factory=utcnow)
    last_status: str = Field(default=RUNNER_STATUS_IDLE, max_length=16)
