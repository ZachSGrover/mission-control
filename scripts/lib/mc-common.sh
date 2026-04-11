#!/usr/bin/env bash
# ── Mission Control shared library ───────────────────────────────────────────
# Source this in every script: source "$(dirname "$0")/lib/mc-common.sh"

# ── Directories & files ───────────────────────────────────────────────────────
MC_STATE_DIR="${MC_STATE_DIR:-/tmp/mc-system}"
MC_LOG_FILE="$MC_STATE_DIR/cycle.log"
MC_JOURNAL_FILE="$MC_STATE_DIR/journal.log"
MC_STATE_FILE="$MC_STATE_DIR/system.state"
MC_PID_FILE="$MC_STATE_DIR/master.pid"
MC_LOCK_FILE="$MC_STATE_DIR/master.lock"

mkdir -p "$MC_STATE_DIR"

# ── Config (overridable via env) ──────────────────────────────────────────────
BACKEND_URL="${BACKEND_URL:-https://mission-control-jbx8.onrender.com}"
FRONTEND_URL="${FRONTEND_URL:-https://app.digidle.com}"
OWNER_TOKEN="${OWNER_TOKEN:-}"
RENDER_API_KEY="${RENDER_API_KEY:-}"
RENDER_SERVICE_ID="${RENDER_SERVICE_ID:-srv-d7cq41q8qa3s73bbke00}"
CYCLE_INTERVAL="${CYCLE_INTERVAL:-60}"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; MAGENTA='\033[0;35m'; NC='\033[0m'

ts()      { date -u +%Y-%m-%dT%H:%M:%SZ; }
info()    { echo -e "${BLUE}[mc]${NC} $(ts) $*"; }
success() { echo -e "${GREEN}[mc]${NC} $(ts) ✓ $*"; }
warn()    { echo -e "${YELLOW}[mc]${NC} $(ts) ⚠ $*"; }
fail()    { echo -e "${RED}[mc]${NC} $(ts) ✗ $*"; }
section() { echo -e "${CYAN}[mc]${NC} $(ts) ── $*"; }
journal_print() { echo -e "${MAGENTA}[journal]${NC} $*"; }

# ── State management ──────────────────────────────────────────────────────────
get_state() {
  [ -f "$MC_STATE_FILE" ] && cat "$MC_STATE_FILE" || echo "stopped"
}

set_state() {
  echo "$1" > "$MC_STATE_FILE"
}

is_running() {
  [ "$(get_state)" = "running" ]
}

is_paused() {
  [ "$(get_state)" = "paused" ]
}

is_stopped() {
  local s; s=$(get_state)
  [ "$s" = "stopped" ] || [ "$s" = "error" ]
}

# ── Logging ───────────────────────────────────────────────────────────────────
# Appends a JSONL record to the cycle log
log_event() {
  local action="$1" result="$2" detail="${3:-}"
  python3 - <<PYEOF >> "$MC_LOG_FILE"
import json
print(json.dumps({
    "ts":     "$(ts)",
    "action": "$action",
    "result": "$result",
    "detail": "$detail",
}))
PYEOF
}

# Appends a JSONL journal entry
log_journal() {
  local cycle="$1" headline="$2" summary="$3"
  python3 - <<PYEOF >> "$MC_JOURNAL_FILE"
import json
print(json.dumps({
    "ts":       "$(ts)",
    "cycle":    $cycle,
    "headline": "$headline",
    "summary":  "$summary",
}))
PYEOF
}

# ── API caller (with Clerk token) ─────────────────────────────────────────────
api_post() {
  local path="$1" body="${2:-{}}"
  local auth_hdr=""
  [ -n "$OWNER_TOKEN" ] && auth_hdr="-H \"Authorization: Bearer $OWNER_TOKEN\""
  eval curl -s -X POST \
    -H "'Content-Type: application/json'" \
    $auth_hdr \
    --max-time 30 \
    -d "'$body'" \
    "'$BACKEND_URL$path'" 2>/dev/null
}

api_get() {
  local path="$1"
  local auth_hdr=""
  [ -n "$OWNER_TOKEN" ] && auth_hdr="-H \"Authorization: Bearer $OWNER_TOKEN\""
  eval curl -s \
    $auth_hdr \
    --max-time 30 \
    "'$BACKEND_URL$path'" 2>/dev/null
}

# ── JSON field extractor ──────────────────────────────────────────────────────
jq_get() {
  local json="$1" field="$2" default="${3:-}"
  python3 -c "
import json, sys
try:
    d = json.loads('''$json''')
    keys = '$field'.split('.')
    v = d
    for k in keys:
        v = v[k]
    print(v)
except:
    print('$default')
" 2>/dev/null || echo "$default"
}
