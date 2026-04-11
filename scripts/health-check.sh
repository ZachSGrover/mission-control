#!/usr/bin/env bash
# ── Workflow 4: System Health Check ──────────────────────────────────────────
# Trigger: scheduled (cron) or manual or webhook
# Output:  JSON report to stdout + /tmp/mc-health.json
#
# Usage:
#   ./scripts/health-check.sh              # full check, JSON output
#   ./scripts/health-check.sh --summary    # one-line status
#   ./scripts/health-check.sh --watch      # loop every 60s
#
# Exit codes:
#   0 = all healthy
#   1 = one or more checks failed
# ─────────────────────────────────────────────────────────────────────────────
BACKEND_URL="${BACKEND_URL:-https://mission-control-jbx8.onrender.com}"
FRONTEND_URL="${FRONTEND_URL:-https://app.digidle.com}"
MODE="${1:-}"

# Parallel arrays: names, statuses, details
CHECK_NAMES=()
CHECK_STATUS=()
CHECK_DETAIL=()
PASS=0
FAIL=0

check() {
  local name="$1" url="$2" method="${3:-GET}" origin="${4:-}" expected="${5:-200}"
  local opts=(-s -o /dev/null -w "%{http_code}" -X "$method" --max-time 10)
  [ -n "$origin" ] && opts+=(-H "Origin: $origin")
  if [ "$method" = "OPTIONS" ]; then
    opts+=(-H "Access-Control-Request-Method: GET" -H "Access-Control-Request-Headers: authorization")
  fi

  local actual
  actual=$(curl "${opts[@]}" "$url" 2>/dev/null) || actual="000"

  CHECK_NAMES+=("$name")
  if [ "$actual" = "$expected" ]; then
    CHECK_STATUS+=("pass")
    CHECK_DETAIL+=("$actual")
    PASS=$((PASS+1))
  else
    CHECK_STATUS+=("fail")
    CHECK_DETAIL+=("expected=$expected got=$actual")
    FAIL=$((FAIL+1))
  fi
}

check_body() {
  local name="$1" url="$2" pattern="$3"
  local body
  body=$(curl -s --max-time 10 "$url" 2>/dev/null) || body=""
  CHECK_NAMES+=("$name")
  if echo "$body" | grep -q "$pattern"; then
    CHECK_STATUS+=("pass")
    CHECK_DETAIL+=("matched")
    PASS=$((PASS+1))
  else
    CHECK_STATUS+=("fail")
    CHECK_DETAIL+=("pattern '$pattern' not found")
    FAIL=$((FAIL+1))
  fi
}

run_checks() {
  PASS=0; FAIL=0
  CHECK_NAMES=(); CHECK_STATUS=(); CHECK_DETAIL=()

  # ── Backend ────────────────────────────────────────────────────────────────
  check     "backend.health"          "$BACKEND_URL/health"                           "GET"     ""             "200"
  check     "backend.readyz"          "$BACKEND_URL/readyz"                           "GET"     ""             "200"
  check_body "backend.health_body"    "$BACKEND_URL/health"                           '"ok"'

  # ── CORS ───────────────────────────────────────────────────────────────────
  check "cors.settings_preflight"     "$BACKEND_URL/api/v1/settings/api-keys"         "OPTIONS" "$FRONTEND_URL" "200"
  check "cors.roles_preflight"        "$BACKEND_URL/api/v1/roles/me"                  "OPTIONS" "$FRONTEND_URL" "200"
  check "cors.openai_preflight"       "$BACKEND_URL/api/v1/openai/status"             "OPTIONS" "$FRONTEND_URL" "200"

  # ── Auth (protected → 401 without token) ──────────────────────────────────
  check "auth.settings"               "$BACKEND_URL/api/v1/settings/api-keys"         "GET"     ""             "401"
  check "auth.roles_me"               "$BACKEND_URL/api/v1/roles/me"                  "GET"     ""             "401"
  check "auth.openai"                 "$BACKEND_URL/api/v1/openai/status"             "GET"     ""             "401"
  check "auth.gemini"                 "$BACKEND_URL/api/v1/gemini/status"             "GET"     ""             "401"

  # ── Frontend (Clerk redirects unauthenticated → 307, follow → 200) ────────
  check "frontend.root"               "$FRONTEND_URL"                                 "GET"     ""             "307"
  check "frontend.chat"               "$FRONTEND_URL/chat"                            "GET"     ""             "307"
  check "frontend.settings"           "$FRONTEND_URL/settings"                        "GET"     ""             "307"
}

emit_json_report() {
  local ts overall
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  if [ "$FAIL" -eq 0 ]; then overall="healthy"; else overall="degraded"; fi

  # Build checks JSON using python3
  local checks_json
  checks_json=$(python3 - <<PYEOF
import json
names   = """${CHECK_NAMES[*]}""".split()
statuses = """${CHECK_STATUS[*]}""".split()
# details have spaces so we stored them differently — rebuild from bash arrays
details = [s for s in """$(printf '%s|||' "${CHECK_DETAIL[@]}")""".split('|||') if s]
checks = []
for i, name in enumerate(names):
    checks.append({
        "name":   name,
        "status": statuses[i] if i < len(statuses) else "unknown",
        "detail": details[i].strip() if i < len(details) else "",
    })
print(json.dumps(checks))
PYEOF
)

  python3 - <<PYEOF
import json
report = {
    "workflow":   "health-check",
    "timestamp":  "$ts",
    "overall":    "$overall",
    "pass":       $PASS,
    "fail":       $FAIL,
    "checks":     $checks_json,
}
print(json.dumps(report, indent=2))
PYEOF
}

emit_summary() {
  local overall failed_list=""
  if [ "$FAIL" -eq 0 ]; then overall="HEALTHY"; else overall="DEGRADED"; fi

  local i=0
  while [ $i -lt ${#CHECK_NAMES[@]} ]; do
    if [ "${CHECK_STATUS[$i]}" = "fail" ]; then
      failed_list="$failed_list ${CHECK_NAMES[$i]}"
    fi
    i=$((i+1))
  done

  local msg="[$overall] pass=$PASS fail=$FAIL"
  [ -n "$failed_list" ] && msg="$msg failed:$failed_list"
  echo "$msg"
}

# ── Entry point ───────────────────────────────────────────────────────────────
if [ "$MODE" = "--watch" ]; then
  while true; do
    run_checks
    emit_summary
    sleep 60
  done
elif [ "$MODE" = "--summary" ]; then
  run_checks
  emit_summary
  [ "$FAIL" -eq 0 ]
else
  run_checks
  emit_json_report | tee /tmp/mc-health.json
  [ "$FAIL" -eq 0 ]
fi
