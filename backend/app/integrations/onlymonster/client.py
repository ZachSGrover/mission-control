"""Async OnlyMonster API client.

Thin httpx adapter that resolves credentials from the encrypted secrets store
(with env-var fallback), exposes a `ping()` for the connection-test endpoint,
and a `fetch_entity()` method the sync orchestrator drives off the
`endpoints.ENDPOINT_CATALOG`.

The key never leaves this module — callers receive structured results, never
the raw token.  Decisions about retries and rate-limit handling live here so
every caller benefits uniformly.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.secrets_store import get_secret_with_source
from app.integrations.onlymonster.endpoints import ENDPOINT_CATALOG, EndpointSpec, find

logger = logging.getLogger(__name__)

ONLYMONSTER_API_KEY_DB_KEY = "onlymonster.api_key"
ONLYMONSTER_BASE_URL_DB_KEY = "onlymonster.base_url"

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_PAGE_LIMIT = 100
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (1.0, 3.0, 8.0)


# ── Result containers ────────────────────────────────────────────────────────


@dataclass
class OnlyMonsterCredentials:
    """Resolved credential bundle.  Source is one of 'db' | 'env' | 'none'."""

    api_key: str
    api_key_source: str
    base_url: str
    base_url_source: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip()) and bool(self.base_url.strip())


@dataclass
class PingResult:
    """Outcome of a connection test."""

    ok: bool
    status_code: int | None = None
    latency_ms: float | None = None
    base_url: str = ""
    api_key_source: str = "none"
    error: str | None = None
    raw: dict[str, Any] | None = None


@dataclass
class EndpointResult:
    """Outcome of a single entity fetch."""

    entity: str
    available: bool
    items: list[dict[str, Any]] = field(default_factory=list)
    page_count: int = 0
    next_cursor: str | None = None
    error: str | None = None
    reason: str | None = None  # 'not_available_from_api' | 'http_error' | 'auth_error' | etc.


# ── Credential resolution ────────────────────────────────────────────────────


async def resolve_credentials(session: AsyncSession) -> OnlyMonsterCredentials:
    """Resolve the active OnlyMonster API key + base URL.

    DB-stored values win over env vars so production keys can be rotated via
    the UI without redeploying the backend.
    """
    api_key, key_source = await get_secret_with_source(
        session,
        ONLYMONSTER_API_KEY_DB_KEY,
        fallback=settings.onlymonster_api_key,
    )
    base_url, url_source = await get_secret_with_source(
        session,
        ONLYMONSTER_BASE_URL_DB_KEY,
        fallback=settings.onlymonster_api_base_url,
    )
    return OnlyMonsterCredentials(
        api_key=api_key.strip(),
        api_key_source=key_source,
        base_url=base_url.strip().rstrip("/"),
        base_url_source=url_source,
    )


# ── Client ───────────────────────────────────────────────────────────────────


class OnlyMonsterClient:
    """Async client for the OnlyMonster API.

    Constructed with already-resolved credentials so callers do not have to
    pass an `AsyncSession` around — keeps the sync orchestrator decoupled
    from request lifecycle.
    """

    def __init__(self, credentials: OnlyMonsterCredentials, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._credentials = credentials
        self._timeout = timeout

    @property
    def credentials(self) -> OnlyMonsterCredentials:
        return self._credentials

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._credentials.api_key}",
            "Accept": "application/json",
            "User-Agent": "MissionControl-OFI/0.1",
        }

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._credentials.base_url}{path}"

    async def ping(self) -> PingResult:
        """Connection test against the OnlyMonster API.

        Tries `/health`, falls back to `/` if that 404s.  We never fail loudly
        here — the UI reads `ok` and `error` and renders accordingly.
        """
        if not self._credentials.configured:
            return PingResult(
                ok=False,
                base_url=self._credentials.base_url,
                api_key_source=self._credentials.api_key_source,
                error="No API key configured. Set ONLYMONSTER_API_KEY or save via Settings.",
            )

        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers()) as client:
            for path in ("/health", "/"):
                started = asyncio.get_event_loop().time()
                try:
                    resp = await client.get(self._url(path))
                except httpx.RequestError as exc:
                    logger.warning("onlymonster.ping.network_error path=%s err=%s", path, exc)
                    return PingResult(
                        ok=False,
                        base_url=self._credentials.base_url,
                        api_key_source=self._credentials.api_key_source,
                        error=f"Network error contacting OnlyMonster: {exc}",
                    )
                latency_ms = (asyncio.get_event_loop().time() - started) * 1000.0

                if resp.status_code == 404 and path == "/health":
                    continue

                ok = 200 <= resp.status_code < 300
                payload: dict[str, Any] | None
                try:
                    payload = resp.json() if resp.content else None
                except ValueError:
                    payload = None

                return PingResult(
                    ok=ok,
                    status_code=resp.status_code,
                    latency_ms=latency_ms,
                    base_url=self._credentials.base_url,
                    api_key_source=self._credentials.api_key_source,
                    error=None if ok else f"HTTP {resp.status_code}: {resp.text[:200]}",
                    raw=payload if isinstance(payload, dict) else None,
                )

        return PingResult(
            ok=False,
            base_url=self._credentials.base_url,
            api_key_source=self._credentials.api_key_source,
            error="No reachable health endpoint.",
        )

    async def fetch_entity(
        self,
        entity: str,
        *,
        params: dict[str, Any] | None = None,
        max_pages: int = 50,
    ) -> EndpointResult:
        """Fetch all pages for *entity* up to *max_pages*.

        Returns an `EndpointResult`.  When the catalog marks an entity as
        unavailable, the result short-circuits with `reason='not_available_from_api'`
        — the caller (sync orchestrator) records a placeholder sync_log entry.
        """
        spec = find(entity)
        if spec is None:
            return EndpointResult(
                entity=entity,
                available=False,
                reason="unknown_entity",
                error=f"Entity '{entity}' is not in the OnlyMonster endpoint catalog.",
            )
        if not spec.available:
            return EndpointResult(
                entity=entity,
                available=False,
                reason="not_available_from_api",
                error=(
                    "OnlyMonster endpoint not yet wired up in app.integrations.onlymonster.endpoints — "
                    "flip `available=True` and set the real path once docs are confirmed."
                ),
            )
        if not self._credentials.configured:
            return EndpointResult(
                entity=entity,
                available=False,
                reason="not_configured",
                error="No API key configured.",
            )

        items: list[dict[str, Any]] = []
        cursor: str | None = None
        pages_fetched = 0

        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers()) as client:
            while pages_fetched < max_pages:
                page_params: dict[str, Any] = dict(params or {})
                page_params.setdefault("limit", DEFAULT_PAGE_LIMIT)
                if cursor:
                    page_params["cursor"] = cursor

                resp = await self._request_with_retry(client, spec, page_params)
                if resp is None:
                    return EndpointResult(
                        entity=entity,
                        available=True,
                        items=items,
                        page_count=pages_fetched,
                        reason="network_error",
                        error="Network error after retries.",
                    )
                if resp.status_code in (401, 403):
                    return EndpointResult(
                        entity=entity,
                        available=True,
                        items=items,
                        page_count=pages_fetched,
                        reason="auth_error",
                        error=f"HTTP {resp.status_code}: authentication failed.",
                    )
                if resp.status_code >= 400:
                    return EndpointResult(
                        entity=entity,
                        available=True,
                        items=items,
                        page_count=pages_fetched,
                        reason="http_error",
                        error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    )

                payload: Any
                try:
                    payload = resp.json()
                except ValueError:
                    return EndpointResult(
                        entity=entity,
                        available=True,
                        items=items,
                        page_count=pages_fetched,
                        reason="invalid_json",
                        error="OnlyMonster returned non-JSON content.",
                    )

                page_items, cursor = _extract_items_and_cursor(payload)
                items.extend(page_items)
                pages_fetched += 1

                if not spec.paginated or not cursor:
                    break

        return EndpointResult(
            entity=entity,
            available=True,
            items=items,
            page_count=pages_fetched,
            next_cursor=cursor,
        )

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        spec: EndpointSpec,
        params: dict[str, Any],
    ) -> httpx.Response | None:
        """GET with simple exponential backoff on network errors and 429/5xx."""
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.request(spec.method, self._url(spec.path), params=params)
            except httpx.RequestError as exc:
                logger.warning(
                    "onlymonster.request.network_error entity=%s attempt=%s err=%s",
                    spec.entity, attempt + 1, exc,
                )
                if attempt + 1 < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt])
                    continue
                return None

            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt + 1 < MAX_RETRIES:
                    delay = RETRY_BACKOFF_SECONDS[attempt]
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        delay = max(delay, float(retry_after))
                    logger.info(
                        "onlymonster.request.retry entity=%s status=%s sleep=%.1fs",
                        spec.entity, resp.status_code, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
            return resp

        return None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _extract_items_and_cursor(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Extract items + next-cursor from a generic OnlyMonster response shape.

    OnlyMonster's exact response shape isn't yet documented; we try a few
    common shapes (`{data: [...], next_cursor: ...}`, `{items: [...]}`,
    bare list) and fall back to wrapping the payload itself.
    """
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)], None

    if isinstance(payload, dict):
        for key in ("data", "items", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                items = [item for item in value if isinstance(item, dict)]
                cursor = (
                    payload.get("next_cursor")
                    or payload.get("cursor")
                    or (payload.get("paging") or {}).get("next_cursor")
                )
                return items, cursor if isinstance(cursor, str) and cursor else None
        # Single-object response — wrap as a one-item page.
        return [payload], None

    return [], None


def supported_entities() -> list[str]:
    """Convenience for the API status endpoint."""
    return [spec.entity for spec in ENDPOINT_CATALOG]
