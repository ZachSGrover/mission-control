"""Tests for the MSA RT/X local Claw runner safety gate + command builder + poll loop."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# The runner lives next door; make it importable without installing it.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from msa_rtxrt_runner import (  # noqa: E402
    ALL_KINDS,
    DRY_RUN_KINDS,
    LIVE_ONE_KINDS,
    RunnerConfig,
    build_command,
    evaluate_live_one_gate,
    execute_job,
    is_mass_live_kind,
    patch_job_status,
    poll_for_job,
    poll_once,
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


# ── RunnerConfig.from_env ───────────────────────────────────────────────────


def _base_env() -> dict[str, str]:
    return {
        "MSA_RTXRT_BACKEND_URL": "http://mc.test",
        "MSA_RTXRT_RUNNER_TOKEN": "tok-xyz",
        "MSA_RTXRT_RUNNER_ID": "claw-test",
        "MSA_RTXRT_BOT_DIR": "/tmp/luis-bot",
    }


def test_runner_config_reads_env() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    assert cfg.base_url == "http://mc.test"
    assert cfg.runner_token == "tok-xyz"
    assert cfg.runner_id == "claw-test"
    assert str(cfg.bot_dir).endswith("luis-bot")


def test_runner_config_strips_trailing_slash_from_base_url() -> None:
    env = _base_env() | {"MSA_RTXRT_BACKEND_URL": "http://mc.test/"}
    cfg = RunnerConfig.from_env(env)
    assert cfg.base_url == "http://mc.test"


def test_runner_config_clamps_poll_interval_floor() -> None:
    env = _base_env() | {"MSA_RTXRT_POLL_INTERVAL_SECONDS": "0.1"}
    cfg = RunnerConfig.from_env(env)
    assert cfg.poll_interval_seconds >= 1.0


def test_runner_config_defaults_runner_id_when_blank() -> None:
    env = _base_env() | {"MSA_RTXRT_RUNNER_ID": ""}
    cfg = RunnerConfig.from_env(env)
    assert cfg.runner_id == "claw-1"


# ── poll_for_job ────────────────────────────────────────────────────────────


def test_poll_for_job_returns_none_when_backend_unset() -> None:
    cfg = RunnerConfig.from_env({"MSA_RTXRT_BACKEND_URL": ""})
    assert poll_for_job(cfg) is None


def test_poll_for_job_returns_the_job_dict_from_backend() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(200, {"job": {"id": "j-1", "kind": "smoke"}}))
    job = poll_for_job(cfg, http=http)
    assert job == {"id": "j-1", "kind": "smoke"}
    # The request must include the runner-token header (verified by inspecting
    # the call kwargs).
    assert http.call_args.kwargs["token"] == "tok-xyz"
    assert "runner_id=claw-test" in http.call_args.kwargs["url"]


def test_poll_for_job_returns_none_when_queue_empty() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(200, {"job": None}))
    assert poll_for_job(cfg, http=http) is None


def test_poll_for_job_returns_none_on_non_200() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(401, {"detail": "nope"}))
    assert poll_for_job(cfg, http=http) is None


# ── patch_job_status ────────────────────────────────────────────────────────


def test_patch_job_status_sends_status_and_runner_id() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(200, {"id": "j-1", "status": "succeeded"}))
    ok = patch_job_status(
        cfg, job_id="j-1", status_value="succeeded", summary="hello", http=http
    )
    assert ok is True
    assert http.call_args.kwargs["method"] == "PATCH"
    body = http.call_args.kwargs["body"]
    assert body["status"] == "succeeded"
    assert body["runner_id"] == "claw-test"
    assert body["summary"] == "hello"


def test_patch_job_status_returns_false_on_non_200() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(400, {"detail": "illegal transition"}))
    assert (
        patch_job_status(cfg, job_id="j-1", status_value="succeeded", http=http)
        is False
    )


# ── execute_job (mass-live / unknown / safety gate paths) ───────────────────


def test_execute_job_blocks_unknown_kind() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(200, None))
    result = execute_job(cfg, {"id": "j-1", "kind": "does_not_exist"}, http=http)
    assert result == "blocked"
    body = http.call_args.kwargs["body"]
    assert body["status"] == "blocked"


def test_execute_job_blocks_mass_live_kind() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(200, None))
    result = execute_job(cfg, {"id": "j-1", "kind": "live_all_blast"}, http=http)
    assert result == "blocked"
    body = http.call_args.kwargs["body"]
    assert body["status"] == "blocked"
    assert "mass live" in (body.get("summary") or "")


def test_execute_job_blocks_live_one_without_safety_env() -> None:
    """Live-one kinds reach build_command, which checks the runner's local
    env. With nothing set, the safety gate denies → blocked."""
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(200, None))
    result = execute_job(cfg, {"id": "j-2", "kind": "live_one_blast"}, http=http)
    assert result == "blocked"


# ── execute_job (success / failure paths via injected runner) ───────────────


def _ok(stdout: str = "done", stderr: str = "") -> Any:
    return subprocess.CompletedProcess(args=["x"], returncode=0, stdout=stdout, stderr=stderr)


def _fail(returncode: int, stdout: str = "", stderr: str = "boom") -> Any:
    return subprocess.CompletedProcess(
        args=["x"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_execute_job_succeeded_path_patches_with_stdout_excerpt() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(200, None))
    fake_runner = MagicMock(return_value=_ok(stdout="200 candidates processed"))
    result = execute_job(
        cfg,
        {"id": "j-3", "kind": "smoke"},
        http=http,
        runner=fake_runner,
    )
    assert result == "succeeded"
    body = http.call_args.kwargs["body"]
    assert body["status"] == "succeeded"
    assert body["stdout_excerpt"] == "200 candidates processed"
    assert "smoke ok" in (body.get("summary") or "")


def test_execute_job_failed_path_patches_with_error_excerpt() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(200, None))
    fake_runner = MagicMock(return_value=_fail(returncode=2, stderr="script crashed"))
    result = execute_job(
        cfg,
        {"id": "j-4", "kind": "dry_run_blast"},
        http=http,
        runner=fake_runner,
    )
    assert result == "failed"
    body = http.call_args.kwargs["body"]
    assert body["status"] == "failed"
    assert body["error_excerpt"] == "script crashed"


def test_execute_job_handles_runner_exception_as_failed() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(200, None))

    def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("boom")

    result = execute_job(
        cfg,
        {"id": "j-5", "kind": "dry_run_dm"},
        http=http,
        runner=explode,
    )
    assert result == "failed"
    body = http.call_args.kwargs["body"]
    assert body["status"] == "failed"
    assert "runner crashed" in (body.get("summary") or "")


def test_execute_job_truncates_long_stdout_to_excerpt_cap() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(200, None))
    huge = "X" * 5000
    fake_runner = MagicMock(return_value=_ok(stdout=huge))
    execute_job(
        cfg,
        {"id": "j-6", "kind": "smoke"},
        http=http,
        runner=fake_runner,
    )
    body = http.call_args.kwargs["body"]
    assert body["stdout_excerpt"] is not None
    assert len(body["stdout_excerpt"]) <= 2000  # 1900 cap + 1 ellipsis ≪ 2000
    assert body["stdout_excerpt"].endswith("…")


# ── poll_once (full cycle) ──────────────────────────────────────────────────


def test_poll_once_returns_none_when_queue_empty() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(200, {"job": None}))
    assert poll_once(cfg, http=http) is None


def test_poll_once_runs_and_reports_succeeded() -> None:
    cfg = RunnerConfig.from_env(_base_env())

    # First HTTP call (poll) returns a job; second (patch) returns 200.
    http = MagicMock()
    http.side_effect = [
        (200, {"job": {"id": "j-7", "kind": "smoke"}}),
        (200, None),
    ]
    fake_runner = MagicMock(return_value=_ok(stdout="ok"))
    result = poll_once(cfg, http=http, runner=fake_runner)
    assert result == "succeeded"
    assert http.call_count == 2


# ── Defensive: runner-token never leaks into anything we patch back ─────────


def test_runner_token_never_appears_in_patched_body() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    captured: list[dict[str, Any]] = []

    def capture(*, method: str, url: str, token: str, body: Any = None, **_: Any) -> tuple[int, Any]:
        _ = method
        _ = url
        _ = token
        if body is not None:
            captured.append(body)
        return 200, None

    fake_runner = MagicMock(return_value=_ok(stdout="ok"))
    execute_job(cfg, {"id": "j-8", "kind": "smoke"}, http=capture, runner=fake_runner)
    for body in captured:
        assert "tok-xyz" not in str(body)


# ── Preflight + AdsPower checks ────────────────────────────────────────────

from msa_rtxrt_runner import (  # noqa: E402
    build_preflight_report,
    check_adspower,
    check_backend_reachable,
    check_backend_token,
    check_local_config_files,
    check_python_imports,
)


def test_check_python_imports_reports_each_module() -> None:
    result = check_python_imports()
    assert set(result) == {"requests", "playwright", "playwright.sync_api"}
    for v in result.values():
        assert isinstance(v, bool)


def test_check_backend_reachable_when_url_blank() -> None:
    cfg = RunnerConfig.from_env({"MSA_RTXRT_BACKEND_URL": ""})
    result = check_backend_reachable(cfg)
    assert result == {"configured": False, "reachable": False, "http_status": None}


def test_check_backend_reachable_200() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(200, {"ok": True}))
    result = check_backend_reachable(cfg, http=http)
    assert result == {"configured": True, "reachable": True, "http_status": 200}


def test_check_backend_reachable_5xx_or_error() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(503, None))
    result = check_backend_reachable(cfg, http=http)
    assert result == {"configured": True, "reachable": False, "http_status": 503}


def test_check_backend_token_accepted() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(200, {"job": None}))
    result = check_backend_token(cfg, http=http)
    assert result == {"configured": True, "accepted": True, "http_status": 200}


def test_check_backend_token_wrong_returns_401() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(401, {"detail": "Invalid runner token."}))
    result = check_backend_token(cfg, http=http)
    assert result == {"configured": True, "accepted": False, "http_status": 401}


def test_check_backend_token_unconfigured_returns_503() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(503, {"detail": "MSA RT/X runner endpoint is disabled..."}))
    result = check_backend_token(cfg, http=http)
    assert result["accepted"] is False
    assert result["http_status"] == 503


def test_check_adspower_unreachable_clean_failure() -> None:
    def boom(*_a: Any, **_kw: Any) -> tuple[int, Any]:
        raise ConnectionError("local.adspower.net unreachable")

    result = check_adspower(http=boom)
    assert result["api_reachable"] is False
    assert result["http_status"] is None
    assert "error" in result


def test_check_adspower_reports_api_key_presence_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADSPOWER_API_KEY", "some-non-empty-value")
    http = MagicMock(return_value=(200, {"data": {"list": []}}))
    result = check_adspower(http=http)
    assert result["api_key_present"] is True
    assert result["api_reachable"] is True


def test_check_adspower_does_not_open_any_profile() -> None:
    """Sanity: only the LIST endpoint, never /browser/start or /browser/stop."""
    seen_urls: list[str] = []

    def capture(*, method: str, url: str, token: str, body: Any = None, **_: Any) -> tuple[int, Any]:
        _ = method
        _ = token
        _ = body
        seen_urls.append(url)
        return 200, {"data": {"list": []}}

    check_adspower(http=capture)
    for url in seen_urls:
        assert "/browser/start" not in url
        assert "/browser/stop" not in url
        assert "/api/v1/user/list" in url


def test_check_local_config_files_returns_bools_only() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    result = check_local_config_files(cfg.bot_dir)
    for name in ("auftrag.json", "contacts.json", "blast_auftrag.json", "repost_auftrag.json", "schedule.json"):
        assert name in result
        assert isinstance(result[name], bool)


def test_build_preflight_report_shape_and_no_token_leak() -> None:
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(
        side_effect=[(200, {"ok": True}), (200, {"job": None}), (200, {"data": {"list": []}})]
    )
    report = build_preflight_report(cfg, http=http)
    assert set(report) == {"env", "python_imports", "backend", "adspower", "config_files", "safety"}
    assert "runner_token_set" in report["env"]
    # The token value itself must not appear anywhere in the serialized report.
    assert "tok-xyz" not in str(report)
    assert report["safety"]["mass_live_kinds_blocked"] is True
    assert report["safety"]["live_one_requires_three_flags"] is True


def test_preflight_report_live_flags_all_false_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for k in ("ALLOW_LIVE_EXTERNAL_ACTIONS", "CONFIRM_LIVE_TEST", "MAX_TEST_ACTIONS", "DRY_RUN"):
        monkeypatch.delenv(k, raising=False)
    cfg = RunnerConfig.from_env(_base_env())
    http = MagicMock(return_value=(200, {}))
    report = build_preflight_report(cfg, http=http)
    flags = report["env"]["live_flags"]
    for key in (
        "ALLOW_LIVE_EXTERNAL_ACTIONS",
        "CONFIRM_LIVE_TEST",
        "MAX_TEST_ACTIONS_is_1",
        "DRY_RUN_explicitly_false",
    ):
        assert flags[key] is False


# ── Multi-runner v2: env-driven runner_id + privacy ────────────────────────


def test_runner_config_distinct_runner_ids_per_machine() -> None:
    """Each machine's env can pick its own ``MSA_RTXRT_RUNNER_ID``."""
    for rid in ("claw-1", "luis-pc-1", "zach-laptop-1", "mac-mini-1"):
        env = _base_env() | {"MSA_RTXRT_RUNNER_ID": rid}
        cfg = RunnerConfig.from_env(env)
        assert cfg.runner_id == rid


def test_poll_for_job_url_carries_runner_id_through() -> None:
    """The poll URL always carries the calling runner's ID for backend filtering."""
    env = _base_env() | {"MSA_RTXRT_RUNNER_ID": "luis-pc-1"}
    cfg = RunnerConfig.from_env(env)
    http = MagicMock(return_value=(200, {"job": None}))
    poll_for_job(cfg, http=http)
    assert "runner_id=luis-pc-1" in http.call_args.kwargs["url"]


def test_patch_job_status_url_carries_runner_id_for_each_runner() -> None:
    """The PATCH body carries the calling runner's ID — backend uses this
    to populate the row's ``runner_id`` field."""
    env = _base_env() | {"MSA_RTXRT_RUNNER_ID": "zach-laptop-1"}
    cfg = RunnerConfig.from_env(env)
    http = MagicMock(return_value=(200, {}))
    patch_job_status(cfg, job_id="j-1", status_value="succeeded", http=http)
    body = http.call_args.kwargs["body"]
    assert body["runner_id"] == "zach-laptop-1"


def test_preflight_report_contains_runner_id_but_never_token() -> None:
    """`build_preflight_report` exposes the runner_id (operator-chosen, not
    secret) but never the token value, only ``runner_token_set: bool``.
    """
    env = _base_env() | {"MSA_RTXRT_RUNNER_ID": "mac-mini-1"}
    cfg = RunnerConfig.from_env(env)
    http = MagicMock(
        side_effect=[
            (200, {"ok": True}),  # /healthz
            (200, {"job": None}),  # /runner/poll
            (200, {"data": {"list": []}}),  # AdsPower
        ]
    )
    report = build_preflight_report(cfg, http=http)
    # Runner ID surfaces (privacy-safe, operator-chosen).
    assert report["env"]["runner_id"] == "mac-mini-1"
    # Token presence surfaces as a boolean only — never the value.
    assert report["env"]["runner_token_set"] is True
    assert "tok-xyz" not in str(report), (
        "preflight must never serialize the token value"
    )
