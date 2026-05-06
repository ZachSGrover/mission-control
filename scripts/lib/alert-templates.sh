#!/usr/bin/env bash
# alert-templates.sh — pre-baked Hermes alert templates.
# Source this file. Requires alert-format.sh to be sourced first.
#
# Each template is a function `tpl_<name>` that prints canonical alert JSON to
# stdout. Templates are starter content with sensible defaults; callers can
# override fields via env vars before invocation:
#
#   H_TIMESTAMP   — RFC3339Z (default: now)
#   H_ALERT_ID    — override dedupe key (default: derived)
#   H_EVIDENCE    — newline-separated evidence lines (default: template's)
#
# Or via --field flags on hermes-alert.sh which deep-merge over the JSON output.
#
# Templates follow the founder-language rule: written for Zach, not for an
# engineer. Direct, specific, useful. Repair prompts always tell Claude:
#   - what to inspect
#   - what to fix
#   - what NOT to touch
#   - what confirmation to report back

# ── Internal: emit canonical JSON from H_* env vars ──────────────────────────
# Pass every H_* explicitly to the python subprocess via inline env-prefix.
# Bash function-scoped assignments are NOT exported by default, so we must
# forward them on the python invocation line.
_tpl_emit() {
  local ts="${H_TIMESTAMP:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
  local id="${H_ALERT_ID:-$(af_dedupe_key "$H_SYSTEM" "$H_STATUS" "$H_ISSUE")}"
  H_SYSTEM="$H_SYSTEM" \
  H_STATUS="$H_STATUS" \
  H_SEVERITY="$H_SEVERITY" \
  H_ISSUE="$H_ISSUE" \
  H_EVIDENCE="${H_EVIDENCE:-}" \
  H_CAUSE="$H_CAUSE" \
  H_IMPACT="$H_IMPACT" \
  H_FIX="$H_FIX" \
  H_PROMPT="$H_PROMPT" \
  H_TS="$ts" \
  H_ID="$id" \
  python3 - <<'PYEOF'
import json, os
ev_raw = os.environ.get('H_EVIDENCE','').strip()
evidence = [l for l in ev_raw.split('\n') if l.strip()] if ev_raw else []
out = {
  "system":          os.environ['H_SYSTEM'],
  "status":          os.environ['H_STATUS'],
  "severity":        os.environ['H_SEVERITY'],
  "exact_issue":     os.environ['H_ISSUE'],
  "evidence":        evidence,
  "likely_cause":    os.environ['H_CAUSE'],
  "business_impact": os.environ['H_IMPACT'],
  "recommended_fix": os.environ['H_FIX'],
  "claude_prompt":   os.environ['H_PROMPT'],
  "timestamp":       os.environ['H_TS'],
  "alert_id":        os.environ['H_ID'],
}
print(json.dumps(out, indent=2, ensure_ascii=False))
PYEOF
}

# ── Templates ─────────────────────────────────────────────────────────────────

tpl_backend_down() {
  H_SYSTEM="Mission Control Backend"
  H_STATUS="failed"
  H_SEVERITY="CRITICAL"
  H_ISSUE="The Mission Control backend (FastAPI) is not responding to /health."
  H_EVIDENCE="${H_EVIDENCE:-Health check returned non-200 or timed out
Expected: HTTP 200 from /health
Last successful response: unknown}"
  H_CAUSE="Process crashed, deploy mid-flight, database/redis dependency down, or env var missing."
  H_IMPACT="Frontend cannot load data, API routes fail, agents cannot run, automation halts."
  H_FIX="Check the backend process, recent deploy logs, and whether postgres+redis are reachable. Restart only the backend service if it is the sole failure."
  H_PROMPT="Mission Control backend is failing /health. Inspect:
  1. Backend launchd job (com.digidle.backend) status and recent stderr.
  2. Render deploy log for the latest backend deploy.
  3. Postgres and Redis reachability from the backend host.
  4. Environment variables that have been added or removed in the last hour.
Fix the root cause. Restart only the backend if needed.
Do NOT touch frontend, OpenClaw gateway, or migrate the database.
Report back: root cause, what you changed, current /health response, and whether any other service was impacted."
  _tpl_emit
}

tpl_frontend_down() {
  H_SYSTEM="Mission Control Frontend"
  H_STATUS="failed"
  H_SEVERITY="HIGH"
  H_ISSUE="The Mission Control frontend (Next.js) is not serving requests."
  H_EVIDENCE="${H_EVIDENCE:-Local dev server not responding on :3000 OR production app.digidle.com returning 5xx
Expected: 200 or 307 redirect on /sign-in}"
  H_CAUSE="Next.js process crashed, Vercel deploy failed, build output missing, or proxy.ts middleware throwing."
  H_IMPACT="You cannot access the dashboard. Anyone using hq.digidle.com or app.digidle.com sees an error page."
  H_FIX="Check the frontend process or latest Vercel deploy. Look for build errors and middleware exceptions. Restart only the frontend service."
  H_PROMPT="Mission Control frontend is down. Inspect:
  1. Local: launchd job com.digidle.next-server and its stderr log.
  2. Production: latest Vercel deploy status and build log.
  3. proxy.ts middleware (Next.js 16) for unhandled errors.
  4. Recent commits to frontend/ that could have broken the build.
Fix only the broken build or runtime error. Restart the frontend service if it is down.
Do NOT modify backend, database, or auth provider configuration.
Report back: root cause, file(s) changed, deploy/restart result, current HTTP status from /sign-in."
  _tpl_emit
}

tpl_gateway_down() {
  H_SYSTEM="OpenClaw Gateway"
  H_STATUS="failed"
  H_SEVERITY="CRITICAL"
  H_ISSUE="OpenClaw gateway is not responding on the expected local port."
  H_EVIDENCE="${H_EVIDENCE:-Health probe http://127.0.0.1:18789/health failed
launchd job com.digidle.openclaw not running OR no openclaw-gateway process
Last successful heartbeat: unknown}"
  H_CAUSE="Gateway crashed, failed to start, port 18789 conflict, or auth token config drift."
  H_IMPACT="Claude/OpenClaw browser execution disconnected. Mission Control may load, but agent actions through the gateway will fail."
  H_FIX="Inspect the gateway process and its log. Confirm port 18789 is free for loopback. Restart only com.digidle.openclaw if safe."
  H_PROMPT="OpenClaw gateway is down. Inspect:
  1. launchctl print gui/\$(id -u)/com.digidle.openclaw — is it running?
  2. ~/.openclaw/logs/gateway.err and gateway.log — last 100 lines.
  3. lsof -iTCP:18789 — is anything else holding the port?
  4. ~/.openclaw/openclaw.json — token/config integrity (do NOT print the token).
Fix the root cause. Then restart with: launchctl kickstart -k gui/\$(id -u)/com.digidle.openclaw
Do NOT touch cloudflared, Cloudflare Access, the backend, or the frontend.
Do NOT regenerate the gateway auth token.
Report back: root cause, log evidence, restart outcome, /health response, and whether claw.digidle.com is now reachable end-to-end."
  _tpl_emit
}

tpl_discord_heartbeat_missing() {
  H_SYSTEM="Discord Bot (Hermes notify path)"
  H_STATUS="disconnected"
  H_SEVERITY="HIGH"
  H_ISSUE="No Discord heartbeat received within the expected window."
  H_EVIDENCE="${H_EVIDENCE:-No successful Discord POST in the last N minutes
Expected: regular system_event or watchdog notify
Bot token present: yes (not displayed)}"
  H_CAUSE="Bot logged out, gateway disconnect, rate-limited, channel deleted, or token revoked."
  H_IMPACT="You stop receiving Hermes alerts in #hermes-general. Real incidents could pass silently."
  H_FIX="Test a manual Discord POST. If it fails with 401/403, rotate the bot token. If it fails with 429, wait and reduce alert volume. Verify the channel ID still exists."
  H_PROMPT="Hermes Discord notify path appears dead. Inspect:
  1. Last successful Discord POST timestamp in ~/.hermes/hooks/state/.
  2. Run a single manual probe: curl POST to channel 1496312417565806592 with a test message via ~/.hermes/hooks/notify.sh 'probe'.
  3. If 401/403: token revoked or bot kicked from server.
  4. If 429: rate-limited — check alert volume in last hour.
  5. If 404: channel deleted or moved.
Fix the cause. Do NOT print or paste the bot token anywhere.
Do NOT modify Telegram path, watchdog cadence, or system_event hook logic.
Report back: HTTP code from probe, root cause, action taken, whether Telegram is also affected."
  _tpl_emit
}

tpl_telegram_heartbeat_missing() {
  H_SYSTEM="Telegram Bot (Hermes notify path)"
  H_STATUS="disconnected"
  H_SEVERITY="HIGH"
  H_ISSUE="No Telegram heartbeat received within the expected window."
  H_EVIDENCE="${H_EVIDENCE:-No successful Telegram sendMessage in the last N minutes
Expected: regular system_event or watchdog notify
Bot token present: yes (not displayed)}"
  H_CAUSE="Bot blocked, chat_id wrong, token revoked, polling stuck, or Telegram API outage."
  H_IMPACT="Mobile alerts stop. You may miss incidents when away from the laptop."
  H_FIX="Test a manual sendMessage. If 401/403 rotate token; if 400 fix chat_id; if 429 throttle alerts."
  H_PROMPT="Hermes Telegram notify path is silent. Inspect:
  1. Last successful Telegram POST in ~/.hermes/hooks/state/.
  2. Run one probe via ~/.hermes/hooks/notify.sh 'probe'.
  3. Check status.telegram.org for an active outage.
  4. If 401: token revoked. If 400: TELEGRAM_HOME_CHANNEL chat_id is wrong.
Do NOT print the token or the chat_id in any commit, log, or message.
Do NOT modify Discord path or alert logic.
Report back: HTTP code, root cause, action taken, whether Discord is also affected."
  _tpl_emit
}

tpl_api_token_invalid() {
  H_SYSTEM="${H_SYSTEM:-Third-party API (unknown)}"
  H_STATUS="failed"
  H_SEVERITY="HIGH"
  H_ISSUE="A request to a third-party API returned an auth error (401/403)."
  H_EVIDENCE="${H_EVIDENCE:-API call returned 401 or 403 Unauthorized
Token in env: present but rejected
Most recent successful call: unknown}"
  H_CAUSE="Token expired, rotated, scope reduced, or wrong env var was loaded."
  H_IMPACT="Any feature that depends on this API will fail until the token is fixed."
  H_FIX="Identify which API. Confirm the env var is set in the right environment. Rotate or refresh the token. Re-run the request."
  H_PROMPT="A third-party API rejected our token. Inspect:
  1. Which API errored — find the exact 401/403 response in recent logs.
  2. Which env var holds that token and which process loaded it.
  3. Whether the token has expired, been rotated, or had scopes reduced.
  4. Where the token is stored (1Password / .env / Render env).
Refresh or rotate the token, update the env var, restart only the affected service.
Do NOT print, paste, or commit the token. Do NOT touch unrelated APIs.
Report back: API name, root cause, what you rotated (not the value), restart outcome."
  _tpl_emit
}

tpl_websocket_failed() {
  H_SYSTEM="${H_SYSTEM:-WebSocket connection}"
  H_STATUS="disconnected"
  H_SEVERITY="HIGH"
  H_ISSUE="A long-lived WebSocket connection failed to establish or dropped repeatedly."
  H_EVIDENCE="${H_EVIDENCE:-Connection closed with non-1000 code OR handshake never completed
Expected: persistent connection
Reconnect attempts: ongoing}"
  H_CAUSE="Auth handshake failure, Origin/Header mismatch, gateway down, or Cloudflare Access blocking."
  H_IMPACT="Real-time features fail (browser control, live agent output, push updates)."
  H_FIX="Check the gateway is up. Verify the connect-frame auth payload and protocol version. Test from a clean local client."
  H_PROMPT="A Hermes/Mission Control WebSocket is failing. Inspect:
  1. Gateway health (see gateway_down template steps).
  2. The exact close code in the client console / network log.
  3. The connect frame: minProtocol/maxProtocol, role, scopes, and Origin header.
  4. Whether Cloudflare Access is blocking ws upgrade for non-browser clients.
Fix only the connection layer. Do NOT regenerate tokens unless you confirm the token is the cause.
Do NOT touch backend, DB, or unrelated routes.
Report back: close code, root cause, fix applied, whether reconnect is now stable for at least 60s."
  _tpl_emit
}

tpl_database_down() {
  H_SYSTEM="Postgres Database"
  H_STATUS="failed"
  H_SEVERITY="CRITICAL"
  H_ISSUE="The Postgres database is not accepting connections."
  H_EVIDENCE="${H_EVIDENCE:-pg_isready returned non-zero
Backend cannot acquire a connection
Last successful query: unknown}"
  H_CAUSE="Service stopped, disk full, max_connections exceeded, or socket/auth misconfig."
  H_IMPACT="Mission Control backend cannot read or write data. Everything dependent on persistence breaks."
  H_FIX="Run pg_isready. Check brew services status for postgresql@16. Inspect the postgres log for fatal errors. Free disk space if low."
  H_PROMPT="Postgres is down. Inspect:
  1. brew services list | grep postgres — is the service running?
  2. /usr/local/var/log/postgresql@16.log — last 200 lines for fatal errors.
  3. Disk space on / and /usr/local/var with df -h.
  4. Open connections vs max_connections.
Restart with brew services restart postgresql@16 ONLY if logs show a benign cause.
Do NOT run any migrations, do NOT drop or truncate any table, do NOT touch Redis or backend code.
Report back: root cause from logs, action taken, current pg_isready status, whether backend reconnected automatically."
  _tpl_emit
}

tpl_rate_limited() {
  H_SYSTEM="${H_SYSTEM:-Outbound API (unknown)}"
  H_STATUS="rate_limited"
  H_SEVERITY="MEDIUM"
  H_ISSUE="An outbound API is returning 429 Too Many Requests."
  H_EVIDENCE="${H_EVIDENCE:-Recent responses include HTTP 429
Retry-After header observed (if present)
Expected: 200/2xx}"
  H_CAUSE="Burst of requests in a short window, hitting per-minute or per-day quota."
  H_IMPACT="Affected feature stalls or queues. Token/credit spend may also spike."
  H_FIX="Slow the caller. Add or tune backoff. Consider whether the burst is a bug (a loop) vs. legitimate volume."
  H_PROMPT="An outbound API is rate-limiting us. Inspect:
  1. Which API and which caller — find the 429 in the most recent logs.
  2. Request volume in the last 10 minutes vs. the documented quota.
  3. Whether a loop or retry storm is firing the same call repeatedly.
  4. Whether Retry-After is being respected.
Fix the caller's pacing. Do NOT raise the quota request without my approval.
Do NOT change unrelated callers.
Report back: API name, requests-per-minute, root cause (legit vs. bug), fix applied, current 429 rate."
  _tpl_emit
}

tpl_port_conflict() {
  H_SYSTEM="${H_SYSTEM:-Local service}"
  H_STATUS="failed"
  H_SEVERITY="HIGH"
  H_ISSUE="A local service cannot bind its expected port — something else is holding it."
  H_EVIDENCE="${H_EVIDENCE:-bind: address already in use
Expected port: unknown — populate H_EVIDENCE
Suspected duplicate process: unknown}"
  H_CAUSE="Stale process from a previous run, two launchd jobs scheduled to the same port, or a manual run colliding with the launchd-managed one."
  H_IMPACT="The service stays down until the port is freed."
  H_FIX="Identify the process holding the port with lsof -iTCP:<port>. Kill the duplicate that should not be running. Restart the launchd-managed instance."
  H_PROMPT="A local service can't bind its port. Inspect:
  1. lsof -iTCP:<port> — what is holding it.
  2. launchctl print for the expected job — is it scheduled?
  3. Any duplicate processes (pgrep -af <name>)?
Kill ONLY the unmanaged duplicate. Restart the launchd-managed one.
Do NOT kill the wrong PID. Confirm by parent process and command line before kill.
Do NOT change the port number — find the offender instead.
Report back: process holding the port, action taken, current bind status, post-restart health."
  _tpl_emit
}

tpl_env_missing() {
  H_SYSTEM="${H_SYSTEM:-Service env config}"
  H_STATUS="blocked"
  H_SEVERITY="HIGH"
  H_ISSUE="A required environment variable is missing or empty at runtime."
  H_EVIDENCE="${H_EVIDENCE:-Service refused to start citing missing env var
OR feature errored citing missing config
Variable name: unknown — populate H_EVIDENCE}"
  H_CAUSE="Variable not set in launchd plist, Render env, Vercel env, or local .env was not loaded."
  H_IMPACT="Service cannot start, or the dependent feature fails on first call."
  H_FIX="Identify which variable. Find the right env source for the environment that is broken. Set it. Restart only the affected service."
  H_PROMPT="A required env var is missing. Inspect:
  1. Service log for the exact missing variable name.
  2. Where that variable should be defined (launchd plist, Render dashboard, Vercel dashboard, or .env).
  3. Whether it was recently rotated or removed.
Set the variable in the correct env source. Restart only the affected service.
Do NOT print the value. Do NOT commit it. Do NOT change unrelated env vars.
Report back: variable name, where it was missing, action taken, restart result."
  _tpl_emit
}

tpl_render_build_failed() {
  H_SYSTEM="Render — Backend Deploy"
  H_STATUS="failed"
  H_SEVERITY="HIGH"
  H_ISSUE="The most recent Render build for the backend failed."
  H_EVIDENCE="${H_EVIDENCE:-Render API reports last deploy status = build_failed
Service: srv-d7cq41q8qa3s73bbke00
Trigger: most recent commit to main}"
  H_CAUSE="Lint/test/typecheck regression, missing dep in pyproject, env var required at build time, or a flaky external during build."
  H_IMPACT="Production backend is not updated; new code is not live. The previous deploy is still serving."
  H_FIX="Open the Render build log. Reproduce the failing step locally. Push a fix commit. Do not roll back unless the previous deploy is also unhealthy."
  H_PROMPT="The latest Render backend deploy failed. Inspect:
  1. Render build log for the failing step (lint, install, test, build, or healthcheck).
  2. The commit that triggered the deploy and the diff vs. last green build.
  3. Whether the failure is reproducible locally.
Fix the root cause with a new commit. Do NOT skip CI. Do NOT force-deploy a broken build.
Do NOT roll back unless the currently-serving deploy is also unhealthy.
Report back: failing step, root cause, fix commit SHA, expected next deploy outcome."
  _tpl_emit
}

tpl_vercel_deploy_failed() {
  H_SYSTEM="Vercel — Frontend Deploy"
  H_STATUS="failed"
  H_SEVERITY="HIGH"
  H_ISSUE="The most recent Vercel build for the frontend failed."
  H_EVIDENCE="${H_EVIDENCE:-Vercel reports build error or deployment error
Project: app.digidle.com / hq.digidle.com
Trigger: most recent commit to main}"
  H_CAUSE="TypeScript error, missing dep, Next.js 16 incompatible API, env var required at build time."
  H_IMPACT="Production frontend is not updated. The previous build is still serving."
  H_FIX="Open the Vercel build log. Reproduce locally. Push a fix commit. Do not promote a broken build."
  H_PROMPT="The latest Vercel frontend deploy failed. Inspect:
  1. Vercel build log for the failing step.
  2. The commit that triggered it and its diff.
  3. Whether the failure is reproducible with: cd frontend && npm run build.
Fix the root cause with a new commit. Use Next.js 16 conventions (proxy.ts, not middleware.ts).
Do NOT skip type checks. Do NOT roll back unless the live build is also broken.
Report back: failing step, root cause, fix commit SHA, expected next deploy outcome."
  _tpl_emit
}

tpl_sync_stuck() {
  H_SYSTEM="${H_SYSTEM:-Sync / queue worker}"
  H_STATUS="degraded"
  H_SEVERITY="MEDIUM"
  H_ISSUE="A background sync or queue worker has stopped making progress."
  H_EVIDENCE="${H_EVIDENCE:-Queue depth has not decreased in N minutes
OR last processed timestamp is stale
Worker process: still running but idle}"
  H_CAUSE="Worker hung on a poison message, lost Redis connection, downstream API blocking, or a long DB transaction."
  H_IMPACT="New work piles up. Downstream features see stale data. Eventually backend may exhaust resources."
  H_FIX="Identify the worker. Inspect its log for the last processed item. Drain or skip a poison message if found. Restart the worker if the queue depth is large."
  H_PROMPT="A background worker is stuck. Inspect:
  1. Worker log for the last processed job and any exception.
  2. Redis queue depth and oldest item age.
  3. The current job (if any) and how long it has been in flight.
  4. Whether the downstream service it calls is healthy.
Decide: drain a single poison message, OR restart the worker, OR fix the downstream.
Do NOT mass-purge the queue. Do NOT change retry semantics without my OK.
Report back: worker name, last processed item, root cause, action taken, current queue depth."
  _tpl_emit
}

tpl_token_spike() {
  H_SYSTEM="LLM Token Spend"
  H_STATUS="degraded"
  H_SEVERITY="HIGH"
  H_ISSUE="LLM token spend has spiked above the expected baseline."
  H_EVIDENCE="${H_EVIDENCE:-Spend in the last hour exceeds the rolling baseline by a large factor
Top callers: unknown — populate H_EVIDENCE
Time window: unknown}"
  H_CAUSE="Loop or retry storm calling a model, oversized prompts, model misrouted to a more expensive tier, or a paid endpoint hit by a public path."
  H_IMPACT="Burning money. May also trigger provider rate limits and cause cascading failures."
  H_FIX="Identify the top caller and stop or throttle it. Check whether a loop is firing. Verify model routing."
  H_PROMPT="LLM token spend is spiking. Inspect:
  1. Spend dashboard or token-spend repo report for the top caller in the last hour.
  2. Whether that caller is in a loop (look for repeated identical prompts).
  3. Whether requests are routed to the right tier (Opus vs. Sonnet vs. Haiku).
  4. Whether a public endpoint is calling a paid model without auth.
Stop or throttle the top caller. Do NOT raise budget limits.
Do NOT change models for unrelated callers.
Report back: top caller name, request rate, root cause, throttle applied, current spend trajectory."
  _tpl_emit
}

tpl_git_dirty() {
  H_SYSTEM="${H_SYSTEM:-Worktree}"
  H_STATUS="degraded"
  H_SEVERITY="LOW"
  H_ISSUE="A worktree has uncommitted changes that look like in-progress work or stale debugging."
  H_EVIDENCE="${H_EVIDENCE:-git status reports modified files
Branch: unknown — populate H_EVIDENCE
Last commit: unknown}"
  H_CAUSE="In-progress work paused, debug code left behind, or auto-generated files not in .gitignore."
  H_IMPACT="Risk of losing work, or accidentally committing debug code on the next commit."
  H_FIX="Decide: keep, commit, stash, or discard. Update .gitignore if the file is auto-generated."
  H_PROMPT="A worktree has uncommitted changes. Inspect:
  1. git status — full list of modified/untracked files.
  2. git diff — what changed.
  3. Whether each file is intentional work, debug, or auto-generated.
For intentional work: leave alone or commit. For debug: revert. For auto-gen: add to .gitignore.
Do NOT discard anything you cannot identify with confidence. Do NOT force-push.
Report back: file-by-file decision, actions taken, final clean status."
  _tpl_emit
}

tpl_machine_restarted() {
  H_SYSTEM="Local Machine"
  H_STATUS="healthy"
  H_SEVERITY="LOW"
  H_ISSUE="The Mac booted or woke. Hermes is verifying that all managed services came back up."
  H_EVIDENCE="${H_EVIDENCE:-System event: boot or wake
Uptime: short
Wi-Fi state: see system_event log}"
  H_CAUSE="Power cycle, scheduled reboot, lid open, or sleep wake."
  H_IMPACT="Brief gap in monitoring while services restart. Most launchd-managed services should self-recover."
  H_FIX="Verify each managed service came back: postgres, redis, openclaw gateway, backend, frontend, cloudflared. Restart any that did not."
  H_PROMPT="The Mac just rebooted or woke. Verify recovery:
  1. brew services list — postgres + redis running?
  2. launchctl print gui/\$(id -u)/com.digidle.openclaw — gateway running?
  3. launchctl print for com.digidle.backend, com.digidle.next-server, com.cloudflare.cloudflared.
  4. Run ~/.hermes/hooks/health_claw_remote.sh and review failures only.
Restart anything that did not auto-recover. Do NOT restart things that are already healthy.
Do NOT redeploy or rebuild.
Report back: which services were down, which you restarted, final all-green or remaining issues."
  _tpl_emit
}

tpl_unknown_cause() {
  H_SYSTEM="${H_SYSTEM:-Unknown system}"
  H_STATUS="${H_STATUS:-unknown}"
  H_SEVERITY="${H_SEVERITY:-MEDIUM}"
  H_ISSUE="${H_ISSUE:-A failure was detected but could not be classified.}"
  H_EVIDENCE="${H_EVIDENCE:-Raw error: see logs
Detector: see calling watchdog}"
  H_CAUSE="Could not be determined automatically — needs human or LLM-driven triage."
  H_IMPACT="Unclear until classified. Treat as 'something is wrong' until proven otherwise."
  H_FIX="Read the raw evidence, classify the failure into one of the known templates if possible, or escalate."
  H_PROMPT="Hermes detected a failure it could not classify. Inspect:
  1. The raw evidence in this alert.
  2. The watchdog or detector that fired (see context in the calling script).
  3. Recent activity logs in ~/.hermes/hooks/state/ from the last 10 minutes.
Classify the failure: which system, which status, which severity. If a known template fits, use it.
Do NOT take destructive action without first identifying the root cause.
Do NOT restart everything 'just in case'.
Report back: classification you settled on, evidence supporting it, recommended next step."
  _tpl_emit
}
