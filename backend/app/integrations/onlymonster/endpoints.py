"""Catalog of OnlyMonster API endpoints, derived from the live OpenAPI spec
at https://omapi.onlymonster.ai/docs/json (om-api-service v0.30.0).

Only **GET** endpoints that are safe under read-only sync are marked
`available=True`.  Every endpoint that mutates OnlyMonster state (POST send-
message, vault upload start/finish/retry/export, fan verify) is included
here for inventory completeness but kept `available=False` and flagged
`write=True` — the sync orchestrator will refuse to fire them.

`messages` is a GET, but discovering `chat_id` requires an endpoint that the
v0.30.0 surface does not expose.  It is kept disabled with
`requires_dynamic_discovery=True` so the operator can see the gate clearly
in sync logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EndpointSpec:
    """Describes a single OnlyMonster endpoint and how to drive it."""

    entity: str
    path: str
    method: str = "GET"
    available: bool = False
    write: bool = False  # True = mutates OnlyMonster state
    requires_dynamic_discovery: bool = False  # True = depends on IDs we cannot enumerate yet
    description: str = ""

    # Pagination — see _paginate_response in client.py
    pagination: str = "none"  # "cursor" | "offset" | "none"
    items_key: str = "items"
    cursor_key: str = "cursor"
    page_limit: int = 100

    # Path parameters and fan-out behaviour
    path_params: tuple[str, ...] = ()
    fan_out: str = "flat"  # "flat" | "per_account" | "per_platform_account"

    # Query parameter handling
    requires_date_range: bool = False  # injects start/end (or from/to) defaulting to last 30d
    date_range_keys: tuple[str, str] = ("start", "end")
    default_query: tuple[tuple[str, str], ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Catalog — order matters: `accounts` MUST run first so per-account /
# per-platform endpoints can fan out off the freshly-synced account list.
# ---------------------------------------------------------------------------

ENDPOINT_CATALOG: tuple[EndpointSpec, ...] = (
    # ── Flat read endpoints ────────────────────────────────────────────────
    EndpointSpec(
        entity="accounts",
        path="/api/v0/accounts",
        available=True,
        description="List of connected creator accounts.",
        pagination="cursor",
        items_key="accounts",
        cursor_key="nextCursor",
        default_query=(("withExpiredSubscriptions", "true"),),
    ),
    EndpointSpec(
        entity="members",
        path="/api/v0/members",
        available=True,
        description="Organisation members (chatters, managers).",
        pagination="offset",
        items_key="users",
        page_limit=50,  # OnlyMonster enforces limit <= 50 on this endpoint.
    ),
    EndpointSpec(
        entity="user_metrics",
        path="/api/v0/users/metrics",
        available=True,
        description="Per-user OnlyFans metrics (replies, sales, work time).",
        pagination="offset",
        items_key="items",
        requires_date_range=True,
        date_range_keys=("from", "to"),
    ),
    # ── Per-account endpoints (fan out over synced accounts) ───────────────
    EndpointSpec(
        entity="account_details",
        path="/api/v0/accounts/{account_id}",
        available=True,
        description="Per-account detail document. One call per account.",
        pagination="none",
        items_key="account",
        path_params=("account_id",),
        fan_out="per_account",
    ),
    EndpointSpec(
        entity="fans",
        path="/api/v0/accounts/{account_id}/fans",
        available=True,
        description="Fan IDs derived from recent chat activity.",
        pagination="none",
        items_key="fan_ids",
        path_params=("account_id",),
        fan_out="per_account",
    ),
    EndpointSpec(
        entity="vault_folders",
        path="/api/v0/accounts/{account_id}/vault/folders",
        available=True,
        description="Vault folders (OnlyFans accounts only).",
        pagination="offset",
        items_key="items",
        path_params=("account_id",),
        fan_out="per_account",
        page_limit=10,  # OnlyMonster enforces limit <= 10 on this endpoint.
    ),
    EndpointSpec(
        entity="vault_uploads",
        path="/api/v0/accounts/{account_id}/vault/medias/uploads",
        available=True,
        description="List of media uploads (read-only listing).",
        pagination="offset",
        items_key="items",
        path_params=("account_id",),
        fan_out="per_account",
    ),
    # ── Folder-scoped — needs vault_folder.id discovered in this run ──────
    # Currently disabled because the sync orchestrator only fans out over
    # accounts; folder discovery / iteration is a follow-up.  Mark for
    # discoverability in /status.
    EndpointSpec(
        entity="vault_folder_medias",
        path="/api/v0/accounts/{account_id}/vault/folders/{folder_id}/medias",
        available=False,
        requires_dynamic_discovery=True,
        description=(
            "Media list inside a vault folder.  Disabled until folder-level "
            "fan-out is wired (needs folder_id from vault_folders sync)."
        ),
        pagination="offset",
        items_key="items",
        path_params=("account_id", "folder_id"),
        fan_out="per_account",
        page_limit=10,  # OnlyMonster enforces limit <= 10 on this endpoint.
    ),
    # ── Per-platform-account endpoints (fan out over (platform, platform_account_id)) ──
    EndpointSpec(
        entity="transactions",
        path="/api/v0/platforms/{platform}/accounts/{platform_account_id}/transactions",
        available=True,
        description="Per-account financial transactions (tips, PPV, subs, posts).",
        pagination="cursor",
        items_key="items",
        cursor_key="cursor",
        path_params=("platform", "platform_account_id"),
        fan_out="per_platform_account",
        requires_date_range=True,
    ),
    EndpointSpec(
        entity="chargebacks",
        path="/api/v0/platforms/{platform}/accounts/{platform_account_id}/chargebacks",
        available=True,
        description="Chargebacks against the account.",
        pagination="cursor",
        items_key="items",
        cursor_key="cursor",
        path_params=("platform", "platform_account_id"),
        fan_out="per_platform_account",
        requires_date_range=True,
    ),
    EndpointSpec(
        entity="trial_links",
        path="/api/v0/platforms/{platform}/accounts/{platform_account_id}/trial-links",
        available=True,
        description="Trial-link campaigns.",
        pagination="cursor",
        items_key="items",
        cursor_key="cursor",
        path_params=("platform", "platform_account_id"),
        fan_out="per_platform_account",
        requires_date_range=True,
    ),
    EndpointSpec(
        entity="tracking_links",
        path="/api/v0/platforms/{platform}/accounts/{platform_account_id}/tracking-links",
        available=True,
        description="Tracking-link campaigns.",
        pagination="cursor",
        items_key="items",
        cursor_key="cursor",
        path_params=("platform", "platform_account_id"),
        fan_out="per_platform_account",
        requires_date_range=True,
    ),
    EndpointSpec(
        entity="trial_link_users",
        path="/api/v0/platforms/{platform}/accounts/{platform_account_id}/trial-link-users",
        available=True,
        description="Fans who claimed a trial link.",
        pagination="cursor",
        items_key="items",
        cursor_key="cursor",
        path_params=("platform", "platform_account_id"),
        fan_out="per_platform_account",
        requires_date_range=True,
        date_range_keys=("collected_from", "collected_to"),
    ),
    EndpointSpec(
        entity="tracking_link_users",
        path="/api/v0/platforms/{platform}/accounts/{platform_account_id}/tracking-link-users",
        available=True,
        description="Fans who arrived via a tracking link.",
        pagination="cursor",
        items_key="items",
        cursor_key="cursor",
        path_params=("platform", "platform_account_id"),
        fan_out="per_platform_account",
        requires_date_range=True,
        date_range_keys=("collected_from", "collected_to"),
    ),
    # ── Read-only but disabled: no safe chat_id discovery ──────────────────
    EndpointSpec(
        entity="messages",
        path="/api/v0/accounts/{account_id}/chats/{chat_id}/messages",
        available=False,
        requires_dynamic_discovery=True,
        description=(
            "Read-only message history. Disabled — the v0.30.0 OpenAPI "
            "surface does not expose a `chats` list endpoint, so chat_id "
            "cannot be safely enumerated.  Re-enable once OnlyMonster ships "
            "a chat-listing endpoint."
        ),
        pagination="cursor",
        items_key="items",
        cursor_key="cursor",
        path_params=("account_id", "chat_id"),
        fan_out="per_account",
    ),
    # ── Write endpoints — INVENTORY ONLY, never fired by sync ──────────────
    EndpointSpec(
        entity="messages_send",
        path="/api/v0/accounts/{account_id}/chats/{chat_id}/messages",
        method="POST",
        available=False,
        write=True,
        description="POST a chat message. NEVER fired by sync.",
        path_params=("account_id", "chat_id"),
    ),
    EndpointSpec(
        entity="vault_upload_start",
        path="/api/v0/accounts/{account_id}/vault/medias/uploads/start",
        method="POST",
        available=False,
        write=True,
        description="Start a vault upload. NEVER fired by sync.",
        path_params=("account_id",),
    ),
    EndpointSpec(
        entity="vault_upload_finish",
        path="/api/v0/accounts/{account_id}/vault/medias/uploads/finish",
        method="POST",
        available=False,
        write=True,
        description="Finish a vault upload. NEVER fired by sync.",
        path_params=("account_id",),
    ),
    EndpointSpec(
        entity="vault_upload_retry",
        path="/api/v0/accounts/{account_id}/vault/medias/uploads/{upload_id}/retry",
        method="POST",
        available=False,
        write=True,
        description="Retry a failed vault upload. NEVER fired by sync.",
        path_params=("account_id", "upload_id"),
    ),
    EndpointSpec(
        entity="vault_upload_export",
        path="/api/v0/accounts/{account_id}/vault/medias/uploads/export",
        method="POST",
        available=False,
        write=True,
        description="Export an uploaded media into the vault. NEVER fired by sync.",
        path_params=("account_id",),
    ),
    EndpointSpec(
        entity="vault_upload_fan_verify",
        path="/api/v0/accounts/{account_id}/vault/medias/uploads/fans/verify",
        method="POST",
        available=False,
        write=True,
        description="Verify fan link before vault export. NEVER fired by sync.",
        path_params=("account_id",),
    ),
)


def find(entity: str) -> EndpointSpec | None:
    for spec in ENDPOINT_CATALOG:
        if spec.entity == entity:
            return spec
    return None


def supported_entities() -> list[str]:
    """Public list of entity names — drives the /status response."""
    return [spec.entity for spec in ENDPOINT_CATALOG]


def enabled_read_entities() -> list[str]:
    """Entities the sync orchestrator should actually drive."""
    return [
        spec.entity
        for spec in ENDPOINT_CATALOG
        if spec.available and not spec.write and not spec.requires_dynamic_discovery
    ]
