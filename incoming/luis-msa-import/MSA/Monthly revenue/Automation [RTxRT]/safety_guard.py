"""
Lightweight safety guard for the RTxRT bots.

The bots in this folder click, type, and send real DMs/reposts on x.com
through AdsPower. Before any of them touch the live browser, they call
`require_live_or_exit()` from this module.

By default DRY_RUN=true and ALLOW_LIVE_EXTERNAL_ACTIONS=false, so any bot
launched without an explicit live opt-in will refuse to run.

Live mode requires THREE env flags set together:

    DRY_RUN=false
    ALLOW_LIVE_EXTERNAL_ACTIONS=true
    CONFIRM_LIVE_TEST=YES

Without CONFIRM_LIVE_TEST=YES the guard refuses even if the first two are
set — this is a manual third gate so accidental flag combinations cannot
go live.

Additional env vars honoured (advisory, not enforced at entry):
    TEST_MODE=true          → verbose logging
    MAX_TEST_ACTIONS=<int>  → hard cap on real actions per run (default 0 = unlimited)

Bots that want MAX_TEST_ACTIONS enforced must call
`record_action_or_exit("DM to @handle")` immediately before each real
external action.
"""
import os
import sys

# Windows consoles default to cp1252 and crash on the unicode banner chars
# (e.g. 🧪 ⛔ ⚡ ─). Reconfigure both streams to UTF-8 at import. No-op on
# systems that already use UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def _envbool(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _envint(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def is_dry_run() -> bool:
    """True unless DRY_RUN is explicitly turned off."""
    return _envbool("DRY_RUN", "true")


def live_allowed() -> bool:
    """True only if the operator explicitly opted into live external actions."""
    return _envbool("ALLOW_LIVE_EXTERNAL_ACTIONS", "false")


def is_test_mode() -> bool:
    """True if TEST_MODE is on. Used for verbose logging only."""
    return _envbool("TEST_MODE", "false")


def max_test_actions() -> int:
    """Cap on real external actions per run. 0 = unlimited (legacy behaviour)."""
    return _envint("MAX_TEST_ACTIONS", 0)


def confirm_live_test_set() -> bool:
    """True only if CONFIRM_LIVE_TEST is set to the literal string 'YES'."""
    return os.environ.get("CONFIRM_LIVE_TEST", "").strip() == "YES"


def _print_flag_table(stream) -> None:
    """Print a compact view of all current safety-related env vars."""
    print("     Current safety flags:", file=stream)
    print(f"       DRY_RUN={os.environ.get('DRY_RUN', '(unset, default=true)')}", file=stream)
    print(f"       ALLOW_LIVE_EXTERNAL_ACTIONS={os.environ.get('ALLOW_LIVE_EXTERNAL_ACTIONS', '(unset, default=false)')}", file=stream)
    print(f"       CONFIRM_LIVE_TEST={os.environ.get('CONFIRM_LIVE_TEST', '(unset)')}", file=stream)
    print(f"       TEST_MODE={os.environ.get('TEST_MODE', '(unset, default=false)')}", file=stream)
    print(f"       MAX_TEST_ACTIONS={os.environ.get('MAX_TEST_ACTIONS', '(unset, default=0/unlimited)')}", file=stream)


def require_live_or_exit(bot_name: str = "this bot") -> None:
    """
    Gate the bot at startup. Three possible outcomes:

    1. DRY_RUN=true  → walk-through mode. Bot starts; every action function
       must check is_dry_run() and log+skip the real call.
    2. DRY_RUN=false AND ALLOW_LIVE_EXTERNAL_ACTIONS=true AND
       CONFIRM_LIVE_TEST=YES → live mode. Real actions happen, capped by
       MAX_TEST_ACTIONS if the bot calls record_action_or_exit().
    3. Anything else (e.g. DRY_RUN=false alone) → refuse + exit 2.
    """
    dry = is_dry_run()
    allowed = live_allowed()
    confirmed = confirm_live_test_set()

    if dry:
        print(f"  🧪 {bot_name}: DRY-RUN walk-through mode.")
        _print_flag_table(sys.stdout)
        print("     No real DMs / reposts / scrapes.")
        print("     Every action site MUST call safety_guard.is_dry_run() and skip.")
        print("     If you see a real x.com click below this line, a code path is missing the check — STOP.")
        return

    if allowed and confirmed:
        print(f"  ⚡ {bot_name}: LIVE mode enabled.")
        _print_flag_table(sys.stdout)
        cap = max_test_actions()
        if cap > 0:
            print(f"     Hard cap: {cap} action(s) this run (MAX_TEST_ACTIONS).")
            print(f"     Note: cap is only enforced if the bot calls record_action_or_exit().")
        else:
            print(f"     WARNING: MAX_TEST_ACTIONS=0 (unlimited). This is a real mass run.")
        return

    print("─" * 70, file=sys.stderr)
    print(f"  ⛔ {bot_name}: refusing to run.", file=sys.stderr)
    _print_flag_table(sys.stderr)
    if allowed and not confirmed:
        print("     Missing the third gate: CONFIRM_LIVE_TEST=YES", file=sys.stderr)
        print("     This is intentional — live runs need an explicit confirm.", file=sys.stderr)
    else:
        print("     For LIVE mode set ALL THREE:", file=sys.stderr)
        print("       set DRY_RUN=false", file=sys.stderr)
        print("       set ALLOW_LIVE_EXTERNAL_ACTIONS=true", file=sys.stderr)
        print("       set CONFIRM_LIVE_TEST=YES", file=sys.stderr)
        print("     For DRY-RUN walk-through just unset DRY_RUN or set it to true.", file=sys.stderr)
    print("─" * 70, file=sys.stderr)
    sys.exit(2)


# ── Per-action helpers (bots opt in by calling these) ──────────────────

_action_count = 0


def record_action_or_exit(label: str) -> None:
    """
    Call this immediately BEFORE each real external action (DM, repost, scrape).
    Increments an internal counter. Once MAX_TEST_ACTIONS is reached, exits 0
    with a clear message. Has no effect when MAX_TEST_ACTIONS=0 (unlimited).
    """
    global _action_count
    cap = max_test_actions()
    _action_count += 1
    if is_test_mode():
        print(f"  ▶ action #{_action_count}: {label}")
    if cap > 0 and _action_count > cap:
        print(f"  🛑 MAX_TEST_ACTIONS={cap} reached — stopping before {label}.")
        sys.exit(0)


def dry_run_log(label: str) -> None:
    """
    Call this in place of a real action when in dry-run mode. Pure logging.
    Bots can use the pattern:

        if safety_guard.is_dry_run():
            safety_guard.dry_run_log(f"would DM {handle}")
        else:
            safety_guard.record_action_or_exit(f"DM {handle}")
            send_dm(handle, ...)
    """
    print(f"  [DRY-RUN] {label}")
