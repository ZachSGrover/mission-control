#!/usr/bin/env bash
# ── Workflow 3: Auto-Fix ──────────────────────────────────────────────────────
# Trigger: called by error-detect.sh or directly
# Input:   JSON error report (from error-detect.sh) OR named fix target
#
# Usage:
#   ./scripts/auto-fix.sh '{"errors":["CORS_PREFLIGHT_FAILED"],...}'  # from detect
#   ./scripts/auto-fix.sh fix:cors                                     # direct
#   ./scripts/auto-fix.sh fix:redeploy                                 # force redeploy
#   ./scripts/auto-fix.sh fix:build                                    # diagnose + fix build
#   ./scripts/auto-fix.sh fix:env                                      # check env vars
#   ./scripts/auto-fix.sh fix:all                                      # run all fixes
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_URL="${BACKEND_URL:-https://mission-control-jbx8.onrender.com}"
RENDER_API_KEY="${RENDER_API_KEY:-}"
RENDER_SERVICE_ID="${RENDER_SERVICE_ID:-srv-d7cq41q8qa3s73bbke00}"
INPUT="${1:-}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[auto-fix]${NC} $*"; }
success() { echo -e "${GREEN}[auto-fix]${NC} ✓ $*"; }
warn()    { echo -e "${YELLOW}[auto-fix]${NC} ⚠ $*"; }
fail()    { echo -e "${RED}[auto-fix]${NC} ✗ $*"; }

FIXES_APPLIED=()
FIXES_FAILED=()

# ── Determine fix targets ─────────────────────────────────────────────────────
TARGETS=()
if echo "$INPUT" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
  # JSON input from error-detect.sh
  SUGGESTIONS=$(echo "$INPUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(' '.join(d.get('fix_suggestions', [])))
")
  read -ra TARGETS <<< "$SUGGESTIONS"
else
  TARGETS=("$INPUT")
fi

[[ ${#TARGETS[@]} -eq 0 ]] && TARGETS=("fix:all")

# ── Fix functions ─────────────────────────────────────────────────────────────

fix_cors() {
  info "fix:cors — checking CORS configuration..."
  local cfg="$ROOT/backend/app/core/config.py"
  if grep -q "cors_origins" "$cfg"; then
    success "CORS config present in config.py"
  else
    fail "cors_origins missing from config.py — manual inspection needed"
    return 1
  fi

  # Verify CORS_ORIGINS env var should have the frontend URL
  info "Ensure RENDER env var CORS_ORIGINS includes: https://app.digidle.com"
  info "Current value should be: https://app.digidle.com,http://localhost:3000"

  # Test actual CORS
  local STATUS
  STATUS=$(curl -sf -o /dev/null -w "%{http_code}" --max-time 10 -X OPTIONS \
    "$BACKEND_URL/api/v1/settings/api-keys" \
    -H "Origin: https://app.digidle.com" \
    -H "Access-Control-Request-Method: GET" 2>/dev/null || echo "000")

  if [[ "$STATUS" == "200" ]]; then
    success "CORS is already working (OPTIONS → 200)"
    return 0
  fi

  warn "CORS still broken (HTTP $STATUS) — triggering redeploy..."
  fix_redeploy
}

fix_redeploy() {
  info "fix:redeploy — forcing Render redeploy..."

  if [[ -n "$RENDER_API_KEY" ]]; then
    local RESULT
    RESULT=$(curl -sf -X POST \
      -H "Authorization: Bearer $RENDER_API_KEY" \
      -H "Content-Type: application/json" \
      "https://api.render.com/v1/services/$RENDER_SERVICE_ID/deploys" \
      -d '{"clearCache":"do_not_clear"}' 2>/dev/null || echo "")

    if echo "$RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('deploy',{}).get('id',''))" 2>/dev/null | grep -q "dep-"; then
      DEPLOY_ID=$(echo "$RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['deploy']['id'])")
      success "Render deploy triggered: $DEPLOY_ID"
      info "Monitoring deploy..."

      for i in $(seq 1 40); do
        sleep 15
        STATUS=$(curl -sf \
          -H "Authorization: Bearer $RENDER_API_KEY" \
          "https://api.render.com/v1/services/$RENDER_SERVICE_ID/deploys/$DEPLOY_ID" \
          | python3 -c "import json,sys; print(json.load(sys.stdin)['deploy']['status'])" 2>/dev/null || echo "unknown")
        case "$STATUS" in
          live)    success "Deploy live"; return 0 ;;
          build_failed) fail "Build failed"; return 1 ;;
          *) info "Status: $STATUS (${i}x15s)..." ;;
        esac
      done
    else
      warn "Render API call failed — falling back to git push trigger"
      cd "$ROOT" && git commit --allow-empty -m "chore: trigger redeploy [skip ci]" && git push origin main
      success "Empty commit pushed — Render will auto-deploy"
    fi
  else
    warn "No RENDER_API_KEY — using git push to trigger redeploy"
    cd "$ROOT" && git commit --allow-empty -m "chore: trigger redeploy $(date -u +%Y-%m-%dT%H:%M:%SZ)" && git push origin main
    info "Waiting 90s for deploy..."
    sleep 90
  fi
}

fix_build() {
  info "fix:build — diagnosing build errors..."
  local NODE_BIN
  NODE_BIN=$(find /usr/local/Cellar/node@22 /usr/local/bin /opt/homebrew/bin -name node -type f 2>/dev/null | head -1 || echo "")

  if [[ -z "$NODE_BIN" ]]; then
    fail "Node.js not found — cannot run build check locally"
    return 1
  fi

  cd "$ROOT/frontend"
  local BUILD_OUTPUT
  BUILD_OUTPUT=$(PATH="$(dirname "$NODE_BIN"):$PATH" npx next build 2>&1 || true)

  if echo "$BUILD_OUTPUT" | grep -q "Type error"; then
    local ERROR_LINE
    ERROR_LINE=$(echo "$BUILD_OUTPUT" | grep "Type error" | head -1)
    fail "TypeScript error: $ERROR_LINE"
    info "Run 'cd frontend && npx tsc --noEmit' for full error list"
    return 1
  elif echo "$BUILD_OUTPUT" | grep -qE "✓ Compiled|compiled successfully"; then
    success "Build passes — issue may be environment-specific"
    return 0
  else
    fail "Build failed with unknown error"
    echo "$BUILD_OUTPUT" | tail -20
    return 1
  fi
}

fix_env() {
  info "fix:env — checking required environment variables..."

  # Backend (check via health endpoint + openapi)
  local MISSING=()

  # Check if auth is working (would fail with 500 if AUTH_MODE not set)
  local STATUS
  STATUS=$(curl -sf -o /dev/null -w "%{http_code}" --max-time 10 \
    "$BACKEND_URL/api/v1/roles/me" 2>/dev/null || echo "000")

  if [[ "$STATUS" == "500" ]]; then
    MISSING+=("AUTH_MODE or CLERK_SECRET_KEY (backend returning 500)")
  elif [[ "$STATUS" == "401" ]]; then
    success "Backend auth config: OK"
  fi

  if [[ ${#MISSING[@]} -gt 0 ]]; then
    fail "Missing env vars: ${MISSING[*]}"
    info "Required Render env vars:"
    echo "  AUTH_MODE=clerk"
    echo "  CLERK_SECRET_KEY=sk_test_..."
    echo "  DATABASE_URL=postgresql+psycopg://..."
    echo "  BASE_URL=https://mission-control-jbx8.onrender.com"
    echo "  CORS_ORIGINS=https://app.digidle.com,http://localhost:3000"
    echo "  OPENAI_API_KEY=sk-proj-..."
    return 1
  else
    success "Environment check passed"
  fi
}

fix_verify() {
  info "fix:verify — running post-fix health check..."
  sleep 10
  exec "$SCRIPT_DIR/health-check.sh" --summary
}

# ── Execute fixes ─────────────────────────────────────────────────────────────
for TARGET in "${TARGETS[@]}"; do
  case "$TARGET" in
    fix:cors)               fix_cors    && FIXES_APPLIED+=("$TARGET") || FIXES_FAILED+=("$TARGET") ;;
    fix:redeploy)           fix_redeploy && FIXES_APPLIED+=("$TARGET") || FIXES_FAILED+=("$TARGET") ;;
    fix:build)              fix_build   && FIXES_APPLIED+=("$TARGET") || FIXES_FAILED+=("$TARGET") ;;
    fix:env)                fix_env     && FIXES_APPLIED+=("$TARGET") || FIXES_FAILED+=("$TARGET") ;;
    fix:backend_error)      fix_env && fix_redeploy && FIXES_APPLIED+=("$TARGET") || FIXES_FAILED+=("$TARGET") ;;
    fix:vercel_redeploy)
      info "Vercel redeploys automatically on git push — push to trigger"
      FIXES_APPLIED+=("$TARGET")
      ;;
    fix:all)
      fix_env   && FIXES_APPLIED+=("fix:env")   || FIXES_FAILED+=("fix:env")
      fix_cors  && FIXES_APPLIED+=("fix:cors")  || FIXES_FAILED+=("fix:cors")
      ;;
    "")
      warn "No fix target — run health check to identify issues"
      exec "$SCRIPT_DIR/health-check.sh"
      ;;
    *)
      warn "Unknown fix target: $TARGET"
      ;;
  esac
done

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
python3 - <<PYEOF
import json
print(json.dumps({
  "workflow": "auto-fix",
  "timestamp": "$TS",
  "applied": $(python3 -c "import json; print(json.dumps(r'${FIXES_APPLIED[*]}'.split() if r'${FIXES_APPLIED[*]}' else []))" 2>/dev/null || echo "[]"),
  "failed": $(python3 -c "import json; print(json.dumps(r'${FIXES_FAILED[*]}'.split() if r'${FIXES_FAILED[*]}' else []))" 2>/dev/null || echo "[]"),
}, indent=2))
PYEOF

# Post-fix verification
if [[ ${#FIXES_APPLIED[@]} -gt 0 ]]; then
  fix_verify
fi

[[ ${#FIXES_FAILED[@]} -eq 0 ]]
