"""Direct OnlyFans **real** read-only client — Sprint 8C skeleton.

This module pins the shape of the future real read-only client.
It is structurally **unable** to perform a network call:

- Imports no HTTP client (`httpx`, `requests`, `aiohttp`, ...).
- Imports no browser-automation library (`playwright`, `selenium`,
  ...).
- Every read method raises :class:`RealClientNotEnabledError`. A
  Sprint 8D implementation must override each method individually
  and prove read-only-by-construction in code review.
- Constructor refuses raw cookies, raw sessions, plaintext
  credentials. The only credential-shaped argument it accepts is a
  :class:`CredentialReference` — a value-free pointer at the
  encrypted vault row.

The Sprint 8C goal is **structural readiness**, not behavior.
Adding the real client to the codebase ahead of any network code
forces the next sprint's reviewer to read this file before any
read method has a body, and to confront the read-only contract
method-by-method.

When Sprint 8D wires real reads, the changes happen here:

1. Replace each ``raise RealClientNotEnabledError`` with a
   read-only HTTP call using a deliberately narrow client.
2. Add the import of that client inside the method body so the
   module-level no-network-import test still passes during the
   transitional commit (or, if module-level is preferred, the
   no-network-import test must be expanded to allow a single,
   audited client).
3. Add per-method tests that verify the real call returns the
   safe shape, no fan PII, no message bodies.

**Until then, this module cannot connect to anything.**
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.onlyfans_direct_client import AbstractOnlyFansReadOnlyClient
from app.core.onlyfans_direct_credential_ref import CredentialReference
from app.core.onlyfans_direct_credentials import (
    assert_no_forbidden_credential_keys,
)

logger = logging.getLogger(__name__)


class RealClientNotEnabledError(RuntimeError):
    """Raised by every read method on the Sprint 8C skeleton.

    A future Sprint 8D will replace each method body with a real
    read-only call. Until then, instantiating the real client is
    fine — actually calling a read method is not.
    """


class RealOnlyFansReadOnlyClient(AbstractOnlyFansReadOnlyClient):
    """Real read-only client skeleton.

    Constructor accepts one typed argument:

    - ``credential_ref`` (:class:`CredentialReference`) — a
      value-free reference to a row in
      :class:`app.models.creator_credentials.CreatorCredential`.
      The class never receives the credential value itself; a
      future Sprint 8D will resolve and decrypt at call time
      inside each method body.

    Constructor refuses any kwarg matching the Sprint 7 forbidden
    set (``cookie``, ``session``, ``session_token``, ``password``,
    ``x-bc``, etc.). A future implementer cannot accidentally
    build a "convenient" constructor that takes a string.

    Every read method raises :class:`RealClientNotEnabledError`.
    Subclasses or future patches must override each method to
    enable it. There is no `__getattr__` magic; the only way to
    add a method is to write its body, which is reviewed.
    """

    def __init__(
        self,
        *,
        credential_ref: CredentialReference,
        **kwargs: Any,
    ) -> None:
        # The reference shape itself rules out cookies/sessions —
        # CredentialReference has no field for them. We still run
        # the credentials contract check on any extra kwargs to
        # catch a future "let's just pass cookie=..." footgun.
        assert_no_forbidden_credential_keys(kwargs)
        if credential_ref.provider != "onlyfans_direct":
            raise ValueError(
                "RealOnlyFansReadOnlyClient requires a credential_ref with "
                f"provider='onlyfans_direct'; got {credential_ref.provider!r}."
            )
        self._credential_ref = credential_ref

    @property
    def credential_ref(self) -> CredentialReference:
        """Return the bound credential reference.

        Useful for the sandbox gate to inspect *which* credential
        a configured client points at without ever asking the
        client to decrypt anything.
        """
        return self._credential_ref

    # ── real client methods are all unimplemented in 8C ─────────────────────

    async def read_account_profile(self, *, creator_id: str) -> dict[str, Any]:
        raise RealClientNotEnabledError("read_account_profile")

    async def read_account_stats(self, *, creator_id: str) -> dict[str, Any]:
        raise RealClientNotEnabledError("read_account_stats")

    async def read_revenue_summary(self, *, creator_id: str) -> dict[str, Any]:
        raise RealClientNotEnabledError("read_revenue_summary")

    async def read_fan_list_metadata(self, *, creator_id: str) -> dict[str, Any]:
        raise RealClientNotEnabledError("read_fan_list_metadata")

    async def read_chat_thread_metadata(self, *, creator_id: str) -> dict[str, Any]:
        raise RealClientNotEnabledError("read_chat_thread_metadata")

    async def read_chat_messages(self, *, creator_id: str) -> dict[str, Any]:
        raise RealClientNotEnabledError("read_chat_messages")

    async def read_vault_metadata(self, *, creator_id: str) -> dict[str, Any]:
        raise RealClientNotEnabledError("read_vault_metadata")

    async def read_post_metadata(self, *, creator_id: str) -> dict[str, Any]:
        raise RealClientNotEnabledError("read_post_metadata")

    async def read_story_metadata(self, *, creator_id: str) -> dict[str, Any]:
        raise RealClientNotEnabledError("read_story_metadata")

    async def read_mass_message_metadata(self, *, creator_id: str) -> dict[str, Any]:
        raise RealClientNotEnabledError("read_mass_message_metadata")
