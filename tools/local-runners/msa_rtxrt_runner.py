"""Local Claw-computer runner for the MSA RT/X Automation Bot.

Architecture (Mission Control split):
  - Mission Control web UI is the *control panel*. It enqueues jobs.
  - This runner lives on Zach's Claw computer. It polls the queue,
    runs the matching local Python command inside Luis's imported
    MSA RT/X folder, captures output, and reports status back.
  - The runner is started manually on the Claw computer. Mission
    Control never starts it remotely.

Safety contract (hard-coded in this file — must not be bypassed):
  - Default mode is dry-run. ``ALLOW_LIVE_EXTERNAL_ACTIONS`` must be
    set to ``true`` *in the runner's local environment* to even
    consider a live-one job.
  - Live-one jobs require ALL of:
      * ``ALLOW_LIVE_EXTERNAL_ACTIONS=true``
      * ``CONFIRM_LIVE_TEST=YES``
      * ``MAX_TEST_ACTIONS=1``
  - Mass live runs are blocked outright. There is no "live many" job
    kind in this runner and the dispatch table refuses to construct
    one even if the queue asks for it.
  - The runner never reads secrets from Mission Control. All env
    vars (AdsPower keys, X session cookies, OnlyFans tokens, etc.)
    live in the Claw computer's local environment and never reach
    the frontend.

This module is import-safe (no side effects at import time) so the
tests next door can call into the safety-gate function directly.

The actual Luis bot code is on the ``coo/import-luis-msa`` branch at
``incoming/luis-msa-import/MSA/Monthly revenue/Automation [RTxRT]``.
This runner does not copy that code anywhere. It expects the Claw
operator to have that branch checked out locally and pointed at via
``MSA_RTXRT_BOT_DIR``.

This PR ships the runner wrapper and the local-command contract.
The backend job-queue endpoint that lets the runner actually pull
work is a deliberate follow-up — see the README in this folder.
"""

from __future__ import annotations

import os
import shlex
import subprocess  # noqa: S404 - intentional; called via list args, no shell.
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# ── Job-kind contract ───────────────────────────────────────────────────────

DRY_RUN_KINDS: Final[tuple[str, ...]] = (
    "smoke",
    "dry_run_blast",
    "dry_run_dm",
    "dry_run_repost",
    "dry_run_builder",
    "dry_run_scan",
)
LIVE_ONE_KINDS: Final[tuple[str, ...]] = (
    "live_one_blast",
    "live_one_dm",
    "live_one_repost",
    "live_one_builder",
    "live_one_scan",
)
ALL_KINDS: Final[tuple[str, ...]] = DRY_RUN_KINDS + LIVE_ONE_KINDS

# Map job kind -> (script filename, default flag args). Live-one jobs add
# the live-mode flags only after passing the safety gate.
_DRY_RUN_COMMANDS: Final[dict[str, tuple[str, list[str]]]] = {
    "smoke": ("safety_guard.py", ["--smoke"]),
    "dry_run_blast": ("blast_bot.py", ["--dry-run"]),
    "dry_run_dm": ("dm_bot.py", ["--dry-run"]),
    "dry_run_repost": ("repost_bot.py", ["--dry-run"]),
    "dry_run_builder": ("builder_bot.py", ["--dry-run"]),
    "dry_run_scan": ("scan_test.py", ["--dry-run"]),
}

_LIVE_ONE_COMMANDS: Final[dict[str, tuple[str, list[str]]]] = {
    "live_one_blast": ("blast_bot.py", ["--live-one", "--max-actions=1"]),
    "live_one_dm": ("dm_bot.py", ["--live-one", "--max-actions=1"]),
    "live_one_repost": ("repost_bot.py", ["--live-one", "--max-actions=1"]),
    "live_one_builder": ("builder_bot.py", ["--live-one", "--max-actions=1"]),
    "live_one_scan": ("scan_test.py", ["--live-one", "--max-actions=1"]),
}


# ── Safety gate ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GateResult:
    """Outcome of the live-one safety gate."""

    allowed: bool
    reason: str


def evaluate_live_one_gate(env: dict[str, str]) -> GateResult:
    """Decide whether a live-one job may proceed given the runner's env.

    The gate enforces the hard contract from the module docstring:
    ALLOW_LIVE_EXTERNAL_ACTIONS=true, CONFIRM_LIVE_TEST=YES,
    MAX_TEST_ACTIONS=1. Anything else => denied.

    Returning a plain dataclass (instead of raising) makes the gate
    trivially unit-testable and keeps the caller in control of how
    to report a denial back to Mission Control.
    """
    allow = env.get("ALLOW_LIVE_EXTERNAL_ACTIONS", "").strip().lower()
    if allow != "true":
        return GateResult(False, "ALLOW_LIVE_EXTERNAL_ACTIONS != true")

    confirm = env.get("CONFIRM_LIVE_TEST", "").strip()
    if confirm != "YES":
        return GateResult(False, "CONFIRM_LIVE_TEST != YES")

    max_actions_raw = env.get("MAX_TEST_ACTIONS", "").strip()
    try:
        max_actions = int(max_actions_raw)
    except ValueError:
        return GateResult(False, "MAX_TEST_ACTIONS is not an integer")
    if max_actions != 1:
        return GateResult(False, "MAX_TEST_ACTIONS != 1")

    return GateResult(True, "ok")


def is_mass_live_kind(kind: str) -> bool:
    """Mass live runs are not supported. Used by the dispatch table.

    No job-kind string in this runner refers to a mass live action. Any
    string that smells like one (contains ``live_all``, ``live_mass``,
    ``live_batch``, etc.) is rejected to defend against future drift.
    """
    suspicious = ("live_all", "live_mass", "live_batch", "live_many")
    lowered = kind.lower()
    return any(token in lowered for token in suspicious)


# ── Command construction ───────────────────────────────────────────────────


def build_command(
    kind: str,
    bot_dir: Path,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Construct the local shell command for ``kind`` against ``bot_dir``.

    Returns the argv list ready for ``subprocess.run`` (no ``shell=True``).
    Raises ``ValueError`` on unknown kinds, blocked mass-live kinds, or
    when a live-one kind fails the safety gate.
    """
    # Mass-live check goes first so a string like ``live_all_blast``
    # gets the specific "mass live runs are not supported" error even
    # if it isn't in ALL_KINDS — clearer signal at the safety boundary.
    if is_mass_live_kind(kind):
        raise ValueError(f"mass live runs are not supported: {kind!r}")
    if kind not in ALL_KINDS:
        raise ValueError(f"unknown job kind: {kind!r}")

    if kind in _DRY_RUN_COMMANDS:
        script, args = _DRY_RUN_COMMANDS[kind]
    else:
        # Live-one path — re-check the safety gate.
        gate = evaluate_live_one_gate(env or {})
        if not gate.allowed:
            raise ValueError(
                f"live-one denied by safety gate: {gate.reason}",
            )
        script, args = _LIVE_ONE_COMMANDS[kind]

    script_path = bot_dir / script
    return [sys.executable, str(script_path), *args]


# ── Runner status helpers ──────────────────────────────────────────────────


def resolve_bot_dir(env: dict[str, str] | None = None) -> Path:
    """Where Luis's MSA RT/X Python folder lives on this machine.

    Prefers ``MSA_RTXRT_BOT_DIR`` if set. Falls back to the expected
    path inside ``incoming/luis-msa-import``. Never reads from the
    frontend.
    """
    env = env if env is not None else dict(os.environ)
    override = env.get("MSA_RTXRT_BOT_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    return (
        repo_root
        / "incoming"
        / "luis-msa-import"
        / "MSA"
        / "Monthly revenue"
        / "Automation [RTxRT]"
    ).resolve()


# ── Local poll loop (stub until the backend bridge ships) ──────────────────


def main() -> int:
    """Stub entrypoint.

    The backend bridge that lets the runner pull queued jobs from Mission
    Control is not in this PR. Running this script today prints the
    configuration the runner would use and exits 0 so the operator can
    sanity-check env setup without sending anything anywhere.
    """
    bot_dir = resolve_bot_dir()
    env_snapshot = {
        "MSA_RTXRT_BOT_DIR": str(bot_dir),
        "ALLOW_LIVE_EXTERNAL_ACTIONS": os.environ.get(
            "ALLOW_LIVE_EXTERNAL_ACTIONS",
            "<unset>",
        ),
        "CONFIRM_LIVE_TEST": os.environ.get("CONFIRM_LIVE_TEST", "<unset>"),
        "MAX_TEST_ACTIONS": os.environ.get("MAX_TEST_ACTIONS", "<unset>"),
        "DRY_RUN": os.environ.get("DRY_RUN", "<unset>"),
    }
    print("MSA RT/X Local Runner — configuration check")  # noqa: T201
    print("--------------------------------------------")  # noqa: T201
    for key, value in env_snapshot.items():
        print(f"  {key}: {value}")  # noqa: T201
    print()  # noqa: T201
    print("Supported job kinds (dry-run):")  # noqa: T201
    for kind in DRY_RUN_KINDS:
        script, args = _DRY_RUN_COMMANDS[kind]
        print(f"  {kind}: {script} {shlex.join(args)}")  # noqa: T201
    print()  # noqa: T201
    print("Supported job kinds (live-one — owner-gated, safety-gated):")  # noqa: T201
    for kind in LIVE_ONE_KINDS:
        script, args = _LIVE_ONE_COMMANDS[kind]
        print(f"  {kind}: {script} {shlex.join(args)}")  # noqa: T201
    print()  # noqa: T201
    print("Backend bridge: NOT CONNECTED YET (see README in this folder).")  # noqa: T201
    print("Mass live runs: BLOCKED by design.")  # noqa: T201
    return 0


# Provide a wired-up ``run_job`` for tests + future backend wiring. Lives
# at module scope (no side effects) so callers can import it without
# starting the poll loop.
def run_job(
    kind: str,
    *,
    bot_dir: Path | None = None,
    env: dict[str, str] | None = None,
    timeout_seconds: int = 600,
) -> subprocess.CompletedProcess[str]:
    """Run the local command for ``kind`` synchronously and return the result.

    Honors the safety gate via :func:`build_command`. Never invokes
    ``shell=True``. Captures stdout + stderr for the caller to report
    back to Mission Control.
    """
    env = env if env is not None else dict(os.environ)
    resolved_dir = bot_dir if bot_dir is not None else resolve_bot_dir(env)
    cmd = build_command(kind, resolved_dir, env=env)
    return subprocess.run(  # noqa: S603 - argv list, no shell.
        cmd,
        cwd=resolved_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
