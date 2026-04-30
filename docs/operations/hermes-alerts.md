# Hermes structured alerts

Hermes upgrade: turn vague one-line notifications into actionable incident
alerts. This is the **first slice** — formatter library, templates, and a
dry-run CLI. It does **not** modify the production watchdog hooks in
`~/.hermes/hooks/` and it cannot send a real notification without two
explicit safety toggles.

## Files

| File | Role |
|------|------|
| [`scripts/hermes-alert.sh`](../../scripts/hermes-alert.sh) | CLI entry point. Renders Discord + Telegram + repair prompt. |
| [`scripts/lib/alert-format.sh`](../../scripts/lib/alert-format.sh) | Pure formatters, validation, redaction, dedupe key, dedupe decision. |
| [`scripts/lib/alert-templates.sh`](../../scripts/lib/alert-templates.sh) | 18 baked templates for common failures. |
| [`scripts/test-hermes-alert.sh`](../../scripts/test-hermes-alert.sh) | Dry-run smoke tests. |

## Alert schema (canonical JSON)

Every firing alert MUST include:

```json
{
  "system":          "OpenClaw Gateway",
  "status":          "failed",
  "severity":        "CRITICAL",
  "exact_issue":     "Gateway is not responding on the expected local port.",
  "evidence":        ["Health probe failed", "launchd job not running"],
  "likely_cause":    "Gateway crashed, port conflict, or auth token drift.",
  "business_impact": "Claude/OpenClaw browser execution disconnected.",
  "recommended_fix": "Inspect process and logs, restart only com.digidle.openclaw.",
  "claude_prompt":   "...full repair prompt — see prompt format below...",
  "timestamp":       "2026-04-28T17:22:00Z",
  "alert_id":        "openclaw-gateway-failed-7a3b1c"
}
```

Validation is enforced by `af_validate_json`. Missing or empty required
fields → exit 3. Bad severity or status → exit 3.

## Severity

| Level | Emoji | Discord color | Meaning |
|-------|-------|--------------|---------|
| LOW       | 🔵 | blue   | Informational. No action needed. |
| MEDIUM    | 🟡 | yellow | Degraded. Should fix soon. |
| HIGH      | 🟠 | orange | Active breakage. |
| CRITICAL  | 🔴 | red    | Major system offline or data/security risk. |

## Status

`healthy`, `degraded`, `failed`, `blocked`, `rate_limited`, `disconnected`,
`unknown`, `resolved`.

## Discord format

`hermes-alert.sh` produces an embed payload ready to POST as the body of
`POST /channels/{channel_id}/messages`:

- **Title** — `<emoji> [SEVERITY] <System> — <status>`
- **Description** — `exact_issue`
- **Color** — driven by severity
- **Fields**: Status, Severity, Evidence, Likely cause, Business impact,
  Recommended fix, Repair prompt (in a code block)
- **Footer** — `id=<alert_id>`, optional `first_seen=...`
- **Timestamp** — RFC3339Z

Discord field values are truncated to ≤1024 chars; the description to ≤2048;
title to ≤256.

## Telegram format

Plain text (no `parse_mode`, so no MarkdownV2 escaping footguns):

```
🔴 CRITICAL — OpenClaw Gateway (failed)

EXACT ISSUE:
...

EVIDENCE:
- ...
- ...

LIKELY CAUSE:
...

BUSINESS IMPACT:
...

RECOMMENDED FIX:
...

COPY/PASTE REPAIR PROMPT:
---
<prompt body>
---

id=<alert_id> • ts=<timestamp>
```

Total text is truncated to ≤4000 chars (Telegram's hard limit is 4096).

## Repair prompt format

The `claude_prompt` field is the heart of the upgrade. Each prompt is written
so you can paste it into Claude verbatim. Every prompt tells Claude:

1. **What to inspect** — specific files, commands, URLs.
2. **What to fix** — only the affected layer.
3. **What NOT to touch** — explicit guard rails.
4. **What to report back** — root cause, action taken, verification.

The founder-language rule applies: written for Zach, not for an engineer.
Direct, specific, useful. No "may", no "consider", no "perhaps".

## Dedupe rules

Implemented by `af_should_fire`. State lives in
`$MC_STATE_DIR/alerts/<alert_id>.json`.

A repeat alert with the same `alert_id` is **suppressed** unless one of:

- severity increased (e.g. HIGH → CRITICAL)
- `exact_issue` text changed
- `claude_prompt` changed
- status moved to `resolved`
- more than `HERMES_DEDUPE_WINDOW_SEC` seconds elapsed (default 1800s = 30m)

A different `alert_id` is novel by definition. The default `alert_id` is
derived from `system + status + sha1(exact_issue)[:6]`, so changing the system
or status produces a new key automatically.

Exit codes from `--check-dedupe`:

- `0` → fire (state file updated)
- `2` → suppress (duplicate within window)

## Resolved alert format

A different schema, simpler:

```json
{
  "system":             "OpenClaw Gateway",
  "what_recovered":     "launchd job restarted, port 18789 listening",
  "last_failed_state":  "failed",
  "first_seen":         "2026-04-28T17:14:22Z",
  "resolved_at":        "2026-04-28T17:31:08Z",
  "failure_count":      4
}
```

Rendered as:

```
✅ Resolved: OpenClaw Gateway is healthy again
Recovered: launchd job restarted, port 18789 listening
Was: failed
First seen: 2026-04-28T17:14:22Z
Resolved at: 2026-04-28T17:31:08Z
Failures during incident: 4
```

Invoke with `--resolved --stdin-json`.

## Daily summary

Implemented as [`scripts/hermes-daily-summary.sh`](../../scripts/hermes-daily-summary.sh).
Reads `${MC_STATE_DIR:-/tmp/mc-system}/alerts/*.json` and emits one founder-readable
plain-text digest covering:

- Active incidents (failed / degraded / blocked / disconnected / rate_limited / unknown)
- Resolved incidents in the last 24 hours
- Repeated issues (alerts whose `failure_count` ≥ 3)
- Recommended cleanup (resolved state files older than 7 days)
- Best next repair prompt — the highest-severity unresolved alert's prompt

Usage:

```bash
# Dry-run on whatever lives in /tmp/mc-system/alerts/:
./scripts/hermes-daily-summary.sh

# Just the structured JSON (useful for piping to other tools or tests):
./scripts/hermes-daily-summary.sh --show json

# Just the Discord payload (POST body shape):
./scripts/hermes-daily-summary.sh --show discord

# Just the Telegram text:
./scripts/hermes-daily-summary.sh --show telegram

# Real send to the existing prod destinations:
HERMES_ALERT_ALLOW_SEND=1 ./scripts/hermes-daily-summary.sh --send --target prod

# Real send to a private test channel (requires the env vars to be set):
HERMES_ALERT_ALLOW_SEND=1 \
  HERMES_TEST_DISCORD_CHANNEL=<id> \
  HERMES_TEST_TELEGRAM_CHAT_ID=<id> \
  ./scripts/hermes-daily-summary.sh --send --target test
```

### Sample output

```
🌅 Hermes daily summary — 2026-04-29 08:00 EDT

⚠ 4 active incident(s): 1 CRITICAL, 3 HIGH.
   (4 alert state file(s) total)

🔴 Active problems
   🔴 CRITICAL — OpenClaw Gateway — failed (last seen 2026-04-29T23:49:31Z)
      OpenClaw gateway is not responding on the expected local port.
   🟠 HIGH — Mission Control Frontend — failed (last seen 2026-04-29T23:40:06Z)
      The Mission Control frontend (Next.js) is not serving requests.
   🟠 HIGH — Mission Control Backend — failed (last seen 2026-04-29T00:44:11Z)
      The Mission Control backend (FastAPI) is not responding to /health.

✅ Resolved in last 24h
   (none)

🔁 Repeated issues (3+ failures)
   (none)

🔧 Best next repair prompt
   System: OpenClaw Gateway (CRITICAL)
   ---
   OpenClaw gateway is down. Inspect:
     1. launchctl print gui/$(id -u)/com.digidle.openclaw — is it running?
     2. ~/.openclaw/logs/gateway.err and gateway.log — last 100 lines.
     ...
   ---

(generated by hermes-daily-summary.sh)
```

### How to schedule (future)

Not auto-scheduled in this slice — the script must be invoked manually for
real sends. When you're ready to put it on a daily timer, the cleanest local
fit is a launchd plist that fires at e.g. 08:00 local time:

```xml
<!-- ~/Library/LaunchAgents/com.digidle.hermes-daily.plist -->
<plist version="1.0"><dict>
  <key>Label</key>                <string>com.digidle.hermes-daily</string>
  <key>ProgramArguments</key>     <array>
    <string>/bin/bash</string>
    <string>-c</string>
    <string>HERMES_ALERT_ALLOW_SEND=1 /Users/zachary/mission-control-hermes-alerts/scripts/hermes-daily-summary.sh --send --target prod</string>
  </array>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key>   <integer>8</integer>
    <key>Minute</key> <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>      <string>/Users/zachary/.local/log/hermes-daily.log</string>
  <key>StandardErrorPath</key>    <string>/Users/zachary/.local/log/hermes-daily.log</string>
</dict></plist>
```

Load with `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.digidle.hermes-daily.plist`.

### What the daily summary does NOT do yet

- No interactive UI (the Mission Control Hermes section already covers live
  state; the daily digest is a different surface — Discord/Telegram).
- No automatic cleanup of old state files. The "Recommended cleanup" line
  prints the count and a `find` command to review; deletion stays manual.
- No per-system trend graphs (count over time, MTTR, etc.). Strictly a
  snapshot of the last-fired state per alert_id.
- No paging / overflow handling beyond hard truncation at Discord 2000 chars
  / Telegram 4000 chars. Long repair prompts may be truncated; if you need
  the full prompt, use the Mission Control Repair Center instead.

## How to test in dry run

```bash
# Run the full dry-run suite:
./scripts/test-hermes-alert.sh

# Verbose (prints each rendered output):
./scripts/test-hermes-alert.sh -v

# One template:
./scripts/hermes-alert.sh --template gateway_down

# Show only the Discord payload:
./scripts/hermes-alert.sh --template gateway_down --show discord

# Show only the repair prompt:
./scripts/hermes-alert.sh --template backend_down --show prompt

# Override fields:
./scripts/hermes-alert.sh --template api_token_invalid \
  --field 'system=Anthropic API' \
  --field 'evidence=401 from /v1/messages
Token in env: ANTHROPIC_API_KEY
Last success: 4 minutes ago'

# Resolved alert:
echo '{"system":"Backend","resolved_at":"2026-04-28T18:00:00Z"}' \
  | ./scripts/hermes-alert.sh --resolved --stdin-json
```

## How to add a new template

1. Open [`scripts/lib/alert-templates.sh`](../../scripts/lib/alert-templates.sh).
2. Add `tpl_<your_name>()` following the existing pattern. Set every `H_*`
   variable. Always include `H_PROMPT` with the full inspect/fix/don't-touch/
   report-back structure.
3. Allow override via `${H_SOMETHING:-default}` for fields that vary per
   incident (system name, evidence).
4. Add a smoke test in `scripts/test-hermes-alert.sh`.
5. Document the new template here.

## Safety guards (first slice)

- `--dry-run` is the default mode.
- `--send` is rejected unless `HERMES_ALERT_ALLOW_SEND=1` is set in the env.
- Even with the env var set, the first-slice `--send` path is **not
  implemented** and exits 4. To wire it up, add the `curl` POST after
  reviewing real dry-run output.
- Redaction runs by default; `--no-redact` opts out and is discouraged.
- Tests run in an isolated `MC_STATE_DIR=$(mktemp -d)` to avoid colliding
  with real Hermes state.

## Live hook status

`~/.hermes/hooks/` is outside this repo. The current wiring as of
2026-04-28 (full fingerprint in
[hermes-live-hooks-snapshot.md](hermes-live-hooks-snapshot.md)):

- `claw_watchdog.sh` — **wired** to `hermes-alert.sh`. Live outside this
  repo. Rollback: `~/.hermes/hooks/claw_watchdog.sh.bak.20260428`.
- `service_watchdog.sh` — **wired** to `hermes-alert.sh`. Live outside
  this repo. Rollback: `~/.hermes/hooks/service_watchdog.sh.bak.20260428`.
- `system_event.sh` — **wired** to `hermes-alert.sh` (boot/wake events
  via `tpl_machine_restarted`). Live outside this repo. Rollback:
  `~/.hermes/hooks/system_event.sh.bak.20260428`.
- `health_claw_remote.sh` — **not wired**, by design. Diagnostic-only
  script invoked manually via `/health claw`; prints to stdout, does not
  post alerts.
- `notify.sh` — legacy plain-string sender. **No active live-hook
  callers** as of this slice. Kept on disk for rollback compatibility —
  the rollback `.bak` files for the three rewired hooks call it by name.
  Safe to retire once you're confident none of the rewired hooks need to
  be reverted.

## What's NOT in this slice

- Wiring into `~/.hermes/hooks/notify.sh`, `service_watchdog.sh`,
  `claw_watchdog.sh`, `system_event.sh`. Those still send plain strings.
  Adopting the new format is a follow-up patch and requires explicit
  approval.
- Real send (HTTP POST to Discord/Telegram).
- Daily summary aggregator.
- A web UI / dashboard.
- Discord interactive components (buttons / threads).
- LLM-driven post-mortem auto-fill of `likely_cause`.
