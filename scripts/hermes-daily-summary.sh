#!/usr/bin/env bash
# hermes-daily-summary.sh — one founder-facing daily digest of Hermes state.
#
# Walks ${MC_STATE_DIR:-/tmp/mc-system}/alerts/*.json and emits a single
# plain-text summary suitable for Discord + Telegram. By default this is
# dry-run; real sending requires BOTH:
#   --send (CLI flag, default: off)
#   HERMES_ALERT_ALLOW_SEND=1 (env, default: unset)
#
# CLI:
#   --dry-run                  Print the rendered summary; no send.
#                              Default if --send is not given.
#   --send                     Actually post to Discord + Telegram.
#                              Requires HERMES_ALERT_ALLOW_SEND=1.
#   --target prod|test         Where to send. Default: prod.
#                                prod → production channels (matches notify.sh).
#                                test → HERMES_TEST_DISCORD_CHANNEL +
#                                       HERMES_TEST_TELEGRAM_CHAT_ID env vars.
#   --show all|discord|telegram|json
#                              Choose which dry-run output to print.
#                              "all" prints the rendered text. "json" prints
#                              the raw structured summary (useful for tests).
#                              Default: all.
#   --no-redact                Skip the secret-redaction pass on the rendered
#                              text (NOT recommended).
#
# Examples:
#   ./scripts/hermes-daily-summary.sh
#   HERMES_ALERT_ALLOW_SEND=1 ./scripts/hermes-daily-summary.sh --send --target test
#
# Exit codes:
#   0  success / dry-run produced output
#   1  usage / argument error
#   3  malformed input (currently unused — bad files are skipped + counted)
#   4  send refused (--send without HERMES_ALERT_ALLOW_SEND=1)
#   5  no safe destination configured for --target test
#   6  both Discord and Telegram failed during real send

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$SCRIPT_DIR/lib"
# shellcheck source=lib/alert-format.sh
. "$LIB_DIR/alert-format.sh"

DRY_RUN=1
SEND=0
SEND_TARGET="prod"
SHOW="all"
NO_REDACT=0

usage() { sed -n '2,40p' "$0" | sed 's/^# \?//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)         DRY_RUN=1; SEND=0; shift ;;
    --send)            SEND=1; DRY_RUN=0; shift ;;
    --target)          SEND_TARGET="$2"; shift 2 ;;
    --show)            SHOW="$2"; shift 2 ;;
    --no-redact)       NO_REDACT=1; shift ;;
    -h|--help)         usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 1 ;;
  esac
done

case "$SEND_TARGET" in
  prod|test) ;;
  *) echo "error: --target must be 'prod' or 'test' (got: $SEND_TARGET)" >&2; exit 1 ;;
esac

case "$SHOW" in
  all|discord|telegram|json) ;;
  *) echo "error: --show must be all|discord|telegram|json (got: $SHOW)" >&2; exit 1 ;;
esac

NOW_HUMAN=$(date '+%Y-%m-%d %H:%M %Z')

# ── 1. Walk state files and produce structured JSON summary ──────────────────
SUMMARY_JSON=$(MC_STATE_DIR_OVERRIDE="${MC_STATE_DIR:-/tmp/mc-system}" python3 - <<'PYEOF'
import json, os, sys, time
from pathlib import Path

base = Path(os.environ["MC_STATE_DIR_OVERRIDE"]) / "alerts"
if not base.is_dir():
    print(json.dumps({"present": False, "warnings": 0, "total_incidents": 0,
                       "active": [], "resolved_recent": [], "repeated": [],
                       "cleanup_count": 0, "top": None, "by_status": {}}))
    sys.exit(0)

now = int(time.time())
DAY = 24 * 3600
SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
ACTIVE_STATUSES = {
    "failed", "degraded", "blocked",
    "disconnected", "rate_limited", "unknown",
}

incidents = []
warnings = 0
for path in sorted(base.glob("*.json")):
    if path.name.endswith(".tmp"):
        continue
    try:
        raw = json.loads(path.read_text())
    except Exception:
        warnings += 1
        continue

    if isinstance(raw, dict) and "alert" in raw and isinstance(raw["alert"], dict):
        alert = raw["alert"]
        last_fired = raw.get("last_fired_at")
    elif isinstance(raw, dict):
        alert = raw
        last_fired = None
    else:
        warnings += 1
        continue

    status = alert.get("status")
    if not isinstance(status, str):
        warnings += 1
        continue

    age_seconds = (
        now - int(last_fired)
        if isinstance(last_fired, (int, float))
        else None
    )
    incidents.append({
        "alert_id":        str(alert.get("alert_id") or path.stem),
        "system":          str(alert.get("system") or "Unknown"),
        "status":          status,
        "severity":        str(alert.get("severity") or "MEDIUM"),
        "exact_issue":     str(alert.get("exact_issue") or ""),
        "claude_prompt":   str(alert.get("claude_prompt") or ""),
        "recommended_fix": str(alert.get("recommended_fix") or ""),
        "evidence":        list(alert.get("evidence") or []),
        "timestamp":       alert.get("timestamp"),
        "first_seen":      alert.get("first_seen"),
        "resolved_at":     alert.get("resolved_at"),
        "failure_count":   alert.get("failure_count"),
        "last_fired_at":   last_fired,
        "age_seconds":     age_seconds,
        "file_mtime":      path.stat().st_mtime,
    })

active = [i for i in incidents if i["status"] in ACTIVE_STATUSES]
resolved_recent = [
    i for i in incidents
    if i["status"] == "resolved"
    and i["age_seconds"] is not None
    and i["age_seconds"] < DAY
]
repeated = [i for i in incidents if (i.get("failure_count") or 0) >= 3]

seven_days_ago = now - 7 * DAY
cleanup_count = sum(
    1 for i in incidents
    if i["status"] == "resolved" and i["file_mtime"] < seven_days_ago
)

top = None
if active:
    top = max(
        active,
        key=lambda i: (
            SEVERITY_RANK.get(i["severity"], 0),
            i["last_fired_at"] or 0,
        ),
    )

by_status = {}
for i in incidents:
    by_status.setdefault(i["status"], []).append(i["system"])

print(json.dumps({
    "present":          True,
    "warnings":         warnings,
    "total_incidents":  len(incidents),
    "active":           active,
    "resolved_recent":  resolved_recent,
    "repeated":         repeated,
    "cleanup_count":    cleanup_count,
    "top":              top,
    "by_status":        by_status,
}))
PYEOF
)

# ── 2. Render the digest as plain text ────────────────────────────────────────
SUMMARY_TEXT=$(SUMMARY_JSON_FOR_RENDER="$SUMMARY_JSON" NOW_HUMAN_FOR_RENDER="$NOW_HUMAN" python3 - <<'PYEOF'
import json, os
data = json.loads(os.environ["SUMMARY_JSON_FOR_RENDER"])
now = os.environ["NOW_HUMAN_FOR_RENDER"]

if not data.get("present"):
    print(f"🌅 Hermes daily summary — {now}\n")
    print("No Hermes alert state directory found yet. Once a watchdog fires an")
    print("alert, the daily summary will start to populate.")
    print("\n(generated by hermes-daily-summary.sh)")
    raise SystemExit(0)

active          = data["active"]
resolved_recent = data["resolved_recent"]
repeated        = data["repeated"]
top             = data.get("top")
warnings        = data.get("warnings", 0)
cleanup         = data.get("cleanup_count", 0)
total           = data.get("total_incidents", 0)

SEV_EMOJI = {"LOW": "🔵", "MEDIUM": "🟡", "HIGH": "🟠", "CRITICAL": "🔴"}
SEV_RANK  = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

lines = [f"🌅 Hermes daily summary — {now}", ""]

# Top-line stats
if active:
    crit = sum(1 for i in active if i["severity"] == "CRITICAL")
    high = sum(1 for i in active if i["severity"] == "HIGH")
    rest = len(active) - crit - high
    parts = []
    if crit: parts.append(f"{crit} CRITICAL")
    if high: parts.append(f"{high} HIGH")
    if rest > 0: parts.append(f"{rest} other")
    lines.append(f"⚠ {len(active)} active incident(s): {', '.join(parts)}.")
else:
    lines.append("✅ No active incidents.")

if total:
    extra = f", {warnings} unparseable" if warnings else ""
    lines.append(f"   ({total} alert state file(s) total{extra})")
lines.append("")

# Active problems
lines.append("🔴 Active problems")
if not active:
    lines.append("   (none)")
else:
    sorted_active = sorted(
        active,
        key=lambda x: (-SEV_RANK.get(x["severity"], 0), -(x.get("last_fired_at") or 0)),
    )
    for i in sorted_active:
        emoji = SEV_EMOJI.get(i["severity"], "⚪")
        ts = i.get("timestamp") or "—"
        lines.append(f"   {emoji} {i['severity']} — {i['system']} — {i['status']} (last seen {ts})")
        if i.get("exact_issue"):
            issue = i["exact_issue"]
            if len(issue) > 110:
                issue = issue[:107] + "…"
            lines.append(f"      {issue}")
lines.append("")

# Resolved in last 24h
lines.append("✅ Resolved in last 24h")
if not resolved_recent:
    lines.append("   (none)")
else:
    for i in resolved_recent:
        ts = i.get("resolved_at") or i.get("timestamp") or "—"
        lines.append(f"   • {i['system']} (resolved {ts})")
lines.append("")

# Repeated issues
lines.append("🔁 Repeated issues (3+ failures)")
if not repeated:
    lines.append("   (none)")
else:
    for i in repeated:
        fc = i.get("failure_count") or 0
        lines.append(f"   • {i['system']} — {fc} failures")
lines.append("")

# Cleanup
if cleanup > 0:
    lines.append("🧹 Recommended cleanup")
    lines.append(f"   {cleanup} resolved alert state file(s) older than 7 days.")
    lines.append("   Review then delete: ls -la $MC_STATE_DIR/alerts/ | sort -k 6,8")
    lines.append("")

# Best next repair prompt
if top:
    if top.get("claude_prompt"):
        lines.append("🔧 Best next repair prompt")
        lines.append(f"   System: {top['system']} ({top['severity']})")
        lines.append("   ---")
        for prompt_line in top["claude_prompt"].splitlines():
            lines.append(f"   {prompt_line}")
        lines.append("   ---")
    else:
        lines.append("🔧 Best next repair target")
        lines.append(f"   System: {top['system']} ({top['severity']})")
        if top.get("recommended_fix"):
            lines.append(f"   Recommended fix: {top['recommended_fix']}")
        else:
            lines.append("   Recommended fix: (not specified)")
    lines.append("")

if warnings > 0:
    lines.append(
        f"⚠ {warnings} alert state file(s) could not be parsed and were skipped."
    )
    lines.append("")

lines.append("(generated by hermes-daily-summary.sh)")
print("\n".join(lines))
PYEOF
)

# ── 3. Redact known secret patterns in the rendered text ─────────────────────
if [ "$NO_REDACT" = "0" ]; then
  SUMMARY_TEXT=$(printf '%s' "$SUMMARY_TEXT" | af_redact)
fi

# ── 4. Dry-run output ─────────────────────────────────────────────────────────
if [ "$DRY_RUN" = "1" ]; then
  case "$SHOW" in
    discord)
      DPAY=$(SUMMARY_TEXT_FOR_DISCORD="$SUMMARY_TEXT" python3 -c '
import json, os
content = os.environ["SUMMARY_TEXT_FOR_DISCORD"][:1990]
print(json.dumps({"content": content}, ensure_ascii=False))')
      printf '%s\n' "$DPAY"
      ;;
    telegram)
      printf '%s\n' "${SUMMARY_TEXT:0:4000}"
      ;;
    json)
      printf '%s\n' "$SUMMARY_JSON"
      ;;
    all|*)
      printf '%s\n' "$SUMMARY_TEXT"
      ;;
  esac
  exit 0
fi

# ── 5. Real send — guarded ────────────────────────────────────────────────────
if [ "$SEND" = "1" ]; then
  if [ "${HERMES_ALERT_ALLOW_SEND:-0}" != "1" ]; then
    echo "error: --send requires HERMES_ALERT_ALLOW_SEND=1 (safety guard)" >&2
    exit 4
  fi

  set +x
  set -a
  if [ -f "$HOME/.hermes/.env" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.hermes/.env" >/dev/null 2>&1 || true
  fi
  set +a

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

  RESP_TMP="$(mktemp -t hermes-daily-resp.XXXXXX)"
  trap 'rm -f "$RESP_TMP"' EXIT

  DISCORD_SENT="no"
  DISCORD_ERR=""
  if [ -z "${DISCORD_BOT_TOKEN:-}" ]; then
    DISCORD_ERR="DISCORD_BOT_TOKEN not set in ~/.hermes/.env"
  elif [ -z "$DISCORD_CHAN" ]; then
    DISCORD_ERR="no Discord channel for target=$SEND_TARGET"
  else
    DISCORD_PAYLOAD=$(SUMMARY_TEXT_FOR_DISCORD="$SUMMARY_TEXT" python3 -c '
import json, os
content = os.environ["SUMMARY_TEXT_FOR_DISCORD"][:1990]
print(json.dumps({"content": content}, ensure_ascii=False))')
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
    TG_TEXT="${SUMMARY_TEXT:0:4000}"
    : > "$RESP_TMP"
    HTTP_CODE=$(curl -sS \
      -o "$RESP_TMP" \
      -w "%{http_code}" \
      --max-time 15 \
      -X POST \
      "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${TELEGRAM_CHAN}" \
      --data-urlencode "text=${TG_TEXT}" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
      TELEGRAM_SENT="yes"
    else
      RED_BODY=$(cat "$RESP_TMP" 2>/dev/null | af_redact | head -c 400)
      TELEGRAM_ERR="HTTP $HTTP_CODE — ${RED_BODY:-<no body>}"
    fi
  fi

  echo "Discord sent: $DISCORD_SENT"
  echo "Telegram sent: $TELEGRAM_SENT"
  [ -n "$DISCORD_ERR" ]  && echo "Discord error: $DISCORD_ERR"
  [ -n "$TELEGRAM_ERR" ] && echo "Telegram error: $TELEGRAM_ERR"
  echo "target: $SEND_TARGET"

  if [ "$DISCORD_SENT" = "yes" ] || [ "$TELEGRAM_SENT" = "yes" ]; then
    exit 0
  fi
  exit 6
fi
