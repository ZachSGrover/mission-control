# Claude Cowork Automation Bot Spec

---

## 1. Automation Name

**X DM Automation — RTxRT**

Internal file reference: `dm_bot.py` + `xdashboard.html`
Dashboard served at: `http://localhost:8765/xdashboard`
Folder: `Automation [RTxRT]/`

---

## 2. Purpose

### Business Goal
Automate outbound direct message (DM) campaigns on X (formerly Twitter) across multiple managed creator accounts. The goal is to reach fans and potential subscribers at scale with a promotional message, driving traffic to the creator's content or subscription links.

### Who Uses It
Luis, who operates an MSA (Model/Social Media Agency) managing multiple OnlyFans and X accounts on behalf of creators. He runs the dashboard manually before or after business hours to trigger daily outreach runs.

### Problem It Solves
Manually sending DMs to hundreds of contacts per account per day is not feasible at human speed. The bot automates the scroll-scan-send loop so Luis can configure one run in under 2 minutes and walk away while the bot delivers 50–200+ messages.

### What Happens Before the Automation Runs
1. Luis opens AdsPower and ensures the target creator account is logged in inside the anti-detect browser profile.
2. Luis starts `server.py` manually from the Monthly Revenue folder.
3. Luis opens `xdashboard.html` in Chrome (served at `http://localhost:8765/xdashboard`).
4. Luis selects the AdsPower profile, types the outreach message, and sets how many DMs to send.
5. Luis clicks "Weiter" (Next), which writes `auftrag.json` and resets `chats.json`.

### What Happens After the Automation Finishes
1. `status.json` is updated to `done` with a summary line (e.g., "200 DMs gesendet in 18m 42s").
2. `contacts.json` is updated with a timestamp for every contact that received a message (used as a 24-hour deduplication filter for the next run).
3. The dashboard live-log shows the completed run. Luis inspects it and decides if any manual follow-up is needed.
4. The AdsPower browser profile is closed by the bot.

---

## 3. Current Automation Summary

When triggered, the bot (`dm_bot.py`) reads `auftrag.json` to obtain the target AdsPower profile ID, the outreach message text, and the maximum number of DMs to send.

It opens the AdsPower anti-detect browser profile via local API, which starts a Chromium window (called "Sunbrowser") with the creator's X session already logged in. The bot then connects to that browser via Playwright's CDP (Chrome DevTools Protocol) interface — meaning no separate browser binary is downloaded; it rides the already-open AdsPower session.

The bot navigates to `https://x.com/messages`, waits for the DM inbox UI to fully render (confirmed by the `dm-search-bar` element), then begins **Pass 1 (Scan)**: scrolling the DM conversation list entirely via JavaScript `querySelectorAll` calls (bypassing Playwright's selector engine, which cannot see X.com's dynamically rendered DOM). For each visible chat link it extracts the conversation URL and display name, checks against the 24-hour contact filter in `contacts.json`, and adds qualifying contacts to a target list. It scrolls until either the target count is reached or the end of the list is found (15 consecutive scrolls with no new URLs).

Once the scan is complete, **Pass 2 (Send)** begins: for each target URL, the bot navigates directly to that conversation, waits for the message composer to appear, types the message character-by-character (using Playwright's `type()` with 10ms delay), handles multi-line messages via Shift+Enter, then submits via the send button or Enter key. After each successful send, it writes the contact to `contacts.json` with a UTC timestamp and updates `status.json` so the dashboard shows live progress.

Read-only conversations (where X restricts sending) are detected by the absence of a composer element and are silently skipped without being logged to `contacts.json`. The bot closes the browser profile when done and writes a completion status.

---

## 4. Full Current Workflow

### Step 1 — Server Startup
- **Trigger:** Manual. Luis opens a terminal and runs `python server.py` from the Monthly Revenue folder.
- **Input used:** None (reads port 8765 from hardcoded constant).
- **Logic applied:** Starts a ThreadedHTTPServer on `localhost:8765`. Serves static HTML files and proxies JSON file reads/writes.
- **Tool/platform:** Python 3 stdlib (`http.server`, `socketserver`).
- **Output created:** HTTP server running. All dashboard API routes available.
- **Mode:** Manual.
- **Safe for sandbox:** Yes — only serves local files.
- **Affects real accounts:** No.

### Step 2 — Dashboard Load
- **Trigger:** Manual. Luis opens `http://localhost:8765/xdashboard` in Chrome.
- **Input used:** None.
- **Logic applied:** Browser fetches `xdashboard.html` from server. JavaScript polls `/status` every 2 seconds.
- **Tool/platform:** Chrome browser, `server.py` GET `/xdashboard`.
- **Output created:** Dashboard UI rendered in browser.
- **Mode:** Manual.
- **Safe for sandbox:** Yes.
- **Affects real accounts:** No.

### Step 3 — AdsPower Profile Selection (Step 1 of Dashboard)
- **Trigger:** Dashboard load triggers `GET /ads-profiles` automatically.
- **Input used:** AdsPower local API at `http://local.adspower.net:50325/api/v1/user/list`; API key in `server.py` environment (not exposed to dashboard JS).
- **Logic applied:** Server fetches the profile list from AdsPower local API and returns it to the dashboard. Dashboard renders a profile picker card for each profile.
- **Tool/platform:** AdsPower local API, `server.py`.
- **Output created:** Profile list displayed in dashboard.
- **Mode:** Automated (triggered on page load).
- **Safe for sandbox:** Yes — read-only API call.
- **Affects real accounts:** No (only lists profiles, does not open them).

### Step 4 — Message & Target Count Configuration (Step 2 of Dashboard)
- **Trigger:** Manual. Luis selects a profile, types the outreach message, and enters the number of DMs to send.
- **Input used:** Selected AdsPower `user_id`, profile name, message text, `max_chats` integer.
- **Logic applied:** Dashboard validates fields are non-empty. No server call yet.
- **Tool/platform:** Dashboard HTML form.
- **Output created:** Form data held in JS memory pending submission.
- **Mode:** Manual.
- **Safe for sandbox:** Yes.
- **Affects real accounts:** No.

### Step 5 — Job Submission (Auftrag Write)
- **Trigger:** Manual. Luis clicks "Weiter" (Next / Start).
- **Input used:** Profile `user_id`, name, message text, `max_chats`.
- **Logic applied:** Dashboard sends `POST /chats` with `{"chats":[]}` (reset), then `POST /auftrag` with the job JSON, then `POST /status` with `{"state":"idle"}`, then `GET /ads-start/<user_id>` (opens the AdsPower browser profile).
- **Tool/platform:** `server.py`, AdsPower local API.
- **Output created:** `auftrag.json` written, `chats.json` reset, `confirm.json` reset, AdsPower browser opened.
- **Mode:** Semi-automated (button click triggers chain of API calls).
- **Safe for sandbox:** The AdsPower browser open call starts a real logged-in session. In sandbox mode this step should be blocked.
- **Affects real accounts:** Yes — opens a real creator account session in AdsPower.

### Step 6 — Bot Invocation
- **Trigger:** Luis (or a Windows Scheduled Task) runs `python dm_bot.py` from the `Automation [RTxRT]` folder. The dashboard "Start Bot" button sends `POST /start-bot` which spawns `dm_bot.py` as a detached subprocess.
- **Input used:** `auftrag.json` (user_id, name, message, max_chats), `contacts.json` (24h filter archive).
- **Logic applied:** Reads auftrag; if no auftrag exists, exits immediately with "skipped" status.
- **Tool/platform:** Python, `dm_bot.py`.
- **Output created:** Initial `status.json` written: `{"state":"running", "step":"Start — 0/N DMs, 1 Account(s)", "log":[]}`.
- **Mode:** Semi-automated.
- **Safe for sandbox:** No. Must be blocked in MVP.
- **Affects real accounts:** Yes — bot begins operating the creator's X session.

### Step 7 — Browser Connection via CDP
- **Trigger:** Automatic (inside `dm_bot.py` `process_account()`).
- **Input used:** AdsPower `user_id`, AdsPower local API response with WebSocket CDP URL.
- **Logic applied:** `ads_open(user_id)` calls AdsPower `browser/start` endpoint, receives the Playwright CDP WebSocket URL. Playwright `connect_over_cdp()` attaches to the existing browser window.
- **Tool/platform:** AdsPower local API, Playwright (Python), Chromium (via AdsPower).
- **Output created:** Playwright `browser`, `context`, `page` objects connected to the live creator session.
- **Mode:** Automated.
- **Safe for sandbox:** No — live session connected.
- **Affects real accounts:** Yes.

### Step 8 — Navigate to DM Inbox
- **Trigger:** Automatic (inside `process_account()`).
- **Input used:** None beyond the connected page object.
- **Logic applied:** `page.goto("https://x.com/messages", ...)` followed by `wait_for_selector('[data-testid="dm-search-bar"]', timeout=15000)` and `wait_for_load_state("networkidle")`, then a 3-second static sleep. If the URL contains "login", raises an error (not logged in).
- **Tool/platform:** Playwright, X.com.
- **Output created:** DM inbox rendered in browser.
- **Mode:** Automated.
- **Safe for sandbox:** No.
- **Affects real accounts:** Only reads page; no writes yet.

### Step 9 — Pass 1: Chat List Scan
- **Trigger:** Automatic (inside `scroll_and_send()` → `collect_chat_urls()`).
- **Input used:** DOM of X.com DM inbox via `page.evaluate()` JavaScript, `contacts.json` for 24h filter.
- **Logic applied:**
  - Repeatedly calls `extract_chats_js(page)` which runs `document.querySelectorAll('a[href*="/messages/"]')` inside the page context, extracting `href` and display name for each visible chat.
  - Name extraction priority: (1) `span[dir="ltr"]`, (2) first span that is not a timestamp/preview/You:/Du: prefix, (3) fallback to URL path segment.
  - Filters out already-seen URLs (dedup within the run) and contacts in `contacts.json` with `last_sent` within the last 24 hours.
  - After each extract pass, calls `scroll_dm_list(page)` which walks up the DOM from a chat link to find the scrollable ancestor container and calls `el.scrollBy(0, 800)`.
  - Waits 1.2 seconds between scrolls.
  - Stops when `len(targets) >= max_chats` OR when 15 consecutive scrolls yield no new URLs (end of list).
  - Writes `status.json` with `state: "scanning"` and current count after each new target found.
  - Writes `status.json` with `state: "scan_done"` when complete.
- **Tool/platform:** Playwright `page.evaluate()`, X.com DOM, Python.
- **Output created:** In-memory list of `(name, full_url)` tuples. Live status updates in `status.json`.
- **Mode:** Automated.
- **Safe for sandbox:** No — operates in live creator browser session. Read-only with respect to DMs, but navigates a real account.
- **Affects real accounts:** Reads DM list only; does not send any messages in this pass.

### Step 10 — Pass 2: DM Send Loop
- **Trigger:** Automatic, immediately after Pass 1 completes.
- **Input used:** Target list from Pass 1, message text from `auftrag.json`, `contacts.json`.
- **Logic applied:** For each `(name, full_url)` in targets (up to `max_chats`):
  1. `page.goto(full_url, wait_until="domcontentloaded", timeout=25000)`.
  2. Verify URL contains `/messages/` or `/i/chat/` — if not, skip.
  3. `wait_for_selector(...)` for composer element (textarea, textbox, contenteditable, or `[data-testid*="composer"]`), up to 6 seconds.
  4. `find_composer(page)` iterates selector priority list, checking `is_visible(timeout=800)` for each.
  5. If no composer found: contact is read-only — skip without logging to `contacts.json`.
  6. If composer found: `composer.click()`, type message with `composer.type(part, delay=10ms)`, handle `\n` with `Shift+Enter`, then find and click send button (`[data-testid*="send"]` variants) or press `Return`.
  7. Sleep 1.5 seconds after send.
  8. On success: call `add_contact()` which upserts the entry in `contacts.json` (key: user_id → array of `{name, url, last_sent}`), save `contacts.json`, append to log, update `status.json` with `state: "running"` and current count.
- **Tool/platform:** Playwright, X.com, Python, `contacts.json`.
- **Output created:** DMs delivered on X.com. `contacts.json` updated per send. `status.json` updated continuously. Console log entries per send.
- **Mode:** Automated.
- **Safe for sandbox:** No — sends real messages to real people.
- **Affects real accounts:** Yes — directly sends DMs on the creator's X account to real users.

### Step 11 — Run Completion
- **Trigger:** Automatic — all targets processed or `max_sends` reached.
- **Input used:** Total sent count, elapsed time.
- **Logic applied:** Calculates elapsed time; calls `set_status("done", summary_string, log)`.
- **Tool/platform:** Python, `status.json`.
- **Output created:** `status.json` with `state: "done"`, full log array, summary message. `contacts.json` persisted.
- **Mode:** Automated.
- **Safe for sandbox:** Yes (status write is safe).
- **Affects real accounts:** No (cleanup only).

### Step 12 — Browser Cleanup
- **Trigger:** Automatic — `finally` block and `ads_close()` call.
- **Input used:** `user_id`.
- **Logic applied:** `browser.close()` via Playwright, then `GET http://local.adspower.net:50325/api/v1/browser/stop?user_id=<id>`.
- **Tool/platform:** Playwright, AdsPower local API.
- **Output created:** AdsPower browser profile closed.
- **Mode:** Automated.
- **Safe for sandbox:** Yes.
- **Affects real accounts:** No (closes the session; does not modify content).

### Step 13 — Scheduled Automation (Optional)
- **Trigger:** Windows Task Scheduler (optional; configured via dashboard "Schedule" toggle).
- **Input used:** `schedule.json` with `{"enabled": true, "time": "HH:MM"}`.
- **Logic applied:** `server.py` receives `POST /schedule`, uses `schtasks /create` to register a daily Windows scheduled task called `XDMBot` that runs `dm_bot.py` at the specified time.
- **Tool/platform:** Windows Task Scheduler, `server.py`, Python `subprocess`.
- **Output created:** Windows scheduled task registered. Bot runs unattended nightly.
- **Mode:** Automated (once configured).
- **Safe for sandbox:** No — configures live unattended execution.
- **Affects real accounts:** Yes — triggers live sends without any human in the loop.

---

## 5. Full Current Prompts

This automation does not use a Claude model for DM execution or chat scanning. `dm_bot.py` is a pure Python + Playwright script.

The **only Claude API call** in the current system is an optional content analysis feature in `server.py` at `POST /analyze`, used by the separate **Models Dashboard** (`models-dashboard.html`), not by the X DM automation.

### Analyze Prompt (Models Dashboard — separate feature, not RTxRT)

```
You are an elite social media content strategist specialized in creator growth and monetization.

Analyze this creator profile and provide a complete weekly content strategy:

**Creator:** {name}{f' (alias: {alias})' if alias else ''}
**Niche / Category:** {niche}
**Platforms:** {platforms_str}
**Notes:** {notes if notes else 'None'}

Provide a structured analysis with these exact sections using markdown:

## 🎯 Niche & Audience Analysis
## 📊 Content Pillars
## 💡 7 Feed Post Ideas
## 🔥 3 Viral Hook Ideas
## 💬 3 Engagement Bait Ideas
## 🎬 3 Short-Form Video / Reel Ideas
## 💰 2 High-Converting Promotional Ideas
## 📅 Weekly Posting Schedule
## ⚠️ Optimization Advice
```

**Model used:** `claude-haiku-4-5-20251001`
**Max tokens:** 1800
**API key source:** `ANTHROPIC_API_KEY` environment variable (never hardcoded; not exposed to frontend)

There are no system prompts, reusable snippets, or example templates in the RTxRT DM automation itself. The outreach message is entirely user-authored at runtime via the dashboard.

---

## 6. Inputs

| # | Input Name | Example Value | Source | Required | Sensitive | Store in MC | Visible to Operator |
|---|---|---|---|---|---|---|---|
| 1 | AdsPower Profile ID (`user_id`) | `k1bhvfaa` | AdsPower local API (auto-fetched) | Yes | No (internal ID) | Yes | Yes |
| 2 | Profile display name | `AVAILABLE` | AdsPower local API | Yes | No | Yes | Yes |
| 3 | Outreach message text | `Hey RtxRt?\nhttps://x.com/...` | Typed by Luis in dashboard | Yes | Soft (contains promo link) | Yes | Yes |
| 4 | Max DMs to send (`max_chats`) | `200` | Typed by Luis in dashboard | Yes | No | Yes | Yes |
| 5 | Schedule time (`HH:MM`) | `01:00` | Dashboard schedule toggle | No | No | Yes | Yes |
| 6 | AdsPower API key | [REDACTED] | Hardcoded in `server.py` | Yes | **Yes** | **No** | **No** |
| 7 | Anthropic API key | [REDACTED] | OS environment variable | No (Models only) | **Yes** | **No** | **No** |
| 8 | contacts.json archive | `{"k1bhvfaa": [...]}` | File on disk, auto-loaded | Yes | Soft (fan handles) | Yes | View-only |
| 9 | auftrag.json job file | `{"max_chats":200,"accounts":[...]}` | Written by dashboard on submit | Yes | No | Yes | Yes |

---

## 7. Outputs

| # | Output Name | Format | Example | Current Destination | MC Destination | Needs Approval | Visible to Operator | Send to Discord/Telegram |
|---|---|---|---|---|---|---|---|---|
| 1 | Live status | JSON file (`status.json`) | `{"state":"running","step":"AVAILABLE – 47/200 DMs gesendet","log":[...]}` | Local file, polled by dashboard every 2s | Bot Run detail panel | No | Yes | Summary only |
| 2 | Run completion summary | Status string | `"Run abgeschlossen — 200 DMs gesendet in 18m 42s"` | `status.json` → dashboard | Run history table | No | Yes | Yes |
| 3 | Contact archive update | JSON file (`contacts.json`) | `{"k1bhvfaa":[{"name":"pulseguy83nyc","url":"https://x.com/messages/...","last_sent":"2026-05-06T..."}]}` | Local file | DB table | No | View-only | No |
| 4 | Per-send log entry | String in log array | `"AVAILABLE: pulseguy83nyc ✓"` | `status.json` log array | Run audit log | No | Yes | No |
| 5 | Scan count update | Status step string | `"🔍 Scanne Chatliste… 47 Ziele gefunden"` | `status.json` | Dashboard scan card | No | Yes | No |
| 6 | Error log entry | String in log array | `"FEHLER AVAILABLE: Nicht eingeloggt"` | `status.json` | Run error panel + alert | No | Yes | Yes (errors) |
| 7 | Schedule config | JSON (`schedule.json`) | `{"enabled":true,"time":"01:00"}` | Local file + Windows Task Scheduler | Bot settings page | Owner only | View | No |

---

## 8. Tools and Integrations

| # | Name | Purpose | Reads | Writes | Logs In | Needs Credentials | MC Connect Later | Block in MVP |
|---|---|---|---|---|---|---|---|---|
| 1 | AdsPower (local API) | Anti-detect browser manager; opens/closes creator browser profiles | Yes (profile list) | No | No (manages sessions) | Yes — API key [REDACTED] | Yes | Yes (browser open/close) |
| 2 | AdsPower Sunbrowser (Chromium) | Hosts the logged-in X.com creator session | Yes | Yes (sends DMs) | Yes (pre-logged in) | Creator X credentials (pre-stored in AdsPower) | No | Yes |
| 3 | X.com / Twitter | Platform where DMs are sent | Yes (DM inbox DOM) | Yes (sends messages) | Via AdsPower session | Via AdsPower | No | Yes |
| 4 | Playwright (Python) | Browser automation; CDP connection to AdsPower browser | Yes | Yes | No | No | No | Yes (DM send) |
| 5 | `server.py` (Python HTTP) | Local API gateway; serves dashboard; reads/writes JSON files | Yes | Yes | No | No | No | Partial (safe routes OK) |
| 6 | `xdashboard.html` | Browser-based operator UI; 3-step job submission + live status | Yes | Yes (via API) | No | No | Replace with MC UI | N/A |
| 7 | `contacts.json` | 24-hour send deduplication archive | Yes | Yes | No | No | Yes (DB table) | No |
| 8 | `auftrag.json` | Job definition file (profile, message, max count) | Yes | Yes (dashboard writes) | No | No | Yes (DB table) | No |
| 9 | `status.json` | Live run status + log | Yes | Yes | No | No | Yes (DB + real-time) | No |
| 10 | `schedule.json` | Schedule config (time, enabled flag) | Yes | Yes | No | No | Yes | Yes (live scheduling) |
| 11 | Windows Task Scheduler | Runs `dm_bot.py` unattended on a daily schedule | No | Yes (task registration) | No | No | No | Yes |
| 12 | Anthropic API (Claude) | Creator content strategy (Models Dashboard only; not RTxRT) | No | No | No | Yes — API key [REDACTED] | Yes | No (separate feature) |

---

## 9. Sensitive Data Touched

| # | Data Type | Store? | Redact? | Hide from Operators? | Appear in Audit Logs? | Appear in Discord/Telegram? |
|---|---|---|---|---|---|---|
| 1 | Creator account X handles / AdsPower names (e.g., `AVAILABLE`) | Yes | No | No — Operators see profile names | Yes (redacted if needed) | Summary only |
| 2 | Fan/contact X handles (e.g., `pulseguy83nyc`) | Yes (contacts archive) | Partial — store internally, don't surface in alerts | View-only for Operators | Yes | No |
| 3 | Fan/contact conversation URLs | Yes (contacts archive) | No (not PII alone) | No | Yes | No |
| 4 | Outreach message body | Yes (per run record) | No | No | Yes | Preview only |
| 5 | AdsPower API key | **No** | **Yes — [REDACTED]** | **Yes — never expose** | **No** | **No** |
| 6 | Anthropic API key | **No** | **Yes — [REDACTED]** | **Yes — never expose** | **No** | **No** |
| 7 | X.com session cookies (in AdsPower) | Managed by AdsPower only | N/A | N/A | **No** | **No** |
| 8 | Creator X account credentials (passwords) | Managed by AdsPower only | N/A | **Yes — never in MC** | **No** | **No** |
| 9 | DM message contents received from fans | Not read or stored by the bot | N/A | N/A | No | No |
| 10 | Revenue numbers / financial data | Not touched by this automation | N/A | N/A | No | No |
| 11 | Adult platform (OnlyFans) links in message body | Yes (part of outreach message) | No | No | Yes | No (do not relay message body externally) |
| 12 | Creator real names / aliases | Yes (in profile metadata) | No | No | Yes | No |

---

## 10. Actions the Automation Takes

### Read-Only Actions
- Fetch AdsPower profile list from local API (`GET /api/v1/user/list`)
- Read `auftrag.json`, `contacts.json`, `status.json`, `schedule.json` from disk
- Navigate to `https://x.com/messages` and inspect the DOM
- Extract chat link URLs and display names from DOM via JavaScript `querySelectorAll`
- Check 24h filter against `contacts.json`

### Draft Actions
- Write `auftrag.json` (job definition — does not trigger sending by itself)
- Write `chats.json` (reset on run start)
- Write `status.json` (status update only — no platform write)

### Live Actions

#### Live Action 1: Open AdsPower Browser Profile
- **What it does:** Calls AdsPower local API to start a Chromium window with the creator's X session.
- **Why it is risky:** Starts a real authenticated session. If anything goes wrong (crash, script error), the browser may be left open in an unpredictable state.
- **Approval required:** Owner confirmation before any run.
- **Who can approve:** Owner (Luis) only.
- **Disabled in MVP:** Yes.

#### Live Action 2: Scroll DM Inbox (Pass 1)
- **What it does:** Scrolls through the creator's real DM inbox on X.com to collect chat URLs. Does not send messages.
- **Why it is risky:** Operates inside a live authenticated session. Any interaction beyond reading could inadvertently mark chats as read or trigger X's bot detection.
- **Approval required:** Owner confirmation before run start.
- **Who can approve:** Owner only.
- **Disabled in MVP:** Yes.

#### Live Action 3: Send Direct Messages on X.com (Pass 2)
- **What it does:** Navigates to each collected chat URL and sends the configured outreach message text to real users.
- **Why it is risky:** Sends unsolicited messages at scale to real people. Risk of platform ban (X bot/spam detection), creator reputation damage, and potential terms-of-service violation. Irreversible once sent.
- **Approval required:** Owner explicit run approval + mandatory message preview before execute.
- **Who can approve:** Owner only. Operators may not approve this action alone.
- **Disabled in MVP:** Yes — absolute block.

#### Live Action 4: Update contacts.json After Each Send
- **What it does:** Writes each sent contact's handle, URL, and timestamp to the persistent archive file after each successful DM.
- **Why it is risky:** Low risk in isolation; incorrect writes could corrupt the 24h deduplication filter, causing repeat sends.
- **Approval required:** None (consequence of an already-approved send).
- **Who can approve:** N/A.
- **Disabled in MVP:** Yes (because sends are disabled).

#### Live Action 5: Register Windows Scheduled Task
- **What it does:** Calls `schtasks /create` to schedule `dm_bot.py` as a daily recurring task on the host Windows machine.
- **Why it is risky:** Enables fully unattended live DM sending with no human in the loop. A bad `auftrag.json` would execute automatically.
- **Approval required:** Owner explicit toggle + time confirmation.
- **Who can approve:** Owner only.
- **Disabled in MVP:** Yes — absolute block.

---

## 11. Dashboard Requirements

### Dashboard Name
**X DM Bot — Mission Control Panel**

### Main Page Layout
Two-column layout on wide screens. Left column: bot status card + current run card. Right column: run log feed.

### Cards / Panels Needed
1. **Bot Status Card** — shows current state (Idle / Scanning / Sending / Done / Error) with color indicator dot.
2. **Active Run Card** — shows: profile name, message preview (first 60 chars), target count, sent count, progress bar.
3. **Scan Progress Card** — shown only during scan phase: "Scanning… N contacts found so far" spinner.
4. **Scan Complete Card** — shown briefly after scan, before sending: "N contacts found — sending begins."
5. **Run Log Feed** — scrollable live log; one line per send success or error.
6. **Last Run Summary Card** — shows final result of most recent completed run (total sent, time elapsed, date).
7. **Contact Archive Card** — read-only summary: total contacts in archive per profile, date of oldest/newest entry.
8. **Schedule Card** — shows next scheduled run time (if enabled). Owner-only toggle to enable/disable.
9. **Error Card** — shown only when state is `error` or `failed`. Displays error message with retry button (owner only).

### Tables Needed
1. **Run History Table** — one row per historical run: date, profile, message preview, target, sent, duration, status.
2. **Contact Archive Table** — filterable by profile; columns: handle, URL, last sent date, sent count.
3. **Read-Only Contacts Table** — contacts that were skipped as read-only (future: for tracking and exclusion).

### Filters Needed
- Run History: by profile, by date range, by status (done / failed / skipped).
- Contact Archive: by profile (user_id), by date range.

### Search Needed
- Contact Archive: search by handle name.

### Status Indicators Needed
- Dot: green = done/idle, amber = scanning/running, red = error/failed, gray = no run yet.
- Progress bar in Active Run Card.
- Scan count badge (live).

### Buttons Needed
- **New Run** — opens New Run form (owner only in MVP).
- **Pause / Kill** — stops bot mid-run (owner only; sends kill signal).
- **Retry** — re-queues a failed run (owner only in MVP).
- **Export Run Log** — downloads current run log as CSV (operator allowed).
- **Export Contact Archive** — downloads contacts.json as CSV (operator allowed, redacted).
- **Refresh** — manual poll trigger.

### Approval Controls Needed
- Run submission form must show: profile selected, full message preview, target count, and require explicit "Confirm and Start" button press by owner.
- Scheduled task changes require a separate "Confirm Schedule Change" modal with current and new settings displayed.

### Sandbox Mode Controls
- Prominent banner at top of dashboard when in sandbox mode: "SANDBOX — No live sends will occur."
- All "Start Run" buttons show as "Start Sandbox Run" in sandbox mode.
- Output of sandbox run shows what would have been sent (dry-run log).

### Logs / History Views Needed
- Per-run audit log: inputs used, scan result count, send result count, errors, start/end times, who initiated.
- Global audit log page: all runs across all profiles, filterable.

### Settings Page Needed
- Bot registry entry (name, version, description).
- Profile management (read-only: sourced from AdsPower).
- Schedule configuration (owner only).
- Sandbox mode toggle (owner only).
- API key status indicators (present/absent — never display value).
- Kill switch (disables all scheduled runs immediately).

### Operator View
Operator sees: run history, contact archive summary, live status, log feed, export buttons. Cannot start runs, change settings, or view raw credentials.

### Owner Admin View
Full access: all above + new run form, settings, schedule control, kill switch, sandbox toggle, approval controls.

---

## 12. Operator Permissions

### An Operator CAN:
1. View current bot status (idle / scanning / running / done / error).
2. View safe inputs (profile display name, message preview, target count, start time).
3. View live run log feed.
4. View run history table (past runs, outcomes, durations).
5. View contact archive summary (counts per profile, date ranges).
6. Export run history as CSV.
7. Export contact archive as CSV (handles only; URLs omitted from export).
8. Pause a running bot (sends pause signal to status.json — owner must confirm before resume).
9. Retry failed **sandbox** runs.
10. View error messages and error log.
11. Upload a new message template for owner review (draft only — does not trigger a run).

### An Operator CANNOT:
1. View or access any API keys, tokens, or credentials.
2. View or access any cookies or AdsPower session data.
3. Start a live run (New Run button is owner-only).
4. Change any settings (schedule, sandbox toggle, profile config).
5. Approve or bypass any live action gate.
6. Delete run history or contact archive records.
7. Access the Windows Task Scheduler configuration.
8. Change bot permissions or operator access levels.
9. Trigger `POST /start-bot` endpoint.
10. View raw `auftrag.json`, `contacts.json`, `status.json` files directly.
11. See the full unredacted contact list (fan X handles must be summarized, not listed by default).

---

## 13. Bot Lifecycle

### 1. Draft
- **Meaning:** A run has been configured (profile, message, count) but not submitted.
- **Who moves it forward:** Owner clicks "Confirm and Start."
- **Data saved:** Proposed auftrag (profile, message, target count), created timestamp, created by.
- **Audit log:** `RUN_DRAFT_CREATED — user: Luis, profile: AVAILABLE, target: 200, message: [preview]`

### 2. Queued
- **Meaning:** `auftrag.json` has been written; bot has not yet started (or scheduled task pending).
- **Who moves it forward:** Automatic (bot launch) or scheduled task trigger.
- **Data saved:** Auftrag snapshot, submission timestamp.
- **Audit log:** `RUN_QUEUED — auftrag written, bot launch pending`

### 3. Running — Scanning
- **Meaning:** `dm_bot.py` is active; Pass 1 in progress. No DMs sent yet.
- **Who moves it forward:** Automatic (scan completes).
- **Data saved:** Scan count updates (every N new targets found), elapsed time.
- **Audit log:** `RUN_SCAN_STARTED — profile: AVAILABLE`, then `RUN_SCAN_UPDATE — targets_found: N` periodically.

### 4. Running — Sending
- **Meaning:** Pass 2 in progress. DMs are being sent.
- **Who moves it forward:** Automatic (all targets processed or max reached).
- **Data saved:** Per-send log entry (handle, URL, timestamp, success/fail).
- **Audit log:** `RUN_SEND_PROGRESS — sent: N/max` after each batch, `RUN_SEND_SUCCESS — contact: [handle]` per send.

### 5. Needs Review
- **Meaning:** A non-critical condition requires human inspection before proceeding (e.g., unusually high read-only skip rate, partial completion).
- **Who moves it forward:** Owner reviews and marks as Approved (continue) or Rejected (discard).
- **Data saved:** Review reason, current sent count, contact list snapshot.
- **Audit log:** `RUN_NEEDS_REVIEW — reason: [description]`

### 6. Approved
- **Meaning:** Owner has reviewed and explicitly approved either a draft (before run) or a mid-run review. The run proceeds.
- **Who moves it forward:** Automatic (run resumes).
- **Data saved:** Approval timestamp, approved by.
- **Audit log:** `RUN_APPROVED — by: Luis, timestamp: ...`

### 7. Rejected
- **Meaning:** Owner or operator has rejected the run at a review gate. No (further) DMs will be sent.
- **Who moves it forward:** Terminal — no further transitions.
- **Data saved:** Rejection reason, rejected by, timestamp, partial results.
- **Audit log:** `RUN_REJECTED — by: [user], reason: [text]`

### 8. Completed
- **Meaning:** Run finished normally. All targets processed or `max_chats` reached.
- **Who moves it forward:** Terminal.
- **Data saved:** Final sent count, total elapsed time, full log array, contacts.json snapshot hash.
- **Audit log:** `RUN_COMPLETED — sent: N, elapsed: Xm Ys, errors: N`

### 9. Failed
- **Meaning:** Bot encountered a critical unrecoverable error (e.g., not logged in, AdsPower offline, crash).
- **Who moves it forward:** Owner can retry (creates a new Draft) or archive.
- **Data saved:** Error message, stack trace (sanitized), partial results if any, failure timestamp.
- **Audit log:** `RUN_FAILED — error: [message], partial_sent: N`

### 10. Paused
- **Meaning:** Operator or owner has paused a running bot. Status halted; no new sends.
- **Who moves it forward:** Owner resumes or terminates.
- **Data saved:** Pause reason, paused by, paused at sent count.
- **Audit log:** `RUN_PAUSED — by: [user], at: N/max`

### 11. Archived
- **Meaning:** Run record is retained for audit history but removed from active dashboard.
- **Who moves it forward:** Automatic after 30 days, or manual owner action.
- **Data saved:** Full record preserved.
- **Audit log:** `RUN_ARCHIVED — run_id: ...`

---

## 14. Audit Logging Needs

Mission Control must log every event below. No raw secrets, cookies, passwords, or full private message bodies should appear in logs.

1. Who started a run (user ID + display name).
2. Run start timestamp (UTC ISO-8601).
3. Inputs used: profile name, message preview (first 80 chars only), target count, sandbox mode flag.
4. Bot version that ran (dm_bot.py file hash or version tag).
5. Run mode: sandbox or live.
6. Scan phase: start timestamp, update events (count at each 10-target milestone), end timestamp, total targets found.
7. Send phase: per-send events (contact handle, success or skip-read-only, timestamp). No message body repeated per-send.
8. Who reviewed a run (if Needs Review was triggered).
9. Who approved a run (username, timestamp, approval note if any).
10. Who rejected a run (username, timestamp, rejection reason).
11. All errors: error type, error message (sanitized), which step failed.
12. Retry events: new run created from failed run, link to original run ID.
13. Live action requests: any attempt to trigger a live send or schedule change.
14. Permission issues: any attempt by an operator to access an owner-only feature.
15. Sensitive data redactions: log that redaction occurred, not the value itself.
16. Schedule changes: enabled/disabled, old time, new time, changed by.
17. Kill switch activations: who activated, timestamp, runs affected.

---

## 15. Safety Gates

The following safety gates must all be active in the Mission Control MVP and must require explicit owner action to relax:

1. **Sandbox mode by default** — all new bot registry entries start in sandbox mode. Sandbox produces a dry-run log without any platform writes.
2. **Draft-only mode by default** — no run can execute until an owner explicitly moves it to "Queued."
3. **No live writes in MVP** — `POST /start-bot`, AdsPower browser open, and all Playwright DM send actions are blocked at the API level in MVP. Routes return `{"error": "live_writes_disabled_in_MVP"}`.
4. **Owner approval required for live actions** — any route that triggers a platform write (browser open, DM send, schedule registration) requires a valid owner session token.
5. **Operator cannot approve dangerous actions alone** — approval records require owner-level role.
6. **Sensitive data redaction** — API keys, AdsPower credentials, X session cookies are never written to any log, never returned in any API response, never stored in any run record.
7. **No secrets in frontend** — the dashboard/operator UI never receives raw API keys, cookie values, or credential strings. The server returns only masked status indicators (`api_key_present: true/false`).
8. **No cookies stored by Mission Control** — MC does not manage or store X.com session cookies. Cookie management is entirely within AdsPower.
9. **No passwords stored** — MC does not store any X account passwords. AdsPower manages credentials.
10. **All runs audited** — every run, regardless of mode, generates a complete audit log entry.
11. **Platform write actions disabled by default** — a feature flag `LIVE_WRITES_ENABLED` must be explicitly set to `true` by the owner before any live send can occur. Default is `false`.
12. **Kill switch** — a single owner-accessible button that immediately sets `LIVE_WRITES_ENABLED = false`, cancels all queued runs, and writes a `RUN_KILLED` audit event.
13. **Rate limits** — maximum of 1 live run per profile per day enforced at the API level. Sandbox runs are not rate-limited.
14. **Duplicate prevention** — if a run is already in status `Queued` or `Running` for a given profile, a new run for the same profile cannot be queued. Returns an error.
15. **Manual review before outreach** — any run with `max_chats > 100` is automatically placed in `Needs Review` status after the scan phase, before any DMs are sent, requiring explicit owner approval to proceed.

---

## 16. Failure Cases

| # | Failure Case | Detection | User-Facing Message | Recovery Step | Alert Hermes | Alert Discord/Telegram |
|---|---|---|---|---|---|---|
| 1 | Bad input (empty message) | Dashboard form validation | "Bitte Nachricht eingeben." | User corrects input. | No | No |
| 2 | Missing input (no profile selected) | Dashboard form validation | "Bitte Profil auswählen." | User selects profile. | No | No |
| 3 | Duplicate run (same profile already queued) | API check on submit | "Für dieses Profil läuft bereits ein Job." | Wait for current run to finish. | No | No |
| 4 | Wrong platform (not X.com after login) | `"login" in page.url` check | "Account nicht eingeloggt — bitte in AdsPower anmelden." | Luis manually logs in via AdsPower. | No | Yes |
| 5 | Tool unavailable (AdsPower offline) | `requests.get()` timeout on `ads_open()` | "AdsPower ist nicht erreichbar. Bitte starten." | Start AdsPower app on host machine. | No | Yes |
| 6 | Login expired (X session dead) | URL check post-navigation | "X-Session abgelaufen — bitte in AdsPower neu anmelden." | Manual re-login in AdsPower browser. | No | Yes |
| 7 | Rate limits (X blocks DM sending) | `find_composer()` returns None repeatedly + all remaining chats read-only | "Möglicher Rate-Limit von X erkannt. Run wird beendet." | Wait 24h before next run. Lower target count. | Yes | Yes |
| 8 | Bad output (0 DMs sent despite targets found) | `sent == 0` after Pass 2 | "Keine DMs gesendet — alle Ziele waren read-only oder gesperrt." | Check account standing in AdsPower. | Yes | Yes |
| 9 | Unsafe output (message garbled) | N/A (no output validation currently) | N/A | Add message preview + approval gate before send. | No | No |
| 10 | Hallucinated information | N/A (no LLM in DM bot) | N/A | N/A | No | No |
| 11 | Permission denied (operator tries live action) | Role check in API | "Diese Aktion erfordert Owner-Rechte." | Owner performs action. | No | No |
| 12 | Operator mistake (wrong profile) | N/A (post-submit) | Prevent via pre-submit confirmation modal. | Cancel run before it executes (if queued). | No | No |
| 13 | Platform policy risk (X bot detection) | High error rate / account suspended | "Account-Aktivität könnte geblockt sein — prüfe AdsPower." | Pause scheduling. Reduce send volume. | Yes | Yes |
| 14 | Client reputation risk (wrong message sent) | N/A (messages are sent instantly) | Prevent via message preview gate. | Issue manual follow-up DMs via AdsPower. | Yes | Yes |
| 15 | Data leak risk (contacts.json exposed) | N/A currently | Protect file via server-side access control. | Restrict `/contacts` endpoint to owner role. | Yes | Yes |
| 16 | Partial completion (bot crashes mid-send) | `state != "done"` after timeout | "Run unvollständig abgebrochen. Letzte Position: N/max." | Resume from last contacts.json entry. | Yes | Yes |
| 17 | Retry loop (bot keeps failing and restarting) | Retry count > 3 for same run | "Maximale Wiederholungsversuche erreicht." | Owner intervenes manually. | Yes | Yes |
| 18 | Bot stuck running (no status update > 5 min) | Watchdog: poll status.json change frequency | "Bot antwortet nicht mehr — möglicher Absturz." | Kill process manually. Restart. | Yes | Yes |
| 19 | Approval skipped (live action fires without gate) | Audit log cross-check | Structural: impossible if gate is enforced at API level. | Audit log review. Gate enforcement audit. | Yes | Yes |
| 20 | Live action attempted while disabled | `LIVE_WRITES_ENABLED == false` check in API | "Live-Aktionen sind deaktiviert (Sandbox-Modus)." | Owner enables live writes explicitly. | No | No |

---

## 17. MVP Version

### What Is Included
- Bot registry entry for "X DM Bot — RTxRT" in Mission Control.
- Read-only dashboard view: bot status, last run summary, run history table, contact archive summary.
- Sandbox run mode: executes scan (Pass 1) against live X DOM to verify targeting, but does not send any DMs. Writes a dry-run output log.
- New Run form (owner only): profile selector (from AdsPower), message input, target count input, message preview panel, sandbox mode indicator, "Start Sandbox Run" button.
- Run detail page: live status polling, log feed, scan count card, completion summary.
- Operator access: view-only dashboard, export run history CSV, export contact archive CSV (summarized).
- Audit log page: all sandbox run events.
- Settings page: sandbox mode toggle (on by default), kill switch, API key status indicators.

### What Is Intentionally Excluded
- Live DM sending (Pass 2).
- AdsPower browser open via API (in sandbox, Playwright connection is simulated/mocked).
- Windows Task Scheduler registration.
- Any write to X.com platform.
- Operator ability to start runs.
- Schedule configuration.

### Actions That Are Blocked
- `POST /start-bot` → disabled.
- `GET /ads-start/<user_id>` → disabled.
- Any Playwright `page.goto()` to a chat URL for sending.
- Any `composer.type()` or `send_message_in_chat()` call.
- `schtasks /create` subprocess call.

### What the Dashboard Can Show
- Sandbox run results: N contacts that would have been messaged, with handles listed.
- 24h filter results: N contacts skipped due to recent contact.
- Read-only contact count from scan.
- Run history for all sandbox runs.
- Contact archive summary (counts per profile).

### What an Operator Can Do
- View dashboard.
- View sandbox run results.
- Export run history.
- Export contact archive (summarized).
- View audit log.
- Pause a running sandbox scan.

### What Only Zach (Owner) Can Do
- Start a sandbox run.
- Change settings.
- Enable live writes (post-MVP).
- Activate/deactivate the kill switch.
- Review and approve any Needs Review runs.
- Delete or archive run records.

### Data That Is Stored
- Bot registry entry.
- Run records (sandbox only): inputs snapshot, scan output, dry-run contact list, elapsed time, status.
- Audit log events.
- Contact archive mirror (read from contacts.json on run).

### Data That Is Redacted
- API keys → `[REDACTED]`.
- AdsPower credentials → `[REDACTED]`.
- X session cookies → not stored.
- Full fan DM message bodies received → not read or stored.

### Tests Required Before Merging
- Sandbox run completes without any network call to X.com send routes.
- Operator cannot access `/start-bot` (returns 403).
- Owner can start sandbox run and view dry-run output.
- Audit log captures all run events.
- No API keys appear in any API response or frontend page source.
- Contact archive loads and displays correctly.
- Kill switch disables all pending runs.
- Rate limit prevents two simultaneous runs for the same profile.

---

## 18. Future Versions

### Version 2 — Supervised Live Sending
**New capabilities:**
- Live DM sending enabled behind explicit owner switch.
- Message preview + contact list preview mandatory before any live send.
- Manual "Approve and Send" gate after scan phase, before Pass 2.
- Per-send confirmation option (one-at-a-time mode for testing).
- Discord/Telegram webhook alerts: run started, run completed, errors.
- Read-only contact tracking (separate list; excluded from future targets).

**New risks:** Live messages sent to real users. Platform TOS risk. Irreversibility.

**New safety gates required:**
- Mandatory pre-send approval modal with full contact list visible.
- Max sends per day per profile: configurable cap (default 50).
- Automatic pause after 10 consecutive read-only skips.

**New permissions required:** Owner must explicitly flip `LIVE_WRITES_ENABLED = true` in settings with a confirmation modal.

**New dashboard requirements:** Contact list preview panel before send; live send progress bar; per-send confirmation mode toggle.

---

### Version 3 — Multi-Account and Scheduled Campaigns
**New capabilities:**
- Multiple accounts in a single run (`accounts` array in auftrag).
- Campaign manager: save and reuse message templates.
- Schedule builder: per-account daily schedule with time-of-day configuration.
- Automatic 24h filter across accounts (shared contacts.json).
- Read-only contact exclusion list auto-populated and persisted.
- Operator can draft campaigns for owner review.
- Bulk import of target message variants (A/B testing).

**New risks:** Automated multi-account execution with no human in loop. Higher X detection risk. Higher volume = higher ban risk.

**New safety gates required:**
- Per-account daily send limit enforced.
- Inter-send delay randomization (configurable).
- X bot detection heuristic: if error rate > 20% in a run, auto-pause and alert.
- Campaign approval gate: operator drafts → owner approves before schedule activates.

**New permissions required:** Operator may draft campaigns; cannot approve or schedule.

**New dashboard requirements:** Campaign manager page; schedule calendar view; per-account performance metrics.

---

### Full Production Version
**New capabilities:**
- Webhook-based status push (no polling).
- Full API abstraction layer — `dm_bot.py` refactored as a standalone service with REST API.
- Mission Control manages bot lifecycle entirely (no manual file edits).
- Multi-agency support: one Mission Control instance manages multiple MSA operators.
- Analytics: send rate trends, read-only rate trends, 24h filter hit rate, estimated reach per campaign.
- Automated compliance checks: flag messages containing regulated content keywords before send.
- Disaster recovery: partial run resume from last successful send.

**New risks:** Multi-tenant data isolation. Compliance exposure. Scale increases ban risk.

**New safety gates required:** Full role-based access control; data isolation per agency; compliance keyword blocklist; mandatory run simulation before any new message template goes live.

---

## 19. Recommended Data Model

### `bot_registry`
| Field | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| name | VARCHAR | "X DM Bot — RTxRT" |
| slug | VARCHAR | "x-dm-rtxrt" |
| version | VARCHAR | "1.0.0" |
| description | TEXT | Plain English summary |
| live_writes_enabled | BOOLEAN | Default FALSE |
| sandbox_mode | BOOLEAN | Default TRUE |
| kill_switch_active | BOOLEAN | Default FALSE |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### `bot_runs`
| Field | Type | Notes |
|---|---|---|
| id | UUID | Primary key |
| bot_id | UUID | FK → bot_registry |
| status | ENUM | draft/queued/running_scan/running_send/needs_review/approved/rejected/completed/failed/paused/archived |
| mode | ENUM | sandbox / live |
| profile_id | VARCHAR | AdsPower user_id (not a credential) |
| profile_name | VARCHAR | Display name |
| message_preview | VARCHAR(100) | First 80 chars only |
| target_count | INTEGER | |
| sent_count | INTEGER | |
| scan_count | INTEGER | Total targets found in scan |
| readonly_count | INTEGER | Skipped as read-only |
| elapsed_seconds | INTEGER | |
| started_at | TIMESTAMP | |
| completed_at | TIMESTAMP | |
| created_by | UUID | FK → users |
| error_message | TEXT | Sanitized; no secrets |

### `bot_run_inputs`
| Field | Type | Notes |
|---|---|---|
| id | UUID | |
| run_id | UUID | FK → bot_runs |
| key | VARCHAR | e.g., "max_chats" |
| value | TEXT | Sensitive keys never stored |
| is_sensitive | BOOLEAN | If true, value is "[REDACTED]" |

### `bot_run_outputs`
| Field | Type | Notes |
|---|---|---|
| id | UUID | |
| run_id | UUID | FK → bot_runs |
| output_type | ENUM | dry_run_list / send_log / error_log / scan_summary |
| content | JSONB | Array of log strings or contact handles |
| created_at | TIMESTAMP | |

### `bot_approvals`
| Field | Type | Notes |
|---|---|---|
| id | UUID | |
| run_id | UUID | FK → bot_runs |
| action | ENUM | approve / reject / pause / resume |
| performed_by | UUID | FK → users |
| role_at_time | ENUM | owner / operator |
| note | TEXT | Optional |
| created_at | TIMESTAMP | |

### `bot_audit_logs`
| Field | Type | Notes |
|---|---|---|
| id | UUID | |
| run_id | UUID | FK → bot_runs (nullable for system events) |
| event_type | VARCHAR | e.g., RUN_STARTED, RUN_SCAN_UPDATE |
| actor | UUID | FK → users (nullable for bot-initiated) |
| payload | JSONB | Non-sensitive context only |
| created_at | TIMESTAMP | |

### `bot_settings`
| Field | Type | Notes |
|---|---|---|
| id | UUID | |
| bot_id | UUID | FK → bot_registry |
| key | VARCHAR | e.g., "schedule_time", "max_sends_per_day" |
| value | TEXT | |
| is_secret | BOOLEAN | If true, value never returned to API |
| updated_by | UUID | |
| updated_at | TIMESTAMP | |

### `bot_contact_archive`
| Field | Type | Notes |
|---|---|---|
| id | UUID | |
| bot_id | UUID | FK → bot_registry |
| profile_id | VARCHAR | AdsPower user_id |
| handle | VARCHAR | X display name or URL path segment |
| conversation_url | VARCHAR | Full URL (not credentials) |
| last_sent_at | TIMESTAMP | UTC |
| sent_count | INTEGER | Lifetime sends to this contact |

### `operator_permissions`
| Field | Type | Notes |
|---|---|---|
| id | UUID | |
| user_id | UUID | FK → users |
| bot_id | UUID | FK → bot_registry |
| role | ENUM | owner / operator |
| can_start_live | BOOLEAN | Only owner |
| can_view_logs | BOOLEAN | All roles |
| can_export | BOOLEAN | All roles |
| can_approve | BOOLEAN | Owner only |
| granted_by | UUID | |
| granted_at | TIMESTAMP | |

### `safety_events`
| Field | Type | Notes |
|---|---|---|
| id | UUID | |
| run_id | UUID | Nullable |
| event_type | VARCHAR | e.g., KILL_SWITCH_ACTIVATED, RATE_LIMIT_DETECTED |
| severity | ENUM | info / warning / critical |
| description | TEXT | |
| resolved | BOOLEAN | |
| created_at | TIMESTAMP | |

### `external_integrations`
| Field | Type | Notes |
|---|---|---|
| id | UUID | |
| name | VARCHAR | e.g., "AdsPower" |
| base_url | VARCHAR | e.g., "http://local.adspower.net:50325" |
| credential_ref | VARCHAR | Reference to secrets manager key — NOT the value |
| status | ENUM | connected / unreachable / unknown |
| last_checked_at | TIMESTAMP | |

---

## 20. Recommended API Endpoints

| # | Path | Method | Purpose | Required Role | Sandbox Only | Can Trigger Live Action | Audit Log Required |
|---|---|---|---|---|---|---|---|
| 1 | `/api/bots` | GET | List all registered bots | Operator | No | No | No |
| 2 | `/api/bots/:id` | GET | Get bot registry entry + current status | Operator | No | No | No |
| 3 | `/api/bots/:id/runs` | GET | List run history for a bot | Operator | No | No | No |
| 4 | `/api/bots/:id/runs` | POST | Create a new draft run | Owner | No | No | Yes |
| 5 | `/api/bots/:id/runs/:runId` | GET | Get run detail + log | Operator | No | No | No |
| 6 | `/api/bots/:id/runs/:runId/start` | POST | Move run from Draft to Queued | Owner | No | **Yes (live mode)** | Yes |
| 7 | `/api/bots/:id/runs/:runId/approve` | POST | Approve a Needs Review run | Owner | No | **Yes (live mode)** | Yes |
| 8 | `/api/bots/:id/runs/:runId/reject` | POST | Reject a run | Owner or Operator | No | No | Yes |
| 9 | `/api/bots/:id/runs/:runId/pause` | POST | Pause a running bot | Owner or Operator | No | No | Yes |
| 10 | `/api/bots/:id/runs/:runId/resume` | POST | Resume a paused run | Owner | No | **Yes (live mode)** | Yes |
| 11 | `/api/bots/:id/runs/:runId/log` | GET | Stream or fetch live log for a run | Operator | No | No | No |
| 12 | `/api/bots/:id/runs/:runId/export` | GET | Export run log as CSV | Operator | No | No | No |
| 13 | `/api/bots/:id/contacts` | GET | Get contact archive summary | Operator | No | No | No |
| 14 | `/api/bots/:id/contacts/export` | GET | Export contact archive as CSV | Operator | No | No | Yes |
| 15 | `/api/bots/:id/settings` | GET | Get bot settings (non-secret keys only) | Owner | No | No | No |
| 16 | `/api/bots/:id/settings` | PATCH | Update bot settings | Owner | No | No | Yes |
| 17 | `/api/bots/:id/kill` | POST | Activate kill switch | Owner | No | No | Yes |
| 18 | `/api/bots/:id/schedule` | GET | Get schedule configuration | Owner | No | No | No |
| 19 | `/api/bots/:id/schedule` | PUT | Set schedule | Owner | No | **Yes** | Yes |
| 20 | `/api/bots/:id/profiles` | GET | List AdsPower profiles (proxied) | Operator | No | No | No |
| 21 | `/api/audit-log` | GET | Global audit log (paginated) | Owner | No | No | No |
| 22 | `/api/audit-log/:botId` | GET | Audit log filtered to one bot | Operator | No | No | No |
| 23 | `/api/safety-events` | GET | List safety events | Owner | No | No | No |
| 24 | `/api/sandbox/run` | POST | Trigger a sandbox (dry-run) | Owner | **Yes** | No | Yes |

---

## 21. Recommended Frontend Pages

### 1. Bot Dashboard Page (`/bots`)
**Purpose:** Overview of all registered bots and their current status.
**Components:** Bot status cards (one per bot); each shows: name, current state dot, last run summary, quick-launch button (owner only).

### 2. Bot Detail Page (`/bots/:id`)
**Purpose:** Main operational view for the X DM Bot.
**Components:** Status card, active run card (if running), scan progress card, send progress bar, run log feed, last run summary card, contact archive summary card, schedule card (owner-only), new run button (owner-only).

### 3. New Run Page (`/bots/:id/runs/new`)
**Purpose:** Configure and submit a new run.
**Components:** Profile selector dropdown (loaded from AdsPower via API), message textarea with character count, target count input, message preview box (full message displayed before submit), sandbox mode indicator banner, "Start Run" / "Start Sandbox Run" button, confirmation modal with summary.

### 4. Run Detail Page (`/bots/:id/runs/:runId`)
**Purpose:** View detail and live status of a specific run.
**Components:** Run metadata (profile, mode, started by, start time), status badge, progress bar, live log feed (auto-scrolling), scan result summary, send result summary, error panel (if applicable), approve/reject buttons (if Needs Review; owner-only).

### 5. Run Review / Approval Page (`/bots/:id/runs/:runId/review`)
**Purpose:** Owner reviews scan results before live sends begin.
**Components:** Full contact list from scan (handles + URLs), 24h filter summary, read-only skip count, full message preview, "Approve and Send" button, "Reject and Cancel" button.

### 6. Audit Log Page (`/bots/:id/audit`)
**Purpose:** Full event history for the bot.
**Components:** Filterable table (by event type, date range, actor), event detail expandable rows. No raw secret values displayed anywhere.

### 7. Settings Page (`/bots/:id/settings`)
**Purpose:** Bot configuration (owner only).
**Components:** Sandbox mode toggle, live writes enabled toggle, kill switch button (red, confirmation modal), API key status indicators (present/absent only), max sends per day input, schedule builder (time input + enable toggle), AdsPower integration status.

### 8. Operator View (`/operator/bots/:id`)
**Purpose:** Stripped-down view for the COO or other Operators.
**Components:** Status card (read-only), last run summary, run history table (view-only), log feed (view-only), export buttons, contact archive summary (no raw handle list by default). Settings, approval, and start buttons are hidden or disabled.

### 9. Owner Admin View (`/admin/bots/:id`)
**Purpose:** Full control view for Luis.
**Components:** All dashboard components + settings panel + approval controls + schedule builder + kill switch + audit log link. All buttons active.

---

## 22. Testing Checklist

### Unit Tests
- [ ] `is_filtered()` returns True for contacts within 24h, False for older or absent contacts.
- [ ] `add_contact()` correctly upserts existing URL and appends new one.
- [ ] `extract_chats_js()` mock: given sample DOM HTML, returns correct handles and URLs.
- [ ] `scroll_dm_list()` correctly identifies scrollable ancestor in mock DOM.
- [ ] `find_composer()` returns first visible element from priority list.
- [ ] `send_message_in_chat()` returns False when composer is None.
- [ ] Status set functions write correct JSON structure to status.json.

### API Tests
- [ ] `GET /api/bots` returns list of bots for operator role.
- [ ] `POST /api/bots/:id/runs` creates a draft run and returns run ID.
- [ ] `POST /api/bots/:id/runs/:id/start` is blocked with 403 for operator role.
- [ ] `POST /api/bots/:id/runs/:id/start` is blocked with sandbox error when live_writes_enabled = false.
- [ ] `GET /api/bots/:id/contacts/export` returns CSV without credential fields.
- [ ] `POST /api/bots/:id/kill` sets kill_switch_active = true and cancels queued runs.
- [ ] `GET /api/audit-log` returns paginated events with no secret values in payload.

### Permission Tests
- [ ] Operator role cannot call `/start`, `/approve`, `/resume`, `/kill`, or `/settings PATCH`.
- [ ] Operator role can call `/runs` (GET), `/log`, `/export`, `/contacts`, `/audit`.
- [ ] Owner role can call all endpoints.
- [ ] Unauthenticated request to any protected endpoint returns 401.
- [ ] Operator cannot elevate their own permissions via settings endpoints.

### Audit Log Tests
- [ ] Every `POST` to a state-changing endpoint generates an audit log entry.
- [ ] Audit log entries contain actor ID, timestamp, event type, and non-sensitive payload.
- [ ] Audit log entries never contain API keys, tokens, cookies, or passwords.
- [ ] Kill switch activation generates a `KILL_SWITCH_ACTIVATED` event.

### Sandbox Mode Tests
- [ ] With `sandbox_mode = true`, `POST /start` triggers a dry-run; no AdsPower API call is made.
- [ ] Dry-run completes without any write to X.com.
- [ ] Dry-run output includes list of contacts that would have been targeted.
- [ ] Dashboard shows "SANDBOX" banner when mode is active.

### Approval Gate Tests
- [ ] Run with `target_count > 100` auto-transitions to `Needs Review` after scan phase.
- [ ] Run cannot transition from `Needs Review` to `Running — Sending` without an approval record.
- [ ] Operator approval record is rejected (only owner approval is valid for live action).

### Redaction Tests
- [ ] API response for `/settings` never includes raw API key values.
- [ ] Bot run record stored in DB has sensitive input keys stored as "[REDACTED]".
- [ ] Audit log payload field never contains API key, cookie, or password strings.
- [ ] Contact export CSV omits conversation URLs by default.

### Duplicate Prevention Tests
- [ ] Submitting a second run for the same profile while one is Queued or Running returns an error.
- [ ] Contacts with `last_sent_at` within 24h are excluded from scan targets.

### Failure State Tests
- [ ] `failed` status is set when AdsPower API returns non-zero code.
- [ ] `failed` status is set when browser navigation returns login URL.
- [ ] Partial completion (crash mid-send) sets state to `failed` with `partial_sent` count preserved.
- [ ] Watchdog: run that has not updated `status.json` in 5 minutes triggers a `RUN_STUCK` safety event.

### No Live Write Tests (MVP Critical)
- [ ] `POST /api/bots/:id/runs/:id/start` in MVP returns `{"error":"live_writes_disabled_in_MVP"}`.
- [ ] `GET /ads-start/<user_id>` in MVP returns `{"error":"live_writes_disabled_in_MVP"}`.
- [ ] No Playwright `page.goto()` call to an X.com chat URL occurs in sandbox mode.
- [ ] No `composer.type()` or `send_message_in_chat()` call occurs in sandbox mode.
- [ ] Windows Task Scheduler registration is not called in any sandbox or MVP code path.

### No Secrets Tests
- [ ] Frontend page source does not contain any API key string.
- [ ] `GET /api/bots/:id/settings` response does not contain AdsPower API key value.
- [ ] Environment variable `ANTHROPIC_API_KEY` is not returned in any API response.
- [ ] ADS_KEY constant in server.py is not forwarded to any client response body.

### Frontend Render Tests
- [ ] Dashboard loads in under 3 seconds for a run with 200 log entries.
- [ ] Live log feed updates within 2.5 seconds of a status.json write.
- [ ] Sandbox mode banner is always visible when sandbox_mode = true.
- [ ] Operator view does not render Start Run, Approve, Settings, or Kill Switch buttons.

---

## 23. Open Questions for Zach

### Required Before MVP
1. Where is Mission Control hosted? (local Windows machine only, or cloud-deployed?)
2. Does the COO (Operator) need a login account, or is the MVP owner-only for now?
3. Should the MVP sandbox scan connect to a real AdsPower session and scan the live DM list, or should it use a fully mocked/stubbed output? (Live sandbox scan gives real targeting data but requires AdsPower to be running.)
4. Which Discord/Telegram channel should bot alerts go to?
5. Is there an existing Hermes alert system to integrate with, or should Mission Control build its own alerting?

### Required Before Live Version
6. What is the maximum number of DMs per account per day that is considered safe from X's detection systems? (Currently uncapped at 200+.)
7. Should read-only contacts be permanently excluded from all future runs, or only temporarily?
8. Who is the COO and what is their email for Mission Control access?
9. Is there a compliance review needed before live DM campaigns go to users on X? (Adult content / OnlyFans promotional links carry specific risk.)
10. What happens if X bans an account mid-campaign? What is the escalation process?
11. Should Mission Control handle multiple client agencies with separate data isolation, or is this a single-agency tool?
12. Should the contact archive be backed up externally (cloud storage), or local disk only?

### Nice to Have Later
13. Should campaign messages eventually support variable fields (e.g., `{{name}}` personalization)?
14. Should Mission Control track reply rates or engagement after DMs are sent?
15. Is A/B testing (multiple message variants per campaign) a future requirement?
16. Should there be a mobile view for the dashboard?

---

## 24. Complete Claude Code Build Prompt for Mission Control

```
You are Claude Code implementing an MVP bot module inside Mission Control.

Before writing any code:
1. Run `git log --oneline -20` to see recent commits.
2. Read the PR #21 description and changed files to understand the COO operator access system.
3. Locate and read the following files (or their current equivalents):
   - The Bots page (likely at /app/bots or /pages/bots)
   - The bot registry model or schema
   - The operator permission model
   - The audit log foundation
   - Any existing safety gate utilities or middleware
   Report what you find before writing any code.

Your task is to implement an MVP for the "X DM Bot — RTxRT" inside Mission Control.

The MVP MUST be sandbox/draft mode only. No live DM sends. No AdsPower browser opens. No X.com writes.

== WHAT TO BUILD ==

1. Bot Registry Entry
   - Add "X DM Bot — RTxRT" to the bot registry with fields:
     name, slug ("x-dm-rtxrt"), version ("1.0.0"),
     live_writes_enabled: false (hardcoded in MVP),
     sandbox_mode: true (default),
     kill_switch_active: false

2. Database Schema (add migrations for):
   - bot_runs: id, bot_id, status (enum), mode (sandbox/live),
     profile_id, profile_name, message_preview (varchar 100),
     target_count, sent_count, scan_count, readonly_count,
     elapsed_seconds, started_at, completed_at, created_by, error_message
   - bot_run_outputs: id, run_id, output_type (enum), content (jsonb), created_at
   - bot_contact_archive: id, bot_id, profile_id, handle, conversation_url, last_sent_at, sent_count
   - bot_audit_logs: id, run_id (nullable), event_type, actor (nullable), payload (jsonb), created_at
   - safety_events: id, run_id (nullable), event_type, severity (enum), description, resolved, created_at
   Do NOT store API keys, cookies, passwords, or session tokens in any table.

3. API Endpoints (implement these routes):
   GET  /api/bots                        → list bots (operator+)
   GET  /api/bots/:id                    → get bot detail (operator+)
   GET  /api/bots/:id/runs               → list runs (operator+)
   POST /api/bots/:id/runs               → create draft run (owner only)
   GET  /api/bots/:id/runs/:runId        → get run detail (operator+)
   POST /api/bots/:id/runs/:runId/start  → start run — sandbox only in MVP (owner only)
   POST /api/bots/:id/runs/:runId/reject → reject run (owner or operator)
   POST /api/bots/:id/runs/:runId/pause  → pause run (owner or operator)
   GET  /api/bots/:id/runs/:runId/log    → get run log (operator+)
   GET  /api/bots/:id/runs/:runId/export → export run CSV (operator+)
   GET  /api/bots/:id/contacts           → contact archive summary (operator+)
   GET  /api/bots/:id/settings           → settings without secret values (owner only)
   POST /api/bots/:id/kill               → kill switch (owner only)
   GET  /api/audit-log/:botId            → audit log for bot (operator+)
   POST /api/sandbox/run                 → trigger sandbox dry-run (owner only)
   All other routes (live start, schedule, approve live) → return {"error":"not_available_in_MVP"}

4. Safety Gates (enforce in middleware):
   - Every route that changes state must check: role === "owner" or explicitly allowed for operator.
   - Every route that would trigger a live write must check: live_writes_enabled === false in MVP.
     If a live write is attempted, return 403 {"error": "live_writes_disabled_in_MVP"}.
   - Audit log entry must be created on every state-changing route call.
   - No API key, cookie, password, or token may appear in any API response body.
   - Duplicate run prevention: if a run is Queued or Running for the same profile, reject new run with 409.

5. Sandbox Run Logic
   The MVP sandbox run should:
   a. Write a draft run record to bot_runs.
   b. Simulate a scan result by returning mock data (N contacts, N filtered out, N read-only).
      Do NOT connect to AdsPower. Do NOT open any browser. Do NOT navigate to X.com.
   c. Write the simulated result to bot_run_outputs.
   d. Set run status to "completed" with mode "sandbox".
   e. Write audit log events: RUN_CREATED, RUN_SCAN_STARTED, RUN_SCAN_COMPLETED, RUN_COMPLETED.

6. Dashboard UI Pages
   Build or extend these pages (match the existing Mission Control UI style):
   a. /bots — bot list page with status cards
   b. /bots/:id — bot detail page:
      - Status card (dot + state label)
      - Active run card (profile, message preview, target/sent counts, progress bar)
      - Last run summary card
      - Contact archive summary card (counts per profile)
      - New Run button (owner only)
      - SANDBOX mode banner (always visible in MVP)
   c. /bots/:id/runs/new — new run form:
      - Profile selector (hardcoded mock profiles in MVP; real AdsPower call blocked)
      - Message textarea
      - Target count input
      - Message preview panel (shows full message before submit)
      - "Start Sandbox Run" button only (live button absent in MVP)
      - Confirmation modal: profile, message preview, target count, sandbox warning
   d. /bots/:id/runs/:runId — run detail page:
      - Run metadata, status badge, dry-run output list
   e. /bots/:id/audit — audit log table (filterable by event type, date)
   f. /bots/:id/settings — settings page (owner only):
      - Sandbox mode toggle (locked ON in MVP; toggle disabled)
      - Kill switch button (red; confirmation modal)
      - API key status indicators (present/absent only — no values)

7. Operator View
   Use the COO operator access system from PR #21.
   Operators can see: bot detail, run history, log export, audit log.
   Operators cannot see: settings page, new run button, kill switch, approve button.
   Hide these elements based on the existing role check pattern in PR #21.

8. Audit Logging
   Every state-changing action must call an audit log write function.
   Payload must include: event_type, actor_id, run_id (if applicable), timestamp.
   Payload must never include: API keys, cookies, passwords, tokens, or full message bodies.
   Use the existing audit log foundation if present; extend it if needed.

9. Tests to Write
   After implementation, write tests for:
   - Operator cannot call /start, /kill, /approve, /settings PATCH → expect 403.
   - Owner can call /start in sandbox → expect 200 with dry-run output.
   - /start in MVP with live_writes_enabled = false → expect 403 with live_writes_disabled_in_MVP error.
   - No API key in any GET /settings response.
   - Audit log is created on run create, start, pause, reject, kill.
   - Duplicate run rejected with 409 when one is already queued for same profile.
   - Kill switch sets kill_switch_active = true and cancels queued runs.

== WHAT NOT TO DO ==
- Do NOT connect to AdsPower local API (http://local.adspower.net:50325).
- Do NOT open any browser via Playwright or CDP.
- Do NOT navigate to X.com in any code path.
- Do NOT store API keys, passwords, cookies, or tokens.
- Do NOT implement live DM sending.
- Do NOT implement Windows Task Scheduler integration.
- Do NOT commit anything. Stage only the files you changed.
- Do NOT invent a database schema that conflicts with the existing Mission Control schema — inspect it first.

== REPORTING ==
When done, report:
1. Files created or modified (with line counts).
2. New features added (list each one).
3. Tests written and whether they pass.
4. Safety gates implemented (list each one).
5. Any remaining blockers or questions before this can be reviewed.
```

---

END OF BOT SPEC
