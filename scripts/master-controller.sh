#!/usr/bin/env bash
# ── Master Controller ─────────────────────────────────────────────────────────
# Autonomous control loop: health check → error detect → auto-fix → deploy
#
# Usage:
#   ./scripts/master-controller.sh           # run in foreground
#   ./scripts/start-system.sh                # run in background (use this)
#
# Kill switch:
#   ./scripts/stop-system.sh                 # graceful stop
#   SYSTEM_PAUSED=true ./scripts/master-controller.sh  # start paused
#
# Env vars (see scripts/lib/mc-common.sh):
#   OWNER_TOKEN, BACKEND_URL, FRONTEND_URL, RENDER_API_KEY, CYCLE_INTERVAL
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/mc-common.sh"

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_FIX_ATTEMPTS=3
JOURNAL_EVERY=10          # write journal entry every N cycles
DAILY_JOURNAL_HOUR=0      # UTC hour to write daily journal (midnight)

# ── Runtime state ─────────────────────────────────────────────────────────────
CYCLE=0
FIX_ATTEMPTS=0
LAST_JOURNAL_CYCLE=0
LAST_DAILY_JOURNAL_DATE=""
CYCLE_ERRORS=()
CYCLE_FIXES=()
CYCLE_DEPLOYS=()

# ── Lock (single instance) ─────────────────────────────────────────────────────
if [ -f "$MC_LOCK_FILE" ]; then
  EXISTING_PID=$(cat "$MC_LOCK_FILE" 2>/dev/null || echo "")
  if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    fail "Master controller already running (PID $EXISTING_PID). Use stop-system.sh first."
    exit 1
  fi
fi
echo $$ > "$MC_LOCK_FILE"
echo $$ > "$MC_PID_FILE"

# ── Signal handlers ───────────────────────────────────────────────────────────
cleanup() {
  info "Shutting down master controller (PID $$)..."
  set_state "stopped"
  rm -f "$MC_LOCK_FILE"
  log_event "master.shutdown" "ok" "cycle=$CYCLE"
  exit 0
}
trap cleanup SIGTERM SIGINT SIGHUP

# ── Pause handling ─────────────────────────────────────────────────────────────
handle_pause() {
  if [ "${SYSTEM_PAUSED:-false}" = "true" ] || is_paused; then
    warn "System is PAUSED. Waiting for resume..."
    set_state "paused"
    while [ "${SYSTEM_PAUSED:-false}" = "true" ] || is_paused; do
      sleep 5
      # Re-read state file to detect external resume
      if [ "$(get_state)" = "running" ] && [ "${SYSTEM_PAUSED:-false}" != "true" ]; then
        info "Resumed."
        return
      fi
    done
  fi
}

# ── Health check ───────────────────────────────────────────────────────────────
run_health_check() {
  local result
  if [ -n "$OWNER_TOKEN" ]; then
    result=$(api_post "/api/v1/workflows/health-check" '{}')
  else
    # Fallback: direct health endpoint (no auth needed)
    result=$(curl -s --max-time 20 "$BACKEND_URL/health" 2>/dev/null || echo '{"ok":false}')
    local ok; ok=$(jq_get "$result" "ok" "false")
    if [ "$ok" = "True" ] || [ "$ok" = "true" ]; then
      result='{"overall":"healthy","pass":1,"fail":0}'
    else
      result='{"overall":"down","pass":0,"fail":1}'
    fi
  fi
  echo "$result"
}

# ── Error detection ─────────────────────────────────────────────────────────────
run_error_detect() {
  if [ -n "$OWNER_TOKEN" ]; then
    api_post "/api/v1/workflows/error-detect" '{}'
  else
    echo '{"status":"errors_detected","errors":["NO_OWNER_TOKEN"],"fix_suggestions":["fix:env"]}'
  fi
}

# ── Auto-fix ────────────────────────────────────────────────────────────────────
run_auto_fix() {
  local suggestions="$1"
  if [ -n "$OWNER_TOKEN" ]; then
    api_post "/api/v1/workflows/auto-fix" "{\"suggestions\": $suggestions}"
  else
    echo '{"applied":[],"failed":["NO_OWNER_TOKEN"]}'
  fi
}

# ── Deploy trigger ──────────────────────────────────────────────────────────────
run_deploy() {
  local message="${1:-Auto-deploy triggered by master controller}"
  if [ -n "$OWNER_TOKEN" ]; then
    api_post "/api/v1/workflows/deploy" "{\"clear_cache\": false, \"message\": \"$message\"}"
  else
    echo '{"triggered":false,"method":"none","message":"No OWNER_TOKEN"}'
  fi
}

# ── Classify if fix is autonomous or needs human ────────────────────────────────
is_auto_fixable() {
  local suggestions="$1"
  # These fixes can be done autonomously
  local auto_fixes="fix:cors fix:redeploy fix:backend_error fix:vercel_redeploy fix:env"
  for s in $suggestions; do
    local found=0
    for af in $auto_fixes; do
      [ "$s" = "$af" ] && found=1 && break
    done
    [ $found -eq 0 ] && return 1
  done
  return 0
}

# ── Journal generation ──────────────────────────────────────────────────────────
generate_journal() {
  local cycle_count="$1" errors_count="$2" fixes_count="$3" deploys_count="$4"
  local ts; ts=$(ts)

  # Build a simple summary from the log
  local recent_log=""
  if [ -f "$MC_LOG_FILE" ]; then
    recent_log=$(tail -20 "$MC_LOG_FILE" | python3 -c "
import json, sys
lines = []
for line in sys.stdin:
    try:
        d = json.loads(line.strip())
        lines.append(f\"{d['ts']} {d['action']} → {d['result']} {d.get('detail','')}\")
    except:
        pass
print('\n'.join(lines[-10:]))
" 2>/dev/null || echo "")
  fi

  # Use backend journal endpoint if we have a token and OpenAI key
  if [ -n "$OWNER_TOKEN" ]; then
    local journal_result
    journal_result=$(curl -s -X POST \
      -H "Authorization: Bearer $OWNER_TOKEN" \
      -H "Content-Type: application/json" \
      --max-time 30 \
      -d "{
        \"date\": \"$(date -u +%Y-%m-%d)\",
        \"messages\": [
          {\"role\": \"user\", \"text\": \"System ran $cycle_count cycles. Errors: $errors_count. Fixes applied: $fixes_count. Deploys: $deploys_count. Recent activity: $recent_log\", \"provider\": \"system\", \"createdAt\": \"$ts\"}
        ]
      }" \
      "$BACKEND_URL/api/v1/journal/generate" 2>/dev/null || echo "")

    if [ -n "$journal_result" ]; then
      local headline; headline=$(jq_get "$journal_result" "headline" "No journal generated")
      local summary; summary=$(jq_get "$journal_result" "summary" "")
      log_journal "$cycle_count" "$headline" "$summary"
      journal_print "JOURNAL: $headline"
      return
    fi
  fi

  # Fallback: generate our own summary
  local status_word="nominal"
  [ "$errors_count" -gt 0 ] && [ "$fixes_count" -gt 0 ] && status_word="self-healed"
  [ "$errors_count" -gt 0 ] && [ "$fixes_count" -eq 0 ] && status_word="degraded"
  [ "$deploys_count" -gt 0 ] && status_word="deployed"

  local headline="Cycle $cycle_count complete — system $status_word"
  local summary="Ran $cycle_count health checks. Detected $errors_count errors. Applied $fixes_count fixes. Triggered $deploys_count deploys."

  log_journal "$cycle_count" "$headline" "$summary"
  journal_print "JOURNAL: $headline"
}

# ── Single control cycle ────────────────────────────────────────────────────────
run_cycle() {
  CYCLE=$((CYCLE + 1))
  local cycle_errors=0 cycle_fixes=0 cycle_deploys=0

  section "=== CYCLE $CYCLE === $(ts)"

  # ── 1. Health check ────────────────────────────────────────────────────────
  info "Step 1: Health check..."
  local health_result overall fail_count
  health_result=$(run_health_check)
  overall=$(jq_get "$health_result" "overall" "unknown")
  fail_count=$(jq_get "$health_result" "fail" "0")

  log_event "health.check" "$overall" "fail=$fail_count cycle=$CYCLE"

  if [ "$overall" = "healthy" ]; then
    success "Health: HEALTHY (all checks pass)"
    FIX_ATTEMPTS=0
    return 0
  fi

  warn "Health: $overall (fail=$fail_count)"
  cycle_errors=$((cycle_errors + fail_count))

  # ── 2. Error detection ─────────────────────────────────────────────────────
  info "Step 2: Error detection..."
  local error_result error_status errors suggestions
  error_result=$(run_error_detect)
  error_status=$(jq_get "$error_result" "status" "unknown")
  errors=$(python3 -c "import json; d=json.loads('''$error_result'''); print(' '.join(d.get('errors',[])))" 2>/dev/null || echo "unknown")
  suggestions=$(python3 -c "import json; d=json.loads('''$error_result'''); print(json.dumps(d.get('fix_suggestions',[])))" 2>/dev/null || echo "[]")
  suggestions_flat=$(python3 -c "import json; d=json.loads('''$error_result'''); print(' '.join(d.get('fix_suggestions',[])))" 2>/dev/null || echo "")

  log_event "error.detect" "$error_status" "$errors"
  info "Errors: $errors"
  info "Suggested fixes: $suggestions_flat"

  # ── 3. Fix decision ────────────────────────────────────────────────────────
  if [ -z "$suggestions_flat" ] || [ "$suggestions_flat" = "None" ]; then
    warn "No fix suggestions — flagging for manual intervention"
    log_event "fix.manual_required" "no_suggestions" "errors=$errors"
    set_state "manual_intervention_required"
    echo "MANUAL_INTERVENTION_REQUIRED" >> "$MC_STATE_DIR/manual-flags.log"
    echo "$(ts) errors=$errors" >> "$MC_STATE_DIR/manual-flags.log"
    return 1
  fi

  if [ $FIX_ATTEMPTS -ge $MAX_FIX_ATTEMPTS ]; then
    fail "Max fix attempts ($MAX_FIX_ATTEMPTS) reached — flagging for manual intervention"
    log_event "fix.max_attempts" "manual_required" "cycle=$CYCLE attempts=$FIX_ATTEMPTS"
    set_state "manual_intervention_required"
    echo "MAX_FIX_ATTEMPTS_REACHED $(ts) after $FIX_ATTEMPTS attempts. Errors: $errors" >> "$MC_STATE_DIR/manual-flags.log"
    return 1
  fi

  FIX_ATTEMPTS=$((FIX_ATTEMPTS + 1))
  info "Fix attempt $FIX_ATTEMPTS/$MAX_FIX_ATTEMPTS"

  # ── 4. Auto-fix ────────────────────────────────────────────────────────────
  info "Step 3: Applying fixes: $suggestions_flat..."
  local fix_result fix_applied fix_failed
  fix_result=$(run_auto_fix "$suggestions")
  fix_applied=$(python3 -c "import json; d=json.loads('''$fix_result'''); print(len(d.get('applied',[])))" 2>/dev/null || echo "0")
  fix_failed=$(python3 -c "import json; d=json.loads('''$fix_result'''); print(len(d.get('failed',[])))" 2>/dev/null || echo "0")

  log_event "fix.apply" "applied=$fix_applied failed=$fix_failed" "$suggestions_flat"

  if [ "$fix_applied" -gt 0 ]; then
    success "Applied $fix_applied fix(es)"
    cycle_fixes=$fix_applied
  fi

  # ── 5. Deploy ──────────────────────────────────────────────────────────────
  info "Step 4: Triggering deploy after fix..."
  local deploy_result deploy_triggered
  deploy_result=$(run_deploy "Auto-deploy after fix: $suggestions_flat (cycle $CYCLE)")
  deploy_triggered=$(jq_get "$deploy_result" "triggered" "false")

  if [ "$deploy_triggered" = "True" ] || [ "$deploy_triggered" = "true" ]; then
    local deploy_id; deploy_id=$(jq_get "$deploy_result" "deploy_id" "unknown")
    success "Deploy triggered: $deploy_id"
    cycle_deploys=1
    log_event "deploy.trigger" "ok" "deploy_id=$deploy_id"

    # Wait for deploy to stabilize before next health check
    info "Waiting 90s for deploy to stabilize..."
    sleep 90
  else
    warn "Deploy not triggered: $(jq_get "$deploy_result" "message" "no message")"
    log_event "deploy.trigger" "skipped" "$(jq_get "$deploy_result" "message" "")"
  fi

  # ── 6. Verify fix worked ──────────────────────────────────────────────────
  info "Step 5: Verifying fix..."
  local verify_result verify_overall
  verify_result=$(run_health_check)
  verify_overall=$(jq_get "$verify_result" "overall" "unknown")

  if [ "$verify_overall" = "healthy" ]; then
    success "System HEALTHY after fix!"
    log_event "fix.verify" "success" "cycle=$CYCLE"
    FIX_ATTEMPTS=0
    set_state "running"
  else
    warn "System still $verify_overall after fix — will retry next cycle"
    log_event "fix.verify" "still_degraded" "overall=$verify_overall"
  fi

  # Update cumulative counters
  CYCLE_ERRORS+=($cycle_errors)
  CYCLE_FIXES+=($cycle_fixes)
  CYCLE_DEPLOYS+=($cycle_deploys)
}

# ── Main loop ──────────────────────────────────────────────────────────────────
main() {
  # Initial state
  if [ "${SYSTEM_PAUSED:-false}" = "true" ]; then
    set_state "paused"
  else
    set_state "running"
  fi

  log_event "master.start" "ok" "pid=$$ interval=${CYCLE_INTERVAL}s"
  info "Master controller started (PID $$)"
  info "Interval: ${CYCLE_INTERVAL}s | Backend: $BACKEND_URL"
  info "State dir: $MC_STATE_DIR"
  info "Log: $MC_LOG_FILE"
  [ -z "$OWNER_TOKEN" ] && warn "OWNER_TOKEN not set — using unauthenticated health checks only"

  local total_errors=0 total_fixes=0 total_deploys=0

  while true; do
    # Check for kill switch
    handle_pause

    current_state=$(get_state)
    if [ "$current_state" = "stopped" ]; then
      info "State=stopped. Exiting."
      break
    fi
    if [ "$current_state" = "manual_intervention_required" ]; then
      warn "Manual intervention required. Controller pausing."
      warn "Check $MC_STATE_DIR/manual-flags.log for details."
      warn "Use ./scripts/resume-system.sh to continue after fixing."
      set_state "paused"
      sleep 60
      continue
    fi

    # Run cycle (don't exit loop on error)
    run_cycle || true

    # Journal every N cycles
    if [ $((CYCLE % JOURNAL_EVERY)) -eq 0 ] && [ $CYCLE -gt 0 ]; then
      generate_journal "$CYCLE" "$total_errors" "$total_fixes" "$total_deploys"
    fi

    # Daily journal at DAILY_JOURNAL_HOUR UTC
    CURRENT_DATE=$(date -u +%Y-%m-%d)
    CURRENT_HOUR=$(date -u +%H)
    if [ "$CURRENT_HOUR" = "$(printf '%02d' $DAILY_JOURNAL_HOUR)" ] && \
       [ "$CURRENT_DATE" != "$LAST_DAILY_JOURNAL_DATE" ]; then
      info "Generating daily journal for $CURRENT_DATE..."
      generate_journal "$CYCLE" "$total_errors" "$total_fixes" "$total_deploys"
      LAST_DAILY_JOURNAL_DATE="$CURRENT_DATE"
    fi

    info "Sleeping ${CYCLE_INTERVAL}s until next cycle..."
    sleep "$CYCLE_INTERVAL"
  done

  log_event "master.stop" "ok" "total_cycles=$CYCLE"
  info "Master controller stopped after $CYCLE cycles"
}

main "$@"
