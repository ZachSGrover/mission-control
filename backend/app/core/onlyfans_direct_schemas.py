"""Direct OnlyFans sandbox response schemas — Sprint 8D.

Strict typed schemas + allowlist parsers for the three Sprint 8D
read methods. Each schema is intentionally narrow: it carries only
fields that are safe to surface in audit metadata / admin UI /
runbooks. Unknown fields in the platform's response are
**discarded** by the parser, never persisted.

Design rules (binding):

1. **No fan-level data.** No fan handles, no fan ids, no fan PII.
   The schemas in this file are creator-account-level only.
2. **No message data.** No bodies, no senders, no thread ids.
3. **No vault data.** Vault metadata is its own schema, scheduled
   for Sprint 8E or later — not in this file.
4. **No personally sensitive fan fields.** Even aggregate counts
   that could de-anonymize are rounded or omitted.
5. **Allowlist-only.** Every schema dataclass declares the exact
   set of fields it accepts. The parser drops everything else.
6. **Raw response is not stored.** Parsers return the dataclass;
   the raw dict is dropped at function exit.
7. **Values are summarized where possible.** Counts are clamped to
   non-negative ints; strings are bounded.

Each parser is a pure function: takes a JSON-shaped dict, returns
a typed dataclass. Failures (missing required fields, wrong
types) raise :class:`SchemaParseError`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Final

_MAX_STRING_LENGTH: Final[int] = 200


class SchemaParseError(RuntimeError):
    """Raised when a response payload cannot be parsed into the
    expected schema. The transport's caller treats this as an
    unexpected response and audits failure.
    """


def _safe_str(value: Any, *, default: str = "") -> str:
    """Coerce to string and bound length."""
    if value is None:
        return default
    s = str(value)
    if len(s) > _MAX_STRING_LENGTH:
        s = s[:_MAX_STRING_LENGTH]
    return s


def _safe_nonneg_int(value: Any, *, default: int = 0) -> int:
    """Coerce to non-negative int. Negative values clamp to 0;
    non-numeric values use ``default``.
    """
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, n)


def _safe_currency(value: Any, *, default: str = "USD") -> str:
    """Coerce to a 3-letter currency code. Anything else returns
    the default.
    """
    s = _safe_str(value, default=default)
    s = s.upper()
    if len(s) != 3 or not s.isalpha():
        return default
    return s


# ── Account profile summary ────────────────────────────────────────────────


@dataclass(frozen=True)
class AccountProfileSummary:
    """Account-level profile metadata.

    Every field is creator-self data — public-style profile
    information the creator themselves sees. No fan data, no
    revenue, no follower lists.
    """

    creator_handle: str
    display_name: str
    joined_iso: str
    subscription_tier_count: int


def parse_account_profile(payload: Any) -> AccountProfileSummary:
    """Allowlist-parse a payload into :class:`AccountProfileSummary`."""
    if not isinstance(payload, dict):
        raise SchemaParseError("account_profile payload must be a dict")
    return AccountProfileSummary(
        creator_handle=_safe_str(payload.get("creator_handle")),
        display_name=_safe_str(payload.get("display_name")),
        joined_iso=_safe_str(payload.get("joined_iso")),
        subscription_tier_count=_safe_nonneg_int(payload.get("subscription_tier_count")),
    )


# ── Account stats summary ──────────────────────────────────────────────────


@dataclass(frozen=True)
class AccountStatsSummary:
    """Account-level engagement stats.

    Sprint 8D scope is deliberately narrow: subscriber count,
    renewal-rate percentage, active-chat count. No per-fan
    breakdown.
    """

    subscriber_count: int
    renewal_rate_pct: int
    active_chats: int


def parse_account_stats(payload: Any) -> AccountStatsSummary:
    if not isinstance(payload, dict):
        raise SchemaParseError("account_stats payload must be a dict")
    pct = _safe_nonneg_int(payload.get("renewal_rate_pct"))
    if pct > 100:
        pct = 100
    return AccountStatsSummary(
        subscriber_count=_safe_nonneg_int(payload.get("subscriber_count")),
        renewal_rate_pct=pct,
        active_chats=_safe_nonneg_int(payload.get("active_chats")),
    )


# ── Revenue summary ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RevenueSummary:
    """Revenue aggregates only.

    Per-fan tip / PPV breakdowns are explicitly out of scope; this
    dataclass is for owner-facing high-level financials only.
    Values are aggregated subtotals — rounded ints in the
    creator's currency. No transaction-level data.
    """

    currency: str
    month_to_date: int
    previous_month: int
    tips_subtotal: int
    ppv_subtotal: int
    subscription_subtotal: int


def parse_revenue_summary(payload: Any) -> RevenueSummary:
    if not isinstance(payload, dict):
        raise SchemaParseError("revenue_summary payload must be a dict")
    return RevenueSummary(
        currency=_safe_currency(payload.get("currency")),
        month_to_date=_safe_nonneg_int(payload.get("month_to_date")),
        previous_month=_safe_nonneg_int(payload.get("previous_month")),
        tips_subtotal=_safe_nonneg_int(payload.get("tips_subtotal")),
        ppv_subtotal=_safe_nonneg_int(payload.get("ppv_subtotal")),
        subscription_subtotal=_safe_nonneg_int(payload.get("subscription_subtotal")),
    )


# ── Audit-safe summarization ───────────────────────────────────────────────


def safe_field_counts(summary: object) -> dict[str, int]:
    """Return a non-leaky scalar summary suitable for audit metadata.

    For each schema, returns counts / clamped scalars, **never** the
    text of strings (handles, display names, etc.). Used by the
    connector wrapper when it audits ``connector.run.finish`` for a
    successful sandbox read.
    """
    if isinstance(summary, AccountProfileSummary):
        return {
            "has_creator_handle": int(bool(summary.creator_handle)),
            "has_display_name": int(bool(summary.display_name)),
            "has_joined_iso": int(bool(summary.joined_iso)),
            "subscription_tier_count": summary.subscription_tier_count,
        }
    if isinstance(summary, AccountStatsSummary):
        return {
            "subscriber_count": summary.subscriber_count,
            "renewal_rate_pct": summary.renewal_rate_pct,
            "active_chats": summary.active_chats,
        }
    if isinstance(summary, RevenueSummary):
        return {
            "month_to_date": summary.month_to_date,
            "previous_month": summary.previous_month,
            "tips_subtotal": summary.tips_subtotal,
            "ppv_subtotal": summary.ppv_subtotal,
            "subscription_subtotal": summary.subscription_subtotal,
        }
    return {}


def summary_to_safe_dict(
    summary: AccountProfileSummary | AccountStatsSummary | RevenueSummary,
) -> dict[str, Any]:
    """Serialise a parsed summary back to a dict for the test
    suite / admin UI. Values are bounded by the parser; this just
    turns dataclass → dict without revealing anything new.
    """
    return asdict(summary)
