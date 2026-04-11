#!/usr/bin/env bash
# ── Workflow 1: Deployment ────────────────────────────────────────────────────
# Trigger: manual or on git push
# Steps:   build check → git push → wait for Render deploy → verify health
#
# Usage:
#   ./scripts/deploy.sh                     # push HEAD, wait, verify
#   ./scripts/deploy.sh --skip-build-check  # skip local TypeScript build
#   RENDER_API_KEY=rnd_xxx ./scripts/deploy.sh
#
# Env vars (can be set in .env or exported):
#   RENDER_API_KEY     - Render API key (get from dashboard.render.com/account/api-keys)
#   RENDER_SERVICE_ID  - Render web service ID (default: srv-d7cq41q8qa3s73bbke00)
#   BACKEND_URL        - Production backend URL
#   FRONTEND_URL       - Production frontend URL
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Config ────────────────────────────────────────────────────────────────────
RENDER_API_KEY="${RENDER_API_KEY:-}"
RENDER_SERVICE_ID="${RENDER_SERVICE_ID:-srv-d7cq41q8qa3s73bbke00}"
BACKEND_URL="${BACKEND_URL:-https://mission-control-jbx8.onrender.com}"
FRONTEND_URL="${FRONTEND_URL:-https://app.digidle.com}"
SKIP_BUILD_CHECK="${1:-}"
DEPLOY_TIMEOUT=600   # seconds to wait for deploy
POLL_INTERVAL=15     # seconds between status polls
NODE_BIN="$(find /usr/local/Cellar/node@22 /usr/local/bin /opt/homebrew/bin -name node -type f 2>/dev/null | head -1)"

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[deploy]${NC} $*"; }
success() { echo -e "${GREEN}[deploy]${NC} ✓ $*"; }
warn()    { echo -e "${YELLOW}[deploy]${NC} ⚠ $*"; }
fail()    { echo -e "${RED}[deploy]${NC} ✗ $*"; exit 1; }

emit_json() {
  local status=$1 msg=$2 commit
  commit=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo "unknown")
  printf '{"workflow":"deploy","status":"%s","message":"%s","commit":"%s","timestamp":"%s","backend":"%s","frontend":"%s"}\n' \
    "$status" "$msg" "$commit" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$BACKEND_URL" "$FRONTEND_URL"
}

# ── Step 1: Local build check ─────────────────────────────────────────────────
if [[ "$SKIP_BUILD_CHECK" != "--skip-build-check" ]] && [[ -n "$NODE_BIN" ]]; then
  info "Step 1/4: TypeScript build check..."
  cd "$ROOT/frontend"
  if PATH="$(dirname "$NODE_BIN"):$PATH" npx next build --no-lint 2>&1 | grep -qE "✓ Compiled|compiled successfully"; then
    success "Build check passed"
  else
    fail "Build failed — fix TypeScript errors before deploying"
  fi
  cd "$ROOT"
else
  warn "Step 1/4: Skipping local build check"
fi

# ── Step 2: Git push ──────────────────────────────────────────────────────────
info "Step 2/4: Pushing to GitHub (triggers Render auto-deploy)..."
cd "$ROOT"
if git diff --quiet && git diff --cached --quiet; then
  COMMIT=$(git rev-parse --short HEAD)
  info "No local changes — pushing current HEAD ($COMMIT)"
else
  fail "Uncommitted changes detected. Commit or stash before deploying."
fi
git push origin main
success "Pushed to GitHub"

# ── Step 3: Wait for Render deploy ───────────────────────────────────────────
info "Step 3/4: Waiting for Render to deploy..."

if [[ -z "$RENDER_API_KEY" ]]; then
  warn "RENDER_API_KEY not set — using health poll instead of Render API"
  info "Waiting 90s for Render to pick up the push..."
  sleep 90
else
  ELAPSED=0
  while [[ $ELAPSED -lt $DEPLOY_TIMEOUT ]]; do
    DEPLOY_STATUS=$(curl -sf \
      -H "Authorization: Bearer $RENDER_API_KEY" \
      "https://api.render.com/v1/services/$RENDER_SERVICE_ID/deploys?limit=1" \
      | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0]['deploy']['status'])" 2>/dev/null || echo "unknown")

    case "$DEPLOY_STATUS" in
      live)
        success "Render deploy: live"
        break
        ;;
      build_failed|canceled|deactivated)
        fail "Render deploy failed with status: $DEPLOY_STATUS"
        ;;
      *)
        info "Render deploy status: $DEPLOY_STATUS (${ELAPSED}s elapsed)..."
        sleep $POLL_INTERVAL
        ELAPSED=$((ELAPSED + POLL_INTERVAL))
        ;;
    esac
  done

  if [[ $ELAPSED -ge $DEPLOY_TIMEOUT ]]; then
    fail "Deploy timed out after ${DEPLOY_TIMEOUT}s"
  fi
fi

# ── Step 4: Verify health ─────────────────────────────────────────────────────
info "Step 4/4: Verifying system health..."

# Backend health
HTTP=$(curl -sf -o /dev/null -w "%{http_code}" "$BACKEND_URL/health" 2>/dev/null || echo "000")
if [[ "$HTTP" == "200" ]]; then
  success "Backend health: OK"
else
  fail "Backend health check failed (HTTP $HTTP)"
fi

# CORS preflight
HTTP=$(curl -sf -o /dev/null -w "%{http_code}" -X OPTIONS \
  "$BACKEND_URL/api/v1/settings/api-keys" \
  -H "Origin: $FRONTEND_URL" \
  -H "Access-Control-Request-Method: GET" 2>/dev/null || echo "000")
if [[ "$HTTP" == "200" ]]; then
  success "CORS preflight: OK"
else
  warn "CORS preflight returned HTTP $HTTP (expected 200)"
fi

# Auth protection
HTTP=$(curl -sf -o /dev/null -w "%{http_code}" \
  "$BACKEND_URL/api/v1/roles/me" 2>/dev/null || echo "000")
if [[ "$HTTP" == "401" ]]; then
  success "Auth protection: OK (401 without token)"
else
  warn "Auth returned unexpected HTTP $HTTP (expected 401)"
fi

# Frontend
HTTP=$(curl -sfL -o /dev/null -w "%{http_code}" "$FRONTEND_URL" 2>/dev/null || echo "000")
if [[ "$HTTP" == "200" ]]; then
  success "Frontend: OK"
else
  warn "Frontend returned HTTP $HTTP (expected 200)"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
COMMIT=$(git rev-parse --short HEAD)
echo ""
success "Deploy complete — commit $COMMIT is live"
emit_json "success" "Deploy complete" | tee /tmp/mc-last-deploy.json
