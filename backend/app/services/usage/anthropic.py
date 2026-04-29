"""Anthropic usage collector — Admin API based, read-only.

Reads aggregated usage and cost from the Anthropic Admin API:

  * ``GET https://api.anthropic.com/v1/organizations/usage_report/messages``
  * ``GET https://api.anthropic.com/v1/organizations/cost_report``

Both endpoints are read-only and free to call.  The collector NEVER touches
the Messages / Completions inference endpoints — those would create spend.
When admin credentials (``ANTHROPIC_ADMIN_KEY``) are missing it short-
circuits with ``status="not_configured"`` BEFORE any HTTP attempt.

Notes specific to Anthropic:

* Auth header is ``x-api-key: sk-ant-admin01-…`` plus the standard
  ``anthropic-version: 2023-06-01`` header that all Anthropic endpoints
  require.
* Admin keys are scoped to a single organization automatically; an org
  id is NOT required.  When supplied (via the Settings UI / .env) we
  forward it as a ``workspace_ids`` filter so the user can scope to a
  particular workspace.  Empty/missing → no filter.
* Time params are ISO-8601 strings (``starting_at`` / ``ending_at``),
  unlike OpenAI which uses Unix timestamps.
* Pagination uses ``next_page`` cursor + ``has_more`` flag; same shape
  as OpenAI so the helper structure mirrors that collector.

Defensive choices match the OpenAI collector exactly:
* The admin key is NEVER logged or echoed in error strings.
* Top-level response keys are logged once per process for observability.
* Per-bucket results are not logged (they may contain workspace ids).
* Pagination is bounded by ``_MAX_PAGES`` so a runaway has_more loop is
  physically impossible.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import httpx

from app.core.time import utcnow
from app.services.usage.base import CollectorResult
from app.services.usage.pricing import estimate_cost, is_priced

if TYPE_CHECKING:
    from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)


PROVIDER = "anthropic"

# Anthropic Admin API endpoints — read-only, no inference cost.
_USAGE_BASE = "https://api.anthropic.com/v1/organizations"
_USAGE_REPORT_PATH = "/usage_report/messages"
_COST_REPORT_PATH = "/cost_report"

# Anthropic API version header — required on every request.
_API_VERSION = "2023-06-01"

# Conservative timeouts (matches OpenAI collector).
_HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)

# Per-page bucket cap.  Anthropic supports up to 30 daily buckets per
# page in the usage_report endpoint; 31 is safely above the largest
# 30-day window we expose in the UI.
_PAGE_LIMIT = 31

# Hard cap on follow-up pages we will fetch in one collector run.
_MAX_PAGES = 5

# Module-level flags so we only log the response *shape* once per worker
# process; subsequent calls run quietly.
_logged_usage_shape: bool = False
_logged_cost_shape: bool = False


# ── Helpers ──────────────────────────────────────────────────────────────────


def _shape_summary(payload: Any) -> str:
    """Return a short, value-free summary of a JSON response shape."""
    if not isinstance(payload, dict):
        return f"non-object ({type(payload).__name__})"
    keys = sorted(payload.keys())
    data_field = payload.get("data")
    if isinstance(data_field, list):
        first = data_field[0] if data_field else None
        sub_keys = sorted(first.keys()) if isinstance(first, dict) else []
        return f"keys={keys} data_len={len(data_field)} bucket_keys={sub_keys}"
    return f"keys={keys}"


def _classify_http_error(status_code: int) -> str:
    if status_code == 401:
        return (
            "Anthropic rejected the admin key (401). "
            "Verify the key in Settings → Usage and that it is an admin key "
            "(sk-ant-admin01-…), not a regular API key."
        )
    if status_code == 403:
        return (
            "Anthropic denied the request (403). "
            "The admin key may be missing the read scope for usage and cost "
            "reports — re-issue from Console → Settings → Admin keys."
        )
    if status_code == 404:
        return (
            "Anthropic returned 404 for the usage endpoint. "
            "Check the API version and that your organization has Admin "
            "Reporting enabled."
        )
    if status_code == 429:
        return (
            "Anthropic rate-limited the usage request (429). "
            "Try Refresh again in a minute; the local throttle is unrelated."
        )
    if 500 <= status_code < 600:
        return (
            f"Anthropic returned a server error ({status_code}). "
            "This is on Anthropic's side — try again later."
        )
    return f"Anthropic returned an unexpected status ({status_code})."


def _safe_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


async def _request(
    client: httpx.AsyncClient,
    *,
    path: str,
    params: dict[str, Any],
    admin_key: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Issue one Admin API GET.

    Returns ``(payload, error)`` where exactly one is non-None.  Never
    raises.  Never includes the admin key in the error string.
    """
    headers = {
        "x-api-key": admin_key,
        "anthropic-version": _API_VERSION,
        "Accept": "application/json",
    }
    url = f"{_USAGE_BASE}{path}"
    try:
        response = await client.get(url, params=params, headers=headers)
    except httpx.TimeoutException:
        return None, "Anthropic usage API timed out — network or service slow."
    except httpx.RequestError as exc:
        return None, f"Could not reach Anthropic usage API ({type(exc).__name__})."

    if response.status_code != 200:
        return None, _classify_http_error(response.status_code)

    try:
        body = response.json()
    except ValueError:
        return None, "Anthropic returned a non-JSON usage response."
    if not isinstance(body, dict):
        return None, "Anthropic returned an unexpected (non-object) usage response."
    return body, None


async def _paginated_request(
    client: httpx.AsyncClient,
    *,
    path: str,
    base_params: dict[str, Any],
    admin_key: str,
    max_pages: int = _MAX_PAGES,
) -> tuple[dict[str, Any] | None, str | None, bool]:
    """Issue Admin API GETs and follow ``next_page`` up to ``max_pages``.

    Returns ``(merged_payload, error, hit_cap)``.  Mirrors the OpenAI
    paginator — see ``app.services.usage.openai._paginated_request`` for
    the contract.
    """
    merged: dict[str, Any] = {}
    page_cursor: str | None = None
    fetched_pages = 0
    last_has_more = False

    for _ in range(max_pages):
        params = dict(base_params)
        if page_cursor:
            params["page"] = page_cursor

        body, err = await _request(client, path=path, params=params, admin_key=admin_key)
        fetched_pages += 1

        if body is None:
            if not merged:
                return None, err, False
            logger.warning(
                "usage.anthropic.pagination_partial path=%s page=%d err=%r",
                path,
                fetched_pages,
                err,
            )
            return merged, None, False

        if not merged:
            merged = {k: v for k, v in body.items() if k != "data"}
            merged["data"] = []

        page_data = body.get("data") or []
        if isinstance(page_data, list):
            merged["data"].extend(page_data)

        last_has_more = bool(body.get("has_more"))
        next_page = body.get("next_page")
        merged["has_more"] = last_has_more
        merged["next_page"] = next_page

        if not last_has_more or not next_page or not isinstance(next_page, str):
            return merged, None, False
        page_cursor = next_page

    # Exhausted page budget while Anthropic still reported has_more=True.
    return merged, None, True


def _aggregate_usage(payload: dict[str, Any]) -> dict[str, Any]:
    """Sum tokens / requests across all buckets of the usage_report response.

    Anthropic's usage_report rows include several token fields (uncached
    input, cache creation, cache read, output, plus the deprecated
    `input_tokens`).  We sum them into a conservative total while keeping
    a per-model breakdown so cost can be estimated when needed.
    """
    total_input = 0
    total_output = 0
    total_cache_create = 0
    total_cache_read = 0
    total_requests = 0
    by_model: dict[str, dict[str, int]] = {}

    data = payload.get("data") or []
    if not isinstance(data, list):
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "requests": 0,
            "by_model": by_model,
            "has_more": bool(payload.get("has_more")),
        }

    for bucket in data:
        if not isinstance(bucket, dict):
            continue
        results = bucket.get("results") or []
        if not isinstance(results, list):
            continue
        for row in results:
            if not isinstance(row, dict):
                continue
            # Try multiple field names — Anthropic's response has shifted
            # over time and may include either ``input_tokens`` or
            # ``uncached_input_tokens``.
            input_tokens = _safe_int(
                row.get("uncached_input_tokens") or row.get("input_tokens")
            )
            output_tokens = _safe_int(row.get("output_tokens"))
            cache_create = _safe_int(row.get("cache_creation_input_tokens"))
            cache_read = _safe_int(row.get("cache_read_input_tokens"))
            requests = _safe_int(
                row.get("server_tool_use_api_calls")
                or row.get("num_model_requests")
                or row.get("requests")
            )
            model = str(row.get("model") or "").strip().lower() or "unknown"

            total_input += input_tokens
            total_output += output_tokens
            total_cache_create += cache_create
            total_cache_read += cache_read
            total_requests += requests

            slot = by_model.setdefault(
                model, {"input_tokens": 0, "output_tokens": 0}
            )
            # Cache reads count as input for cost modeling, treat conservatively.
            slot["input_tokens"] += input_tokens + cache_create + cache_read
            slot["output_tokens"] += output_tokens

    return {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "cache_creation_input_tokens": total_cache_create,
        "cache_read_input_tokens": total_cache_read,
        "requests": total_requests,
        "by_model": by_model,
        "has_more": bool(payload.get("has_more")),
    }


def _aggregate_costs(payload: dict[str, Any]) -> tuple[float, bool]:
    """Sum USD cost across all buckets of the cost_report response.

    Anthropic's cost_report rows expose ``amount`` either as a string or
    a number, with a ``currency`` sibling field.  Skip non-USD rows.
    """
    total = 0.0
    saw_non_usd = False
    data = payload.get("data") or []
    if not isinstance(data, list):
        return 0.0, False

    for bucket in data:
        if not isinstance(bucket, dict):
            continue
        results = bucket.get("results") or []
        if not isinstance(results, list):
            continue
        for row in results:
            if not isinstance(row, dict):
                continue
            currency = str(row.get("currency") or "").lower()
            if currency and currency != "usd":
                saw_non_usd = True
                continue
            # Some shapes nest the amount under "amount" as a dict like
            # OpenAI's; others place it directly.  Try both.
            amount = row.get("amount")
            if isinstance(amount, dict):
                inner_currency = str(amount.get("currency") or "").lower()
                if inner_currency and inner_currency != "usd":
                    saw_non_usd = True
                    continue
                total += _safe_float(amount.get("value"))
            else:
                total += _safe_float(amount)
    return total, saw_non_usd


# ── Entry point ──────────────────────────────────────────────────────────────


async def collect(
    session: AsyncSession,
    *,
    window_hours: int = 24,
) -> CollectorResult:
    """Pull a recent-window snapshot from the Anthropic Admin API.

    Returns ``CollectorResult(status="not_configured")`` when the admin
    key is missing — never raises, never makes an inference call.  Org id
    is OPTIONAL: if absent we still call the endpoint (admin keys are
    org-scoped); if present we forward it as a ``workspace_ids`` filter.
    """
    global _logged_usage_shape, _logged_cost_shape

    from app.core.config import settings
    from app.core.secrets_store import get_secret_with_source

    admin_key, _src = await get_secret_with_source(
        session,
        "admin_key.anthropic",
        fallback=settings.anthropic_admin_key,
    )
    org_id_raw, _org_src = await get_secret_with_source(
        session,
        "admin_org_id.anthropic",
        fallback=settings.anthropic_org_id,
    )
    org_id = org_id_raw.strip()

    end = utcnow()
    start = end - timedelta(hours=window_hours)

    # ── No admin key → no HTTP call.  Return early. ─────────────────────────
    if not admin_key.strip():
        return CollectorResult(
            provider=PROVIDER,
            status="not_configured",
            source="placeholder",
            period_start=start,
            period_end=end,
            notes=[
                "Set ANTHROPIC_ADMIN_KEY to enable live usage snapshots.",
                "Anthropic admin keys are issued separately from regular API "
                "keys and require Console > Settings > Admin keys.",
            ],
        )

    # ── Live read-only call. ───────────────────────────────────────────────
    # Anthropic uses ISO-8601 with Z suffix for UTC.
    starting_at = start.replace(microsecond=0).isoformat() + "Z"
    ending_at = end.replace(microsecond=0).isoformat() + "Z"
    base_params: dict[str, Any] = {
        "starting_at": starting_at,
        "ending_at": ending_at,
        "bucket_width": "1d",
        "limit": _PAGE_LIMIT,
    }
    if org_id:
        base_params["workspace_ids"] = org_id

    notes: list[str] = []
    logger.info(
        "usage.anthropic.fetch.start org_id_set=%s window_hours=%d "
        "starting_at=%s",
        bool(org_id),
        window_hours,
        starting_at,
    )

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        usage_payload, usage_err, usage_capped = await _paginated_request(
            client,
            path=_USAGE_REPORT_PATH,
            base_params=base_params,
            admin_key=admin_key,
        )
        cost_payload, cost_err, cost_capped = await _paginated_request(
            client,
            path=_COST_REPORT_PATH,
            base_params=base_params,
            admin_key=admin_key,
        )

    if usage_payload is None:
        logger.warning("usage.anthropic.usage_failed err=%r", usage_err)
        return CollectorResult(
            provider=PROVIDER,
            status="error",
            source="placeholder",
            period_start=start,
            period_end=end,
            error=usage_err,
        )

    if not _logged_usage_shape:
        logger.info(
            "usage.anthropic.usage_shape %s",
            _shape_summary(usage_payload),
        )
        _logged_usage_shape = True

    usage = _aggregate_usage(usage_payload)
    if usage_capped or cost_capped:
        notes.append(
            f"Anthropic returned more pages than the {_MAX_PAGES}-page safety cap; "
            "totals shown cover the most recent buckets."
        )

    # Cost path — authoritative when available; local estimate otherwise.
    cost_actual: float | None = None
    cost_estimated: float = 0.0
    if cost_payload is not None:
        if not _logged_cost_shape:
            logger.info(
                "usage.anthropic.cost_shape %s",
                _shape_summary(cost_payload),
            )
            _logged_cost_shape = True
        cost_actual, saw_non_usd = _aggregate_costs(cost_payload)
        if saw_non_usd:
            notes.append("Some cost rows used non-USD currency and were skipped.")
    else:
        logger.info(
            "usage.anthropic.cost_unavailable err=%r — falling back to local estimate.",
            cost_err,
        )
        notes.append(
            f"Cost endpoint unavailable ({cost_err}). "
            "Cost shown is estimated locally from token counts."
        )

    if usage["by_model"]:
        unpriced_models: list[str] = []
        for model_name, tokens in usage["by_model"].items():
            in_t = int(tokens["input_tokens"])
            out_t = int(tokens["output_tokens"])
            if not is_priced(model_name) and (in_t or out_t):
                unpriced_models.append(model_name)
            cost_estimated += estimate_cost(
                model_name, input_tokens=in_t, output_tokens=out_t
            )
        if unpriced_models:
            notes.append(
                "No local price for: "
                + ", ".join(sorted(set(unpriced_models)))
                + ". Their tokens are not included in the estimate."
            )

    if cost_actual is not None:
        cost_for_snapshot = cost_actual
        if cost_estimated > 0 and cost_actual > 0:
            ratio = cost_estimated / cost_actual
            if ratio < 0.5 or ratio > 2.0:
                notes.append(
                    f"Note: local estimate (${cost_estimated:.4f}) diverged "
                    f"≥2× from Anthropic's reported cost (${cost_actual:.4f}); "
                    "the local pricing table may be stale."
                )
    else:
        cost_for_snapshot = cost_estimated

    total_tokens = (
        usage["input_tokens"]
        + usage["output_tokens"]
        + usage["cache_creation_input_tokens"]
        + usage["cache_read_input_tokens"]
    )
    logger.info(
        "usage.anthropic.fetch.ok requests=%d input_tokens=%d output_tokens=%d "
        "cache_create=%d cache_read=%d cost_actual=%s cost_estimated=%.4f",
        usage["requests"],
        usage["input_tokens"],
        usage["output_tokens"],
        usage["cache_creation_input_tokens"],
        usage["cache_read_input_tokens"],
        f"{cost_actual:.4f}" if cost_actual is not None else "n/a",
        cost_estimated,
    )

    return CollectorResult(
        provider=PROVIDER,
        status="ok",
        source="live",
        period_start=start,
        period_end=end,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        total_tokens=total_tokens,
        requests=usage["requests"],
        cost_usd=cost_for_snapshot,
        notes=notes,
    )
