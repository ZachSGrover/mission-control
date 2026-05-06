"""Best-effort $ / 1M token price table for cost estimation.

WARNING: prices change frequently and this table is **manually maintained**.
Treat the numbers as approximate.  When provider Admin/Usage APIs return
authoritative cost figures, prefer those over local estimates — see the
``cost_usd`` column on ``usage_snapshots``.

Used only for:
* Estimating cost on internal ``UsageEvent`` rows where the provider does not
  return a $ figure inline.
* Showing rough cost in the UI before the first billing snapshot lands.

Do NOT use this table for billing or any user-facing $ amounts where accuracy
matters; use the snapshot ``cost_usd`` instead.
"""

from __future__ import annotations

# All prices are USD per 1,000,000 tokens.
# Sourced from each provider's public pricing page as of 2026-04-28.  Re-check
# before quoting in customer-facing contexts.
_MODEL_PRICES_PER_M_TOKENS: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "o1": (15.00, 60.00),
    "o1-mini": (1.10, 4.40),
    "o3": (10.00, 40.00),
    "o3-mini": (1.10, 4.40),
    # Anthropic
    "claude-opus-4-7": (15.00, 75.00),
    "claude-opus-4-6": (15.00, 75.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
    # Google Gemini
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-2.5-flash": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 5.00),
}


def _normalize(model: str) -> str:
    """Normalize model identifiers for table lookup.

    Strips common version suffixes (``-2025-04-01``, ``@latest``) so e.g.
    ``gpt-4o-2024-08-06`` and ``gpt-4o`` collapse to one entry.
    """
    name = model.strip().lower()
    # Strip date-like suffixes after the last dash if it looks like YYYY-MM-DD.
    parts = name.split("-")
    if len(parts) >= 4 and parts[-3].isdigit() and parts[-2].isdigit() and parts[-1].isdigit():
        name = "-".join(parts[:-3])
    name = name.split("@", 1)[0]
    return name


def estimate_cost(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Return an estimated USD cost for a single call.

    Returns ``0.0`` for unknown models — callers should treat ``0.0`` as
    "unknown" rather than "free" and decide whether to surface a warning.
    """
    if not model:
        return 0.0
    prices = _MODEL_PRICES_PER_M_TOKENS.get(_normalize(model))
    if prices is None:
        return 0.0
    in_per_m, out_per_m = prices
    return (input_tokens * in_per_m + output_tokens * out_per_m) / 1_000_000.0


def is_priced(model: str) -> bool:
    """Whether ``model`` has a price entry in the local table."""
    return _normalize(model) in _MODEL_PRICES_PER_M_TOKENS
