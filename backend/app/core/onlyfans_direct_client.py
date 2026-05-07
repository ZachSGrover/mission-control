"""Direct OnlyFans read-only client — interface and abstract base.

Sprint 8B: pins the **shape** of a future direct OnlyFans
read-only client. Every method here maps one-to-one onto a Sprint 7
``READ_ACTIONS`` entry. There are no write methods; an abstract
implementation that adds one would fail the test in
:mod:`tests.test_of_direct_dryrun`.

This module defines two surfaces:

- :class:`OnlyFansReadOnlyClient` — a :class:`typing.Protocol` so
  callers can type the dependency without importing a concrete
  class. The connector shell accepts any object satisfying this
  Protocol (real or fake).
- :class:`AbstractOnlyFansReadOnlyClient` — a concrete base class
  whose every method raises :class:`NotImplementedError`. A future
  real implementation MUST subclass this and override the read
  methods individually. Subclassing the abstract base is the only
  supported path: it forces the implementer to confront the
  read-only contract method-by-method instead of pasting a class
  with arbitrary methods.

What this module does NOT do:

- It does not perform I/O.
- It does not import any HTTP client (`httpx`, `requests`,
  `aiohttp`, `urllib`, `http.client`, `playwright`, `selenium`, or
  any browser automation library).
- It does not accept credentials.
- It does not store any state. Implementations may add their own
  state, but the interface itself is stateless.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class OnlyFansReadOnlyClient(Protocol):
    """Typed contract a future direct OnlyFans read-only client must
    satisfy. One method per Sprint 7 ``READ_ACTIONS`` entry. All
    methods are async and return a flat dict of safe fields.

    Implementations MUST NOT add any method whose name suggests a
    write action (``send_message``, ``post``, ``tip``, etc.). The
    Sprint 7/8B test
    :func:`tests.test_of_direct_dryrun.test_no_write_method_names_on_protocol_or_base`
    enforces this.
    """

    async def read_account_profile(self, *, creator_id: str) -> dict[str, Any]: ...

    async def read_account_stats(self, *, creator_id: str) -> dict[str, Any]: ...

    async def read_revenue_summary(self, *, creator_id: str) -> dict[str, Any]: ...

    async def read_fan_list_metadata(self, *, creator_id: str) -> dict[str, Any]: ...

    async def read_chat_thread_metadata(self, *, creator_id: str) -> dict[str, Any]: ...

    async def read_chat_messages(self, *, creator_id: str) -> dict[str, Any]: ...

    async def read_vault_metadata(self, *, creator_id: str) -> dict[str, Any]: ...

    async def read_post_metadata(self, *, creator_id: str) -> dict[str, Any]: ...

    async def read_story_metadata(self, *, creator_id: str) -> dict[str, Any]: ...

    async def read_mass_message_metadata(self, *, creator_id: str) -> dict[str, Any]: ...


# Maps Sprint 7 action vocabulary → method name on the client. Used
# by the connector shell to dispatch a single ``dry_run(action=...)``
# call to the right client method without a giant elif tree.
READ_ACTION_TO_METHOD: dict[str, str] = {
    "account_profile_read": "read_account_profile",
    "account_stats_read": "read_account_stats",
    "revenue_summary_read": "read_revenue_summary",
    "fan_list_metadata_read": "read_fan_list_metadata",
    "chat_thread_metadata_read": "read_chat_thread_metadata",
    "chat_message_read": "read_chat_messages",
    "vault_metadata_read": "read_vault_metadata",
    "post_metadata_read": "read_post_metadata",
    "story_metadata_read": "read_story_metadata",
    "mass_message_metadata_read": "read_mass_message_metadata",
}


class AbstractOnlyFansReadOnlyClient:
    """Concrete abstract base for any future real read-only client.

    Every read method raises :class:`NotImplementedError`. A real
    implementation must subclass this and override each method
    individually. There is no constructor; subclasses pick whatever
    constructor shape they need (but must still refuse cookie /
    session inputs — see
    :data:`app.core.onlyfans_direct_credentials.FORBIDDEN_CREDENTIAL_KEYS`).
    """

    async def read_account_profile(self, *, creator_id: str) -> dict[str, Any]:
        raise NotImplementedError("read_account_profile must be implemented")

    async def read_account_stats(self, *, creator_id: str) -> dict[str, Any]:
        raise NotImplementedError("read_account_stats must be implemented")

    async def read_revenue_summary(self, *, creator_id: str) -> dict[str, Any]:
        raise NotImplementedError("read_revenue_summary must be implemented")

    async def read_fan_list_metadata(self, *, creator_id: str) -> dict[str, Any]:
        raise NotImplementedError("read_fan_list_metadata must be implemented")

    async def read_chat_thread_metadata(self, *, creator_id: str) -> dict[str, Any]:
        raise NotImplementedError("read_chat_thread_metadata must be implemented")

    async def read_chat_messages(self, *, creator_id: str) -> dict[str, Any]:
        raise NotImplementedError("read_chat_messages must be implemented")

    async def read_vault_metadata(self, *, creator_id: str) -> dict[str, Any]:
        raise NotImplementedError("read_vault_metadata must be implemented")

    async def read_post_metadata(self, *, creator_id: str) -> dict[str, Any]:
        raise NotImplementedError("read_post_metadata must be implemented")

    async def read_story_metadata(self, *, creator_id: str) -> dict[str, Any]:
        raise NotImplementedError("read_story_metadata must be implemented")

    async def read_mass_message_metadata(self, *, creator_id: str) -> dict[str, Any]:
        raise NotImplementedError("read_mass_message_metadata must be implemented")
