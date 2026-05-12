"""
Smoke test for the RTxRT automation.

What this does:
  1. Loads MSA/.env (if present) without depending on python-dotenv.
  2. Reports which API keys are configured (yes/no — never prints values).
  3. Reports current safety-flag state.
  4. Imports safety_guard and verifies the guard refuses by default.
  5. Tries to import each bot module without running it (catches missing deps).
  6. Reports a clear PASS / FAIL summary.

What this DOES NOT do:
  - Open AdsPower
  - Open Playwright
  - Log in anywhere
  - Send DMs / reposts / scrape
  - Call Anthropic, Notion, or X
  - Touch OnlyFans / OnlyMonster

Run from the [RTxRT] folder:
    python smoke_test.py

Exit codes:
    0 = all checks passed (or only soft warnings)
    1 = at least one critical check failed
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

# Windows consoles default to cp1252 and crash on the unicode banner chars.
# Reconfigure stdout/stderr to UTF-8. Safe no-op on Mac/Linux.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


HERE = Path(__file__).resolve().parent
MSA_ROOT = HERE.parent.parent  # …/MSA
ENV_PATH = MSA_ROOT / ".env"
ENV_EXAMPLE_PATH = MSA_ROOT / ".env.example"

REQUIRED_KEYS = ["ADSPOWER_API_KEY", "ANTHROPIC_API_KEY", "NOTION_API_KEY"]
SAFETY_FLAGS = [
    "DRY_RUN",
    "ALLOW_LIVE_EXTERNAL_ACTIONS",
    "TEST_MODE",
    "MAX_TEST_ACTIONS",
    "CONFIRM_LIVE_TEST",
]
BOT_MODULES = ["safety_guard", "blast_bot", "dm_bot", "repost_bot", "builder_bot", "scan_test"]


# Track results
results: list[tuple[str, str, str]] = []  # (status, name, detail)


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    icon = {"PASS": "✓", "WARN": "!", "FAIL": "✗", "INFO": "·"}.get(status, "?")
    line = f"  {icon} [{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)


def load_dotenv_lite(path: Path) -> dict[str, str]:
    """Minimal .env parser, stdlib only. Does NOT mutate os.environ."""
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        loaded[key.strip()] = value.strip()
    return loaded


def section(title: str) -> None:
    print(f"\n── {title} " + "─" * (60 - len(title)))


def main() -> int:
    print("═" * 64)
    print("  RTxRT smoke test — no live actions, no installs")
    print("═" * 64)
    print(f"  Script:  {HERE}")
    print(f"  MSA root: {MSA_ROOT}")

    # 1. .env presence
    section("Environment file")
    if ENV_PATH.is_file():
        record("PASS", ".env exists", str(ENV_PATH.name))
        env_from_file = load_dotenv_lite(ENV_PATH)
    elif ENV_EXAMPLE_PATH.is_file():
        record("WARN", ".env missing", f"copy {ENV_EXAMPLE_PATH.name} → .env and fill in keys")
        env_from_file = {}
    else:
        record("FAIL", ".env and .env.example both missing", "import looks broken")
        env_from_file = {}

    # 2. API keys (only check presence, never print values)
    section("API keys (presence only — values never printed)")
    for key in REQUIRED_KEYS:
        in_env = bool(os.environ.get(key, "").strip())
        in_file = bool(env_from_file.get(key, "").strip())
        if in_env:
            record("PASS", key, "set in process env")
        elif in_file:
            record("INFO", key, "present in .env (not loaded into this process)")
        else:
            record("WARN", key, "not set anywhere — required for that feature")

    # 3. Safety flags
    section("Safety flags")
    for flag in SAFETY_FLAGS:
        # Prefer .env value if process env is empty
        value = os.environ.get(flag, env_from_file.get(flag, ""))
        if value == "":
            record("INFO", flag, "(unset → safe default applies)")
        else:
            record("INFO", flag, value)

    # 4. Guard behavior in each scenario
    section("safety_guard scenarios (each in a clean subprocess)")

    def _run_guard(label: str, env_overrides: dict[str, str]):
        env = os.environ.copy()
        # Strip everything safety-related, then apply this scenario's overrides
        for key in ("DRY_RUN", "ALLOW_LIVE_EXTERNAL_ACTIONS", "CONFIRM_LIVE_TEST",
                    "TEST_MODE", "MAX_TEST_ACTIONS"):
            env.pop(key, None)
        env.update(env_overrides)
        script = (
            "import sys; "
            "[s.reconfigure(encoding='utf-8') for s in (sys.stdout, sys.stderr) if hasattr(s, 'reconfigure')]; "
            "sys.path.insert(0, r'" + str(HERE) + "'); "
            "from safety_guard import require_live_or_exit; "
            "require_live_or_exit('smoke_test')"
        )
        return subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=15, env=env,
        )

    try:
        # Scenario A: dry-run default → walk-through allowed (exit 0)
        proc = _run_guard("default", {})
        ok = proc.returncode == 0 and "DRY-RUN walk-through" in proc.stdout
        record("PASS" if ok else "FAIL", "default env → walk-through allowed",
               f"exit={proc.returncode}")

        # Scenario B: half-live (DRY_RUN=false, others unset) → refuse
        proc = _run_guard("half-live", {"DRY_RUN": "false"})
        ok = proc.returncode == 2 and "refusing to run" in proc.stderr
        record("PASS" if ok else "FAIL", "DRY_RUN=false alone → refuse",
               f"exit={proc.returncode}")

        # Scenario C: two-of-three (missing CONFIRM_LIVE_TEST) → refuse
        proc = _run_guard("two-of-three", {
            "DRY_RUN": "false", "ALLOW_LIVE_EXTERNAL_ACTIONS": "true",
        })
        ok = proc.returncode == 2 and "Missing the third gate" in proc.stderr
        record("PASS" if ok else "FAIL", "live without CONFIRM_LIVE_TEST → refuse",
               f"exit={proc.returncode}")

        # Scenario D: all three gates set → live allowed (exit 0)
        proc = _run_guard("all-three", {
            "DRY_RUN": "false", "ALLOW_LIVE_EXTERNAL_ACTIONS": "true",
            "CONFIRM_LIVE_TEST": "YES", "MAX_TEST_ACTIONS": "1",
        })
        ok = proc.returncode == 0 and "LIVE mode enabled" in proc.stdout
        record("PASS" if ok else "FAIL", "all three gates set → live allowed",
               f"exit={proc.returncode}")
    except Exception as exc:
        record("FAIL", "safety_guard subprocess", f"could not launch: {exc}")

    # 5. Import each module without running __main__
    section("Bot module imports (no __main__ executed)")
    sys.path.insert(0, str(HERE))
    for mod in BOT_MODULES:
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError as exc:
            # Most common: playwright / requests not installed yet.
            record("WARN", mod, f"missing dep: {exc.name}")
        except Exception as exc:
            record("FAIL", mod, f"{type(exc).__name__}: {exc}")
        else:
            record("PASS", mod, "imported cleanly")

    # 6. Summary
    section("Summary")
    passes = sum(1 for s, _, _ in results if s == "PASS")
    warns = sum(1 for s, _, _ in results if s == "WARN")
    fails = sum(1 for s, _, _ in results if s == "FAIL")
    print(f"  {passes} pass · {warns} warn · {fails} fail")
    print()
    if fails:
        print("  ✗ Smoke test FAILED. Fix the FAIL items above before going further.")
        return 1
    if warns:
        print("  ! Smoke test passed with warnings.")
        print("    Warnings usually mean 'not configured yet' — not 'broken'.")
        return 0
    print("  ✓ Smoke test PASSED clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
