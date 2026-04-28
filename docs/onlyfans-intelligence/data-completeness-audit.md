# OnlyFans Intelligence — Data Completeness Audit

**Date:** 2026-04-28
**Branch audited:** `feat/ofi-daily-qc-scheduler` (which sits on top of `feat/of-intelligence` PR #10).
**Source of truth:** `https://omapi.onlymonster.ai/docs/json` (om-api-service v0.30.0, 21 paths, 0 named schemas — schemas are inline).
**Scope:** read-only audit. No code changed.

---

## TL;DR

OnlyFans Intelligence currently ingests and **persists** about **35–40 % of the
useful upstream data** that OnlyMonster v0.30.0 exposes. Another **~25 %** is
fetched and counted in `of_intelligence_sync_logs` but **never lands in a
table** because no persister is wired (`vault_folders`, `vault_uploads`,
`user_metrics`, `trial_link_users`, `tracking_link_users`). The remaining
**~35 %** is unreachable today — either the upstream endpoint does not exist
(no `/chats`, no `/posts`, no `/stories`, no `/mass-messages`, no `/auto-messages`,
no `/webhooks`), or it depends on an ID we can't yet enumerate (`messages`
needs a `chat_id`; `vault_folder_medias` needs a `folder_id`).

Three tables (`of_intelligence_chats`, `of_intelligence_mass_messages`,
`of_intelligence_posts`) were created during the original migration based
on the original feature spec but have **0 rows and no upstream endpoint**.
They are ghost tables.

The single biggest blocker to replacing OnlyMonster is the absence of a
**chat-listing endpoint**. Without it we cannot enumerate conversations,
which means we cannot drive AI chatting, response-time QC, or per-fan
message memory.

The single biggest **quick win** is wiring `user_metrics` into a real
table — that endpoint already gives us per-chatter `reply_time_avg`,
`paid_messages_price_sum`, `tips_amount_sum`, `work_time`, plus AI/template
usage breakdowns. It's the chatter QC signal we've been treating as
"unavailable until /chats lands" — it's actually available right now.

---

## A. What we currently collect successfully

For each entity below: **enabled in catalog → fetched on every sync run →
persisted into a dedicated OFI table → deduplicated by a stable key**.

| Entity | Path | Table | Dedup key | Live row count |
|---|---|---|---|---|
| `accounts` | `GET /api/v0/accounts` | `of_intelligence_accounts` | `(source, source_id)` | **23** |
| `account_details` | `GET /api/v0/accounts/{id}` | merges into `of_intelligence_accounts.raw` | same | (refresh-only) |
| `fans` | `GET /api/v0/accounts/{id}/fans` | `of_intelligence_fans` | `(source, source_id)` | **859** |
| `members` (→ chatters) | `GET /api/v0/members` | `of_intelligence_chatters` | `(source, source_id)` | **24** |
| `transactions` | `GET /api/v0/platforms/{p}/accounts/{a}/transactions` | `of_intelligence_revenue` | `(source, source_external_id)` partial unique index | **4 013** distinct |
| `chargebacks` | `GET /api/v0/platforms/{p}/accounts/{a}/chargebacks` | `of_intelligence_revenue` (negative-cents rows, `breakdown.kind="chargeback"`) | same dedup index | (counted in 4 013 above) |
| `trial_links` | `GET /api/v0/platforms/{p}/accounts/{a}/trial-links` | `of_intelligence_tracking_links` (prefixed `trial:<id>`) | `(source, source_id)` upsert | **(part of 11)** |
| `tracking_links` | `GET /api/v0/platforms/{p}/accounts/{a}/tracking-links` | `of_intelligence_tracking_links` (prefixed `tracking:<id>`) | same | **(part of 11)** |

Total persisted rows across these tables: **23 accounts · 24 chatters ·
859 fans · 4 013 revenue events · 11 link rows**. Every dedup key has been
verified as `rows == distinct_keys` in production data.

## B. What we store permanently

The migration `a8c4f1e2d703_add_of_intelligence_tables.py` (squashed in the
cleanup pass) creates **13 tables**:

| Table | Columns | Currently populated? |
|---|---|---|
| `of_intelligence_accounts` | 10 | yes (23) |
| `of_intelligence_fans` | 11 | yes (859) |
| `of_intelligence_chatters` | 10 | yes (24) |
| `of_intelligence_revenue` | 14 (incl. `source_external_id`) | yes (4 013) |
| `of_intelligence_tracking_links` | 11 | yes (11) |
| `of_intelligence_sync_logs` | 17 (incl. 5 counter cols + `source_endpoint`) | yes (1 762) |
| `of_intelligence_qc_reports` | 9 | yes (1 from scheduler test) |
| `of_intelligence_alerts` | 13 | yes (alerts engine writes here when rules trigger) |
| `business_memory_entries` | 15 | yes (mirrors QC reports + Obsidian exports) |
| `of_intelligence_chats` | 10 | **0 — ghost table, no upstream endpoint** |
| `of_intelligence_messages` | 13 | **0 — endpoint exists but blocked on chat_id discovery** |
| `of_intelligence_mass_messages` | 11 | **0 — no upstream endpoint** |
| `of_intelligence_posts` | 10 | **0 — no upstream endpoint** |

The `raw` JSON column on every entity table preserves the full upstream
payload — schema changes upstream don't need a migration; the persister
just starts using the new fields when ready.

## C. What is deduped and safe

- **Revenue** — `(source, source_external_id)` partial unique index in
  Postgres rejects duplicate transactions/chargebacks at the DB level.
  The persister generates a stable key from the upstream `id` (or a
  deterministic SHA-256 over endpoint+account+timestamp+amount+fan+type+status
  if the id is missing). **Verified live: two consecutive Sync Now clicks
  produced identical revenue totals; second sync reported `transactions:
  3866 skipped_duplicate, 0 created`.**
- **Accounts / fans / chatters / chats / messages** — all use a
  `(source, source_id)` UNIQUE constraint at the table level. The
  persisters do an explicit lookup-then-update-or-insert.
- **Tracking links** — same `(source, source_id)` upsert by the persister,
  but the underlying constraint is `(source, source_id, snapshot_at)` so
  history-style appends are still possible if we want them later.
- **Sync logs** — append-only, indexed by `(run_id, entity)` — never deduplicated
  (it's an audit trail, by design).
- **QC reports** — append-only by `report_date`. The Daily QC scheduler
  enforces 1-per-UTC-day before generating; manual generations also
  count.
- **Alerts** — open alerts are deduplicated by `(code, account_source_id)`
  while still in `status="open"` so the same condition does not fire a
  second alert until acknowledged or resolved.

## D. What is partially collected

These endpoints **fetch successfully** every sync run, but the data goes
nowhere — only the count appears in `of_intelligence_sync_logs`.
Implementing a persister for each is **purely additive**: a new SQLModel
class + a new migration creating the table + a `_persist_<entity>`
function in `sync.py`. No changes to the catalog, client, or scheduler.

| Entity | Path | Page-limit reality | Why it matters |
|---|---|---|---|
| `vault_folders` | `GET /api/v0/accounts/{id}/vault/folders` | OpenAPI says **5 req/sec** (catalog enforces `limit ≤ 10`) | Folder-level inventory: `videos_count`, `photos_count`, `gifs_count`, `audios_count`. Required first step before vault folder media listing fan-out. |
| `vault_uploads` | `GET /api/v0/accounts/{id}/vault/medias/uploads` | OpenAPI says **3 req/sec** | Upload status, `metadata.{name,size,content_type,duration,export_type,export_fan_id,rf_guest,rf_partner,rf_tag}`. Direct path to vault organization / fan-targeted media tracking. |
| `user_metrics` | `GET /api/v0/users/metrics` | 15 req/sec | **The single richest endpoint we ignore.** Per-chatter: `messages_count`, `reply_time_avg`, `paid_messages_count/price_sum`, `sold_messages_count/price_sum`, `tips_amount_sum`, `chargedback_*_sum`, `purchase_interval_avg/min/max`, `posts_count`, `deleted_posts_count`, `work_time`, `break_time`, `template_messages_count`, `copied_messages_count`, `ai_generated_messages_count`. **This is the chatter-QC signal we've been describing as "unavailable until /chats lands" — it's actually here today.** |
| `trial_link_users` | `GET /api/v0/platforms/{p}/accounts/{a}/trial-link-users` | 15 req/sec | `link_id`, `fan.{id,name,username}`, `subscribed_at`, `collected_at`. Maps trial campaign → individual fan acquisition. |
| `tracking_link_users` | same shape, tracking-link variant | 15 req/sec | Same — but for evergreen tracking links. Combined with `trial_link_users` this is our **traffic-source-to-fan** mapping. Combined with `transactions[].fan.id` we can derive **traffic-source-to-revenue**. |

## E. What is completely missing

### E.1 Endpoints that do not exist on OnlyMonster v0.30.0

| Logical entity | Status | Reason |
|---|---|---|
| **chats** (`/chats` listing) | does not exist | No way to enumerate conversations on an account. This is the gating issue for messages, response-time, fan-thread memory. |
| **mass messages** (`/mass-messages`) | does not exist | Cannot pull historical or in-flight DM blasts. The original spec listed it; OnlyMonster does not expose it. `of_intelligence_mass_messages` is a ghost table. |
| **auto messages** (`/auto-messages`) | does not exist | Cannot inspect drip campaigns. |
| **posts** (`/posts`) | does not exist | Cannot enumerate wall posts. Aggregated counts are visible via `users/metrics.posts_count` and `deleted_posts_count`. `of_intelligence_posts` is a ghost table. |
| **stories** (`/stories`) | does not exist | Cannot inspect any story content or analytics. |
| **subscriptions** (`/subscriptions`) | does not exist as a list | Subscription events are visible inside transactions (`type` field includes `recurring subscription`); no dedicated endpoint. |
| **PPV** (`/ppv-performance`) | does not exist as a list | PPV events visible inside transactions (`type` includes `Payment for message`, `post purchase`, etc.); no dedicated endpoint. |
| **traffic-metrics** (`/traffic-metrics`) | does not exist | Closest signal is `tracking_link_users` + `trial_link_users` joined back to `transactions[].fan.id`. |
| **team-performance** (`/team-performance`) | does not exist as a list | But `users/metrics` is per-user and includes work_time / break_time, so team rollups can be computed locally. |
| **account-insights** (`/account-insights`) | does not exist | No upstream signal. |
| **webhooks** | does not exist | OnlyMonster has no operator-facing webhook surface in v0.30.0. All ingest is poll-based. |
| **explicit access status flag** | does not exist | We currently derive `access_status` from `subscription_expiration_date` (active/expired/unknown). There is no upstream "lost access" / "blocked" / "auth failed" signal. |

### E.2 Read-only endpoints that exist but are gated on missing IDs

| Entity | Path | Blocked because |
|---|---|---|
| `messages` (read) | `GET /api/v0/accounts/{a}/chats/{chat_id}/messages` | requires `chat_id` and there's no `/chats` enumeration. Endpoint **catalog flag** is `requires_dynamic_discovery=True`. Response data is rich (`text`, `from_user`, `is_sent_by_me`, `media[]`, `price`, `is_free`, `is_new`, `is_opened`, `media_count`) and would directly enable AI chat, fan history, response-time QC. |
| `vault_folder_medias` | `GET /api/v0/accounts/{a}/vault/folders/{folder_id}/medias` | requires `folder_id`. We sync `vault_folders` (which returns folder ids) but the orchestrator has no folder-level fan-out yet. **Catalog flag** is `requires_dynamic_discovery=True`. |
| `vault_media_thumbnail` | `GET /api/v0/accounts/{a}/vault/media/{media_id}/thumbnail` | binary stream, returns image bytes. Not a sync target — only useful for direct UI fetches. |

### E.3 Mutating endpoints — disabled by design

The catalog inventories all 6 mutating endpoints with `available=False, write=True`.
The client refuses each at the entrypoint with `reason="write_disabled"` —
no network call possible. They will remain disabled until and unless we
explicitly build out OnlyFans-side actions:

- `POST /api/v0/accounts/{a}/chats/{chat_id}/messages` — send DM
- `POST /api/v0/accounts/{a}/vault/medias/uploads/start`
- `POST /api/v0/accounts/{a}/vault/medias/uploads/finish`
- `POST /api/v0/accounts/{a}/vault/medias/uploads/{upload_id}/retry`
- `POST /api/v0/accounts/{a}/vault/medias/uploads/export`
- `POST /api/v0/accounts/{a}/vault/medias/uploads/fans/verify`

---

## F. Coverage matrix

One row per OnlyMonster endpoint. Sorted in catalog order so it matches
the sync-orchestrator execution order.

### F.1 Read endpoints

| # | Endpoint | Method | Read/Write | Enabled | Synced | Persisted | Destination table | Dedup key | Pagination | Required IDs | Returns | Why it matters | Current limitation | Recommended next |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `/api/v0/accounts` | GET | read | yes | yes | **yes** | `of_intelligence_accounts` | `(source, source_id)` | cursor (`nextCursor`) | none | per-account `id`, `platform`, `platform_account_id`, `username`, `name`, `email`, `avatar`, `organisation_id`, `subscribe_price`, `subscription_expiration_date` | The discovery root. Drives every per-account / per-platform fan-out. | none — works | keep as-is |
| 2 | `/api/v0/accounts/{account_id}` | GET | read | yes | yes (per-account) | merges into `accounts.raw` | same row | same | none | account_id | same fields as #1 | Refreshes the row's `raw` snapshot — useful for fields we don't promote to columns yet. | identical payload to /accounts list — no extra info | low priority; could deprecate if /accounts is up to date |
| 3 | `/api/v0/accounts/{account_id}/fans` | GET | read | yes | yes (per-account) | **yes** | `of_intelligence_fans` | `(source, source_id)` | none (max 10 000 per call) | account_id | `fan_ids[]` only — bare ID list | Fan inventory per account ("based on recent chat activity"). | (a) Returns IDs only — no fan profile/name/username/spend. (b) Catalog-level rate limit is **wrong** — endpoint is **1 req/sec** (we treat as 15/sec), causes intermittent 429s on big runs. (c) "Recent chat activity" filter means we miss long-quiet fans. | **Lower the rate limit to 1 req/sec for this endpoint.** Cross-reference with `tracking_link_users.fan.{id,name,username}` and `transactions[].fan.id` to enrich. |
| 4 | `/api/v0/accounts/{account_id}/vault/folders` | GET | read | yes | yes (per-account) | **no — counted only** | (none) | n/a | offset/limit (max 10) | account_id | `id`, `type`, `name`, `has_media`, `can_update`, `can_delete`, `videos_count`, `photos_count`, `gifs_count`, `audios_count` | Vault inventory + media-type breakdown per folder. Required precursor for folder-level media listing. | Not persisted. Catalog claims default rate limit; OpenAPI says **5/sec**. | Add `of_intelligence_vault_folders` table + persister + lower rate limit. Then enable `vault_folder_medias` fan-out. |
| 5 | `/api/v0/accounts/{account_id}/vault/folders/{folder_id}/medias` | GET | read | **no** | no | no | (none) | n/a | offset/limit (max 10) | account_id, **folder_id** | media `id`, `type`, `can_view`, `is_ready`, `has_error`, `converted_to_video`, `created_at`, `thumbnail_url` | The actual vault media list. Required for AI vault organization, "find me all videos tagged X" workflows. | `requires_dynamic_discovery=True` — orchestrator only fans out over accounts, not over folders within accounts. Rate limit should be 5/sec. | Wire folder-level fan-out: after `vault_folders` persists, iterate folders and call this endpoint per (account_id, folder_id). |
| 6 | `/api/v0/accounts/{account_id}/vault/media/{media_id}/thumbnail` | GET | read (binary) | n/a | n/a | n/a | (none — image bytes) | n/a | none | account_id, media_id | binary image | Not a sync target — only consumed by UI when rendering thumbnails on demand. | n/a | leave as on-demand |
| 7 | `/api/v0/accounts/{account_id}/vault/medias/uploads` | GET | read | yes | yes (per-account) | **no — counted only** | (none) | n/a | offset/limit | account_id | `id`, `status`, `media_id`, `metadata.{name,size,content_type,duration,key,e_tag,get_url,export_type,export_fan_id,rf_guest[],rf_partner[],rf_tag[]}`, `created_at`, `updated_at` | Upload pipeline state — which media is in progress, exported, or failed. `metadata.export_fan_id` shows which fan a vault export was earmarked for; `rf_*` fields look like reference / referrer tagging. | Not persisted. Rate limit should be 3/sec. | Add `of_intelligence_vault_uploads` table + persister; expose in UI as a "vault pipeline" view. |
| 8 | `/api/v0/members` | GET | read | yes | yes | **yes** | `of_intelligence_chatters` | `(source, source_id)` | offset/limit (max **50**) | none | `id`, `avatar`, `name`, `email`, `createdAt`, `customName` | Org members → chatters table. | We do not persist `customName` or `createdAt` to dedicated columns — only via `raw`. Page limit override is correct (50). | Promote `customName` and `createdAt` to columns when needed. |
| 9 | `/api/v0/users/metrics` | GET | read | yes | yes | **no — counted only** | (none) | n/a | offset/limit, **start/end required** | none — but `creator_ids`, `user_ids`, `account_group_id`, `role_id` filters available | per-user: `fans_count`, `messages_count`, `template_messages_count`, `ai_generated_messages_count`, `copied_messages_count`, `media_messages_count`, `paid_messages_count`, `paid_messages_price_sum`, `words_count_sum`, `unsent_messages_count`, `purchase_interval_{avg,min,max}`, `reply_time_avg`, `posts_count`, `deleted_posts_count`, `work_time`, `break_time`, `sold_messages_{count,price_sum}`, `total_sold_messages_{count,price_sum}`, `sold_posts_{count,price_sum}`, `total_sold_posts_{count,price_sum}`, `tips_amount_sum`, `total_tips_amount_sum`, all `chargedback_*` variants, `internal_templates_count` | **The single richest endpoint we ignore.** This is per-chatter / per-creator KPIs over a date window. Direct path to chatter QC, marketing QC, AI-vs-human style analysis, work-time tracking, posting cadence, refund rate per creator. | Not persisted. We've been wrongly describing chatter QC as blocked on /chats — `reply_time_avg` and `paid_messages_price_sum` are right here. | **Highest-leverage build.** Add `of_intelligence_user_metrics` time-series table (one row per (user_id, period_start, period_end)). Pull daily; long-term retention. |
| 10 | `/api/v0/platforms/{p}/accounts/{a}/transactions` | GET | read | yes | yes (per-platform) | **yes** | `of_intelligence_revenue` (one row per txn) | `(source, source_external_id)` partial unique index | cursor, **start/end required** | platform, platform_account_id | `id`, `amount`, `fan.id`, `type` (Tip from / Payment for message / recurring subscription / post purchase / live stream / unknown), `status` (done / loading / pending return), `timestamp` | Money. Maps revenue → fan. Tip / PPV / sub / post-purchase classification. | Currently only buckets last 30 d (`requires_date_range=True` defaults to now-30d). Long-term backfill would need explicit `start` override. | Make the date range configurable per account (last full sync timestamp + small overlap) for incremental long-term ingestion. |
| 11 | `/api/v0/platforms/{p}/accounts/{a}/chargebacks` | GET | read | yes | yes (per-platform) | **yes** | `of_intelligence_revenue` (negative cents, `breakdown.kind=chargeback`) | same index | cursor, **start/end** | platform, platform_account_id | `id`, `amount`, `fan.id`, `type`, `status`, `chargeback_timestamp`, `transaction_timestamp` | Refund tracking. Joined with original transactions, identifies fans / chatters / mass-messages with elevated chargeback rates. | Same 30-day window. We don't yet correlate chargeback id → original transaction id (the API doesn't link them either). | Add a `chargeback_of_transaction_id` resolver later if we build a model that needs it. |
| 12 | `/api/v0/platforms/{p}/accounts/{a}/trial-links` | GET | read | yes | yes | **yes** | `of_intelligence_tracking_links` (id prefixed `trial:<id>`) | `(source, source_id)` upsert | cursor, **start/end** | platform, platform_account_id | `id`, `name`, `claims`, `claims_limit`, `url`, `duration_days`, `expires_at`, `is_active`, `clicks`, `created_at` | Free-trial campaign performance. | none of significance | keep |
| 13 | `/api/v0/platforms/{p}/accounts/{a}/tracking-links` | GET | read | yes | yes | **yes** | same table (`tracking:<id>`) | same | cursor, **start/end** | platform, platform_account_id | `id`, `name`, `subscribers`, `url`, `is_active`, `clicks`, `created_at` | Evergreen tracking-link campaign performance. | Subscribers count is aggregate; per-subscriber breakdown is in `tracking_link_users`. | keep |
| 14 | `/api/v0/platforms/{p}/accounts/{a}/trial-link-users` | GET | read | yes | yes | **no — counted only** | (none) | n/a | cursor (no required date) | platform, platform_account_id, optional `link_id` | `link_id`, `fan.{id,name,username}`, `subscribed_at`, `collected_at` | **Traffic source → fan acquisition mapping.** Joined with `transactions[].fan.id` this gives traffic-source → revenue. | Not persisted. Lifetime data with no date range — important for full traffic backfill. | Add `of_intelligence_link_acquisitions` table (or a join row in fans). |
| 15 | `/api/v0/platforms/{p}/accounts/{a}/tracking-link-users` | GET | read | yes | yes | **no — counted only** | (none) | n/a | cursor (no required date) | platform, platform_account_id, optional `link_id` | same shape as #14 | same purpose for evergreen tracking links | same | same |
| 16 | `/api/v0/accounts/{a}/chats/{chat_id}/messages` | GET | read | **no** | no | no | (`of_intelligence_messages` exists but empty) | `(source, source_id)` | cursor (uses `message_id` + `order`) | account_id, **chat_id** | `id`, `text`, `from_user`, `is_sent_by_me`, `created_at`, `media[].{id,type,can_view,is_ready,has_error,converted_to_video,created_at,thumbnail_url}`, `media_count`, `is_opened`, `is_new`, `price`, `is_free`, `can_purchase`, `can_purchase_reason` | Chat-level history. Drives AI chat, response-time-per-thread, fan memory, PPV unlock tracking. | `requires_dynamic_discovery=True` — there is no `/chats` listing endpoint, so we can't enumerate `chat_id`s to fan out. Rate limit should be 1/sec. | **Cannot be unblocked from our side.** Ask OnlyMonster for `/chats`. As an interim, we could hand-feed known chat_ids from operator input. |

### F.2 Mutating endpoints — disabled by design

| # | Endpoint | Method | Status | Reason |
|---|---|---|---|---|
| 17 | `/api/v0/accounts/{a}/chats/{c}/messages` | POST | disabled | `write=True`. Send-message via API. We will not enable until OFI is the sender of record. |
| 18 | `/api/v0/accounts/{a}/vault/medias/uploads/start` | POST | disabled | `write=True`. Vault upload init. |
| 19 | `/api/v0/accounts/{a}/vault/medias/uploads/finish` | POST | disabled | `write=True`. Vault upload commit. |
| 20 | `/api/v0/accounts/{a}/vault/medias/uploads/{upload_id}/retry` | POST | disabled | `write=True`. |
| 21 | `/api/v0/accounts/{a}/vault/medias/uploads/export` | POST | disabled | `write=True`. Vault → wall publish. |
| 22 | `/api/v0/accounts/{a}/vault/medias/uploads/fans/verify` | POST | disabled | `write=True`. Pre-flight fan-link check before vault export. |

---

## G. Critical-question answers

> **Are we syncing all accounts?**
Yes. The `accounts` endpoint paginates with `nextCursor`. Catalog default
query passes `withExpiredSubscriptions=true` so accounts whose subs lapsed
are still included. Live: 23 accounts captured.

> **Are we syncing all fans?**
Partially. The `accounts/{id}/fans` endpoint returns "fan IDs based on
recent chat activity" — fans who have not chatted recently are excluded.
Plus, the per-endpoint rate limit is **1 req/sec** but the rate limiter
treats it as the default 15/sec, which has caused intermittent
`429 Rate limit exceeded` on bigger sweeps. Fix: lower the per-endpoint
limit + iterate slowly. Until then we have 859 fans, but they're the
"recently active" subset.

> **Can we discover all chats?**
**No.** OnlyMonster v0.30.0 exposes no `/chats` listing endpoint. This is
the largest single blocker. The `of_intelligence_chats` table is a ghost
table.

> **Can we pull all messages?**
**No.** The `messages` endpoint exists and has rich data (`text`,
`from_user`, `is_sent_by_me`, `media`, `price`, `is_free`, `is_new`,
`is_opened`), but it requires a `chat_id` and there's no chat-listing
endpoint to enumerate them.

> **Can we pull mass-message history?**
**No.** No `/mass-messages` endpoint. `of_intelligence_mass_messages` is a
ghost table.

> **Can we pull post history?**
**No** — for individual posts. We can pull aggregated counts via
`users/metrics` (`posts_count`, `deleted_posts_count`, `sold_posts_count`,
`sold_posts_price_sum`, etc.), but not per-post text/media/timestamps.

> **Can we pull story history?**
**No.** No `/stories` endpoint. (Stories aren't even mentioned in
v0.30.0.)

> **Can we pull vault / media metadata?**
**Partially.** `vault_folders` and `vault_uploads` are fetched today (just
not persisted). `vault_folder_medias` is the per-folder media listing —
that's gated on folder-level fan-out which we haven't wired. The
binary `thumbnail` endpoint is on-demand, not sync-able.

> **Can we map revenue to fans?**
**Yes.** Every `transactions[]` and `chargebacks[]` row carries `fan.id`.
Joined to `of_intelligence_fans.source_id` it gives lifetime-value-per-fan.
Currently the persister only stores `fan.id` in the `breakdown` JSON; it
should also be promoted to a `fan_source_id` column for fast SQL joins.

> **Can we map revenue to chatters?**
**Partially.** Transactions don't carry a chatter id directly. But
`users/metrics` aggregates per-user revenue (`paid_messages_price_sum`,
`sold_messages_price_sum`, `tips_amount_sum`) over a window — once we
persist `user_metrics`, we have it at the daily level even though we
can't attribute a specific transaction to a specific chatter.

> **Can we map traffic source to revenue?**
**Yes, derivable.** Combine `tracking_link_users.fan.id` (or
`trial_link_users.fan.id`) with `transactions[].fan.id`: any fan who
arrived via link X had revenue Y. Requires persisting the link-users
endpoints (currently only counted in sync_logs).

> **Can we detect account access problems?**
**Partially.** No upstream "lost access" flag. We currently derive
`access_status` from `subscription_expiration_date` (active / expired /
unknown). We can also detect indirectly: an account that returned 0 fans
or 0 transactions for several runs while peers returned data is likely
broken. The sync-log error rows already surface auth failures (HTTP 401
on per-account calls).

> **Can we detect missed fans or stale conversations?**
**Partially / no.** "Missed fans" requires per-thread last-message-at —
that needs `messages` which is blocked. We can detect stale fans
(`first_seen_at` weeks ago, no new transaction) but not stale
conversations.

> **What is the biggest blocker to replacing OnlyMonster?**
The absence of a **chat-listing endpoint**. Without it:
- AI chatting cannot iterate over open conversations.
- Per-fan message memory cannot be built.
- Response-time-per-fan QC cannot be measured (only per-chatter aggregates
  via `users/metrics`).
- Mass-message replies cannot be tracked.
- "Missed fans" / "high-value fan ignored" alerts cannot fire.

Everything else is buildable today. The chat list is the single
inflection point.

---

## H. Recommended sequence

These are concrete next steps in priority order. Each step is independent
of the next so we can stop / re-prioritize at any boundary.

### H.1 Data ingestion

1. **Fix the per-endpoint rate-limit overrides** for the four limits
   currently mis-defaulted. Add `page_limit` (where applicable) and
   `per_endpoint_rate` to `EndpointSpec`, plumb the rate into
   `OnlyMonsterRateLimiter._endpoint_bucket`. Endpoints to override:
   `/api/v0/accounts/{a}/fans` → 1/sec; `/api/v0/accounts/{a}/chats/{c}/messages`
   → 1/sec; `/api/v0/accounts/{a}/vault/folders` → 5/sec;
   `/api/v0/accounts/{a}/vault/folders/{f}/medias` → 5/sec;
   `/api/v0/accounts/{a}/vault/medias/uploads` → 3/sec;
   `/api/v0/accounts/{a}/vault/media/{m}/thumbnail` → 3/sec.
   *Migration: none. New table: none.*

2. **Persist `user_metrics`** into `of_intelligence_user_metrics`
   (time-series; one row per `(user_id, period_start, period_end)`).
   Wire daily ingest with `from = now-1d, to = now` (and a one-time backfill
   to grab whatever history is available). Promote `reply_time_avg`,
   `paid_messages_price_sum`, `tips_amount_sum`, `work_time`, `break_time`,
   `template_messages_count`, `ai_generated_messages_count`,
   `copied_messages_count`, `chargedback_*` fields to columns. Keep `raw`
   for the rest. *Migration: 1 new table.*

3. **Persist `vault_folders`** into `of_intelligence_vault_folders` with
   columns for `videos_count` / `photos_count` / `gifs_count` /
   `audios_count`. Then **enable `vault_folder_medias`** by adding
   per-folder fan-out to the orchestrator (iterate persisted folders for
   each account). Persist into `of_intelligence_vault_media`. *Migration:
   2 new tables.*

4. **Persist `vault_uploads`** into `of_intelligence_vault_uploads` with
   `metadata.export_fan_id` promoted to a column so we can group uploads
   by intended-recipient fan. *Migration: 1 new table.*

5. **Persist `trial_link_users` + `tracking_link_users`** into a single
   `of_intelligence_link_acquisitions` table. Columns: `link_id`,
   `link_kind` (trial / tracking), `fan_source_id`, `subscribed_at`,
   `collected_at`. Adds the traffic-source-to-fan mapping. *Migration: 1
   new table.*

6. **Promote `fan_source_id` to a column** in `of_intelligence_revenue`
   (currently only in `raw.fan.id` and `breakdown.fan_id`). Backfill
   from `raw->'fan'->>'id'`. Indexed. Enables fast lifetime-value-per-fan
   queries and "high-value-fan-ignored" alerts when chats become
   discoverable. *Migration: 1 column.*

7. **Drop the ghost tables** (`of_intelligence_chats`,
   `of_intelligence_mass_messages`, `of_intelligence_posts`) — they are
   misleading. If chats become available in a future OnlyMonster
   version, recreate then. *Migration: 3 dropped tables.*

8. **Make transaction date-range incremental.** Currently every sync pulls
   the last 30 d. Track per-account `(source, account_source_id)`
   high-watermark in a small `of_intelligence_sync_cursors` table; pull
   `from = max(cursor, now - 30d)` so steady-state syncs only fetch new
   transactions. Big-bang backfill becomes a one-shot operation.
   *Migration: 1 new table.*

After steps 1-8 the data ingestion layer covers everything OnlyMonster
v0.30.0 actually exposes.

### H.2 Memory bank

9. **Mirror `user_metrics` rollups into `business_memory_entries`** as
   weekly per-creator notes ("Creator Alice last 7d: $X messages, Y replies,
   reply_time_avg Z s, chargedback W"). One row per `(creator_id, week)`.
   AI agents can search creator history without re-aggregating raw
   metrics tables. *Migration: none — uses existing table.*

10. **Mirror per-fan lifetime summaries into `business_memory_entries`**.
    Computed from `revenue.fan_source_id + acquisition link + first/last txn`.
    Refreshed weekly. Key insight: this is what an AI chatter needs to
    open a thread well. *Migration: none.*

11. **Daily sync digest into Obsidian export** — already wired, but extend
    the daily note to include the per-creator rollups from step 9 and
    fan-growth attribution from step 5. *No code changes; just template
    updates in `obsidian_export.py`.*

### H.3 QC bot

12. **Replace the chatter-QC placeholder** in `qc_bot.py` with real
    metrics from `of_intelligence_user_metrics`. The "Message-level
    chatter QC unavailable until chat discovery is wired" note can be
    deleted: per-chatter QC is doable today, just at the daily-aggregate
    level rather than per-message. Surface `reply_time_avg`,
    `template_vs_ai_vs_copied` ratios, `chargedback_messages_count` per
    chatter.

13. **Add per-account revenue-attribution to the QC report** — for each
    account, what % of revenue came from which traffic source? Possible
    once H.1 step 5 lands.

14. **Add "stale fan" detection** — fan with high lifetime value but no
    transaction in 14+ days. Real signal even without chat data.

### H.4 Real-time alerts (toward Discord)

15. **Add new alert rules** that depend on the H.1 data: revenue drop
    week-over-week (already in QC, lift into the alert engine for
    real-time), chargeback rate spike per chatter, vault upload
    failure rate, traffic-source dry-up.

16. **Build the Discord delivery layer.** The alert engine writes to
    `of_intelligence_alerts` today; the engine just needs a hook that
    POSTs each new (or escalated) alert to a configured Discord webhook.
    Use the existing `app/api/discord.py` patterns.

17. **Add a `daily_qc_report → Discord` poster** so the daily QC summary
    lands in Discord every morning. Reuses the same webhook config.

### H.5 Future CRM replacement

To actually replace OnlyMonster's CRM (rather than just observe it):

18. **Negotiate `/chats` endpoint with OnlyMonster.** Without it there is
    no path to AI chatting from inside Mission Control. If OnlyMonster
    won't expose it, the long-term path requires either browser-level
    automation (similar to OpenClaw) or migrating away from OnlyMonster
    as the chat hub.

19. **Build the operator-side chat ingest fallback** — a small UI where
    operators paste known chat_ids; we then enable `messages` per pasted
    `(account_id, chat_id)`. Bridge until step 18 lands.

20. **Replace mutating actions** (`messages_send`, vault upload pipeline)
    one at a time, behind explicit feature flags + per-account allow-lists.
    Each action gets an audit row in `of_intelligence_actions` (new table)
    + Discord notification before-and-after.

21. **CRM views in Mission Control** — fan timeline (from revenue +
    acquisitions + memory entries), creator dashboard (from user_metrics),
    chatter dashboard (from user_metrics + messages once chats land).

---

## Appendix — data we ARE storing successfully (at audit time)

```
                    table                    | rows  | dedup_correct
---------------------------------------------+-------+---------------
of_intelligence_accounts                     |    23 | yes
of_intelligence_chatters                     |    24 | yes
of_intelligence_fans                         |   859 | yes
of_intelligence_revenue                      | 4 013 | yes (by source_external_id)
of_intelligence_tracking_links               |    11 | yes
of_intelligence_qc_reports                   |     1 | (append-only; daily-unique enforced by scheduler)
of_intelligence_alerts                       |     0 | (rule engine writes when conditions trigger)
of_intelligence_sync_logs                    | 1 762 | (audit trail; intentionally not deduped)
business_memory_entries                      |     1 | (mirrors qc reports / exports)

GHOSTS (tables exist, no upstream endpoint):
of_intelligence_chats                        |     0 | n/a — no /chats endpoint
of_intelligence_messages                     |     0 | n/a — endpoint exists but blocked on chat discovery
of_intelligence_mass_messages                |     0 | n/a — no /mass-messages endpoint
of_intelligence_posts                        |     0 | n/a — no /posts endpoint
```

Total useful rows in OFI today: **6 933** across 8 populated tables, all
deduped at the DB or persister level. Steady-state daily growth (after
the H.1 work lands) is dominated by `transactions` (~150 / account / day),
`user_metrics` (~25 / day for the org), and `link_acquisitions`
(~10–50 / day). Hardware will not be the bottleneck for a long time.
