# Redaction log

What was committed verbatim, what was redacted into an example/schema, and
what was skipped entirely. Verified on `2026-05-21`.

## Committed verbatim (no private data)

| File | Why safe |
|---|---|
| `server.py` | HTTP server code only — no recipient data, no tokens. |
| `dashboards/xdashboard.html` | UI markup + inline CSS/JS — references endpoints, contains no committed recipient data. |
| `dashboards/blast_dashboard.html` | Same as above. |
| `bots/dm_bot.py` | Bot logic — reads private files at runtime but does not embed them. |
| `bots/blast_bot.py` | Same. |
| `bots/repost_bot.py` | Same. |
| `bots/builder_bot.py` | Same. |
| `bots/scan_test.py` | Read-only scanner — same reasoning. |
| `bots/safety_guard.py` | Safety gate — no private data; lists env-flag names only. |
| `bots/_preflight.py` | Shared preflight — same reasoning. |
| `bots/campaign.py` | Orchestrator — same reasoning. |

## Redacted into example / schema files

| Live file | Reason | Snapshot path | What was removed |
|---|---|---|---|
| `auftrag.json` | Real AdsPower user IDs + per-account message bodies | `examples/auftrag.example.json` | All `user_id`, `name`, `username`, `message` values |
| `repost_auftrag.json` | Real AdsPower user IDs + real tweet URLs | `examples/repost_auftrag.example.json` | All `user_id`, `name`, `links` values |
| `blast_auftrag.json` | Real sender IDs + recipient source key + message body | `examples/blast_auftrag.example.json` | All `user_id`, `name`, `message`, `source_user_id` values |
| `builder_auftrag.json` | Real AdsPower user ID + account name | `examples/builder_auftrag.example.json` | All `user_id`, `name` values |
| `campaign_auftrag.json` | Real sender accounts + real tweet URLs + real message body | `examples/campaign_auftrag.example.json` | All real IDs, URLs, and bodies |
| `promo_groups.json` | Luis's AdsPower profile keys grouped by name | `examples/promo_groups.example.json` | Real IDs → placeholders like `profile-id-1` |
| `contacts.json` | Real X handles + chat URLs per AdsPower user | `examples/contacts.schema.json` | Replaced with JSON Schema describing shape |
| `follower_lists.json` | Scraped X handles | `examples/follower_lists.schema.json` | Replaced with JSON Schema describing shape |

## Tiny safe JSONs committed verbatim

These contain no private data on the running system. They are committed
verbatim so future operators can see exactly what shape the local
dashboard reads / writes for these tiny files.

| File | Size | Content |
|---|---|---|
| `examples/schedule.example.json` | tiny | `{ "enabled": false, "time": "20:45" }` (verbatim) |
| `examples/chats.example.json` | tiny | `{ "chats": [] }` (verbatim) |
| `examples/confirm.example.json` | tiny | `{ "confirmed": false, "selected": [] }` (verbatim) |

## Skipped entirely (not committed in any form)

| Live file | Reason |
|---|---|
| `*_status.json` (status / blast_status / repost_status / builder_status / campaign_status) | Live operator state — may include current account name, last action, and time-bound log entries. The shape is documented in the bot source code; not duplicated here. |
| `*_log.json` (blast_log / repost_log) | **Real DM bodies + recipient handles**. Hard skip. |
| `preflight_status.json` | Real account names + last preflight result. Skipped. |
| `.env`, `.env.*`, `*.env` | Secrets (AdsPower API key, runner token, etc). Skipped. |
| Any cookies / sessions / browser profile data | These are stored by AdsPower / Playwright outside the bot folder. Out of scope. |

## What changes between this snapshot and the live system

The bot scripts in `bots/` reflect the state on luis-pc-1 as of
`2026-05-21`, including the `--dry-run` argparse + `1×1 live cap` additions
made earlier in the same session. Future edits Luis makes locally are
**not** reflected here until the snapshot is manually refreshed via a
follow-up PR.

The HTML dashboards in `dashboards/` reflect the same date. Same caveat.

## Mission Control does not execute anything from this folder

Nothing under `integrations/luis-rtxrt-source/` is imported by the
frontend bundle, the backend, the runner, or CI. It is reference-only.
The MSA RT/X React dashboard is hand-ported from `xdashboard.html` —
it does not parse it at runtime.
