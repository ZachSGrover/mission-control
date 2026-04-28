"""Catalog of OnlyMonster entity endpoints exposed to the sync orchestrator.

Each entry maps a logical entity (matching the `of_intelligence_*` table names
in `app.models.of_intelligence`) to its OnlyMonster API path and availability
flag.  Until the real OnlyMonster API surface is documented, every entry is
marked `available=False` and the sync orchestrator will record a placeholder
sync log row stating "not_available_from_api" rather than failing.

When real endpoints are confirmed, flip `available=True` and set the correct
`path` — the rest of the sync pipeline picks the change up automatically.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EndpointSpec:
    """Describes a single OnlyMonster entity endpoint."""

    entity: str
    path: str
    method: str = "GET"
    available: bool = False
    description: str = ""
    paginated: bool = True


# Order here matters — it dictates sync execution order so dependent entities
# (messages → chats → accounts) fan out from the broadest scope first.
ENDPOINT_CATALOG: tuple[EndpointSpec, ...] = (
    EndpointSpec("accounts",        "/accounts",          description="Connected creator accounts."),
    EndpointSpec("creators",        "/creators",          description="Creator profiles per account."),
    EndpointSpec("fans",            "/fans",              description="Fan/subscriber records."),
    EndpointSpec("chats",           "/chats",             description="DM threads."),
    EndpointSpec("messages",        "/messages",          description="Individual DM messages within chats."),
    EndpointSpec("chatters",        "/chatters",          description="Team-member chatters assigned to accounts."),
    EndpointSpec("mass_messages",   "/mass-messages",     description="Mass DM blasts."),
    EndpointSpec("auto_messages",   "/auto-messages",     description="Auto-replies / drip flows."),
    EndpointSpec("posts",           "/posts",             description="Wall posts."),
    EndpointSpec("stories",         "/stories",           description="Stories (where supported)."),
    EndpointSpec("revenue",         "/revenue",           description="Per-account revenue rollups."),
    EndpointSpec("transactions",    "/transactions",      description="Individual transaction records."),
    EndpointSpec("subscriptions",   "/subscriptions",     description="Active/lapsed subscriptions."),
    EndpointSpec("tips",            "/tips",              description="Tip events."),
    EndpointSpec("ppv_performance", "/ppv-performance",   description="PPV unlock rates and revenue."),
    EndpointSpec("trial_links",     "/trial-links",       description="Trial link conversions."),
    EndpointSpec("tracking_links",  "/tracking-links",    description="Tracking link clicks/conversions."),
    EndpointSpec("traffic_metrics", "/traffic-metrics",   description="Traffic source performance."),
    EndpointSpec("account_insights","/account-insights",  description="Per-account analytics insights."),
    EndpointSpec("team_performance","/team-performance",  description="Team member KPI rollups."),
    EndpointSpec("access_status",   "/access-status",     description="Account access / login health."),
    EndpointSpec("warnings",        "/warnings",          description="Account-level warnings or errors.", paginated=False),
)


def find(entity: str) -> EndpointSpec | None:
    """Return the spec for *entity* or None if it is not in the catalog."""
    for spec in ENDPOINT_CATALOG:
        if spec.entity == entity:
            return spec
    return None
