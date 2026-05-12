# MSA Import Audit

Branch: `coo/import-luis-msa`
Source: `/Users/zachary/Downloads/MSA.zip` (~46MB)
Date: 2026-05-12

## 1. What was imported

The entire MSA bundle was unzipped into [MSA/](MSA/). Three components share one folder:

- `MSA/Monthly revenue/` — Revenue dashboard (Notion → JSON → HTML).
- `MSA/Monthly revenue/Automation [RTxRT]/` — X/Twitter DM/repost/scraper bots driven by Playwright + AdsPower.
- `MSA/Monthly revenue/Automation [Content]/` — Per-model content briefs + `/analyze` LLM endpoint.

Plus a stray Windows installer `MSA/python/python-manager-26.1.msix` that's unused on macOS (kept for now — harmless, ignored by `.gitignore` patterns only if added to gitignore, otherwise left as a file).

## 2. What was preserved

Everything that's code or documentation, in its original location:

- `MSA/Monthly revenue/server.py` (with the AdsPower key removed — see §3)
- `MSA/Monthly revenue/notion_sync.py`
- `MSA/Monthly revenue/dashboard.html`
- `MSA/Monthly revenue/Automation [RTxRT]/blast_bot.py`, `dm_bot.py`, `repost_bot.py`, `builder_bot.py`, `scan_test.py`, `xdashboard.html`, `blast_dashboard.html`, `start_bot.bat`, `logo.jpg`, `Automation structures/` (including `backup_working_v1/`)
- `MSA/Monthly revenue/Automation [Content]/models-dashboard.html`
- All briefings: `PROJECT_BRIEFING.md`, `BRIEFING.md`, `COWORK_INSTRUCTIONS.txt`, `RECOVERY_README.md`, `PROJECT_INSTRUCTIONS.txt`, `claude-cowork-automation-bot-spec.md`
- The two `.env.example` files (root and `Monthly revenue/`)
- Small config files that don't contain client data: `chats.json` (empty), `confirm.json`, `schedule.json`

Project structure under `MSA/` is otherwise the same as Luis sent.

## 3. What secrets were replaced with env vars

| Where | Before | After |
|---|---|---|
| `MSA/Monthly revenue/server.py` line 120 (was) | hardcoded `ADS_KEY = "659e8c5…f647"` | reads `ADSPOWER_API_KEY` from env at module top; endpoint returns a clear error if unset |
| `MSA/Monthly revenue/server.py` line 496 (was) | same hardcoded key | same env-var reference, same error-on-unset |
| `MSA/Monthly revenue/Automation [RTxRT]/Automation structures/backup_working_v1/server.py` line 95 | same hardcoded key in the rollback copy | replaced with `os.environ.get("ADSPOWER_API_KEY", "")` |

Verification: a grep for the original key string returns no hits anywhere in `MSA/`. (The literal value is intentionally not reproduced here — Luis has it in his AdsPower app.)

Notion + Anthropic keys were already env-var-only (`NOTION_TOKEN` via `.env`, `ANTHROPIC_API_KEY` via shell env). The unified template now lists them as `NOTION_API_KEY` / `ANTHROPIC_API_KEY` in [MSA/.env.example](MSA/.env.example). `notion_sync.py` still reads `NOTION_TOKEN` from the inner `Monthly revenue/.env` — Luis can either keep that, or migrate to the outer `MSA/.env`.

## 4. What real data was moved/ignored

Moved into `MSA/private_data_DO_NOT_COMMIT/` (gitignored, structure mirrors originals):

- `Monthly revenue/data.json` — Notion revenue cache (58 revenue rows + 100 payments, real names + amounts)
- `Monthly revenue/SOP_Monthly_Revenue_Entry.docx`
- `Monthly revenue/WhatsApp Image 2026-05-06 at 20.29.21.jpeg`
- `Monthly revenue/Automation [RTxRT]/contacts.json` — real X handles + chat URLs
- `Monthly revenue/Automation [RTxRT]/follower_lists.json` — scraped third-party X handles
- `Monthly revenue/Automation [RTxRT]/blast_log.json` (~890KB), `blast_status.json` (~340KB) — real sent-DM records
- `Monthly revenue/Automation [RTxRT]/status.json` — real DM message log
- `Monthly revenue/Automation [RTxRT]/repost_log.json`, `repost_status.json`, `builder_status.json`
- `Monthly revenue/Automation [RTxRT]/auftrag.json`, `blast_auftrag.json`, `repost_auftrag.json`, `builder_auftrag.json` — pre-loaded real promo messages (incl. live OnlyFans URLs)
- `Monthly revenue/Automation [RTxRT]/promo_groups.json` — real AdsPower user_ids
- `Monthly revenue/Automation [Content]/models.json` — real model list
- `Monthly revenue/Automation [Content]/profiles/{mike-mains,zach-grover}.json` — model profile schemas with real data
- `Monthly revenue/Automation [Content]/{mike-mains,valerie,zach-grover}/` — full per-model brief/persona/audit folders (`.docx` + `.md` + `.json`)
- `Monthly revenue/Automation [Content]/{Mike,Zach}_Content_Brief.docx`, `Zach_Weekly_Content_Plan.docx`

Belt-and-suspenders: even if any of these files reappear at their original paths (e.g., from a sync), [MSA/.gitignore](MSA/.gitignore) patterns will still keep them out of git.

Fake example replacements created at original paths (committed) to keep the project structure self-documenting:

- `MSA/Monthly revenue/data.example.json`
- `MSA/Monthly revenue/Automation [RTxRT]/contacts.example.json`
- `MSA/Monthly revenue/Automation [RTxRT]/auftrag.example.json`
- `MSA/Monthly revenue/Automation [RTxRT]/promo_groups.example.json`
- `MSA/Monthly revenue/Automation [RTxRT]/follower_lists.example.json`
- `MSA/Monthly revenue/Automation [Content]/models.example.json`
- `MSA/Monthly revenue/Automation [Content]/profiles/example-model.example.json`

All examples use fake names, fake handles, fake revenue, fake links (`example.invalid`).

## 5. Dry-run / live-mode guard added

New file: `MSA/Monthly revenue/Automation [RTxRT]/safety_guard.py` (committed).

Wired into the `if __name__ == "__main__":` block of all five live-action bots:

- `blast_bot.py`
- `dm_bot.py`
- `repost_bot.py`
- `builder_bot.py`
- `scan_test.py`

Each bot now calls `require_live_or_exit("<bot_name>")` before any Playwright/AdsPower work. The guard exits with code 2 unless **both** env vars are set:

```
DRY_RUN=false
ALLOW_LIVE_EXTERNAL_ACTIONS=true
```

Defaults (in `.env.example`): `DRY_RUN=true`, `ALLOW_LIVE_EXTERNAL_ACTIONS=false`.

This is a shallow guard — it blocks accidental script launches but doesn't simulate every Playwright call. A deeper dry-run mode is a future option.

Sanity-checked manually: running the guard with default env vars prints a refusal banner and exits 2.

## 6. What still needs setup (for Luis, locally)

1. Copy `MSA/.env.example` → `MSA/.env` and fill in real `ADSPOWER_API_KEY`, `ANTHROPIC_API_KEY`, `NOTION_API_KEY`.
2. Decide where `notion_sync.py` reads its token. It currently expects an inner `Monthly revenue/.env` with `NOTION_TOKEN=`. Either keep that file (gitignored) or change `notion_sync.py` to use the outer `.env`. Right now both are gitignored; either works.
3. Copy or symlink the data files you actually need from `MSA/private_data_DO_NOT_COMMIT/` back into their original paths to run the dashboards against real data.
4. `pip install requests playwright anthropic` + `playwright install chromium`. (No `requirements.txt` exists; add one if you want.)
5. Run the server: `cd "MSA/Monthly revenue" && python server.py`.

## 7. What can be committed

Everything still inside `MSA/` after the move:

- All `.py`, `.html`, `.md`, `.txt`, `.bat` source/doc files
- `MSA/.gitignore`, `MSA/.env.example`
- All `*.example.json` fake data files
- `MSA/Monthly revenue/Automation [RTxRT]/safety_guard.py`
- `incoming/luis-msa-import/README.md`, `incoming/luis-msa-import/IMPORT_AUDIT.md`, `incoming/luis-msa-import/.gitignore`

Verified via `git add -n incoming/` — see report §E.

## 8. What should never be committed

- `MSA/.env`
- `MSA/private_data_DO_NOT_COMMIT/` (entire tree)
- Any `*.docx`, `*.jpeg`, `*.jpg` under `MSA/`
- Any real `data.json`, `contacts*.json`, `follower_lists*.json`, `blast_*.json`, `repost_*.json`, `status*.json`, `*_auftrag.json`, `promo_groups.json`, `models.json`, `chats.json`, `confirm.json`
- Per-model folders under `Automation [Content]/{mike-mains,valerie,zach-grover}/` and the `profiles/` dir with real names
- Logs, cookies, sessions, local DBs

All of these are matched by [MSA/.gitignore](MSA/.gitignore).

## 9. Open questions

- `requirements.txt` doesn't exist. Worth adding before this gets handed back to Luis.
- `notion_sync.py` reads from `Monthly revenue/.env` rather than `MSA/.env`. Acceptable but slightly inconsistent.
- `python/python-manager-26.1.msix` is a Windows installer left in the zip. Likely safe to delete on macOS; left in place for now since the user said don't delete unless asked.
- The Notion DB IDs (`2ecc4ce4…` and `2edc4ce4…`) are hardcoded in `notion_sync.py` *as defaults*. They're not secrets — Notion DB IDs are part of the URL — but if Luis wants them out of source, they're overridable via env (`NOTION_DB_REVENUE`, `NOTION_DB_PAYMENTS`).
