#!/usr/bin/env bash
# alert-format.sh — formatting library for Hermes structured alerts.
#
# This file is a SOURCE-ONLY library. Do not execute directly.
# All functions are pure: no network, no writes outside $MC_STATE_DIR.
#
# Public API:
#   af_severity_emoji LEVEL              -> "🔵|🟡|🟠|🔴|⚪"
#   af_severity_color LEVEL              -> Discord embed color (decimal)
#   af_severity_valid LEVEL              -> exit 0 if valid
#   af_status_valid STATUS               -> exit 0 if valid
#   af_redact                            -> stdin -> stdout, redacts secret patterns
#   af_dedupe_key SYSTEM STATUS ISSUE    -> "<slug>-<status>-<6char>"
#   af_validate_json FILE                -> exit 0 if file is valid alert JSON
#   af_format_discord FILE               -> Discord {"embeds":[…]} on stdout
#   af_format_telegram FILE              -> plain text on stdout
#   af_format_prompt FILE                -> repair prompt body on stdout
#   af_format_resolved FILE              -> resolved-alert text on stdout
#   af_should_fire FILE                  -> exit 0=fire, 2=suppress (dedupe)
#
# IMPORTANT: helpers take a file path argument (not stdin) because a here-doc
# `<<HEREDOC` used to inline python rebinds the function's stdin to the
# here-doc body, hiding any stream the caller wanted to pipe in. Passing the
# path explicitly avoids that conflict.
#
# Canonical alert schema (JSON):
#   {
#     "system":          "OpenClaw Gateway",
#     "status":          "failed",
#     "severity":        "CRITICAL",
#     "exact_issue":     "...",
#     "evidence":        ["...", "..."],
#     "likely_cause":    "...",
#     "business_impact": "...",
#     "recommended_fix": "...",
#     "claude_prompt":   "...",
#     "timestamp":       "2026-04-28T17:22:00Z",
#     "alert_id":        "openclaw-gateway-failed-7a3b1c"
#   }

# ── Severity → presentation ───────────────────────────────────────────────────
af_severity_emoji() {
  case "$1" in
    LOW)      printf '🔵' ;;
    MEDIUM)   printf '🟡' ;;
    HIGH)     printf '🟠' ;;
    CRITICAL) printf '🔴' ;;
    *)        printf '⚪' ;;
  esac
}

af_severity_color() {
  case "$1" in
    LOW)      echo "3447003"  ;;  # blue
    MEDIUM)   echo "16776960" ;;  # yellow
    HIGH)     echo "15105570" ;;  # orange
    CRITICAL) echo "15158332" ;;  # red
    *)        echo "9807270"  ;;  # gray
  esac
}

af_severity_valid() {
  case "$1" in LOW|MEDIUM|HIGH|CRITICAL) return 0 ;; *) return 1 ;; esac
}

af_status_valid() {
  case "$1" in
    healthy|degraded|failed|blocked|rate_limited|disconnected|unknown|resolved) return 0 ;;
    *) return 1 ;;
  esac
}

# ── Redaction ─────────────────────────────────────────────────────────────────
# Reads stdin, prints redacted text to stdout. We capture stdin into a shell
# variable first to free up stdin for the python here-doc.
af_redact() {
  local input
  input="$(cat)"
  ALERT_TEXT="$input" python3 - <<'PYEOF'
import re, os, sys
src = os.environ.get('ALERT_TEXT','')
patterns = [
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
  (r'(?i)\b(token|secret|password|api[_-]?key|auth[_-]?token)\b\s*[:=]\s*"?[^\s"\',]+',
                                                             r'\1=[REDACTED]'),
]
for pat, repl in patterns:
  src = re.sub(pat, repl, src)
sys.stdout.write(src)
PYEOF
}

# ── Dedupe key ────────────────────────────────────────────────────────────────
af_dedupe_key() {
  AF_SYS="$1" AF_STATUS="$2" AF_ISSUE="$3" python3 - <<'PYEOF'
import re, hashlib, os
sys_    = os.environ['AF_SYS']
status  = os.environ['AF_STATUS']
issue   = os.environ['AF_ISSUE']
slug    = re.sub(r'[^a-z0-9]+', '-', sys_.lower()).strip('-')[:32] or 'unknown'
h       = hashlib.sha1((sys_ + '|' + status + '|' + issue).encode()).hexdigest()[:6]
print(f"{slug}-{status}-{h}")
PYEOF
}

# ── Validation ────────────────────────────────────────────────────────────────
af_validate_json() {
  ALERT_FILE="$1" python3 - <<'PYEOF'
import json, os, sys
required = ['system','status','severity','exact_issue','evidence',
            'likely_cause','business_impact','recommended_fix','claude_prompt']
try:
  with open(os.environ['ALERT_FILE']) as f:
    d = json.load(f)
except Exception as e:
  print(f"INVALID_JSON: {e}", file=sys.stderr); sys.exit(2)
missing = [k for k in required if k not in d or d[k] in (None, '', [])]
if missing:
  print(f"MISSING_FIELDS: {','.join(missing)}", file=sys.stderr); sys.exit(3)
if d['severity'] not in ('LOW','MEDIUM','HIGH','CRITICAL'):
  print(f"BAD_SEVERITY: {d['severity']}", file=sys.stderr); sys.exit(4)
if d['status'] not in ('healthy','degraded','failed','blocked',
                        'rate_limited','disconnected','unknown','resolved'):
  print(f"BAD_STATUS: {d['status']}", file=sys.stderr); sys.exit(5)
sys.exit(0)
PYEOF
}

# ── Discord embed formatter ───────────────────────────────────────────────────
af_format_discord() {
  ALERT_FILE="$1" python3 - <<'PYEOF'
import json, os, sys
def trunc(s, n):
  s = '' if s is None else str(s)
  return s if len(s) <= n else s[:n-1] + '…'

COLORS = {'LOW':3447003,'MEDIUM':16776960,'HIGH':15105570,'CRITICAL':15158332}
EMOJI  = {'LOW':'🔵','MEDIUM':'🟡','HIGH':'🟠','CRITICAL':'🔴'}

with open(os.environ['ALERT_FILE']) as f:
  d = json.load(f)

sev = d['severity']
title = f"{EMOJI.get(sev,'⚪')} [{sev}] {d['system']} — {d['status']}"

ev = d['evidence']
if isinstance(ev, list):
  ev_txt = '\n'.join(f"• {e}" for e in ev)
else:
  ev_txt = str(ev)

prompt_block = f"```\n{trunc(d['claude_prompt'], 980)}\n```"

embed = {
  "title": trunc(title, 256),
  "description": trunc(d['exact_issue'], 2048),
  "color": COLORS.get(sev, 9807270),
  "fields": [
    {"name":"Status","value":trunc(d['status'],1024),"inline":True},
    {"name":"Severity","value":trunc(sev,1024),"inline":True},
    {"name":"Evidence","value":trunc(ev_txt,1024)},
    {"name":"Likely cause","value":trunc(d['likely_cause'],1024)},
    {"name":"Business impact","value":trunc(d['business_impact'],1024)},
    {"name":"Recommended fix","value":trunc(d['recommended_fix'],1024)},
    {"name":"Repair prompt (copy/paste to Claude)","value":trunc(prompt_block,1024)},
  ],
}
if d.get('timestamp'):
  embed['timestamp'] = d['timestamp']
footer_bits = []
if d.get('alert_id'):   footer_bits.append(f"id={d['alert_id']}")
if d.get('first_seen'): footer_bits.append(f"first_seen={d['first_seen']}")
if footer_bits:
  embed['footer'] = {"text": ' • '.join(footer_bits)}

print(json.dumps({"embeds":[embed]}, ensure_ascii=False, indent=2))
PYEOF
}

# ── Telegram plain-text formatter ─────────────────────────────────────────────
af_format_telegram() {
  ALERT_FILE="$1" python3 - <<'PYEOF'
import json, os, sys
EMOJI = {'LOW':'🔵','MEDIUM':'🟡','HIGH':'🟠','CRITICAL':'🔴'}

with open(os.environ['ALERT_FILE']) as f:
  d = json.load(f)

sev = d['severity']
ev = d['evidence']
if isinstance(ev, list):
  ev_block = '\n'.join(f"- {x}" for x in ev) if ev else '(none)'
else:
  ev_block = str(ev) or '(none)'

parts = [
  f"{EMOJI.get(sev,'⚪')} {sev} — {d['system']} ({d['status']})",
  "",
  "EXACT ISSUE:",
  d['exact_issue'],
  "",
  "EVIDENCE:",
  ev_block,
  "",
  "LIKELY CAUSE:",
  d['likely_cause'],
  "",
  "BUSINESS IMPACT:",
  d['business_impact'],
  "",
  "RECOMMENDED FIX:",
  d['recommended_fix'],
  "",
  "COPY/PASTE REPAIR PROMPT:",
  "---",
  d['claude_prompt'],
  "---",
]
meta = []
if d.get('alert_id'):   meta.append(f"id={d['alert_id']}")
if d.get('timestamp'):  meta.append(f"ts={d['timestamp']}")
if meta:
  parts += ["", " • ".join(meta)]

text = '\n'.join(parts)
if len(text) > 4000:
  text = text[:3990] + "\n…(truncated)"
sys.stdout.write(text)
PYEOF
}

# ── Repair-prompt body only ───────────────────────────────────────────────────
af_format_prompt() {
  ALERT_FILE="$1" python3 - <<'PYEOF'
import json, os, sys
with open(os.environ['ALERT_FILE']) as f:
  d = json.load(f)
sys.stdout.write(d['claude_prompt'])
PYEOF
}

# ── Resolved-alert formatter ──────────────────────────────────────────────────
# Schema for resolved alerts:
#   { "system":"...", "what_recovered":"...", "last_failed_state":"...",
#     "first_seen":"...", "resolved_at":"...", "failure_count": N }
af_format_resolved() {
  ALERT_FILE="$1" python3 - <<'PYEOF'
import json, os, sys
with open(os.environ['ALERT_FILE']) as f:
  d = json.load(f)
parts = [f"✅ Resolved: {d.get('system','(unknown)')} is healthy again"]
if d.get('what_recovered'):    parts.append(f"Recovered: {d['what_recovered']}")
if d.get('last_failed_state'): parts.append(f"Was: {d['last_failed_state']}")
if d.get('first_seen'):        parts.append(f"First seen: {d['first_seen']}")
if d.get('resolved_at'):       parts.append(f"Resolved at: {d['resolved_at']}")
if d.get('failure_count') is not None:
                               parts.append(f"Failures during incident: {d['failure_count']}")
sys.stdout.write('\n'.join(parts))
PYEOF
}

# ── Dedupe / should-fire decision ─────────────────────────────────────────────
# Reads canonical alert JSON from $1 (file path). Compares to last-fired alert
# for the same dedupe_key in $MC_STATE_DIR/alerts/. Returns:
#   0  -> novel alert; caller should send. Updates state file.
#   2  -> duplicate within window; caller should suppress.
#
# "Novel" means any of:
#   - severity increased
#   - affected system changed (different dedupe_key implies novel by definition)
#   - exact_issue text changed
#   - status moved to "resolved"
#   - claude_prompt changed
#   - more than $HERMES_DEDUPE_WINDOW_SEC since last fire (default 1800s = 30m)
af_should_fire() {
  local file="$1"
  local state_dir="${MC_STATE_DIR:-/tmp/mc-system}/alerts"
  mkdir -p "$state_dir"
  ALERT_FILE="$file" \
  HERMES_STATE_DIR="$state_dir" \
  HERMES_DEDUPE_WINDOW_SEC="${HERMES_DEDUPE_WINDOW_SEC:-1800}" \
  python3 - <<'PYEOF'
import json, os, sys, time

with open(os.environ['ALERT_FILE']) as f:
  cur = json.load(f)

state_dir = os.environ['HERMES_STATE_DIR']
window    = int(os.environ['HERMES_DEDUPE_WINDOW_SEC'])
key       = cur.get('alert_id') or 'unknown'
state_file = os.path.join(state_dir, key + '.json')

SEV_RANK = {'LOW':1, 'MEDIUM':2, 'HIGH':3, 'CRITICAL':4}

now = int(time.time())
prev = None
if os.path.exists(state_file):
  try:
    with open(state_file) as f:
      prev = json.load(f)
  except Exception:
    prev = None

def write_state():
  cur_state = {"last_fired_at": now, "alert": cur}
  tmp = state_file + ".tmp"
  with open(tmp, 'w') as f:
    json.dump(cur_state, f)
  os.replace(tmp, state_file)

def fire(reason):
  write_state()
  print(f"FIRE:{reason}", file=sys.stderr)
  sys.exit(0)

def suppress(reason):
  print(f"SUPPRESS:{reason}", file=sys.stderr)
  sys.exit(2)

if prev is None:
  fire("first_seen")

prev_alert = prev.get('alert', {})
prev_at    = prev.get('last_fired_at', 0)

if cur.get('status') == 'resolved' and prev_alert.get('status') != 'resolved':
  fire("status_changed_to_resolved")

if SEV_RANK.get(cur['severity'],0) > SEV_RANK.get(prev_alert.get('severity',''),0):
  fire("severity_increased")

if cur.get('exact_issue') != prev_alert.get('exact_issue'):
  fire("exact_issue_changed")

if cur.get('claude_prompt') != prev_alert.get('claude_prompt'):
  fire("repair_prompt_changed")

if (now - prev_at) > window:
  fire("window_elapsed")

suppress("duplicate_within_window")
PYEOF
}
