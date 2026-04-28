"""OnlyMonster API integration — data source for OnlyFans Intelligence.

OnlyMonster is the *first* data source under the OnlyFans Intelligence product
area.  Future data sources (e.g. direct OnlyFans scrapers, Infloww, Supercreator)
will live alongside this package and feed into the same `of_intelligence_*`
tables via the same sync orchestrator.

Setup:
  1. Set ONLYMONSTER_API_KEY in backend/.env for local development, or
  2. Save the key via Mission Control → Settings → Integrations (encrypted in
     `app_settings`).  DB value always wins over the env var.

The base URL defaults to a placeholder host (`https://api.onlymonster.ai/v1`)
that should be overridden via ONLYMONSTER_API_BASE_URL once the real API
endpoint is confirmed.  Until the endpoint catalog is documented, entity
methods return `EndpointResult(available=False, reason="not_available_from_api")`
so the sync orchestrator can record placeholder rows without crashing.
"""

from app.integrations.onlymonster.client import (
    OnlyMonsterClient,
    OnlyMonsterCredentials,
    PingResult,
    resolve_credentials,
)

__all__ = [
    "OnlyMonsterClient",
    "OnlyMonsterCredentials",
    "PingResult",
    "resolve_credentials",
]
