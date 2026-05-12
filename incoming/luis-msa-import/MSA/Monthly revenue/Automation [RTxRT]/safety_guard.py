"""
Lightweight safety guard for the RTxRT bots.

The bots in this folder click, type, and send real DMs/reposts on x.com
through AdsPower. Before any of them touch the live browser, they call
`require_live_or_exit()` from this module.

By default DRY_RUN=true and ALLOW_LIVE_EXTERNAL_ACTIONS=false, so any bot
launched without an explicit live opt-in will refuse to run. This is meant
as belt-and-suspenders, not a full dry-run mode — go live by setting BOTH:

    export DRY_RUN=false
    export ALLOW_LIVE_EXTERNAL_ACTIONS=true

Then re-run the bot.
"""
import os
import sys


def _envbool(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def is_dry_run() -> bool:
    """True unless DRY_RUN is explicitly turned off."""
    return _envbool("DRY_RUN", "true")


def live_allowed() -> bool:
    """True only if the operator explicitly opted into live external actions."""
    return _envbool("ALLOW_LIVE_EXTERNAL_ACTIONS", "false")


def require_live_or_exit(bot_name: str = "this bot") -> None:
    """
    Refuse to run live unless BOTH env flags are set correctly.
    Prints a clear message and exits with code 2 otherwise.
    """
    dry = is_dry_run()
    allowed = live_allowed()
    if (not dry) and allowed:
        print(f"  ⚡ {bot_name}: LIVE mode (DRY_RUN=false, ALLOW_LIVE_EXTERNAL_ACTIONS=true).")
        return
    print("─" * 70, file=sys.stderr)
    print(f"  ⛔ {bot_name}: refusing to run.", file=sys.stderr)
    print(f"     DRY_RUN={os.environ.get('DRY_RUN', '(unset, default=true)')}", file=sys.stderr)
    print(f"     ALLOW_LIVE_EXTERNAL_ACTIONS={os.environ.get('ALLOW_LIVE_EXTERNAL_ACTIONS', '(unset, default=false)')}", file=sys.stderr)
    print("     To run live, set BOTH:", file=sys.stderr)
    print("       export DRY_RUN=false", file=sys.stderr)
    print("       export ALLOW_LIVE_EXTERNAL_ACTIONS=true", file=sys.stderr)
    print("─" * 70, file=sys.stderr)
    sys.exit(2)
