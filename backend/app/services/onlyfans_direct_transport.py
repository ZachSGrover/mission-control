"""Direct OnlyFans sandbox transport — Sprint 8D.

Defines the **transport abstraction** the real read-only client
uses for its three Sprint 8D read methods. The abstraction
deliberately:

- Hides the raw response body. A caller never sees bytes; it sees
  a parsed JSON object plus a structured status. The audit
  pipeline cannot accidentally log a body because the body never
  escapes the transport.
- Hides cookies. There is no `set_cookie` field on
  :class:`TransportResponse`, no cookie jar on
  :class:`Transport`, and the Protocol explicitly forbids
  cookie-shaped kwargs in :meth:`Transport.fetch`.
- Hides session values. Same rationale.
- Hides browser automation. There is no headless-browser hook
  here; if a future Sprint 8E+ ever needs one, it must add a
  separate transport class with its own audited safety review.

This module imports **no HTTP client and no browser-automation
library**. The fake transport is the only working implementation
in Sprint 8D. The real HTTP transport stays abstract — when a
future sprint wires it, the implementation goes inside a method
body so the module-level no-network-import test still passes
during the transitional commit.

Status surface:
- :class:`Transport` — runtime-checkable Protocol.
- :class:`FakeTransport` — deterministic synthetic responses,
  used by Sprint 8D tests.
- :class:`TransportResponse` — structured response carrying only
  safe fields (status code, parsed JSON, optional content-type).
- :class:`ChallengeDetectedError` — raised when the platform
  serves a CAPTCHA, login redirect, or other bot-detection signal.
- :class:`UnexpectedStatusError` — raised on any non-200,
  non-challenge response.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Final, Mapping, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# Sprint 8D requires *both* the sandbox flag (Sprint 8C) and a new
# real-client flag for any future real HTTP transport to be
# considered. The fake transport is unconditionally available
# outside production; tests use it.
ENV_REAL_CLIENT_ALLOWED: Final[str] = "MC_OF_DIRECT_REAL_CLIENT_ALLOWED"


class TransportNotEnabledError(RuntimeError):
    """Raised by a transport implementation that is not wired in this
    sprint (e.g. the real HTTP transport).
    """


class ChallengeDetectedError(RuntimeError):
    """Raised when the transport detects a CAPTCHA / login challenge
    / unusual platform response.

    The connector wrapper catches this, audits
    ``connector.session.challenged``, calls the notifier, and
    returns a blocked sandbox result.
    """

    def __init__(self, reason_category: str, status_code: int | None = None) -> None:
        super().__init__(f"challenge detected: {reason_category}")
        self.reason_category = reason_category
        self.status_code = status_code


class UnexpectedStatusError(RuntimeError):
    """Raised on a non-200, non-challenge response. The connector
    wrapper audits a failure row and returns a blocked sandbox
    result.
    """

    def __init__(self, status_code: int) -> None:
        super().__init__(f"unexpected status: {status_code}")
        self.status_code = status_code


@dataclass(frozen=True)
class TransportResponse:
    """Safe structured response the transport returns.

    Carries only:
    - ``status_code`` — the HTTP status (or a synthetic int the fake
      uses to drive challenge / unexpected paths).
    - ``json_body`` — the parsed JSON object as a dict / list / scalar.
      The transport is responsible for parsing; callers must not
      receive raw bytes.
    - ``content_type`` — short string for the audit metadata. Capped
      at 80 chars to keep logs bounded.

    There is **no** ``raw_body``, ``cookies``, ``headers``, or
    ``set_cookie`` field. A future implementer adding any of these
    must amend the audit-safety contract first.
    """

    status_code: int
    json_body: Any
    content_type: str | None = None


@runtime_checkable
class Transport(Protocol):
    """Transport contract used by the real client's read methods.

    Implementations MUST:

    - Refuse cookie / session / password kwargs in their constructor.
    - Never expose a raw body, cookie, or session value to the caller.
    - Raise :class:`ChallengeDetectedError` on platform CAPTCHA /
      login challenge / unexpected-HTML signals.
    - Raise :class:`UnexpectedStatusError` on any other non-200
      response.
    """

    async def fetch(
        self,
        *,
        path: str,
        params: Mapping[str, str] | None = None,
    ) -> TransportResponse:
        """Perform a single read request and return a safe response.

        Implementations must accept only `path` and `params`. Any
        cookie / session / Authorization header is the
        implementation's internal concern and MUST NOT be
        observable on this signature.
        """
        ...


# ── Fake transport ──────────────────────────────────────────────────────────


@dataclass
class FakeTransport:
    """Deterministic synthetic transport for Sprint 8D tests.

    Configured at construction with a path → response map. Calling
    :meth:`fetch` looks up the path and returns the configured
    response, or raises a configured exception. Useful for testing
    the success, challenge, and unexpected-status paths without any
    network code.

    Synthetic-only invariants:

    - Returned ``json_body`` carries ``"synthetic": True`` if it's a
      dict (Sprint 8D test fixtures always do).
    - No real OnlyFans handles, fans, or revenue figures. Tests
      should pass deliberately fake data.
    """

    responses: dict[str, TransportResponse] = field(default_factory=dict)
    raise_on: dict[str, Exception] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list, init=False)

    async def fetch(
        self,
        *,
        path: str,
        params: Mapping[str, str] | None = None,
    ) -> TransportResponse:
        del params  # FakeTransport keys on path alone
        self.calls.append(path)
        if path in self.raise_on:
            raise self.raise_on[path]
        if path not in self.responses:
            raise UnexpectedStatusError(status_code=404)
        return self.responses[path]


# ── Real HTTP transport (NOT WIRED) ─────────────────────────────────────────


class RealHTTPTransport:
    """Placeholder for a future real HTTP transport.

    Sprint 8D does NOT wire a real HTTP client. This class exists
    so the call site has a typed shape to swap in later, and so
    the env-flag check is reviewable here.

    Future Sprint 8E+ wiring rules (binding):

    1. The HTTP client import (``httpx`` is the most likely
       candidate) goes inside :meth:`fetch` so the module-level
       no-network-import test continues to pass during the
       transitional commit. The test must be expanded explicitly,
       reviewed against this docstring, before any module-level
       import.
    2. The implementation refuses to construct unless BOTH
       ``MC_OF_DIRECT_SANDBOX_ALLOWED=1`` (Sprint 8C) AND
       ``MC_OF_DIRECT_REAL_CLIENT_ALLOWED=1`` (this sprint) are
       set in the environment.
    3. The implementation never returns raw bytes; it always parses
       to JSON and surfaces a :class:`TransportResponse`.
    4. Cookies / session tokens are resolved inside :meth:`fetch`
       from the encrypted vault and dropped on stack exit. No
       attribute on the transport instance carries them.

    Until Sprint 8E lands these, every method here raises
    :class:`TransportNotEnabledError`.
    """

    def __init__(self) -> None:
        # Refuse construction outside the sandbox + real-client flag
        # combination. The check happens at __init__ so a future
        # contributor's first call after wiring fails loudly if the
        # flags aren't set.
        from app.core import startup_guard
        from app.services.onlyfans_direct_connector import ENV_SANDBOX_ALLOWED

        if startup_guard.is_production():
            raise TransportNotEnabledError("RealHTTPTransport refused in production. Sandbox-only.")
        if os.environ.get(ENV_SANDBOX_ALLOWED, "0").strip() != "1":
            raise TransportNotEnabledError(f"RealHTTPTransport requires {ENV_SANDBOX_ALLOWED}=1.")
        if os.environ.get(ENV_REAL_CLIENT_ALLOWED, "0").strip() != "1":
            raise TransportNotEnabledError(
                f"RealHTTPTransport requires {ENV_REAL_CLIENT_ALLOWED}=1."
            )

    async def fetch(
        self,
        *,
        path: str,
        params: Mapping[str, str] | None = None,
    ) -> TransportResponse:
        del path, params
        raise TransportNotEnabledError(
            "RealHTTPTransport.fetch is not wired in Sprint 8D. A future "
            "Sprint 8E+ will replace this body with a deliberately narrow "
            "HTTP call inside this method only."
        )
