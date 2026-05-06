"""OnlyMonster read-only fake client.

Sprint 8A: a **fake client** that conforms to the
:func:`app.services.onlymonster_integration.fetch_creator_snapshot`
seam's expected shape. It exists to:

- Prove the gated chain end-to-end on the OnlyMonster path without
  requiring the real OnlyMonster client (which lives on
  ``feat/of-intelligence``).
- Pin the read-only contract a future real client must satisfy:
  one async method, one creator id input, a flat dict of
  obviously-safe metadata as output.
- Be **refused in production** unless the operator explicitly opts
  in via ``MC_ONLYMONSTER_ALLOW_FAKE_CLIENT=1``. The default refusal
  catches the bug where this fake leaks into a production deploy.

This module does NOT:

- Open a network connection of any kind.
- Accept a real credential.
- Perform any write — there is no method named ``post``,
  ``message``, ``update``, ``delete``, etc.
- Carry real handles, real revenue, or real fan data. Every
  payload uses the ``test-creator-`` placeholder prefix and a
  ``synthetic: True`` marker.

When the OFI branch merges and a real ``OnlyMonsterClient`` is
available, the wiring point is at
:func:`resolve_onlymonster_client` — the call site decides whether
to use the real client or the fake based on env flag and presence.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Final, Protocol

from app.core import startup_guard
from app.core.logging import get_logger

logger = get_logger(__name__)


ENV_ALLOW_FAKE_IN_PROD: Final[str] = "MC_ONLYMONSTER_ALLOW_FAKE_CLIENT"


class FakeClientRefusedInProductionError(RuntimeError):
    """Raised when the fake client is requested in a production
    environment without ``MC_ONLYMONSTER_ALLOW_FAKE_CLIENT=1``.

    The fake is for tests and dry-run drills. Production should
    only ever hold the real client; if it doesn't, the answer is to
    wire the real client, not to flip the fake on.
    """


class OnlyMonsterReadOnlyClient(Protocol):
    """Typed contract a future real client must satisfy.

    The Sprint 6 seam (`fetch_creator_snapshot`) expects exactly this
    method shape. Pinning it as a Protocol lets the seam swap real
    and fake clients with no other code change.
    """

    async def read_only_pull(self, *, creator_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class FakeOnlyMonsterClient:
    """Deterministic, synthetic, no-network fake.

    The single entrypoint :meth:`read_only_pull` returns a flat
    dict carrying ``rows_read`` and ``last_event_at_iso`` — the two
    fields the Sprint 6 ``CreatorSnapshot`` requires — plus a
    ``synthetic: True`` marker so any leak into logs / audit / UI
    is unmistakably a fake.
    """

    rows_read: int = 7
    last_event_at_iso: str | None = "2026-04-30T12:00:00+00:00"

    async def read_only_pull(self, *, creator_id: str) -> dict[str, Any]:
        # Deliberately ignore creator_id beyond logging it. A real
        # client would scope by creator; the fake is per-instance and
        # returns the same payload for any creator. This prevents an
        # accidental "the fake learned the creator's data" footgun.
        logger.debug(
            "fake_onlymonster_client.read_only_pull creator_id=%s rows_read=%d",
            creator_id,
            self.rows_read,
        )
        return {
            "rows_read": int(self.rows_read),
            "last_event_at_iso": self.last_event_at_iso,
            "synthetic": True,
            "creator_id_echo": creator_id,
        }


def _fake_allowed_in_production() -> bool:
    return os.environ.get(ENV_ALLOW_FAKE_IN_PROD, "0").strip() == "1"


def resolve_onlymonster_client(
    *,
    real_client: OnlyMonsterReadOnlyClient | None = None,
    fake_client: OnlyMonsterReadOnlyClient | None = None,
) -> OnlyMonsterReadOnlyClient:
    """Pick the client the seam should call.

    Selection rules (fail-closed in production):

    1. If a ``real_client`` was passed, use it. The OFI-branch wiring
       will pass the real client here.
    2. Otherwise, if ``fake_client`` is passed and we are NOT in
       production, use it.
    3. Otherwise, if ``fake_client`` is passed and we ARE in
       production, the fake is refused unless
       ``MC_ONLYMONSTER_ALLOW_FAKE_CLIENT=1`` is set.
    4. Otherwise (no client at all), raise — the caller forgot to
       wire one.

    The function never returns ``None``. Either it returns a usable
    client or it raises. This keeps the caller's branching simple
    (no ``if client is None``).
    """
    if real_client is not None:
        return real_client
    if fake_client is None:
        raise RuntimeError(
            "No OnlyMonster client supplied. Pass either real_client "
            "(post-OFI-merge wiring) or fake_client (Sprint 8A drill / tests)."
        )
    if startup_guard.is_production() and not _fake_allowed_in_production():
        raise FakeClientRefusedInProductionError(
            "FakeOnlyMonsterClient refused in production. The fake is for "
            "drills and tests only. Wire the real OnlyMonsterClient instead, "
            f"or — for an explicit, audited drill — set {ENV_ALLOW_FAKE_IN_PROD}=1."
        )
    return fake_client
