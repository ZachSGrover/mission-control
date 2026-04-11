#!/usr/bin/env bash
# ── Start the autonomous master controller ────────────────────────────────────
# Runs master-controller.sh in the background, captures logs.
#
# Usage:
#   ./scripts/start-system.sh
#   OWNER_TOKEN=xxx RENDER_API_KEY=yyy ./scripts/start-system.sh
#   CYCLE_INTERVAL=30 ./scripts/start-system.sh   # 30s cycles
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/mc-common.sh"

# ── Check if already running ──────────────────────────────────────────────────
if [ -f "$MC_PID_FILE" ]; then
  EXISTING_PID=$(cat "$MC_PID_FILE" 2>/dev/null || echo "")
  if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    warn "Master controller already running (PID $EXISTING_PID)"
    echo "Use ./scripts/stop-system.sh to stop it first."
    exit 1
  fi
fi

# ── Environment validation ─────────────────────────────────────────────────────
if [ -z "$OWNER_TOKEN" ]; then
  warn "OWNER_TOKEN not set — controller will use unauthenticated health checks only"
  warn "Set OWNER_TOKEN to enable full workflow automation"
fi

# ── Start ─────────────────────────────────────────────────────────────────────
MC_STDOUT="$MC_STATE_DIR/master.log"
mkdir -p "$MC_STATE_DIR"

success "Starting Mission Control master controller..."
info "Logs: $MC_STDOUT"
info "State: $MC_STATE_DIR"
info "Cycle interval: ${CYCLE_INTERVAL:-60}s"
info "Backend: ${BACKEND_URL:-https://mission-control-jbx8.onrender.com}"

# Export all relevant env vars for the subprocess
export OWNER_TOKEN RENDER_API_KEY BACKEND_URL FRONTEND_URL RENDER_SERVICE_ID CYCLE_INTERVAL MC_STATE_DIR

nohup "$SCRIPT_DIR/master-controller.sh" >> "$MC_STDOUT" 2>&1 &
BG_PID=$!

sleep 1
if kill -0 "$BG_PID" 2>/dev/null; then
  success "Master controller started (PID $BG_PID)"
  echo ""
  echo "  Commands:"
  echo "    ./scripts/stop-system.sh     — stop the controller"
  echo "    ./scripts/pause-system.sh    — pause without stopping"
  echo "    ./scripts/resume-system.sh   — resume from pause"
  echo "    ./scripts/system-status.sh   — current status"
  echo "    tail -f $MC_STDOUT           — live logs"
  echo ""
else
  fail "Master controller failed to start. Check $MC_STDOUT"
  exit 1
fi
