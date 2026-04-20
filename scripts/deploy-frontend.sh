#!/usr/bin/env bash
# deploy-frontend.sh — Build Next.js from source and restart the server
# Usage: ./scripts/deploy-frontend.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
NODE="/Users/zachary/.openclaw/tools/node-v22.22.0/bin/node"
NEXT="$FRONTEND_DIR/node_modules/next/dist/bin/next"

echo "==> Building frontend…"
cd "$FRONTEND_DIR"
"$NODE" "$NEXT" build

echo "==> Restarting next-server…"
launchctl kickstart -k "gui/$(id -u)/com.digidle.next-server"

echo "==> Restarting backend…"
launchctl kickstart -k "gui/$(id -u)/com.digidle.backend"

echo "==> Waiting for services…"
sleep 5

NEXT_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 2>/dev/null || echo "000")
BACKEND_STATUS=$(curl -sf http://localhost:8000/healthz 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('ok' if d.get('ok') else 'degraded')" 2>/dev/null || echo "down")

echo "  Next.js: HTTP $NEXT_STATUS"
echo "  Backend: $BACKEND_STATUS"
echo "  BUILD_ID: $(cat "$FRONTEND_DIR/.next/BUILD_ID" 2>/dev/null || echo 'unknown')"
