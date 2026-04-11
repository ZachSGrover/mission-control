#!/usr/bin/env bash
# ── Workflow 5: OpenClaw Gateway Setup ───────────────────────────────────────
# Makes /chat (Claude tab) functional by connecting an OpenClaw WebSocket gateway
#
# What OpenClaw is:
#   A WebSocket server that connects AI agents (Claude, etc.) to the Mission
#   Control frontend. The frontend at /chat opens a WS to this server, authenticates,
#   and exchanges chat.send / chat event frames.
#
# What you need:
#   1. An OpenClaw gateway server running at a public WSS URL
#   2. A token for the frontend to authenticate with
#   3. The gateway registered in the Mission Control backend DB
#   4. NEXT_PUBLIC_OPENCLAW_WS_URL + NEXT_PUBLIC_OPENCLAW_TOKEN set in Vercel
#
# Usage:
#   ./scripts/setup-openclaw-gateway.sh --check        # check current state
#   ./scripts/setup-openclaw-gateway.sh --register     # register gateway in DB
#   ./scripts/setup-openclaw-gateway.sh --vercel       # print Vercel env vars to set
#   ./scripts/setup-openclaw-gateway.sh --full         # all steps
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

BACKEND_URL="${BACKEND_URL:-https://mission-control-jbx8.onrender.com}"
OPENCLAW_WS_URL="${OPENCLAW_WS_URL:-}"        # e.g. wss://your-gateway.example.com:18789
OPENCLAW_TOKEN="${OPENCLAW_TOKEN:-}"          # token for frontend auth
OWNER_TOKEN="${OWNER_TOKEN:-}"               # your Clerk JWT (for API calls)
MODE="${1:---check}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${BLUE}[openclaw]${NC} $*"; }
success() { echo -e "${GREEN}[openclaw]${NC} ✓ $*"; }
warn()    { echo -e "${YELLOW}[openclaw]${NC} ⚠ $*"; }
fail()    { echo -e "${RED}[openclaw]${NC} ✗ $*"; }
step()    { echo -e "${CYAN}[openclaw]${NC} ── $*"; }

# ── Step A: Check current gateway state ──────────────────────────────────────
check_state() {
  step "Checking current gateway state..."

  if [[ -z "$OWNER_TOKEN" ]]; then
    warn "OWNER_TOKEN not set — skipping API checks"
    warn "Set: export OWNER_TOKEN='your-clerk-jwt'"
    return
  fi

  # List registered gateways
  local GATEWAYS
  GATEWAYS=$(curl -sf \
    -H "Authorization: Bearer $OWNER_TOKEN" \
    "$BACKEND_URL/api/v1/gateways?limit=10" 2>/dev/null || echo "")

  if [[ -z "$GATEWAYS" ]]; then
    warn "Could not reach gateways API"
  else
    local COUNT
    COUNT=$(echo "$GATEWAYS" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('total',0))" 2>/dev/null || echo "0")

    if [[ "$COUNT" == "0" ]]; then
      fail "No gateways registered. Run --register to add one."
    else
      success "Found $COUNT registered gateway(s):"
      echo "$GATEWAYS" | python3 -c "
import json,sys
d=json.load(sys.stdin)
for g in d.get('items',[]):
    print(f\"  id={g['id']} name={g['name']} url={g['url']}\")
" 2>/dev/null || true
    fi
  fi

  # Check frontend env vars
  echo ""
  step "Required Vercel environment variables:"
  echo "  NEXT_PUBLIC_OPENCLAW_WS_URL  = ${OPENCLAW_WS_URL:-<NOT SET>}"
  echo "  NEXT_PUBLIC_OPENCLAW_TOKEN   = ${OPENCLAW_TOKEN:-<NOT SET>}"
  echo "  NEXT_PUBLIC_OPENCLAW_SESSION = agent:main:missioncontrol"
  echo ""

  if [[ -z "$OPENCLAW_WS_URL" ]]; then
    fail "OPENCLAW_WS_URL not set"
    echo ""
    echo "  Options to run an OpenClaw gateway:"
    echo ""
    echo "  Option 1 — Render (recommended for production):"
    echo "    1. Create a new Render web service from: https://github.com/openclaw/openclaw"
    echo "    2. Set env: PORT=18789, OPENCLAW_TOKEN=<generate a secret>"
    echo "    3. Use the resulting wss://your-service.onrender.com URL"
    echo ""
    echo "  Option 2 — Self-hosted (VPS/local):"
    echo "    docker run -p 18789:18789 -e OPENCLAW_TOKEN=mysecret openclaw/gateway"
    echo "    Then expose via ngrok: ngrok tcp 18789"
    echo "    Use: wss://<ngrok-host>:443"
    echo ""
    echo "  Option 3 — Tailscale (private network):"
    echo "    Run gateway on any machine in your Tailnet"
    echo "    Use: wss://<tailnet-hostname>:18789"
    echo ""
    echo "  After setup, re-run: OPENCLAW_WS_URL=wss://... OPENCLAW_TOKEN=... ./scripts/setup-openclaw-gateway.sh --full"
  else
    # Test WS reachability (just TCP check via curl)
    local HOST PORT
    HOST=$(echo "$OPENCLAW_WS_URL" | sed 's|wss\?://||' | cut -d: -f1 | cut -d/ -f1)
    PORT=$(echo "$OPENCLAW_WS_URL" | grep -oP ':\d+' | head -1 | tr -d ':' || echo "18789")

    if curl -sf --max-time 5 "https://$HOST:$PORT" -o /dev/null 2>/dev/null || \
       nc -z -w 3 "$HOST" "$PORT" 2>/dev/null; then
      success "Gateway host reachable: $HOST:$PORT"
    else
      warn "Gateway host may not be reachable: $HOST:$PORT"
    fi
  fi
}

# ── Step B: Register gateway in backend DB ────────────────────────────────────
register_gateway() {
  step "Registering gateway in Mission Control backend..."

  if [[ -z "$OPENCLAW_WS_URL" ]]; then
    fail "OPENCLAW_WS_URL is required. Export it before running."
    exit 1
  fi
  if [[ -z "$OWNER_TOKEN" ]]; then
    fail "OWNER_TOKEN (Clerk JWT) is required. Export it before running."
    exit 1
  fi

  local PAYLOAD
  PAYLOAD=$(python3 -c "
import json
print(json.dumps({
  'name': 'mission-control-gateway',
  'url': '$OPENCLAW_WS_URL',
  'workspace_root': '/workspace',
  'token': '${OPENCLAW_TOKEN:-}' or None,
  'allow_insecure_tls': False,
  'disable_device_pairing': False,
}))
")

  local RESULT
  RESULT=$(curl -sf -X POST \
    -H "Authorization: Bearer $OWNER_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    "$BACKEND_URL/api/v1/gateways" 2>/dev/null || echo "")

  if [[ -z "$RESULT" ]]; then
    fail "Gateway registration failed — check OWNER_TOKEN and OPENCLAW_WS_URL"
    return 1
  fi

  local GW_ID
  GW_ID=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")

  if [[ -n "$GW_ID" ]]; then
    success "Gateway registered with id=$GW_ID"
    echo ""
    info "Next: sync gateway templates to bootstrap agent sessions"
    info "POST $BACKEND_URL/api/v1/gateways/$GW_ID/templates/sync"
    echo ""

    # Auto-sync templates
    SYNC=$(curl -sf -X POST \
      -H "Authorization: Bearer $OWNER_TOKEN" \
      "$BACKEND_URL/api/v1/gateways/$GW_ID/templates/sync?include_main=true&force_bootstrap=true" \
      2>/dev/null || echo "")
    if [[ -n "$SYNC" ]]; then
      success "Templates synced"
    else
      warn "Template sync returned empty — may need to retry once gateway is live"
    fi
  else
    fail "Unexpected response: $RESULT"
    return 1
  fi
}

# ── Step C: Print Vercel env vars ─────────────────────────────────────────────
print_vercel_vars() {
  step "Vercel environment variables needed for /chat to work:"
  echo ""
  echo "  Go to: https://vercel.com/dashboard → mission-control → Settings → Environment Variables"
  echo ""
  echo "  Variable                        Value"
  echo "  ─────────────────────────────── ──────────────────────────────────────────"
  printf "  %-31s %s\n" "NEXT_PUBLIC_OPENCLAW_WS_URL"  "${OPENCLAW_WS_URL:-<your-wss-url>}"
  printf "  %-31s %s\n" "NEXT_PUBLIC_OPENCLAW_TOKEN"   "${OPENCLAW_TOKEN:-<your-token>}"
  printf "  %-31s %s\n" "NEXT_PUBLIC_OPENCLAW_SESSION" "agent:main:missioncontrol"
  echo ""
  echo "  After adding, redeploy Vercel: https://vercel.com/dashboard → Deployments → Redeploy"
  echo ""

  if [[ -n "$OPENCLAW_WS_URL" ]] && [[ -n "$OPENCLAW_TOKEN" ]]; then
    info "Vercel CLI (if installed):"
    echo "  vercel env add NEXT_PUBLIC_OPENCLAW_WS_URL production <<< '$OPENCLAW_WS_URL'"
    echo "  vercel env add NEXT_PUBLIC_OPENCLAW_TOKEN production  <<< '$OPENCLAW_TOKEN'"
    echo "  vercel env add NEXT_PUBLIC_OPENCLAW_SESSION production <<< 'agent:main:missioncontrol'"
    echo "  vercel --prod deploy"
  fi
}

# ── Protocol reference ────────────────────────────────────────────────────────
print_protocol() {
  step "OpenClaw WebSocket Protocol (for implementing/debugging a gateway):"
  cat <<'PROTO'

  Connection flow:
    1. Client opens WS to wss://<gateway>:<port>
    2. Server sends: {"type":"event","event":"connect.challenge"}
    3. Client sends connect request:
       {
         "type": "req", "id": "<uuid>", "method": "connect",
         "params": {
           "minProtocol": 3, "maxProtocol": 3,
           "role": "operator",
           "scopes": ["operator.read","operator.write","operator.admin"],
           "client": {"id":"openclaw-control-ui","version":"1.0.0","platform":"darwin","mode":"ui"},
           "auth": {"token": "<NEXT_PUBLIC_OPENCLAW_TOKEN>"}
         }
       }
    4. Server responds: {"type":"res","id":"<uuid>","ok":true,"payload":{...}}
       → Client status: "connected"

  Sending a chat message:
    {
      "type": "req", "id": "<uuid>", "method": "chat.send",
      "params": {
        "sessionKey": "agent:main:missioncontrol",
        "message": "hello",
        "deliver": false,
        "idempotencyKey": "<uuid>"
      }
    }

  Receiving chat events (server → client):
    {"type":"event","event":"chat","payload":{
      "runId":"<id>","sessionKey":"...","seq":1,
      "state":"delta","message":{"delta":{"type":"text_delta","text":"..."}}
    }}
    {"type":"event","event":"chat","payload":{"runId":"<id>","state":"final","message":{...}}}

PROTO
}

# ── Dispatch ──────────────────────────────────────────────────────────────────
case "$MODE" in
  --check)    check_state ;;
  --register) register_gateway ;;
  --vercel)   print_vercel_vars ;;
  --protocol) print_protocol ;;
  --full)
    check_state
    echo ""
    if [[ -n "$OPENCLAW_WS_URL" ]]; then
      register_gateway
      echo ""
    fi
    print_vercel_vars
    ;;
  *)
    echo "Usage: $0 [--check | --register | --vercel | --protocol | --full]"
    exit 1
    ;;
esac
