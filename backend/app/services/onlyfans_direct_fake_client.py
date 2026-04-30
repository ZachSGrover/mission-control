"""Direct OnlyFans read-only **fake** client.

Sprint 8B: a fake implementation of
:class:`app.core.onlyfans_direct_client.OnlyFansReadOnlyClient` for
the dry-run graduation. The fake:

- Reuses Sprint 7's synthetic fixtures (``test-creator-`` /
  ``test-fan-`` placeholders, ``synthetic: True`` markers).
- Refuses cookie / session / password kwargs at construction
  (same contract as the disabled connector shell).
- Refuses to be used in production unless the operator explicitly
  sets ``MC_OF_DIRECT_ALLOW_FAKE_CLIENT=1``. This catches the bug
  where this file leaks into a production deploy.
- Imports no HTTP client, no browser automation, no scraper.
- Never accepts a real credential in any form.

Why this fake exists:

- Sprint 7 proved the **policy boundary**. The disabled shell
  computed-and-discarded a fixture; nothing called a "client."
- Sprint 8B graduates: the connector now calls a *typed client*.
  Until a real client is implementable (post-merge of the OnlyFans
  read-only client which lives outside this branch), the only
  thing that can satisfy the typed seam is this fake. A future
  Sprint 8C+ replaces the fake with a real client behind a fresh
  set of safety checks.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Final

from app.core import startup_guard
from app.core.onlyfans_direct_client import AbstractOnlyFansReadOnlyClient
from app.core.onlyfans_direct_credentials import (
    assert_no_forbidden_credential_keys,
)
from app.services.onlyfans_direct_fixtures import fixture_payload_for

logger = logging.getLogger(__name__)


ENV_ALLOW_FAKE_IN_PROD: Final[str] = "MC_OF_DIRECT_ALLOW_FAKE_CLIENT"


class FakeClientRefusedInProductionError(RuntimeError):
    """Raised when the OF-direct fake client is requested in
    production without the explicit drill flag.
    """


def _fake_allowed_in_production() -> bool:
    return os.environ.get(ENV_ALLOW_FAKE_IN_PROD, "0").strip() == "1"


class FakeOnlyFansReadOnlyClient(AbstractOnlyFansReadOnlyClient):
    """Fixture-backed fake implementation of the read-only client
    Protocol.

    Constructor refuses credential-shaped kwargs (same set as the
    Sprint 7 connector shell) and refuses production usage without
    the explicit drill flag.

    Each read method:

    - Logs the call at debug level (no fan PII, just creator id).
    - Looks up the corresponding Sprint 7 fixture payload.
    - Adds a ``creator_id_echo`` field so a leak into logs is
      easy to spot.
    - Returns the fixture as a fresh dict (callers may mutate
      without affecting the canonical fixture).
    """

    def __init__(self, **kwargs: Any) -> None:
        # Refuse cookie / session / password / x-bc / etc. before
        # any code that could touch them runs.
        assert_no_forbidden_credential_keys(kwargs)
        # Production fake-refusal. We do this in __init__ so that
        # accidentally instantiating the fake in production (e.g.
        # by an admin endpoint that didn't set the flag) raises
        # before any read method is reachable.
        if startup_guard.is_production() and not _fake_allowed_in_production():
            raise FakeClientRefusedInProductionError(
                "FakeOnlyFansReadOnlyClient refused in production. The fake "
                "is for drills and tests only. Wire a real "
                "OnlyFansReadOnlyClient instead, or — for an explicit, "
                f"audited drill — set {ENV_ALLOW_FAKE_IN_PROD}=1."
            )

    # ── one method per Sprint 7 READ_ACTION ─────────────────────────────────

    async def read_account_profile(self, *, creator_id: str) -> dict[str, Any]:
        return self._payload("account_profile_read", creator_id)

    async def read_account_stats(self, *, creator_id: str) -> dict[str, Any]:
        return self._payload("account_stats_read", creator_id)

    async def read_revenue_summary(self, *, creator_id: str) -> dict[str, Any]:
        return self._payload("revenue_summary_read", creator_id)

    async def read_fan_list_metadata(self, *, creator_id: str) -> dict[str, Any]:
        return self._payload("fan_list_metadata_read", creator_id)

    async def read_chat_thread_metadata(self, *, creator_id: str) -> dict[str, Any]:
        return self._payload("chat_thread_metadata_read", creator_id)

    async def read_chat_messages(self, *, creator_id: str) -> dict[str, Any]:
        return self._payload("chat_message_read", creator_id)

    async def read_vault_metadata(self, *, creator_id: str) -> dict[str, Any]:
        return self._payload("vault_metadata_read", creator_id)

    async def read_post_metadata(self, *, creator_id: str) -> dict[str, Any]:
        return self._payload("post_metadata_read", creator_id)

    async def read_story_metadata(self, *, creator_id: str) -> dict[str, Any]:
        return self._payload("story_metadata_read", creator_id)

    async def read_mass_message_metadata(self, *, creator_id: str) -> dict[str, Any]:
        return self._payload("mass_message_metadata_read", creator_id)

    # ── helpers ─────────────────────────────────────────────────────────────

    def _payload(self, action: str, creator_id: str) -> dict[str, Any]:
        logger.debug("fake_of_readonly_client.%s creator_id=%s", action, creator_id)
        payload = fixture_payload_for(action)
        payload["creator_id_echo"] = creator_id
        # Defensive sanity: the fixture must already carry the
        # synthetic marker. If it doesn't, something is wrong.
        if not payload.get("synthetic"):
            raise RuntimeError(
                f"fixture for {action!r} missing synthetic marker — refuse to return"
            )
        return payload
