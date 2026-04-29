"""OpenAI usage collector — Admin API based, read-only.

Reads aggregated usage and cost from the OpenAI Admin API:

  * ``GET https://api.openai.com/v1/organization/usage/completions``
  * ``GET https://api.openai.com/v1/organization/costs``

Both endpoints are read-only and free to call.  The collector NEVER touches
chat / completions / embeddings inference endpoints — those would create
spend.  When admin credentials (``OPENAI_ADMIN_KEY`` + ``OPENAI_ORG_ID``)
are missing it short-circuits with ``status="not_configured"`` BEFORE any
HTTP attempt.

Defensive choices:

* The admin key is NEVER logged or echoed in error strings (``mask_key``).
* The organization id IS logged (it is a public identifier).
* Response parsing uses ``dict.get`` everywhere — missing fields just
  count as zero rather than raising.
* Top-level response keys are logged once per process for observability
  (``object`` / ``data`` / ``has_more``).  Per-bucket results are not
  logged in full because they contain ``project_id`` / ``user_id`` /
  ``api_key_id`` values that are organization-private.
* Pagination is intentionally NOT followed in Phase 3A — we set a small
  ``limit`` and surface ``has_more`` in notes.  Phase 3B will paginate.
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

PROVIDER = "openai"

# OpenAI Admin API endpoints — read-only, no inference cost.
_USAGE_BASE = "https://api.openai.com/v1/organization"
_USAGE_COMPLETIONS_PATH = "/usage/completions"
_USAGE_COSTS_PATH = "/costs"

# Conservative timeouts so a slow OpenAI response cannot block a refresh.
_HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)

# Per-page bucket cap.  With bucket_width="1d" a 30-day window fits in a
# single page (31 ≥ 30).  Larger windows page through up to ``_MAX_PAGES``.
_PAGE_LIMIT = 31

# Hard cap on follow-up pages we will fetch in one collector run.  Even at
# the largest allowed window (30 d / 720 h) we never expect more than a
# single page; this cap exists to make a runaway pagination loop physically
# impossible if the upstream ever lies about ``has_more``.  31 × 5 = 155
# buckets — well above any realistic need for one refresh click.
_MAX_PAGES = 5

# Module-level flag so we only log the response *shape* once per worker
# process; subsequent calls run quietly.
_logged_completions_shape: bool = False
_logged_costs_shape: bool = False


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
            "OpenAI rejected the admin key (401). "
            "Verify the key in Settings → Usage and that it is an admin key "
            "(sk-admin-…), not a regular API key."
        )
    if status_code == 403:
        return (
            "OpenAI denied the request (403). "
            "The admin key may be missing the 'Usage and cost' read scope, or "
            "OPENAI_ORG_ID may be wrong for this key."
        )
    if status_code == 404:
        return (
            "OpenAI returned 404 for the usage endpoint. "
            "If you recently changed organization, re-check OPENAI_ORG_ID."
        )
    if status_code == 429:
        return (
            "OpenAI rate-limited the usage request (429). "
            "Try Refresh again in a minute; the local throttle is unrelated."
        )
    if 500 <= status_code < 600:
        return (
            f"OpenAI returned a server error ({status_code}). "
            "This is on OpenAI's side — try again later."
        )
    return f"OpenAI returned an unexpected status ({status_code})."


async def _request(
    client: httpx.AsyncClient,
    *,
    path: str,
    params: dict[str, Any],
    admin_key: str,
    org_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """Issue one Admin API GET.

    Returns ``(payload, error)`` where exactly one is non-None.  Never raises.
    Never includes the admin key in the error string.
    """
    headers = {
        "Authorization": f"Bearer {admin_key}",
        # OpenAI scopes the admin key to its organization, but this header is
        # also accepted and helps avoid surprises if the key has access to
        # multiple orgs in the future.
        "OpenAI-Organization": org_id,
        "Accept": "application/json",
    }
    url = f"{_USAGE_BASE}{path}"
    try:
        response = await client.get(url, params=params, headers=headers)
    except httpx.TimeoutException:
        return None, "OpenAI usage API timed out — network or service slow."
    except httpx.RequestError as exc:
        # Strip the URL in case it ever ends up containing query-string secrets
        # in a future refactor; we know the admin key is in headers, not URLs.
        return None, f"Could not reach OpenAI usage API ({type(exc).__name__})."

    if response.status_code != 200:
        return None, _classify_http_error(response.status_code)

    try:
        body = response.json()
    except ValueError:
        return None, "OpenAI returned a non-JSON usage response."
    if not isinstance(body, dict):
        return None, "OpenAI returned an unexpected (non-object) usage response."
    return body, None


async def _paginated_request(
    client: httpx.AsyncClient,
    *,
    path: str,
    base_params: dict[str, Any],
    admin_key: str,
    org_id: str,
    max_pages: int = _MAX_PAGES,
) -> tuple[dict[str, Any] | None, str | None, bool]:
    """Issue Admin API GETs and follow ``next_page`` up to ``max_pages``.

    Returns ``(merged_payload, error, hit_cap)``.

    * ``merged_payload`` is a synthetic dict with ``data`` containing every
      bucket fetched across pages, plus the latest page's ``has_more``.  All
      other top-level fields come from the first page.
    * ``error`` is non-None only if the FIRST page failed; later-page errors
      stop pagination but still return the partial result.
    * ``hit_cap`` is True iff we stopped because we ran out of page budget
      while ``has_more`` was still true — caller surfaces a note.

    Never raises.  Never echoes the admin key.  Bounded by ``max_pages``.
    """
    merged: dict[str, Any] = {}
    page_cursor: str | None = None
    fetched_pages = 0
    last_has_more = False

    for _ in range(max_pages):
        params = dict(base_params)
        if page_cursor:
            params["page"] = page_cursor

        body, err = await _request(
            client,
            path=path,
            params=params,
            admin_key=admin_key,
            org_id=org_id,
        )
        fetched_pages += 1

        if body is None:
            # Page-1 failure → no merged data to return.  Subsequent-page
            # failures keep what we have and surface the error.
            if not merged:
                return None, err, False
            logger.warning(
                "usage.openai.pagination_partial path=%s page=%d err=%r",
                path,
                fetched_pages,
                err,
            )
            return merged, None, False

        if not merged:
            # Seed merged structure from the first page; preserve top-level
            # metadata fields we don't recognise so callers can introspect.
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

    # Exhausted page budget while OpenAI still reported has_more=True.
    return merged, None, True


def _safe_int(value: Any) -> int:
    """Coerce *value* to int, returning 0 on any failure (None, str, …)."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _aggregate_completions(payload: dict[str, Any]) -> dict[str, Any]:
    """Sum tokens / requests across all buckets.

    Also returns a model→tokens map so cost can be estimated when the
    /costs endpoint isn't available.
    """
    total_input = 0
    total_output = 0
    total_requests = 0
    by_model: dict[str, dict[str, int]] = {}

    data = payload.get("data") or []
    if not isinstance(data, list):
        return {
            "input_tokens": 0,
            "output_tokens": 0,
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
            input_tokens = _safe_int(row.get("input_tokens"))
            output_tokens = _safe_int(row.get("output_tokens"))
            requests = _safe_int(row.get("num_model_requests"))
            model = str(row.get("model") or "").strip().lower() or "unknown"
            total_input += input_tokens
            total_output += output_tokens
            total_requests += requests
            slot = by_model.setdefault(
                model, {"input_tokens": 0, "output_tokens": 0}
            )
            slot["input_tokens"] += input_tokens
            slot["output_tokens"] += output_tokens

    return {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "requests": total_requests,
        "by_model": by_model,
        "has_more": bool(payload.get("has_more")),
    }


def _aggregate_costs(payload: dict[str, Any]) -> tuple[float, bool]:
    """Sum USD cost across all buckets.  Returns (total, saw_non_usd)."""
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
            amount = row.get("amount")
            if not isinstance(amount, dict):
                continue
            currency = str(amount.get("currency") or "").lower()
            value = amount.get("value")
            if currency != "usd":
                saw_non_usd = True
                continue
            try:
                total += float(value or 0)
            except (TypeError, ValueError):
                continue
    return total, saw_non_usd


# ── Entry point ──────────────────────────────────────────────────────────────


async def collect(
    session: AsyncSession,
    *,
    window_hours: int = 24,
) -> CollectorResult:
    """Pull a recent-window snapshot from the OpenAI Admin API.

    Returns ``CollectorResult(status="not_configured")`` when admin
    credentials are missing — never raises, never makes an inference call.
    """
    global _logged_completions_shape, _logged_costs_shape

    from app.core.config import settings
    from app.core.secrets_store import get_secret_with_source

    admin_key, _src = await get_secret_with_source(
        session,
        "admin_key.openai",
        fallback=settings.openai_admin_key,
    )
    # Org ID is now stored in the encrypted AppSetting alongside the admin
    # key (so the user can save it via the Settings UI).  The .env value
    # remains a transparent fallback for env-only deployments.
    org_id_raw, _org_src = await get_secret_with_source(
        session,
        "admin_org_id.openai",
        fallback=settings.openai_org_id,
    )
    org_id = org_id_raw.strip()

    end = utcnow()
    start = end - timedelta(hours=window_hours)

    # ── No credentials → no HTTP call.  Return early. ───────────────────────
    if not admin_key.strip() or not org_id:
        missing = []
        if not admin_key.strip():
            missing.append("OPENAI_ADMIN_KEY")
        if not org_id:
            missing.append("OPENAI_ORG_ID")
        return CollectorResult(
            provider=PROVIDER,
            status="not_configured",
            source="placeholder",
            period_start=start,
            period_end=end,
            notes=[
                "Set " + " and ".join(missing) + " to enable live billing snapshots.",
                "OpenAI requires an Admin key (sk-admin-...) — this is different "
                "from the regular API key used for chat completions.",
            ],
        )

    # ── Live read-only call. ───────────────────────────────────────────────
    start_unix = int(start.timestamp())
    base_params = {
        "start_time": start_unix,
        "bucket_width": "1d",
        "limit": _PAGE_LIMIT,
    }

    notes: list[str] = []
    logger.info(
        "usage.openai.fetch.start org_id=%s window_hours=%d start_unix=%d",
        org_id,
        window_hours,
        start_unix,
    )

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        completions_payload, completions_err, completions_capped = (
            await _paginated_request(
                client,
                path=_USAGE_COMPLETIONS_PATH,
                base_params=base_params,
                admin_key=admin_key,
                org_id=org_id,
            )
        )
        costs_payload, costs_err, costs_capped = await _paginated_request(
            client,
            path=_USAGE_COSTS_PATH,
            base_params=base_params,
            admin_key=admin_key,
            org_id=org_id,
        )

    # If the completions endpoint failed, surface that — without it we have
    # nothing meaningful to store.
    if completions_payload is None:
        logger.warning(
            "usage.openai.completions_failed err=%r org_id=%s",
            completions_err,
            org_id,
        )
        return CollectorResult(
            provider=PROVIDER,
            status="error",
            source="placeholder",
            period_start=start,
            period_end=end,
            error=completions_err,
        )

    if not _logged_completions_shape:
        logger.info(
            "usage.openai.completions_shape %s",
            _shape_summary(completions_payload),
        )
        _logged_completions_shape = True

    completions = _aggregate_completions(completions_payload)
    if completions_capped or costs_capped:
        notes.append(
            f"OpenAI returned more pages than the {_MAX_PAGES}-page safety cap; "
            "totals shown cover the most recent buckets."
        )

    # Determine cost path.
    cost_actual: float | None = None
    cost_estimated: float = 0.0
    if costs_payload is not None:
        if not _logged_costs_shape:
            logger.info("usage.openai.costs_shape %s", _shape_summary(costs_payload))
            _logged_costs_shape = True
        cost_actual, saw_non_usd = _aggregate_costs(costs_payload)
        if saw_non_usd:
            notes.append("Some cost rows used non-USD currency and were skipped.")
    else:
        logger.info(
            "usage.openai.costs_unavailable err=%r — falling back to local estimate.",
            costs_err,
        )
        notes.append(
            f"Cost endpoint unavailable ({costs_err}). "
            "Cost shown is estimated locally from token counts."
        )

    # If costs_payload is unavailable OR returned $0 with non-zero tokens, also
    # compute an estimate so the UI never shows blank.  The note above tells
    # the user when the displayed value is estimated.
    if completions["by_model"]:
        unpriced_models: list[str] = []
        for model_name, tokens in completions["by_model"].items():
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
        # Disambiguate when local estimate diverges materially from actual.
        if cost_estimated > 0 and cost_actual > 0:
            ratio = cost_estimated / cost_actual
            if ratio < 0.5 or ratio > 2.0:
                notes.append(
                    f"Note: local estimate (${cost_estimated:.4f}) diverged "
                    f"≥2× from OpenAI's reported cost (${cost_actual:.4f}); "
                    "the local pricing table may be stale."
                )
    else:
        cost_for_snapshot = cost_estimated

    total_tokens = completions["input_tokens"] + completions["output_tokens"]
    logger.info(
        "usage.openai.fetch.ok requests=%d input_tokens=%d output_tokens=%d "
        "cost_actual=%s cost_estimated=%.4f",
        completions["requests"],
        completions["input_tokens"],
        completions["output_tokens"],
        f"{cost_actual:.4f}" if cost_actual is not None else "n/a",
        cost_estimated,
    )

    return CollectorResult(
        provider=PROVIDER,
        status="ok",
        source="live",
        period_start=start,
        period_end=end,
        input_tokens=completions["input_tokens"],
        output_tokens=completions["output_tokens"],
        total_tokens=total_tokens,
        requests=completions["requests"],
        cost_usd=cost_for_snapshot,
        notes=notes,
    )
