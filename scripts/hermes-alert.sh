#!/usr/bin/env bash
# hermes-alert.sh — CLI entry point for Hermes structured alerts.
#
# By default, no network call is made. Real sending requires BOTH:
#   --send (CLI flag, default: off)
#   HERMES_ALERT_ALLOW_SEND=1 (env, default: unset)
#
# Inputs (mutually exclusive primary modes):
#   --template NAME          Use a baked template from alert-templates.sh
#   --stdin-json             Read full canonical alert JSON on stdin
#   --resolved               Read resolved-alert JSON on stdin (different schema)
#
# Field overrides (apply after template):
#   --field key=value        Override a top-level field. Repeatable.
#                            Special: --field evidence=line1\nline2  splits on \n.
#
# Modes:
#   --dry-run                Print Discord payload + Telegram text + repair
#                            prompt. Default if --send is not given.
#   --send                   Actually post. Requires HERMES_ALERT_ALLOW_SEND=1.
#   --target prod|test       Where to send. Default: prod.
#                              prod → production channel matching notify.sh
#                                     (Discord HERMES_GENERAL_CHANNEL hard-coded
#                                     to match notify.sh; Telegram TELEGRAM_HOME_CHANNEL).
#                              test → HERMES_TEST_DISCORD_CHANNEL +
#                                     HERMES_TEST_TELEGRAM_CHAT_ID env vars.
#                                     Refuses if neither is set.
#   --check-dedupe           Apply dedupe rules. Suppresses duplicates with exit 2.
#   --no-redact              Skip the secret-redaction pass (NOT recommended).
#   --show all|discord|telegram|prompt|json   What to print in dry-run.
#                            Default: all.
#
# Examples:
#   ./scripts/hermes-alert.sh --template gateway_down
#   ./scripts/hermes-alert.sh --template backend_down --field severity=HIGH
#   echo '{...}' | ./scripts/hermes-alert.sh --stdin-json
#   HERMES_ALERT_ALLOW_SEND=1 ./scripts/hermes-alert.sh \
#     --template gateway_down --send --target test
#
# Exit codes:
#   0  success
#   1  usage / argument error
#   2  duplicate suppressed by --check-dedupe
#   3  validation error (missing required fields, bad severity, etc.)
#   4  send refused (--send without HERMES_ALERT_ALLOW_SEND=1, or stub guard)
#   5  no safe destination found (e.g. --target test with no test channels set)
#   6  both Discord and Telegram failed during a real send

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$SCRIPT_DIR/lib"
# shellcheck source=lib/alert-format.sh
. "$LIB_DIR/alert-format.sh"
# shellcheck source=lib/alert-templates.sh
. "$LIB_DIR/alert-templates.sh"

MODE=""
TEMPLATE=""
RESOLVED=0
DRY_RUN=1
SEND=0
SEND_TARGET="prod"
CHECK_DEDUPE=0
REDACT=1
SHOW="all"
FIELD_OVERRIDES=()

usage() {
  sed -n '2,50p' "$0" | sed 's/^# \?//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --template)        MODE="template"; TEMPLATE="$2"; shift 2 ;;
    --stdin-json)      MODE="stdin"; shift ;;
    --resolved)        RESOLVED=1; MODE="${MODE:-stdin}"; shift ;;
    --field)           FIELD_OVERRIDES+=("$2"); shift 2 ;;
    --dry-run)         DRY_RUN=1; SEND=0; shift ;;
    --send)            SEND=1; DRY_RUN=0; shift ;;
    --target)          SEND_TARGET="$2"; shift 2 ;;
    --check-dedupe)    CHECK_DEDUPE=1; shift ;;
    --no-redact)       REDACT=0; shift ;;
    --show)            SHOW="$2"; shift 2 ;;
    -h|--help)         usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 1 ;;
  esac
done

case "$SEND_TARGET" in
  prod|test) ;;
  *) echo "error: --target must be 'prod' or 'test' (got: $SEND_TARGET)" >&2; exit 1 ;;
esac

if [ -z "$MODE" ]; then
  echo "error: must specify --template NAME or --stdin-json" >&2
  exit 1
fi

# ── 1. Build canonical alert JSON ─────────────────────────────────────────────
TMP_JSON="$(mktemp -t hermes-alert.XXXXXX.json)"
trap 'rm -f "$TMP_JSON"' EXIT

if [ "$MODE" = "template" ]; then
  if ! declare -F "tpl_$TEMPLATE" >/dev/null; then
    echo "error: unknown template '$TEMPLATE'" >&2
    echo "available templates:" >&2
    declare -F | awk '/-f tpl_/{print "  " $3}' | sed 's/^  tpl_/  /' >&2
    exit 1
  fi
  "tpl_$TEMPLATE" > "$TMP_JSON"
else
  cat > "$TMP_JSON"
fi

# ── 2. Apply field overrides ──────────────────────────────────────────────────
if [ ${#FIELD_OVERRIDES[@]} -gt 0 ]; then
  for kv in "${FIELD_OVERRIDES[@]}"; do
    key="${kv%%=*}"
    val="${kv#*=}"
    KEY_IN="$key" VAL_IN="$val" python3 - <<'PYEOF' "$TMP_JSON"
import json, os, sys
path = sys.argv[1]
key = os.environ['KEY_IN']
val = os.environ['VAL_IN']
with open(path) as f:
  d = json.load(f)
if key == 'evidence':
  # Accept both real newlines (shell heredocs / multi-line quoted args) and
  # the literal two-char "\n" sequence (single-quoted single-line args).
  parts = val.replace('\\n', '\n').split('\n')
  d[key] = [l for l in parts if l.strip()]
else:
  d[key] = val
with open(path, 'w') as f:
  json.dump(d, f, indent=2, ensure_ascii=False)
PYEOF
  done
fi

# ── 3. Redact ─────────────────────────────────────────────────────────────────
if [ "$REDACT" = "1" ] && [ "$RESOLVED" = "0" ]; then
  REDACTED_JSON="$(mktemp -t hermes-alert-redacted.XXXXXX.json)"
  trap 'rm -f "$TMP_JSON" "$REDACTED_JSON"' EXIT
  python3 - "$TMP_JSON" <<'PYEOF' > "$REDACTED_JSON"
import json, sys, re, subprocess
with open(sys.argv[1]) as f:
  d = json.load(f)

PATTERNS = [
  (r'(?i)bearer\s+[A-Za-z0-9._\-]{8,}',                      'Bearer [REDACTED]'),
  (r'pk_(test|live)_[A-Za-z0-9_]+',                          r'pk_\1_[REDACTED]'),
  (r'sk_(test|live)_[A-Za-z0-9_]+',                          r'sk_\1_[REDACTED]'),
  (r'xox[baprs]-[A-Za-z0-9-]{10,}',                          'xox?-[REDACTED]'),
  (r'https://discord\.com/api/webhooks/\d+/[A-Za-z0-9_-]+',  'https://discord.com/api/webhooks/[REDACTED]'),
  (r'https://hooks\.slack\.com/services/[A-Z0-9/]+',         'https://hooks.slack.com/services/[REDACTED]'),
  (r'ghp_[A-Za-z0-9]{20,}',                                  'ghp_[REDACTED]'),
  (r'github_pat_[A-Za-z0-9_]{20,}',                          'github_pat_[REDACTED]'),
  (r'AKIA[0-9A-Z]{16}',                                      'AKIA[REDACTED]'),
  (r'rnd_[A-Za-z0-9]{20,}',                                  'rnd_[REDACTED]'),
  (r'(?i)\b(token|secret|password|api[_-]?key|auth[_-]?token)\b\s*[:=]\s*"?[^\s"\',]+', r'\1=[REDACTED]'),
]

def red(s):
  if not isinstance(s, str): return s
  for pat, repl in PATTERNS:
    s = re.sub(pat, repl, s)
  return s

def walk(x):
  if isinstance(x, dict):  return {k: walk(v) for k, v in x.items()}
  if isinstance(x, list):  return [walk(v) for v in x]
  if isinstance(x, str):   return red(x)
  return x

print(json.dumps(walk(d), indent=2, ensure_ascii=False))
PYEOF
  mv "$REDACTED_JSON" "$TMP_JSON"
fi

# ── 4. Validate (skip for resolved schema; it has different fields) ───────────
if [ "$RESOLVED" = "0" ]; then
  if ! af_validate_json "$TMP_JSON"; then
    echo "error: alert JSON failed validation" >&2
    exit 3
  fi
fi

# ── 5. Dedupe check (only for firing alerts; resolved always fires) ───────────
if [ "$CHECK_DEDUPE" = "1" ] && [ "$RESOLVED" = "0" ]; then
  # Direct call so $? captures the real exit code. `if ! cmd` would lose it.
  af_should_fire "$TMP_JSON" 2>/tmp/hermes-dedupe-reason.txt
  rc=$?
  echo "[hermes-alert] dedupe: $(cat /tmp/hermes-dedupe-reason.txt 2>/dev/null)" >&2
  if [ "$rc" = "2" ]; then exit 2; fi
  if [ "$rc" != "0" ]; then exit "$rc"; fi
fi

# ── 6. Compute payloads (used by both dry-run and real-send) ──────────────────
emit_section() {
  local label="$1" body="$2"
  printf '\n=== %s ===\n%s\n' "$label" "$body"
}

if [ "$RESOLVED" = "1" ]; then
  RESOLVED_TEXT="$(af_format_resolved "$TMP_JSON")"
  # Resolved alerts post a plain `{"content": "..."}` body; no embeds.
  DISCORD_PAYLOAD="$(RT="$RESOLVED_TEXT" python3 -c '
import json, os
print(json.dumps({"content": os.environ["RT"]}))')"
  TELEGRAM_TEXT="$RESOLVED_TEXT"
  REPAIR_PROMPT=""
else
  DISCORD_PAYLOAD="$(af_format_discord  "$TMP_JSON")"
  TELEGRAM_TEXT="$(af_format_telegram   "$TMP_JSON")"
  REPAIR_PROMPT="$(af_format_prompt     "$TMP_JSON")"
fi

# ── 7. Dry-run output ────────────────────────────────────────────────────────
if [ "$DRY_RUN" = "1" ]; then
  if [ "$RESOLVED" = "1" ]; then
    case "$SHOW" in
      all)
        emit_section "RESOLVED — Discord/Telegram body" "$TELEGRAM_TEXT"
        emit_section "RESOLVED — Discord payload"       "$DISCORD_PAYLOAD"
        emit_section "RESOLVED — JSON"                  "$(cat "$TMP_JSON")"
        ;;
      discord)     printf '%s\n' "$DISCORD_PAYLOAD" ;;
      telegram)    printf '%s\n' "$TELEGRAM_TEXT" ;;
      json)        cat "$TMP_JSON" ;;
      *)           printf '%s\n' "$TELEGRAM_TEXT" ;;
    esac
  else
    case "$SHOW" in
      all)
        emit_section "DISCORD payload (POST body)" "$DISCORD_PAYLOAD"
        emit_section "TELEGRAM message text"       "$TELEGRAM_TEXT"
        emit_section "REPAIR PROMPT (Claude)"      "$REPAIR_PROMPT"
        emit_section "ALERT JSON (canonical)"      "$(cat "$TMP_JSON")"
        ;;
      discord)     printf '%s\n' "$DISCORD_PAYLOAD" ;;
      telegram)    printf '%s\n' "$TELEGRAM_TEXT" ;;
      prompt)      printf '%s\n' "$REPAIR_PROMPT" ;;
      json)        cat "$TMP_JSON" ;;
      *)           echo "unknown --show value: $SHOW" >&2; exit 1 ;;
    esac
  fi
  exit 0
fi

# ── 8. Real send (only if --send AND HERMES_ALERT_ALLOW_SEND=1) ───────────────
if [ "$SEND" = "1" ]; then
  if [ "${HERMES_ALERT_ALLOW_SEND:-0}" != "1" ]; then
    echo "error: --send requires HERMES_ALERT_ALLOW_SEND=1 (safety guard)" >&2
    exit 4
  fi

  # Source secrets quietly. Match notify.sh behaviour: silence -x, set -a so
  # vars are exported. Subshell isn't used because we need vars locally; the
  # script process exits at the end so leakage scope is bounded.
  set +x
  set -a
  if [ -f "$HOME/.hermes/.env" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.hermes/.env" >/dev/null 2>&1 || true
  fi
  set +a

  # Channel resolution.
  # PROD: hard-coded Discord channel that matches ~/.hermes/hooks/notify.sh
  # exactly (1496312417565806592 — #hermes-general). Telegram uses
  # TELEGRAM_HOME_CHANNEL same as notify.sh.
  # TEST: requires HERMES_TEST_DISCORD_CHANNEL and/or HERMES_TEST_TELEGRAM_CHAT_ID
  # to be set in the shell env. We deliberately do NOT auto-pick a channel
  # from any directory file or env name pattern.
  case "$SEND_TARGET" in
    prod)
      DISCORD_CHAN="${HERMES_GENERAL_CHANNEL:-1496312417565806592}"
      TELEGRAM_CHAN="${TELEGRAM_HOME_CHANNEL:-}"
      ;;
    test)
      DISCORD_CHAN="${HERMES_TEST_DISCORD_CHANNEL:-}"
      TELEGRAM_CHAN="${HERMES_TEST_TELEGRAM_CHAT_ID:-}"
      if [ -z "$DISCORD_CHAN" ] && [ -z "$TELEGRAM_CHAN" ]; then
        echo "error: --target test requires HERMES_TEST_DISCORD_CHANNEL or HERMES_TEST_TELEGRAM_CHAT_ID" >&2
        echo "no safe test channel was found; refusing to send" >&2
        exit 5
      fi
      ;;
  esac

  # Per-channel send. Capture HTTP code only; redact response bodies before
  # printing any error. Never print URLs, tokens, or chat ids.
  RESP_TMP="$(mktemp -t hermes-send-resp.XXXXXX)"
  trap 'rm -f "$TMP_JSON" "$RESP_TMP"' EXIT

  DISCORD_SENT="no"
  DISCORD_ERR=""
  if [ -z "${DISCORD_BOT_TOKEN:-}" ]; then
    DISCORD_ERR="DISCORD_BOT_TOKEN not set in ~/.hermes/.env"
  elif [ -z "$DISCORD_CHAN" ]; then
    DISCORD_ERR="no Discord channel for target=$SEND_TARGET"
  else
    : > "$RESP_TMP"
    HTTP_CODE=$(curl -sS \
      -o "$RESP_TMP" \
      -w "%{http_code}" \
      --max-time 15 \
      -X POST \
      "https://discord.com/api/v10/channels/${DISCORD_CHAN}/messages" \
      -H "Authorization: Bot ${DISCORD_BOT_TOKEN}" \
      -H "Content-Type: application/json" \
      -d "$DISCORD_PAYLOAD" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
      DISCORD_SENT="yes"
    else
      # Redact any tokens that might appear in the response body before printing.
      RED_BODY=$(cat "$RESP_TMP" 2>/dev/null | af_redact | head -c 400)
      DISCORD_ERR="HTTP $HTTP_CODE — ${RED_BODY:-<no body>}"
    fi
  fi

  TELEGRAM_SENT="no"
  TELEGRAM_ERR=""
  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
    TELEGRAM_ERR="TELEGRAM_BOT_TOKEN not set in ~/.hermes/.env"
  elif [ -z "$TELEGRAM_CHAN" ]; then
    TELEGRAM_ERR="no Telegram channel for target=$SEND_TARGET"
  else
    : > "$RESP_TMP"
    HTTP_CODE=$(curl -sS \
      -o "$RESP_TMP" \
      -w "%{http_code}" \
      --max-time 15 \
      -X POST \
      "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${TELEGRAM_CHAN}" \
      --data-urlencode "text=${TELEGRAM_TEXT}" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
      TELEGRAM_SENT="yes"
    else
      RED_BODY=$(cat "$RESP_TMP" 2>/dev/null | af_redact | head -c 400)
      TELEGRAM_ERR="HTTP $HTTP_CODE — ${RED_BODY:-<no body>}"
    fi
  fi

  # Result output. Never print the channel id, token, or URL.
  echo "Discord sent: $DISCORD_SENT"
  echo "Telegram sent: $TELEGRAM_SENT"
  [ -n "$DISCORD_ERR" ]  && echo "Discord error: $DISCORD_ERR"
  [ -n "$TELEGRAM_ERR" ] && echo "Telegram error: $TELEGRAM_ERR"
  echo "target: $SEND_TARGET"
  if [ -n "${ALERT_FILE_ID_FOR_LOG:-}" ]; then :; fi  # noop placeholder

  if [ "$DISCORD_SENT" = "yes" ] || [ "$TELEGRAM_SENT" = "yes" ]; then
    exit 0
  fi
  exit 6
fi
