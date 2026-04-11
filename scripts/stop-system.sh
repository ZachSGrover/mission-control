#!/usr/bin/env bash
# ── Stop the master controller ────────────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/mc-common.sh"

FORCE="${1:-}"

if [ -f "$MC_PID_FILE" ]; then
  PID=$(cat "$MC_PID_FILE" 2>/dev/null || echo "")
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    if [ "$FORCE" = "--force" ]; then
      kill -9 "$PID" 2>/dev/null || true
      success "Force-killed master controller (PID $PID)"
    else
      kill -TERM "$PID" 2>/dev/null || true
      success "Sent SIGTERM to master controller (PID $PID)"
      # Wait up to 10s for clean shutdown
      for i in $(seq 1 10); do
        kill -0 "$PID" 2>/dev/null || { success "Controller stopped cleanly."; break; }
        sleep 1
      done
    fi
  else
    warn "No running controller found (stale PID $PID)"
  fi
else
  warn "No PID file found at $MC_PID_FILE"
fi

set_state "stopped"
rm -f "$MC_LOCK_FILE" "$MC_PID_FILE"
log_event "master.stop" "ok" "manual"
success "System stopped."
