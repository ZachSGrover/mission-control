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

from typing import Any, Final

from app.core.logging import get_logger
from app.core.onlyfans_direct_client import AbstractOnlyFansReadOnlyClient
from app.core.onlyfans_direct_credential_ref import CredentialReference
from app.core.onlyfans_direct_credentials import (
    assert_no_forbidden_credential_keys,
)
from app.core.onlyfans_direct_schemas import (
    SchemaParseError,
    parse_account_profile,
    parse_account_stats,
    parse_revenue_summary,
    summary_to_safe_dict,
)
from app.services.onlyfans_direct_transport import (
    ChallengeDetectedError,
    Transport,
    TransportResponse,
    UnexpectedStatusError,
)

logger = get_logger(__name__)


# Sprint 8D paths used by the three implemented reads. Kept here
# (not in the schemas module) because they are transport-layer
# concerns; the schemas module never sees a path.
_PATH_ACCOUNT_PROFILE: Final[str] = "/sandbox/account/profile"
_PATH_ACCOUNT_STATS: Final[str] = "/sandbox/account/stats"
_PATH_REVENUE_SUMMARY: Final[str] = "/sandbox/account/revenue-summary"


class RealClientNotEnabledError(RuntimeError):
    """Raised by every read method on the Sprint 8C skeleton, and by
    Sprint 8D unimplemented methods.

    Sprint 8D enables only the three account-level reads (profile,
    stats, revenue) — and only when a transport is configured. Any
    other method, or any call without a configured transport,
    raises this.
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
        transport: Transport | None = None,
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
        self._transport: Transport | None = transport

    @property
    def credential_ref(self) -> CredentialReference:
        """Return the bound credential reference.

        Useful for the sandbox gate to inspect *which* credential
        a configured client points at without ever asking the
        client to decrypt anything.
        """
        return self._credential_ref

    @property
    def transport(self) -> Transport | None:
        return self._transport

    # ── helper: handle a transport response or raise typed errors ──────────

    def _process_response(self, response: TransportResponse) -> Any:
        """Validate a :class:`TransportResponse` and return its
        ``json_body``.

        Raises :class:`ChallengeDetectedError` on platform-side
        challenge signals (the transport may also raise this
        directly; we double-check the status code here).

        Raises :class:`UnexpectedStatusError` on any other non-200
        response. The raw body is never returned.
        """
        # 200 is the only acceptable status. A 401 means session
        # invalid — treat as a challenge so the sandbox gate audits
        # session.challenged. 403 / 429 / 5xx all surface as
        # unexpected status.
        if response.status_code == 200:
            return response.json_body
        if response.status_code == 401:
            raise ChallengeDetectedError(
                reason_category="login_required",
                status_code=response.status_code,
            )
        # The transport itself may have raised ChallengeDetectedError
        # before we get here; if we see a non-200 code at this layer,
        # surface it as unexpected.
        raise UnexpectedStatusError(status_code=response.status_code)

    def _require_transport(self) -> Transport:
        if self._transport is None:
            raise RealClientNotEnabledError(
                "Sprint 8D real read requires a transport. Construct "
                "RealOnlyFansReadOnlyClient(credential_ref=..., transport=...)."
            )
        return self._transport

    # ── Sprint 8D: three account-level read methods ─────────────────────────

    async def read_account_profile(self, *, creator_id: str) -> dict[str, Any]:
        """Sandbox-only read of public-style profile metadata.

        Goes through the configured transport. On 401, raises
        :class:`ChallengeDetectedError` (login expired). On any
        other non-200, raises :class:`UnexpectedStatusError`. The
        raw response body never escapes this method; the parser
        builds a typed :class:`AccountProfileSummary` from
        allowlisted keys only and the dataclass is returned as a
        flat dict.
        """
        del creator_id  # transport is per-creator via credential_ref binding
        transport = self._require_transport()
        response = await transport.fetch(path=_PATH_ACCOUNT_PROFILE)
        body = self._process_response(response)
        try:
            summary = parse_account_profile(body)
        except SchemaParseError as exc:
            logger.warning("read_account_profile parse_failed: %s", type(exc).__name__)
            raise UnexpectedStatusError(status_code=200) from exc
        return summary_to_safe_dict(summary)

    async def read_account_stats(self, *, creator_id: str) -> dict[str, Any]:
        """Sandbox-only read of subscriber count, renewal rate, and
        active-chat count.
        """
        del creator_id
        transport = self._require_transport()
        response = await transport.fetch(path=_PATH_ACCOUNT_STATS)
        body = self._process_response(response)
        try:
            summary = parse_account_stats(body)
        except SchemaParseError as exc:
            logger.warning("read_account_stats parse_failed: %s", type(exc).__name__)
            raise UnexpectedStatusError(status_code=200) from exc
        return summary_to_safe_dict(summary)

    async def read_revenue_summary(self, *, creator_id: str) -> dict[str, Any]:
        """Sandbox-only read of aggregate revenue subtotals.

        No transaction-level breakdown, no per-fan numbers, no
        timestamps beyond the month buckets the platform returns.
        """
        del creator_id
        transport = self._require_transport()
        response = await transport.fetch(path=_PATH_REVENUE_SUMMARY)
        body = self._process_response(response)
        try:
            summary = parse_revenue_summary(body)
        except SchemaParseError as exc:
            logger.warning("read_revenue_summary parse_failed: %s", type(exc).__name__)
            raise UnexpectedStatusError(status_code=200) from exc
        return summary_to_safe_dict(summary)

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
