"""Tests for the MSA RT/X local Claw runner safety gate + command builder."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The runner lives next door; make it importable without installing it.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from msa_rtxrt_runner import (  # noqa: E402
    ALL_KINDS,
    DRY_RUN_KINDS,
    LIVE_ONE_KINDS,
    build_command,
    evaluate_live_one_gate,
    is_mass_live_kind,
    resolve_bot_dir,
)

# Live-mode env that *passes* the gate. Tests mutate copies of this.
_PASSING_LIVE_ENV: dict[str, str] = {
    "ALLOW_LIVE_EXTERNAL_ACTIONS": "true",
    "CONFIRM_LIVE_TEST": "YES",
    "MAX_TEST_ACTIONS": "1",
}


# ── Safety gate ─────────────────────────────────────────────────────────────


def test_gate_denies_empty_env() -> None:
    result = evaluate_live_one_gate({})
    assert result.allowed is False
    assert "ALLOW_LIVE_EXTERNAL_ACTIONS" in result.reason


def test_gate_denies_when_allow_flag_missing() -> None:
    env = dict(_PASSING_LIVE_ENV)
    env["ALLOW_LIVE_EXTERNAL_ACTIONS"] = "false"
    result = evaluate_live_one_gate(env)
    assert result.allowed is False
    assert "ALLOW_LIVE_EXTERNAL_ACTIONS" in result.reason


def test_gate_denies_when_confirm_wrong() -> None:
    env = dict(_PASSING_LIVE_ENV)
    env["CONFIRM_LIVE_TEST"] = "yes"  # case-sensitive on purpose
    result = evaluate_live_one_gate(env)
    assert result.allowed is False
    assert "CONFIRM_LIVE_TEST" in result.reason


def test_gate_denies_when_max_actions_is_not_one() -> None:
    for bad in ("0", "2", "100", "one"):
        env = dict(_PASSING_LIVE_ENV)
        env["MAX_TEST_ACTIONS"] = bad
        result = evaluate_live_one_gate(env)
        assert result.allowed is False, f"expected denial for MAX_TEST_ACTIONS={bad!r}"
        assert "MAX_TEST_ACTIONS" in result.reason


def test_gate_allows_when_all_three_flags_match() -> None:
    result = evaluate_live_one_gate(dict(_PASSING_LIVE_ENV))
    assert result.allowed is True
    assert result.reason == "ok"


# ── Mass-live block ─────────────────────────────────────────────────────────


def test_is_mass_live_kind_blocks_obvious_strings() -> None:
    for kind in ("live_all_blast", "live_mass_dm", "live_batch_scan", "live_many"):
        assert is_mass_live_kind(kind) is True, f"expected {kind!r} to be blocked"


def test_is_mass_live_kind_allows_single_live_one_strings() -> None:
    for kind in LIVE_ONE_KINDS:
        assert is_mass_live_kind(kind) is False, f"{kind!r} should not be blocked"


# ── Command builder ─────────────────────────────────────────────────────────


def test_build_command_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown job kind"):
        build_command("does_not_exist", Path("/tmp/anywhere"))


def test_build_command_rejects_mass_live_kind() -> None:
    with pytest.raises(ValueError, match="mass live runs are not supported"):
        build_command("live_all_blast", Path("/tmp/anywhere"))


def test_build_command_returns_dry_run_argv_with_no_shell() -> None:
    bot_dir = Path("/tmp/luis-bot")
    cmd = build_command("dry_run_blast", bot_dir)
    # Argv shape: [python, /path/to/script, ...flags]
    assert cmd[0] == sys.executable
    assert cmd[1].endswith("blast_bot.py")
    assert "--dry-run" in cmd
    # Defensive: nothing in the command list should ever be a shell metachar
    # that would be dangerous if accidentally rejoined into a string.
    for token in cmd:
        assert "\n" not in token


def test_build_command_denies_live_one_without_gate_pass() -> None:
    for kind in LIVE_ONE_KINDS:
        with pytest.raises(ValueError, match="live-one denied by safety gate"):
            build_command(kind, Path("/tmp/luis-bot"), env={})


def test_build_command_allows_live_one_when_gate_passes() -> None:
    bot_dir = Path("/tmp/luis-bot")
    for kind in LIVE_ONE_KINDS:
        cmd = build_command(kind, bot_dir, env=dict(_PASSING_LIVE_ENV))
        assert cmd[0] == sys.executable
        # The live-one branch must include the explicit single-action flag.
        assert "--live-one" in cmd
        assert "--max-actions=1" in cmd


# ── Bot-dir resolution ──────────────────────────────────────────────────────


def test_resolve_bot_dir_uses_env_override_when_set() -> None:
    custom = Path("/tmp/override-luis-bot").expanduser().resolve()
    out = resolve_bot_dir({"MSA_RTXRT_BOT_DIR": str(custom)})
    assert out == custom


def test_resolve_bot_dir_falls_back_to_incoming_path() -> None:
    out = resolve_bot_dir({})
    parts = out.parts
    assert "incoming" in parts
    assert "luis-msa-import" in parts
    assert parts[-1] == "Automation [RTxRT]"


# ── Kind catalog ────────────────────────────────────────────────────────────


def test_all_kinds_split_into_dry_run_and_live_one_with_no_extras() -> None:
    assert set(ALL_KINDS) == set(DRY_RUN_KINDS) | set(LIVE_ONE_KINDS)
    # No accidental "live-all" / "live-mass" / "live-batch" kinds.
    for kind in ALL_KINDS:
        assert not is_mass_live_kind(kind)
