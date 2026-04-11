#!/usr/bin/env bash
# ── Workflow 2: Error Detection ───────────────────────────────────────────────
# Trigger: failed deploy, webhook from Render, or scheduled
# Output:  JSON error report → stdout + /tmp/mc-errors.json
#          Passes to auto-fix.sh if --auto-fix flag is set
#
# Usage:
#   ./scripts/error-detect.sh                    # detect only, JSON report
#   ./scripts/error-detect.sh --auto-fix         # detect + trigger auto-fix
#   RENDER_API_KEY=rnd_xxx ./scripts/error-detect.sh --auto-fix
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_URL="${BACKEND_URL:-https://mission-control-jbx8.onrender.com}"
FRONTEND_URL="${FRONTEND_URL:-https://app.digidle.com}"
RENDER_API_KEY="${RENDER_API_KEY:-}"
RENDER_SERVICE_ID="${RENDER_SERVICE_ID:-srv-d7cq41q8qa3s73bbke00}"
AUTO_FIX="${1:-}"

declare -a ERRORS=()
declare -a WARNINGS=()

add_error()   { ERRORS+=("$1"); }
add_warning() { WARNINGS+=("$1"); }

# ── Check 1: Backend reachability ─────────────────────────────────────────────
HEALTH=$(curl -sf --max-time 15 "$BACKEND_URL/health" 2>/dev/null || echo "UNREACHABLE")
if [[ "$HEALTH" == "UNREACHABLE" ]]; then
  add_error "BACKEND_DOWN: $BACKEND_URL/health not reachable"
elif ! echo "$HEALTH" | grep -q '"ok"'; then
  add_error "BACKEND_UNHEALTHY: health response: $HEALTH"
fi

# ── Check 2: CORS preflight ────────────────────────────────────────────────────
CORS_STATUS=$(curl -sf -o /dev/null -w "%{http_code}" --max-time 10 -X OPTIONS \
  "$BACKEND_URL/api/v1/settings/api-keys" \
  -H "Origin: $FRONTEND_URL" \
  -H "Access-Control-Request-Method: GET" 2>/dev/null || echo "000")
if [[ "$CORS_STATUS" != "200" ]]; then
  add_error "CORS_PREFLIGHT_FAILED: OPTIONS returned $CORS_STATUS (expected 200)"
fi

# ── Check 3: Auth protection ───────────────────────────────────────────────────
for endpoint in "settings/api-keys" "roles/me" "openai/status"; do
  STATUS=$(curl -sf -o /dev/null -w "%{http_code}" --max-time 10 \
    "$BACKEND_URL/api/v1/$endpoint" 2>/dev/null || echo "000")
  if [[ "$STATUS" == "500" ]]; then
    add_error "SERVER_ERROR_500: /api/v1/$endpoint returned 500"
  elif [[ "$STATUS" == "000" ]]; then
    add_error "ENDPOINT_UNREACHABLE: /api/v1/$endpoint"
  elif [[ "$STATUS" != "401" ]]; then
    add_warning "UNEXPECTED_STATUS: /api/v1/$endpoint returned $STATUS (expected 401)"
  fi
done

# ── Check 4: Frontend reachability ────────────────────────────────────────────
FRONTEND_STATUS=$(curl -sfL -o /dev/null -w "%{http_code}" --max-time 15 "$FRONTEND_URL" 2>/dev/null || echo "000")
if [[ "$FRONTEND_STATUS" != "200" ]]; then
  add_error "FRONTEND_DOWN: $FRONTEND_URL returned $FRONTEND_STATUS"
fi

# ── Check 5: Recent Render deploy failure ─────────────────────────────────────
if [[ -n "$RENDER_API_KEY" ]]; then
  DEPLOY_STATUS=$(curl -sf --max-time 10 \
    -H "Authorization: Bearer $RENDER_API_KEY" \
    "https://api.render.com/v1/services/$RENDER_SERVICE_ID/deploys?limit=1" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['deploy']['status'])" 2>/dev/null || echo "unknown")
  if [[ "$DEPLOY_STATUS" == "build_failed" ]]; then
    add_error "RENDER_BUILD_FAILED: last deploy status=$DEPLOY_STATUS"
  elif [[ "$DEPLOY_STATUS" == "canceled" ]]; then
    add_warning "RENDER_DEPLOY_CANCELED: last deploy was canceled"
  fi
fi

# ── Check 6: Local code drift ─────────────────────────────────────────────────
cd "$ROOT"
if git fetch origin main --quiet 2>/dev/null; then
  LOCAL=$(git rev-parse HEAD 2>/dev/null)
  REMOTE=$(git rev-parse origin/main 2>/dev/null)
  if [[ "$LOCAL" != "$REMOTE" ]]; then
    add_warning "CODE_DRIFT: local ($LOCAL) != origin/main ($REMOTE)"
  fi
fi

# ── Classify errors → suggested fixes ────────────────────────────────────────
declare -a FIX_SUGGESTIONS=()
for err in "${ERRORS[@]}"; do
  case "$err" in
    CORS_PREFLIGHT_FAILED*)    FIX_SUGGESTIONS+=("fix:cors") ;;
    SERVER_ERROR_500*)          FIX_SUGGESTIONS+=("fix:backend_error") ;;
    RENDER_BUILD_FAILED*)       FIX_SUGGESTIONS+=("fix:build") ;;
    BACKEND_DOWN*)              FIX_SUGGESTIONS+=("fix:redeploy") ;;
    FRONTEND_DOWN*)             FIX_SUGGESTIONS+=("fix:vercel_redeploy") ;;
  esac
done

# ── Emit JSON report ──────────────────────────────────────────────────────────
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
STATUS=$( [[ ${#ERRORS[@]} -eq 0 ]] && echo "clean" || echo "errors_detected" )

python3 - <<PYEOF | tee /tmp/mc-errors.json
import json
report = {
  "workflow": "error-detect",
  "timestamp": "$TS",
  "status": "$STATUS",
  "error_count": ${#ERRORS[@]},
  "warning_count": ${#WARNINGS[@]},
  "errors": $(python3 -c "import json,sys; print(json.dumps(r'${ERRORS[*]}'.split() if r'${ERRORS[*]}' else []))" 2>/dev/null || echo "[]"),
  "warnings": $(python3 -c "import json,sys; print(json.dumps(r'${WARNINGS[*]}'.split() if r'${WARNINGS[*]}' else []))" 2>/dev/null || echo "[]"),
  "fix_suggestions": $(python3 -c "import json,sys; print(json.dumps(list(set(r'${FIX_SUGGESTIONS[*]}'.split())) if r'${FIX_SUGGESTIONS[*]}' else []))" 2>/dev/null || echo "[]"),
}
print(json.dumps(report, indent=2))
PYEOF

# ── Trigger auto-fix if requested ─────────────────────────────────────────────
if [[ "$AUTO_FIX" == "--auto-fix" ]] && [[ ${#ERRORS[@]} -gt 0 ]]; then
  echo ""
  echo "[error-detect] Passing to auto-fix.sh..."
  exec "$SCRIPT_DIR/auto-fix.sh" "$(cat /tmp/mc-errors.json)"
fi

# Exit 1 if errors found
[[ ${#ERRORS[@]} -eq 0 ]]
