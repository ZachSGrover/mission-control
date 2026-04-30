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

import json as _json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Final, Mapping, Protocol, runtime_checkable

# Sprint 8E: ``httpx`` is the existing repo-wide async HTTP client
# (already used by app.core.auth, app.core.telegram_polling, app.api.*).
# It is imported here at module level so the no-network-import walker
# tests must explicitly allow it in this *one* file. Both walker tests
# (Sprint 8B and Sprint 8D) skip ``onlyfans_direct_transport.py`` for
# this single audited reason; every other ``onlyfans_direct_*.py``
# module must remain network-import-free.
import httpx

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


# ── Real HTTP transport — Sprint 8E ─────────────────────────────────────────


# Sprint 8E: timeouts for the real transport. Conservative values; a
# future sprint can lower them but should not raise without review.
_DEFAULT_CONNECT_TIMEOUT_S: Final[float] = 10.0
_DEFAULT_READ_TIMEOUT_S: Final[float] = 20.0


# Sprint 8E: response headers we are willing to round-trip into the
# audit pipeline (as a small summary). Anything not in this set is
# dropped entirely. ``set-cookie``, ``cookie``, ``authorization``,
# ``x-bc``, etc. are deliberately absent.
_SAFE_HEADER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "content-type",
        "content-length",
        "x-ratelimit-remaining",
        "x-ratelimit-limit",
        "retry-after",
    }
)


@dataclass(frozen=True)
class CredentialMaterial:
    """Header-shaped credential material the loader returns.

    Carries only what :class:`RealHTTPTransport` will set on the
    outbound request. The dataclass is intentionally narrow — the
    transport reads these fields, builds headers, and the dataclass
    falls out of scope at function exit. There is no encrypted
    blob, no cookie jar, no session object.

    A future sprint that needs more (e.g. additional X-BC fingerprint
    fields) should extend this dataclass deliberately, with an
    audit-safety review.
    """

    cookie: str | None = None
    authorization: str | None = None
    user_agent: str | None = None


class CredentialLoaderError(RuntimeError):
    """Raised by a credential loader when the credential cannot be
    resolved (missing row, decrypt failure, wrong provider). The
    transport translates this into a blocked sandbox result; it
    never surfaces the original exception's contents.
    """


CredentialLoaderFn = Callable[[], Awaitable[CredentialMaterial]]


@runtime_checkable
class CredentialLoader(Protocol):
    """Async credential loader the transport calls inside
    :meth:`RealHTTPTransport.fetch`.

    Implementations MUST:

    - Resolve the credential from the encrypted vault at call time.
    - Drop the decrypted value before returning.
    - Return a :class:`CredentialMaterial` carrying only the header
      fields the transport will set.
    - Never log, audit, or persist the decrypted value.
    """

    async def load(self) -> CredentialMaterial: ...


class RealHTTPTransport:
    """Real HTTP transport for the sandbox path.

    Sprint 8E wires the actual ``httpx`` call. Every safety property
    must hold:

    - Constructor refuses unless **both**
      ``MC_OF_DIRECT_SANDBOX_ALLOWED=1`` (Sprint 8C) AND
      ``MC_OF_DIRECT_REAL_CLIENT_ALLOWED=1`` (Sprint 8D) are set,
      AND we are not in production.
    - Constructor accepts only ``base_url`` and ``credential_loader``.
      No cookie / session / password kwargs.
    - ``fetch`` resolves the credential by calling
      ``credential_loader.load()`` *inside the method scope*. The
      decrypted material is used to build the request headers and
      dropped before return. No attribute on the transport instance
      carries the credential.
    - Response is classified into one of:
      - :class:`TransportResponse` (status 200 + parseable JSON).
      - :class:`ChallengeDetectedError` for 401 / 403 / 429 / HTML
        when JSON expected / suspicious redirects.
      - :class:`UnexpectedStatusError` for 5xx, empty body, or
        malformed JSON.
    - Headers exposed to callers / audit are filtered through
      :data:`_SAFE_HEADER_KEYS`. No ``Set-Cookie``, no
      ``Authorization``, no ``X-BC`` ever appears in
      :class:`TransportResponse` or any log line.
    - The ``json_body`` is the parsed JSON only — never the raw
      response bytes.

    **Endpoint mapping is still synthetic.** The path constants in
    ``onlyfans_direct_real_client`` (``/sandbox/account/profile``
    etc.) are pinned for sandbox-server compatibility tests. Before
    pointing this transport at a real OnlyFans-compatible endpoint,
    an operator must:

    1. Replace each path constant with the actual endpoint URL.
    2. Validate the response shape against
       ``AccountProfileSummary`` etc. *with sample synthetic data*
       before any real-account fetch.
    3. Walk ``docs/security/security-sprint-8e-of-sandbox-transport.md`` §10.
    """

    def __init__(
        self,
        *,
        base_url: str,
        credential_loader: CredentialLoader,
    ) -> None:
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
        if not base_url:
            raise ValueError("RealHTTPTransport requires a non-empty base_url.")
        # Strip trailing slash so path concatenation is predictable.
        self._base_url = base_url.rstrip("/")
        self._loader = credential_loader

    @staticmethod
    def safe_header_summary(headers: Mapping[str, str]) -> dict[str, str]:
        """Return a small dict of headers safe for audit / status.

        Drops every key not in :data:`_SAFE_HEADER_KEYS`. Values are
        bounded at 200 chars.
        """
        out: dict[str, str] = {}
        for k, v in headers.items():
            if k.lower() in _SAFE_HEADER_KEYS:
                s = str(v)
                out[k.lower()] = s[:200]
        return out

    @staticmethod
    def classify_status(
        *,
        status_code: int,
        content_type: str | None,
        body_text: str,
    ) -> None:
        """Raise the right typed error for non-success responses.

        Returns ``None`` on success (status 200 with non-empty body
        and JSON-compatible content type). Raises
        :class:`ChallengeDetectedError` or
        :class:`UnexpectedStatusError` otherwise.

        Pure function — a test can drive the classification matrix
        without standing up an httpx mock.
        """
        if status_code == 401:
            raise ChallengeDetectedError(reason_category="login_required", status_code=status_code)
        if status_code == 403:
            raise ChallengeDetectedError(reason_category="captcha", status_code=status_code)
        if status_code == 429:
            raise ChallengeDetectedError(
                reason_category="rate_limit_response", status_code=status_code
            )
        if 500 <= status_code < 600:
            raise UnexpectedStatusError(status_code=status_code)
        if status_code != 200:
            raise UnexpectedStatusError(status_code=status_code)
        ct = (content_type or "").lower()
        if ct and "json" not in ct and "html" in ct:
            raise ChallengeDetectedError(reason_category="unexpected_html", status_code=status_code)
        if not body_text.strip():
            raise UnexpectedStatusError(status_code=status_code)

    async def fetch(
        self,
        *,
        path: str,
        params: Mapping[str, str] | None = None,
    ) -> TransportResponse:
        """Perform one safe sandbox read.

        Steps:

        1. Resolve credential by calling ``self._loader.load()``.
           The decrypted material is in scope **only inside this
           method**.
        2. Build request headers from the loader output. Drop the
           loader output reference after this step.
        3. ``httpx.AsyncClient`` request with explicit timeouts and
           ``follow_redirects=False`` (a redirect is itself a
           challenge signal).
        4. Classify the response. Non-200 paths raise typed errors
           the connector wrapper catches and audits.
        5. On 200, parse JSON. Malformed JSON is treated as
           unexpected.
        6. Return :class:`TransportResponse` with safe fields only.
        """
        try:
            material = await self._loader.load()
        except CredentialLoaderError:
            raise
        except Exception as exc:
            logger.warning("of_direct.transport.loader_failed type=%s", type(exc).__name__)
            raise UnexpectedStatusError(status_code=0) from None

        headers: dict[str, str] = {"Accept": "application/json"}
        if material.cookie:
            headers["Cookie"] = material.cookie
        if material.authorization:
            headers["Authorization"] = material.authorization
        if material.user_agent:
            headers["User-Agent"] = material.user_agent
        # Drop the loader output reference. ``headers`` still holds
        # the values, but the dataclass instance can be GC'd; the
        # ``headers`` dict is cleared in the finally block below.
        del material

        url = f"{self._base_url}{path}"
        timeout = httpx.Timeout(
            connect=_DEFAULT_CONNECT_TIMEOUT_S,
            read=_DEFAULT_READ_TIMEOUT_S,
            write=10.0,
            pool=10.0,
        )
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.get(url, headers=headers, params=dict(params or {}))
        except httpx.HTTPError as exc:
            logger.warning("of_direct.transport.http_error type=%s", type(exc).__name__)
            raise UnexpectedStatusError(status_code=0) from None
        finally:
            headers.clear()

        if 300 <= response.status_code < 400:
            raise ChallengeDetectedError(reason_category="other", status_code=response.status_code)

        body_text = response.text
        content_type = response.headers.get("content-type")
        self.classify_status(
            status_code=response.status_code,
            content_type=content_type,
            body_text=body_text,
        )

        try:
            json_body: Any = _json.loads(body_text)
        except _json.JSONDecodeError:
            logger.warning(
                "of_direct.transport.malformed_json status=%d",
                response.status_code,
            )
            raise UnexpectedStatusError(status_code=response.status_code) from None

        return TransportResponse(
            status_code=response.status_code,
            json_body=json_body,
            content_type=(content_type or "")[:80] if content_type else None,
        )
