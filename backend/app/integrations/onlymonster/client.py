"""Async OnlyMonster API client.

Wired to the live OpenAPI spec at https://omapi.onlymonster.ai/docs/json.

Responsibilities:
  • Resolve credentials (DB-encrypted with env-var fallback).
  • Authenticate with the `x-om-auth-token` header (NOT Bearer).
  • Substitute path parameters (account_id, platform, etc.).
  • Drive three pagination shapes used by the API:
       - "cursor"  : `{<items_key>: [...], <cursor_key>: "..."}` — accounts, transactions, links, …
       - "offset"  : `{items: [...]}` — drive `offset` & `limit`, stop when a short page is returned
       - "none"    : single object or short list, no paging
  • Inject default query params (e.g. start/end date ranges).
  • Honour the documented rate limits (25/s global, 15/s per endpoint).
  • Refuse to fire any endpoint flagged `write=True`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.secrets_store import get_secret_with_source
from app.integrations.onlymonster.endpoints import ENDPOINT_CATALOG, EndpointSpec, find
from app.integrations.onlymonster.rate_limiter import OnlyMonsterRateLimiter

logger = logging.getLogger(__name__)

ONLYMONSTER_API_KEY_DB_KEY = "onlymonster.api_key"
ONLYMONSTER_BASE_URL_DB_KEY = "onlymonster.base_url"

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_PAGE_LIMIT = 100
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = (1.0, 3.0, 8.0)
DEFAULT_DATE_RANGE_DAYS = 30
AUTH_HEADER = "x-om-auth-token"


# ── Result containers ────────────────────────────────────────────────────────


@dataclass
class OnlyMonsterCredentials:
    api_key: str
    api_key_source: str
    base_url: str
    base_url_source: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key.strip()) and bool(self.base_url.strip())


@dataclass
class PingResult:
    ok: bool
    status_code: int | None = None
    latency_ms: float | None = None
    base_url: str = ""
    api_key_source: str = "none"
    error: str | None = None
    raw: dict[str, Any] | None = None


@dataclass
class EndpointResult:
    entity: str
    available: bool
    items: list[dict[str, Any]] = field(default_factory=list)
    page_count: int = 0
    next_cursor: str | None = None
    error: str | None = None
    reason: str | None = None
    path_params: dict[str, Any] = field(default_factory=dict)


# ── Credential resolution ────────────────────────────────────────────────────


async def resolve_credentials(session: AsyncSession) -> OnlyMonsterCredentials:
    api_key, key_source = await get_secret_with_source(
        session, ONLYMONSTER_API_KEY_DB_KEY, fallback=settings.onlymonster_api_key,
    )
    base_url, url_source = await get_secret_with_source(
        session, ONLYMONSTER_BASE_URL_DB_KEY, fallback=settings.onlymonster_api_base_url,
    )
    return OnlyMonsterCredentials(
        api_key=api_key.strip(),
        api_key_source=key_source,
        base_url=base_url.strip().rstrip("/"),
        base_url_source=url_source,
    )


# ── Client ───────────────────────────────────────────────────────────────────


class OnlyMonsterClient:
    """Thin async client.  Construct with already-resolved credentials."""

    def __init__(
        self,
        credentials: OnlyMonsterCredentials,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        rate_limiter: OnlyMonsterRateLimiter | None = None,
    ) -> None:
        self._credentials = credentials
        self._timeout = timeout
        self._rate_limiter = rate_limiter or OnlyMonsterRateLimiter()

    @property
    def credentials(self) -> OnlyMonsterCredentials:
        return self._credentials

    @property
    def rate_limiter(self) -> OnlyMonsterRateLimiter:
        return self._rate_limiter

    def _headers(self) -> dict[str, str]:
        return {
            AUTH_HEADER: self._credentials.api_key,
            "Accept": "application/json",
            "User-Agent": "MissionControl-OFI/0.2",
        }

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._credentials.base_url}{path}"

    # ── Connection test ──────────────────────────────────────────────────

    async def ping(self) -> PingResult:
        """Connection test — calls `GET /api/v0/accounts?limit=1`.

        That endpoint exists, requires auth, returns a tiny payload, and
        does not mutate state — perfect heartbeat.
        """
        if not self._credentials.configured:
            return PingResult(
                ok=False,
                base_url=self._credentials.base_url,
                api_key_source=self._credentials.api_key_source,
                error="No API key configured. Set ONLYMONSTER_API_KEY or save via Settings.",
            )

        await self._rate_limiter.acquire("/api/v0/accounts")
        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers()) as client:
            started = time.monotonic()
            try:
                resp = await client.get(self._url("/api/v0/accounts"), params={"limit": 1})
            except httpx.RequestError as exc:
                logger.warning("onlymonster.ping.network_error err=%s", exc)
                return PingResult(
                    ok=False,
                    base_url=self._credentials.base_url,
                    api_key_source=self._credentials.api_key_source,
                    error=f"Network error contacting OnlyMonster: {exc}",
                )
            latency_ms = (time.monotonic() - started) * 1000.0

            ok = 200 <= resp.status_code < 300
            payload: dict[str, Any] | None
            try:
                payload = resp.json() if resp.content else None
            except ValueError:
                payload = None

            error: str | None = None
            if not ok:
                if resp.status_code in (401, 403):
                    error = f"HTTP {resp.status_code}: API key rejected by OnlyMonster."
                elif resp.status_code == 429:
                    error = "HTTP 429: rate-limited (the rate-limiter should normally prevent this)."
                else:
                    error = f"HTTP {resp.status_code}: {resp.text[:200]}"

            return PingResult(
                ok=ok,
                status_code=resp.status_code,
                latency_ms=latency_ms,
                base_url=self._credentials.base_url,
                api_key_source=self._credentials.api_key_source,
                error=error,
                raw=payload if isinstance(payload, dict) else None,
            )

    # ── Entity fetch ─────────────────────────────────────────────────────

    async def fetch_entity(
        self,
        entity: str,
        *,
        path_params: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        max_pages: int = 50,
    ) -> EndpointResult:
        """Fetch all pages for *entity*.  Hard-refuses write endpoints."""
        spec = find(entity)
        if spec is None:
            return EndpointResult(
                entity=entity,
                available=False,
                reason="unknown_entity",
                error=f"Entity '{entity}' is not in the OnlyMonster endpoint catalog.",
                path_params=path_params or {},
            )
        if spec.write:
            return EndpointResult(
                entity=entity, available=False, reason="write_disabled",
                error="This endpoint mutates OnlyMonster data and is disabled by policy.",
                path_params=path_params or {},
            )
        if not spec.available:
            return EndpointResult(
                entity=entity, available=False,
                reason="dynamic_discovery_required" if spec.requires_dynamic_discovery else "not_available_from_api",
                error=spec.description or "Endpoint is not currently enabled.",
                path_params=path_params or {},
            )
        if not self._credentials.configured:
            return EndpointResult(
                entity=entity, available=False, reason="not_configured",
                error="No API key configured.",
                path_params=path_params or {},
            )

        # Substitute path parameters.
        effective_path, missing = _substitute_path(spec.path, path_params or {})
        if missing:
            return EndpointResult(
                entity=entity, available=True, reason="missing_path_params",
                error=f"Missing path params: {missing}",
                path_params=path_params or {},
            )

        # Build query baseline.
        base_params = dict(spec.default_query)
        if spec.requires_date_range:
            start_key, end_key = spec.date_range_keys
            now = datetime.now(timezone.utc)
            base_params.setdefault(start_key, (now - timedelta(days=DEFAULT_DATE_RANGE_DAYS)).isoformat())
            base_params.setdefault(end_key, now.isoformat())
        if query:
            base_params.update(query)

        # Drive pagination.
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        offset = 0
        pages = 0

        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers()) as client:
            while pages < max_pages:
                page_params: dict[str, Any] = dict(base_params)
                page_params.setdefault("limit", spec.page_limit or DEFAULT_PAGE_LIMIT)

                if spec.pagination == "cursor":
                    if cursor:
                        page_params[spec.cursor_key] = cursor
                elif spec.pagination == "offset":
                    page_params["offset"] = offset

                await self._rate_limiter.acquire(spec.path)
                resp = await self._request_with_retry(client, spec.method, effective_path, page_params)
                if resp is None:
                    return EndpointResult(
                        entity=entity, available=True, items=items, page_count=pages,
                        reason="network_error", error="Network error after retries.",
                        path_params=path_params or {},
                    )
                if resp.status_code in (401, 403):
                    return EndpointResult(
                        entity=entity, available=True, items=items, page_count=pages,
                        reason="auth_error", error=f"HTTP {resp.status_code}: authentication failed.",
                        path_params=path_params or {},
                    )
                if resp.status_code >= 400:
                    return EndpointResult(
                        entity=entity, available=True, items=items, page_count=pages,
                        reason="http_error",
                        error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                        path_params=path_params or {},
                    )

                try:
                    payload = resp.json()
                except ValueError:
                    return EndpointResult(
                        entity=entity, available=True, items=items, page_count=pages,
                        reason="invalid_json", error="OnlyMonster returned non-JSON content.",
                        path_params=path_params or {},
                    )

                page_items, next_cursor = _paginate_response(payload, spec)
                items.extend(page_items)
                pages += 1

                if spec.pagination == "cursor":
                    if not next_cursor:
                        break
                    cursor = next_cursor
                elif spec.pagination == "offset":
                    if len(page_items) < (page_params.get("limit") or spec.page_limit):
                        break
                    offset += len(page_items)
                else:
                    break

        return EndpointResult(
            entity=entity, available=True, items=items, page_count=pages,
            next_cursor=cursor, path_params=path_params or {},
        )

    # ── HTTP retry helper ────────────────────────────────────────────────

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        params: dict[str, Any],
    ) -> httpx.Response | None:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.request(method, self._url(path), params=params)
            except httpx.RequestError as exc:
                logger.warning(
                    "onlymonster.request.network_error path=%s attempt=%s err=%s",
                    path, attempt + 1, exc,
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
                        "onlymonster.request.retry path=%s status=%s sleep=%.1fs",
                        path, resp.status_code, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
            return resp

        return None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _substitute_path(path: str, path_params: dict[str, Any]) -> tuple[str, list[str]]:
    """Replace `{name}` placeholders.  Returns (path, missing_param_names)."""
    missing: list[str] = []
    out = path
    # Iterate placeholders in declaration order.
    import re
    for match in re.findall(r"\{([^}]+)\}", path):
        if match not in path_params or path_params[match] in (None, ""):
            missing.append(match)
            continue
        out = out.replace("{" + match + "}", str(path_params[match]))
    return out, missing


def _paginate_response(payload: Any, spec: EndpointSpec) -> tuple[list[dict[str, Any]], str | None]:
    """Extract (items, next_cursor) according to *spec.pagination* rules."""
    if spec.items_key == "fan_ids" and isinstance(payload, dict):
        # Special case: /fans returns `{fan_ids: ["str", ...]}`. Wrap each id.
        ids = payload.get("fan_ids")
        if isinstance(ids, list):
            return [{"fan_id": i} for i in ids if isinstance(i, str)], None
        return [], None

    if spec.items_key == "account" and isinstance(payload, dict):
        # Single-object endpoint.
        account = payload.get("account")
        if isinstance(account, dict):
            return [account], None
        return [], None

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)], None

    if not isinstance(payload, dict):
        return [], None

    raw_items = payload.get(spec.items_key)
    if not isinstance(raw_items, list):
        # Tolerate unexpected shapes by also checking common alternatives.
        for fallback in ("data", "items", "results"):
            if isinstance(payload.get(fallback), list):
                raw_items = payload[fallback]
                break
        else:
            return [], None

    items = [item for item in raw_items if isinstance(item, dict)]

    cursor: Any = None
    if spec.pagination == "cursor":
        cursor = payload.get(spec.cursor_key)
        # Tolerate alternative spellings.
        if not cursor:
            for alt in ("nextCursor", "cursor", "next_cursor"):
                if payload.get(alt):
                    cursor = payload[alt]
                    break
    return items, cursor if isinstance(cursor, str) and cursor else None


def supported_entities() -> list[str]:
    return [spec.entity for spec in ENDPOINT_CATALOG]
