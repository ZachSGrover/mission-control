#!/usr/bin/env bash
# ── Pause the master controller (keeps process alive) ────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/mc-common.sh"

if is_stopped; then
  warn "System is not running. Use ./scripts/start-system.sh"
  exit 1
fi

set_state "paused"
log_event "master.pause" "ok" "manual"
success "System PAUSED. Use ./scripts/resume-system.sh to continue."
echo "State: $MC_STATE_FILE"
