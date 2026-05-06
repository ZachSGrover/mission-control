#!/usr/bin/env bash
# test-hermes-alert.sh — dry-run smoke tests for the Hermes alert library.
#
# This file does NOT send any real notification. It only exercises the
# formatting, validation, redaction, and dedupe-key logic on local files.
#
# Usage:
#   ./scripts/test-hermes-alert.sh           # run all tests
#   ./scripts/test-hermes-alert.sh -v        # also print rendered output
#
# Exit code: 0 = all tests passed, 1 = at least one failed.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERMES="$SCRIPT_DIR/hermes-alert.sh"
# shellcheck source=lib/alert-format.sh
. "$SCRIPT_DIR/lib/alert-format.sh"

VERBOSE=0
[ "${1:-}" = "-v" ] && VERBOSE=1

PASS=0
FAIL=0
declare -a FAIL_NAMES

# Use an isolated state dir so dedupe tests don't collide with real Hermes.
export MC_STATE_DIR="$(mktemp -d -t hermes-alert-test.XXXXXX)"
trap 'rm -rf "$MC_STATE_DIR"' EXIT

ok()    { echo "  ✓ $*"; PASS=$((PASS+1)); }
bad()   { echo "  ✗ $*"; FAIL=$((FAIL+1)); FAIL_NAMES+=("$1"); }
hdr()   { echo; echo "── $* ──"; }
v()     { [ "$VERBOSE" = "1" ] && printf '%s\n' "$*"; }

assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if printf '%s' "$haystack" | grep -qF -- "$needle"; then
    ok "$name"
  else
    bad "$name (expected to contain: $needle)"
    [ "$VERBOSE" = "1" ] && printf '       got: %s\n' "$haystack" | head -20
  fi
}

assert_not_contains() {
  local name="$1" haystack="$2" needle="$3"
  if printf '%s' "$haystack" | grep -qF -- "$needle"; then
    bad "$name (should NOT contain: $needle)"
  else
    ok "$name"
  fi
}

assert_exit() {
  local name="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    ok "$name (exit=$actual)"
  else
    bad "$name (expected exit=$expected, got=$actual)"
  fi
}

# ── 1. missing Discord heartbeat ─────────────────────────────────────────────
hdr "missing Discord heartbeat"
out=$("$HERMES" --template discord_heartbeat_missing 2>&1) || true
assert_contains "renders Discord payload"           "$out" '"embeds"'
assert_contains "renders Telegram block"            "$out" "TELEGRAM message text"
assert_contains "shows status=disconnected"         "$out" "disconnected"
assert_contains "severity=HIGH present"             "$out" "HIGH"
assert_contains "repair prompt mentions notify.sh"  "$out" "notify.sh"
assert_not_contains "no token leak"                 "$out" "DISCORD_BOT_TOKEN="
v "$out"

# ── 2. invalid API token style error ─────────────────────────────────────────
hdr "invalid API token (with deliberately leaky evidence)"
LEAKY_EV=$'API call returned 401\nAuthorization: Bearer sk-abc1234567890longish\npk_test_thisIsACle67rkKey\nAKIA1234567890ABCDEF'
out=$(H_SYSTEM="OpenAI" H_EVIDENCE="$LEAKY_EV" \
      "$HERMES" --template api_token_invalid 2>&1) || true
assert_contains    "system override applied"        "$out" "OpenAI"
assert_contains    "Bearer redacted"                "$out" "Bearer [REDACTED]"
assert_not_contains "raw bearer token leaked"       "$out" "sk-abc1234567890longish"
assert_contains    "pk_test redacted"               "$out" "pk_test_[REDACTED]"
assert_not_contains "raw pk_test leaked"            "$out" "pk_test_thisIsACle67rkKey"
assert_contains    "AKIA redacted"                  "$out" "AKIA[REDACTED]"
assert_not_contains "raw AWS key leaked"            "$out" "AKIA1234567890ABCDEF"
v "$out"

# ── 3. backend route failure ─────────────────────────────────────────────────
hdr "backend route failure"
out=$("$HERMES" --template backend_down --field severity=CRITICAL 2>&1) || true
assert_contains "title shows CRITICAL"              "$out" "[CRITICAL]"
assert_contains "Mission Control Backend"           "$out" "Mission Control Backend"
assert_contains "embeds rendered"                   "$out" '"color": 15158332'
assert_contains "repair prompt has report-back"     "$out" "Report back"
v "$out"

# ── 4. websocket / gateway failure ───────────────────────────────────────────
hdr "websocket / gateway failure"
out=$("$HERMES" --template gateway_down 2>&1) || true
assert_contains "system = OpenClaw Gateway"         "$out" "OpenClaw Gateway"
assert_contains "evidence mentions :18789 OR port"  "$out" "18789"
assert_contains "fix mentions kickstart"            "$out" "kickstart"
assert_contains "prompt forbids touching cloudflared" "$out" "Do NOT touch cloudflared"

out2=$("$HERMES" --template websocket_failed 2>&1) || true
assert_contains "websocket: status disconnected"    "$out2" "disconnected"
assert_contains "websocket: prompt covers close code" "$out2" "close code"
v "$out"
v "$out2"

# ── 5. repeated identical alert (dedupe) ─────────────────────────────────────
hdr "repeated identical alert — dedupe should suppress 2nd identical fire"
# First fire: novel, exit 0
"$HERMES" --template gateway_down --check-dedupe --show json --field alert_id=test-dedupe-fixed > /tmp/hermes-test-1.json
rc1=$?
assert_exit "first fire allowed" "0" "$rc1"

# Second identical fire: should be suppressed (exit 2)
"$HERMES" --template gateway_down --check-dedupe --show json --field alert_id=test-dedupe-fixed > /tmp/hermes-test-2.json
rc2=$?
assert_exit "duplicate suppressed" "2" "$rc2"

# Third fire with severity bump: should be allowed again
"$HERMES" --template gateway_down --check-dedupe --show json \
  --field alert_id=test-dedupe-fixed \
  --field severity=CRITICAL \
  --field exact_issue="severity escalated" > /tmp/hermes-test-3.json
rc3=$?
assert_exit "severity bump fires" "0" "$rc3"

# ── 6. resolved alert ────────────────────────────────────────────────────────
hdr "resolved alert"
RESOLVED_JSON='{
  "system": "OpenClaw Gateway",
  "what_recovered": "launchd job restarted, port 18789 listening",
  "last_failed_state": "failed",
  "first_seen": "2026-04-28T17:14:22Z",
  "resolved_at": "2026-04-28T17:31:08Z",
  "failure_count": 4
}'
out=$(printf '%s' "$RESOLVED_JSON" | "$HERMES" --resolved --stdin-json 2>&1) || true
assert_contains "starts with Resolved:"             "$out" "Resolved: OpenClaw Gateway"
assert_contains "shows failure count"               "$out" "Failures during incident: 4"
assert_contains "shows resolved_at"                 "$out" "Resolved at: 2026-04-28T17:31:08Z"
v "$out"

# ── 7. validation: missing required field ────────────────────────────────────
hdr "validation: missing required field"
BAD_JSON='{"system":"X","status":"failed","severity":"CRITICAL"}'
out=$(printf '%s' "$BAD_JSON" | "$HERMES" --stdin-json 2>&1)
rc=$?
assert_exit "validation rejects missing fields" "3" "$rc"
assert_contains "error mentions MISSING_FIELDS" "$out" "MISSING_FIELDS"

# ── 8. validation: bad severity ──────────────────────────────────────────────
hdr "validation: bad severity"
out=$("$HERMES" --template backend_down --field severity=URGENT 2>&1)
rc=$?
assert_exit "validation rejects bad severity"   "3" "$rc"
assert_contains "error mentions BAD_SEVERITY"   "$out" "BAD_SEVERITY"

# ── 8b. field-override evidence accepts real newlines AND literal \n ────────
hdr "field-override evidence multi-line parsing"
EV_REAL=$'one
two
three'
out=$("$HERMES" --template backend_down --field "evidence=$EV_REAL" --show telegram 2>&1)
assert_contains "real-newline: bullet on line 1" "$out" "- one"
assert_contains "real-newline: bullet on line 2" "$out" "- two"
assert_contains "real-newline: bullet on line 3" "$out" "- three"

out=$("$HERMES" --template backend_down --field 'evidence=alpha\nbeta\ngamma' --show telegram 2>&1)
assert_contains "literal-\\n: bullet on alpha"   "$out" "- alpha"
assert_contains "literal-\\n: bullet on beta"    "$out" "- beta"
assert_contains "literal-\\n: bullet on gamma"   "$out" "- gamma"

# ── 9. dedupe key generator is stable ────────────────────────────────────────
hdr "dedupe key generator"
k1=$(af_dedupe_key "OpenClaw Gateway" "failed" "Gateway not responding")
k2=$(af_dedupe_key "OpenClaw Gateway" "failed" "Gateway not responding")
k3=$(af_dedupe_key "Backend" "failed" "Gateway not responding")
[ "$k1" = "$k2" ] && ok "same input -> same key ($k1)" || bad "key not stable: $k1 vs $k2"
[ "$k1" != "$k3" ] && ok "different system -> different key" || bad "different system shouldn't collide"

# ── 10. send is refused without env guard ────────────────────────────────────
hdr "send refused without HERMES_ALERT_ALLOW_SEND"
out=$("$HERMES" --template backend_down --send 2>&1)
rc=$?
assert_exit   "exit code is 4"                     "4" "$rc"
assert_contains "error message about safety guard" "$out" "HERMES_ALERT_ALLOW_SEND"

# ── Summary ──────────────────────────────────────────────────────────────────
echo
echo "─────────────────────────────────────────"
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  echo "Failed tests:"
  for n in "${FAIL_NAMES[@]}"; do echo "  - $n"; done
  exit 1
fi
echo "All Hermes alert dry-run tests passed."
