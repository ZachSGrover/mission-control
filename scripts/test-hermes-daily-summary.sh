#!/usr/bin/env bash
# test-hermes-daily-summary.sh — dry-run smoke tests for the daily summary.
#
# Builds isolated MC_STATE_DIR fixtures, runs hermes-daily-summary.sh against
# each, and asserts that the rendered text contains the expected sections.
# No real send is ever performed — every test runs in dry-run mode against
# a fresh tmp directory.
#
# Usage:
#   ./scripts/test-hermes-daily-summary.sh           # all tests
#   ./scripts/test-hermes-daily-summary.sh -v        # also print rendered output
#
# Exit code: 0 = all passed, 1 = at least one failed.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DAILY="$SCRIPT_DIR/hermes-daily-summary.sh"

VERBOSE=0
[ "${1:-}" = "-v" ] && VERBOSE=1

PASS=0
FAIL=0
declare -a FAIL_NAMES

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
    [ "$VERBOSE" = "1" ] && printf '       got:\n%s\n' "$haystack" | head -20
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

# Build a wrapped state file at $1 with alert body $2 (JSON object as string).
# $3 is optional last_fired_at unix timestamp; defaults to now.
mkalert() {
  local path="$1" alert_json="$2" lf="${3:-$(date +%s)}"
  python3 - "$path" "$alert_json" "$lf" <<'PY'
import json, sys
path, alert_json, lf = sys.argv[1], sys.argv[2], sys.argv[3]
alert = json.loads(alert_json)
state = {"last_fired_at": int(lf), "alert": alert}
with open(path, "w") as f:
    json.dump(state, f)
PY
}

mk_dir() {
  local d
  d=$(mktemp -d -t hermes-daily-test.XXXXXX)
  mkdir -p "$d/alerts"
  echo "$d"
}

# ── 1. No alert state exists ─────────────────────────────────────────────────
hdr "1. no alert state directory"
D1=$(mktemp -d -t hermes-daily-empty.XXXXXX)
out=$(MC_STATE_DIR="$D1" "$DAILY" 2>&1)
rc=$?
assert_exit "exits 0"                       "0" "$rc"
assert_contains "header line"               "$out" "🌅 Hermes daily summary"
assert_contains "empty-state copy"          "$out" "No Hermes alert state directory found yet"
rm -rf "$D1"
v "$out"

# ── 2. One unresolved CRITICAL alert ─────────────────────────────────────────
hdr "2. one unresolved CRITICAL alert"
D2=$(mk_dir)
mkalert "$D2/alerts/openclaw-gateway-failed-aaa.json" '{
  "alert_id":"openclaw-gateway-failed-aaa",
  "system":"OpenClaw Gateway",
  "status":"failed",
  "severity":"CRITICAL",
  "exact_issue":"Gateway is not responding on port 18789.",
  "evidence":["probe failed","process missing"],
  "likely_cause":"Crashed.",
  "business_impact":"Browser control disconnected.",
  "recommended_fix":"Restart com.digidle.openclaw.",
  "claude_prompt":"OpenClaw gateway is down. Inspect:\n  1. launchctl print\n  2. ~/.openclaw/logs/gateway.err\nFix the root cause.",
  "timestamp":"2026-04-29T23:45:53Z"
}'
out=$(MC_STATE_DIR="$D2" "$DAILY" 2>&1)
assert_contains "shows 1 active CRITICAL"      "$out" "1 active incident"
assert_contains "CRITICAL count"               "$out" "1 CRITICAL"
assert_contains "system name in active list"   "$out" "OpenClaw Gateway"
assert_contains "Best next repair prompt"      "$out" "Best next repair prompt"
assert_contains "prompt content rendered"      "$out" "launchctl print"
rm -rf "$D2"
v "$out"

# ── 3. Repeated duplicate issue (failure_count >= 3) ─────────────────────────
hdr "3. repeated duplicate issue"
D3=$(mk_dir)
mkalert "$D3/alerts/svc-flap.json" '{
  "alert_id":"svc-flap",
  "system":"Mission Control Backend",
  "status":"failed",
  "severity":"HIGH",
  "exact_issue":"Backend flapping.",
  "evidence":["several restarts"],
  "likely_cause":"unknown",
  "business_impact":"intermittent",
  "recommended_fix":"investigate",
  "claude_prompt":"Inspect: 1. logs",
  "timestamp":"2026-04-29T22:00:00Z",
  "failure_count": 5
}'
out=$(MC_STATE_DIR="$D3" "$DAILY" 2>&1)
assert_contains "Repeated section header"    "$out" "Repeated issues"
assert_contains "shows 5 failures"            "$out" "5 failures"
assert_contains "system name shown"           "$out" "Mission Control Backend"
rm -rf "$D3"
v "$out"

# ── 4. One resolved issue in last 24h ────────────────────────────────────────
hdr "4. one resolved in last 24h"
D4=$(mk_dir)
NOW=$(date +%s)
mkalert "$D4/alerts/just-resolved.json" '{
  "alert_id":"just-resolved",
  "system":"Mission Control Backend",
  "status":"resolved",
  "severity":"HIGH",
  "exact_issue":"Backend recovered.",
  "evidence":[],
  "likely_cause":"transient",
  "business_impact":"none",
  "recommended_fix":"none",
  "claude_prompt":"",
  "timestamp":"2026-04-29T22:00:00Z",
  "resolved_at":"2026-04-29T22:30:00Z"
}' "$NOW"
out=$(MC_STATE_DIR="$D4" "$DAILY" 2>&1)
assert_contains "Resolved section"          "$out" "Resolved in last 24h"
assert_contains "system listed"             "$out" "Mission Control Backend"
assert_contains "no active section empty"   "$out" "No active incidents"
rm -rf "$D4"
v "$out"

# ── 5. Mixed healthy / degraded / failed ─────────────────────────────────────
hdr "5. mixed healthy / degraded / failed"
D5=$(mk_dir)
mkalert "$D5/alerts/a.json" '{
  "alert_id":"a","system":"OpenClaw Gateway","status":"failed","severity":"CRITICAL",
  "exact_issue":"down","evidence":[],"likely_cause":"x","business_impact":"y",
  "recommended_fix":"z","claude_prompt":"p1","timestamp":"2026-04-29T23:00:00Z"
}'
mkalert "$D5/alerts/b.json" '{
  "alert_id":"b","system":"Mission Control Backend","status":"degraded","severity":"HIGH",
  "exact_issue":"slow","evidence":[],"likely_cause":"x","business_impact":"y",
  "recommended_fix":"z","claude_prompt":"p2","timestamp":"2026-04-29T23:10:00Z"
}'
mkalert "$D5/alerts/c.json" '{
  "alert_id":"c","system":"Local Machine","status":"resolved","severity":"LOW",
  "exact_issue":"boot","evidence":[],"likely_cause":"x","business_impact":"y",
  "recommended_fix":"z","claude_prompt":"","timestamp":"2026-04-29T22:00:00Z",
  "resolved_at":"2026-04-29T22:01:00Z"
}' "$(date +%s)"
out=$(MC_STATE_DIR="$D5" "$DAILY" 2>&1)
assert_contains "2 active reported"             "$out" "2 active incident"
assert_contains "1 CRITICAL"                    "$out" "1 CRITICAL"
assert_contains "1 HIGH"                        "$out" "1 HIGH"
assert_contains "active gateway listed"         "$out" "OpenClaw Gateway"
assert_contains "active backend listed"         "$out" "Mission Control Backend"
assert_contains "resolved local machine listed" "$out" "Local Machine"
# Top-pick = highest severity (CRITICAL)
assert_contains "top pick is CRITICAL"          "$out" "OpenClaw Gateway (CRITICAL)"
rm -rf "$D5"
v "$out"

# ── 6. Malformed JSON ignored safely ─────────────────────────────────────────
hdr "6. malformed JSON ignored safely"
D6=$(mk_dir)
mkalert "$D6/alerts/good.json" '{
  "alert_id":"good","system":"OpenClaw Gateway","status":"failed","severity":"HIGH",
  "exact_issue":"x","evidence":[],"likely_cause":"x","business_impact":"x",
  "recommended_fix":"x","claude_prompt":"x","timestamp":"2026-04-29T23:00:00Z"
}'
echo "{not valid json"          > "$D6/alerts/broken.json"
echo "[\"unexpected array\"]"  > "$D6/alerts/wrong-shape.json"
out=$(MC_STATE_DIR="$D6" "$DAILY" 2>&1)
rc=$?
assert_exit "did not crash"                "0" "$rc"
assert_contains "1 active reported"        "$out" "1 active incident"
assert_contains "warning footer"           "$out" "could not be parsed"
assert_contains "warning count = 2"        "$out" "2 alert state file(s)"
rm -rf "$D6"
v "$out"

# ── 7. Secret-shaped values are redacted ─────────────────────────────────────
# Daily summary renders exact_issue and (for the top unresolved alert) the
# claude_prompt. Putting secrets in those rendered fields exercises the
# redaction layer in the same path the operator would actually see.
hdr "7. secret-shaped values redacted"
D7=$(mk_dir)
mkalert "$D7/alerts/leaky.json" '{
  "alert_id":"leaky",
  "system":"Anthropic API",
  "status":"failed",
  "severity":"HIGH",
  "exact_issue":"Bearer abc12345secrettokenvalue1234 rejected.",
  "_extra_note_for_daily_summary":"unused",
  "evidence":[],
  "likely_cause":"rotated",
  "business_impact":"calls fail",
  "recommended_fix":"refresh",
  "claude_prompt":"Investigate. Logs showed:\n  ghp_abcdefghijklmnopqrstuvwxyz1234567890\n  pk_test_thisIsACle67rkKey\n  AKIA0123456789ABCDEF",
  "timestamp":"2026-04-29T23:00:00Z"
}'
out=$(MC_STATE_DIR="$D7" "$DAILY" 2>&1)
assert_contains    "Bearer redacted"      "$out" "Bearer [REDACTED]"
assert_not_contains "raw bearer leaked"   "$out" "abc12345secrettokenvalue1234"
assert_contains    "pk_test redacted"     "$out" "pk_test_[REDACTED]"
assert_not_contains "raw pk_test leaked"  "$out" "pk_test_thisIsACle67rkKey"
assert_contains    "AKIA redacted"        "$out" "AKIA[REDACTED]"
assert_not_contains "raw AKIA leaked"     "$out" "AKIA0123456789ABCDEF"
# ghp_ in claude_prompt is consumed by the specific ghp_ pattern (no preceding
# "token:" prefix to trigger the generic key=val rule first).
assert_contains    "ghp_ redacted"        "$out" "ghp_[REDACTED]"
assert_not_contains "raw ghp_ leaked"     "$out" "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
rm -rf "$D7"
v "$out"

# ── 8. Send guard refuses without HERMES_ALERT_ALLOW_SEND=1 ──────────────────
hdr "8. send guard refuses without env var"
D8=$(mk_dir)
mkalert "$D8/alerts/x.json" '{
  "alert_id":"x","system":"OpenClaw Gateway","status":"failed","severity":"LOW",
  "exact_issue":"x","evidence":[],"likely_cause":"x","business_impact":"x",
  "recommended_fix":"x","claude_prompt":"x","timestamp":"2026-04-29T23:00:00Z"
}'
out=$(MC_STATE_DIR="$D8" "$DAILY" --send 2>&1)
rc=$?
assert_exit       "exit code 4"            "4" "$rc"
assert_contains   "safety-guard message"   "$out" "HERMES_ALERT_ALLOW_SEND"
assert_not_contains "no real send markers" "$out" "Discord sent: yes"
rm -rf "$D8"

# ── 9. --target test refuses without test channels configured ────────────────
hdr "9. --target test refuses with no test env"
D9=$(mk_dir)
mkalert "$D9/alerts/x.json" '{
  "alert_id":"x","system":"OpenClaw Gateway","status":"failed","severity":"LOW",
  "exact_issue":"x","evidence":[],"likely_cause":"x","business_impact":"x",
  "recommended_fix":"x","claude_prompt":"x","timestamp":"2026-04-29T23:00:00Z"
}'
# Both env vars unset; HERMES_ALERT_ALLOW_SEND=1 to get past the first guard.
unset HERMES_TEST_DISCORD_CHANNEL HERMES_TEST_TELEGRAM_CHAT_ID 2>/dev/null
out=$(HERMES_ALERT_ALLOW_SEND=1 MC_STATE_DIR="$D9" "$DAILY" --send --target test 2>&1)
rc=$?
assert_exit     "exit code 5"               "5" "$rc"
assert_contains "no test channel msg"       "$out" "no safe test channel"
rm -rf "$D9"

# ── 10. --show json produces parseable JSON ──────────────────────────────────
hdr "10. --show json output is parseable"
D10=$(mk_dir)
mkalert "$D10/alerts/x.json" '{
  "alert_id":"x","system":"S","status":"failed","severity":"HIGH",
  "exact_issue":"e","evidence":[],"likely_cause":"x","business_impact":"x",
  "recommended_fix":"x","claude_prompt":"x","timestamp":"2026-04-29T23:00:00Z"
}'
out=$(MC_STATE_DIR="$D10" "$DAILY" --show json 2>&1)
if printf '%s' "$out" | python3 -c 'import sys, json; d = json.loads(sys.stdin.read()); assert d["present"] and d["total_incidents"] == 1' 2>/dev/null; then
  ok "--show json parses; total_incidents=1"
else
  bad "--show json output is not valid JSON or wrong shape"
fi
rm -rf "$D10"

# ── Summary ──────────────────────────────────────────────────────────────────
echo
echo "─────────────────────────────────────────"
echo "Results: $PASS passed, $FAIL failed"
if [ "$FAIL" -gt 0 ]; then
  echo "Failed tests:"
  for n in "${FAIL_NAMES[@]}"; do echo "  - $n"; done
  exit 1
fi
echo "All Hermes daily-summary dry-run tests passed."
