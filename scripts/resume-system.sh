#!/usr/bin/env bash
# ── Resume from pause or manual-intervention-required ────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/mc-common.sh"

CURRENT=$(get_state)
case "$CURRENT" in
  paused|manual_intervention_required)
    set_state "running"
    log_event "master.resume" "ok" "was=$CURRENT"
    success "System RESUMED."
    ;;
  running)
    success "System is already running."
    ;;
  stopped)
    warn "System is stopped. Use ./scripts/start-system.sh to start it."
    ;;
  *)
    warn "Unknown state: $CURRENT. Setting to running."
    set_state "running"
    ;;
esac
