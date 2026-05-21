# `integrations/luis-rtxrt-source/` — Luis RT/X local dashboard, snapshot reference

This folder is a **point-in-time reference snapshot** of Luis's current working
local RT/X bot + dashboard, imported into Mission Control so the Digital OS
team has a single canonical place to read the source-of-truth interface and
workflow.

It is **not** the live system. Luis's working bot still runs from his own
folder on his runner PC (currently `luis-pc-1`). Nothing in this folder is
executed by Mission Control or by any deploy.

## Why this exists

The migration goal is:

1. Digital OS becomes the main RT/X operating interface at
   `https://hq.digidle.com/bots/msa-rtxrt`.
2. Luis's PC stays as the runner (where automation actually executes).
3. Luis's standalone localhost dashboard at `http://localhost:8765/xdashboard`
   becomes a working **backup / reference** once Digital OS is verified.

For Digital OS to faithfully match Luis's current interface, we need a
snapshot we can refer to inside the Mission Control repo without operators
needing to ssh into Luis's PC.

## What is inside

```
integrations/luis-rtxrt-source/
├── README.md               (this file)
├── REDACTION_LOG.md        what was redacted/skipped and why
├── server.py               local HTTP server that serves the dashboard
├── dashboards/
│   ├── xdashboard.html     5-tab RT/X dashboard
│   └── blast_dashboard.html  legacy blast view (still served via /blast-dashboard)
├── bots/
│   ├── dm_bot.py           DM bot (per-account chat sweeper)
│   ├── blast_bot.py        cross-account blast
│   ├── repost_bot.py       cross-account repost
│   ├── builder_bot.py      followers / chats list builder
│   ├── scan_test.py        read-only chat scanner
│   ├── safety_guard.py     --smoke + --gate-check
│   ├── _preflight.py       shared per-account preflight
│   └── campaign.py         DM-then-repost orchestrator
└── examples/
    ├── auftrag.example.json
    ├── repost_auftrag.example.json
    ├── blast_auftrag.example.json
    ├── builder_auftrag.example.json
    ├── campaign_auftrag.example.json
    ├── promo_groups.example.json
    ├── schedule.example.json
    ├── chats.example.json
    ├── confirm.example.json
    ├── contacts.schema.json
    └── follower_lists.schema.json
```

## What is the live source

The actual live versions of these files live on Luis's PC at:

```
C:\Users\Besitzer\Documents\Onedrive\Desktop\Luis Uni\MSA\Monthly revenue\
    server.py
    Automation [RTxRT]\
        xdashboard.html
        blast_dashboard.html
        dm_bot.py / blast_bot.py / repost_bot.py / builder_bot.py /
        scan_test.py / safety_guard.py / _preflight.py / campaign.py
        auftrag.json / blast_auftrag.json / repost_auftrag.json /
        builder_auftrag.json / campaign_auftrag.json /
        promo_groups.json / schedule.json / chats.json / confirm.json
        contacts.json / follower_lists.json
        *_status.json / *_log.json / preflight_status.json
```

Luis can keep editing those live files. **Drift between the live files and
this snapshot is expected** — the snapshot is reviewed and refreshed
manually, not auto-synced.

## What is NOT inside (and what to do instead)

The following live files contain real recipient handles, message bodies,
AdsPower profile IDs, or live status, so they are **not committed here**:

| Live file | What it contains | Reference in snapshot |
|---|---|---|
| `contacts.json` | Real X handles + AdsPower user IDs | `examples/contacts.schema.json` (shape only) |
| `follower_lists.json` | Scraped follower handles | `examples/follower_lists.schema.json` |
| `*_auftrag.json` | Current job queue with real account IDs + tweet URLs + message bodies | `examples/*.example.json` (placeholders) |
| `promo_groups.json` | Luis's AdsPower profile IDs grouped | `examples/promo_groups.example.json` (placeholder IDs) |
| `*_status.json` | Per-bot live status — may include account names | skipped entirely |
| `*_log.json` | Per-bot historical log — DM bodies + handles | skipped entirely |
| `preflight_status.json` | Per-account preflight result | skipped entirely |
| `.env`, cookies, sessions, AdsPower credentials, browser profile data | secrets | skipped entirely |

See `REDACTION_LOG.md` for the full redaction inventory.

## How to refresh this snapshot

When Luis lands a meaningful change to his local source and we want
Digital OS to mirror it:

1. Diff the live files vs this snapshot manually.
2. Copy the changed source code (`.py`, `.html`) verbatim if no private data.
3. Re-generate the affected `examples/*.example.json` if the schema changed.
4. Update `REDACTION_LOG.md` if any new file type was added.
5. Open a small PR titled `chore(rtxrt-source): refresh snapshot from luis-pc-1`.

## How Digital OS consumes this snapshot

`MsaRtxrtDashboard.tsx` and surrounding frontend code use this folder as
**developer reference only** — the React UI is hand-ported from the HTML
here, it does not parse it at runtime. The example JSON files are referenced
in component comments to document the expected shape of fields the local
bridge will eventually deliver.
