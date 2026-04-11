#!/usr/bin/env bash
# ── Show master controller status ─────────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/mc-common.sh"

OUTPUT_JSON="${1:-}"

STATE=$(get_state)
PID=$(cat "$MC_PID_FILE" 2>/dev/null || echo "")
PROCESS_ALIVE="false"
[ -n "$PID" ] && kill -0 "$PID" 2>/dev/null && PROCESS_ALIVE="true"

# Recent log entries
LAST_EVENTS="[]"
if [ -f "$MC_LOG_FILE" ]; then
  LAST_EVENTS=$(tail -5 "$MC_LOG_FILE" | python3 -c "
import json, sys
events = []
for line in sys.stdin:
    try: events.append(json.loads(line.strip()))
    except: pass
print(json.dumps(events))
" 2>/dev/null || echo "[]")
fi

# Last journal
LAST_JOURNAL="{}"
if [ -f "$MC_JOURNAL_FILE" ]; then
  LAST_JOURNAL=$(tail -1 "$MC_JOURNAL_FILE" 2>/dev/null || echo "{}")
fi

# Cycle count from log
CYCLE_COUNT=$([ -f "$MC_LOG_FILE" ] && wc -l < "$MC_LOG_FILE" 2>/dev/null | tr -d ' ' || echo "0")

# Manual flags
MANUAL_FLAGS=""
if [ -f "$MC_STATE_DIR/manual-flags.log" ]; then
  MANUAL_FLAGS=$(tail -3 "$MC_STATE_DIR/manual-flags.log" 2>/dev/null || echo "")
fi

if [ "$OUTPUT_JSON" = "--json" ]; then
  python3 - <<PYEOF
import json
print(json.dumps({
    "state":         "$STATE",
    "pid":           "$PID",
    "process_alive": $PROCESS_ALIVE,
    "cycle_count":   $CYCLE_COUNT,
    "log_file":      "$MC_LOG_FILE",
    "journal_file":  "$MC_JOURNAL_FILE",
    "state_dir":     "$MC_STATE_DIR",
    "last_events":   $LAST_EVENTS,
    "last_journal":  $LAST_JOURNAL,
    "manual_flags":  "$MANUAL_FLAGS",
    "backend_url":   "$BACKEND_URL",
}, indent=2))
PYEOF
else
  echo ""
  echo "Mission Control — System Status"
  echo "────────────────────────────────────────"
  printf "  %-20s %s\n" "State:"       "$STATE"
  printf "  %-20s %s\n" "PID:"         "${PID:-none}"
  printf "  %-20s %s\n" "Process:"     "$( [ "$PROCESS_ALIVE" = "true" ] && echo "alive" || echo "dead")"
  printf "  %-20s %s\n" "Cycles run:"  "$CYCLE_COUNT"
  printf "  %-20s %s\n" "Backend:"     "$BACKEND_URL"
  printf "  %-20s %s\n" "Log:"         "$MC_LOG_FILE"
  echo ""

  if [ -n "$MANUAL_FLAGS" ]; then
    echo "  ⚠ MANUAL INTERVENTION REQUIRED:"
    echo "  $MANUAL_FLAGS"
    echo ""
  fi

  if [ -f "$MC_LOG_FILE" ] && [ "$CYCLE_COUNT" -gt 0 ]; then
    echo "  Recent activity:"
    tail -5 "$MC_LOG_FILE" | python3 -c "
import json, sys
for line in sys.stdin:
    try:
        d = json.loads(line.strip())
        print(f\"    {d['ts']}  {d['action']:<30} {d['result']}\")
    except: pass
" 2>/dev/null || true
    echo ""
  fi

  if [ -f "$MC_JOURNAL_FILE" ]; then
    echo "  Last journal entry:"
    tail -1 "$MC_JOURNAL_FILE" | python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read().strip())
    print(f\"    {d.get('ts','')}  {d.get('headline','')}\")
    print(f\"    {d.get('summary','')}\")
except: pass
" 2>/dev/null || true
    echo ""
  fi

  echo "  Commands:"
  echo "    ./scripts/stop-system.sh     stop"
  echo "    ./scripts/pause-system.sh    pause"
  echo "    ./scripts/resume-system.sh   resume"
  echo "    ./scripts/health-check.sh    manual health check"
fi
