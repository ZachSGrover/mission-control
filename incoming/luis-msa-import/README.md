# Luis MSA Import

This is Luis's MSA (Model-Management-Agentur) tooling, imported on 2026-05-12 onto branch `coo/import-luis-msa`. Code lives under [MSA/](MSA/) and is meant to keep working as Luis built it — just with secrets and client data kept out of git.

## What this project does

One Python HTTP server (`MSA/Monthly revenue/server.py`, port 8765) serving three loosely-coupled components:

1. **Model Revenue** — pulls revenue + payments from two Notion DBs into `data.json`, renders `dashboard.html`. Read-only against Notion.
2. **Automation [RTxRT]** — X (Twitter) DM blast / repost / follower-scrape bots. Drives AdsPower-managed X profiles via Playwright. Live-action.
3. **Automation [Content]** — Per-model content strategy generator that calls Anthropic Claude Haiku 4.5 from the `/analyze` endpoint.

Dashboards:
- `http://localhost:8765/` — Revenue
- `http://localhost:8765/xdashboard` — RTxRT bot console
- `http://localhost:8765/models-dashboard` — Content strategy

## How Luis runs it locally

1. Copy `MSA/.env.example` to `MSA/.env` and fill in real values:
   - `ADSPOWER_API_KEY` — from AdsPower app → Settings → API
   - `ANTHROPIC_API_KEY` — Anthropic console
   - `NOTION_API_KEY` — Notion integration token; share both DBs with the integration
2. Put real client data files into `MSA/private_data_DO_NOT_COMMIT/` mirroring the original paths (or copy them back to where the code expects them). See "Where real client data lives" below.
3. Install deps (no `requirements.txt` was provided; observed imports):
   ```
   pip install requests playwright anthropic
   playwright install chromium
   ```
4. Start the server:
   ```
   cd "MSA/Monthly revenue"
   python server.py
   ```
5. Bots default to DRY mode and refuse to run live unless **both** `DRY_RUN=false` and `ALLOW_LIVE_EXTERNAL_ACTIONS=true`. See "Dry-run / live mode" below.

## Where to put real `.env` values

`MSA/.env` — gitignored. Use `MSA/.env.example` as the template.

## Where real client data lives

Everything moved during import is in `MSA/private_data_DO_NOT_COMMIT/`, with the same relative paths as the originals. To put a file back where the code expects it, copy or symlink from that folder into `MSA/Monthly revenue/...`.

Examples:
- Revenue cache: `MSA/private_data_DO_NOT_COMMIT/Monthly revenue/data.json` → `MSA/Monthly revenue/data.json`
- RTxRT state: `MSA/private_data_DO_NOT_COMMIT/Monthly revenue/Automation [RTxRT]/*.json` → `MSA/Monthly revenue/Automation [RTxRT]/`
- Per-model briefs: `MSA/private_data_DO_NOT_COMMIT/Monthly revenue/Automation [Content]/{mike-mains,valerie,zach-grover}/` → `MSA/Monthly revenue/Automation [Content]/`

Why the move: those files contain real revenue numbers, model names, X handles, follower lists, DM bodies, OnlyFans links, and personas. They're useful at runtime, not in commits.

## Which files are not committed

See [MSA/.gitignore](MSA/.gitignore). Summary:
- `.env`
- All run state / data dumps (`data.json`, `contacts*.json`, `follower_lists*.json`, `blast_*.json`, `repost_*.json`, `status*.json`, `*_auftrag.json`, `promo_groups.json`, `models.json`, `chats.json`, `confirm.json`)
- `logs/`, `*.log`
- `private_data_DO_NOT_COMMIT/` (whole tree)
- Per-model client folders under `Automation [Content]/`
- `*.docx`, `*.jpeg`, `*.jpg`
- Local DBs, sessions, cookies, Python bytecode

Source code, dashboards, briefings, README, audit, `.example` files, and the `safety_guard.py` module **are** committed.

## Dry-run / live mode

Bots that touch X / AdsPower (`blast_bot.py`, `dm_bot.py`, `repost_bot.py`, `builder_bot.py`, `scan_test.py`) start with a call to `safety_guard.require_live_or_exit()`. They refuse to run unless **both**:

```
DRY_RUN=false
ALLOW_LIVE_EXTERNAL_ACTIONS=true
```

Default: `DRY_RUN=true`, `ALLOW_LIVE_EXTERNAL_ACTIONS=false` — the guard exits with code 2. Today the guard is a single entry-point check, not a full simulate-everything dry-run. A deeper dry-run (where every Playwright `.click()` / `.fill()` becomes a logged no-op) is a follow-up if you want it.

## What is risky / live

- **`blast_bot.py`, `dm_bot.py`** — send real DMs on x.com via Playwright. Guarded by `safety_guard`.
- **`repost_bot.py`** — reposts on x.com. Guarded.
- **`builder_bot.py`** — scrapes follower lists + chat lists. Guarded.
- **`scan_test.py`** — opens an AdsPower profile and scans the message grid. Guarded.
- **`server.py`** endpoints `/start-bot`, `/ads-profiles`, `/ads-clean-cache` hit AdsPower's local API. Not guarded by `safety_guard` — the server itself is plumbing; only running the bots actually clicks anything. AdsPower endpoints require `ADSPOWER_API_KEY` from env now.
- **`notion_sync.py`** — `POST /sync` reads from Notion and overwrites `data.json`. Read-only against Notion.
- **`/analyze`** — calls Anthropic API on a model profile. Paid endpoint.

## How this should eventually map into Mission Control

Not a now-decision; documenting the natural shape so the eventual move is obvious:

- **Model Revenue** → Modern Sales Agency → Revenue sub-page, fed from MC's existing backend (not a local JSON cache).
- **Automation [Content]** → OnlyFans Intelligence or MSA → Content, as a Tool. The `/analyze` call moves into MC's FastAPI backend.
- **Automation [RTxRT]** → a Bot under MSA, behind a feature flag, with the `safety_guard` keeping live mode opt-in. Stays as-is here until that path is built.

Until that move, keep building in `MSA/` exactly the way Luis is used to.

## See also

- [IMPORT_AUDIT.md](IMPORT_AUDIT.md) — exactly what was preserved, moved, or changed during this import.
- [MSA/.env.example](MSA/.env.example) — env var template.
- [MSA/.gitignore](MSA/.gitignore) — ignore rules.
- [MSA/Monthly revenue/PROJECT_BRIEFING.md](MSA/Monthly%20revenue/PROJECT_BRIEFING.md) — Luis's Revenue briefing.
- [MSA/Monthly revenue/Automation [RTxRT]/BRIEFING.md](MSA/Monthly%20revenue/Automation%20%5BRTxRT%5D/BRIEFING.md) — Luis's RTxRT briefing.
- [MSA/Monthly revenue/RECOVERY_README.md](MSA/Monthly%20revenue/RECOVERY_README.md) — Luis's recovery notes.
