"""Unit tests for the read-only Hermes diagnostic alert API.

These tests exercise the parsing + derivation helpers in app.api.hermes
directly (without spinning up FastAPI) so they don't depend on Clerk auth
or a running database.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.api import hermes as hermes_api


def _write_state(dir_: Path, alert_id: str, alert: dict, *, wrap: bool = False) -> None:
    payload = {"last_fired_at": 1_700_000_000, "alert": alert} if wrap else alert
    (dir_ / f"{alert_id}.json").write_text(json.dumps(payload))


def _alert(**overrides) -> dict:
    base = {
        "alert_id": "openclaw-gateway-failed-aaa111",
        "system": "OpenClaw Gateway",
        "status": "failed",
        "severity": "CRITICAL",
        "exact_issue": "Gateway not responding.",
        "evidence": ["probe failed", "process missing"],
        "likely_cause": "Gateway crashed.",
        "business_impact": "Browser control disconnected.",
        "recommended_fix": "Restart com.digidle.openclaw.",
        "claude_prompt": (
            "OpenClaw gateway is down. Inspect:\n"
            "  1. launchctl print gui/$(id -u)/com.digidle.openclaw\n"
            "  2. ~/.openclaw/logs/gateway.err\n"
            "  3. lsof -iTCP:18789\n"
            "Fix the root cause."
        ),
        "timestamp": "2026-04-29T12:00:00Z",
    }
    base.update(overrides)
    return base


def test_load_one_handles_wrapped_state(tmp_path: Path) -> None:
    """State files written by --check-dedupe are wrapped in {last_fired_at, alert}."""
    _write_state(tmp_path, "wrapped", _alert(), wrap=True)
    incident, failed = hermes_api._load_one(tmp_path / "wrapped.json")
    assert not failed
    assert incident is not None
    assert incident.system == "OpenClaw Gateway"
    assert incident.severity == "CRITICAL"
    assert incident.last_fired_at_unix == 1_700_000_000


def test_load_one_handles_bare_state(tmp_path: Path) -> None:
    """Resolved-style or legacy state files may be a bare alert dict."""
    _write_state(tmp_path, "bare", _alert(severity="LOW"), wrap=False)
    incident, failed = hermes_api._load_one(tmp_path / "bare.json")
    assert not failed
    assert incident is not None
    assert incident.severity == "LOW"
    assert incident.last_fired_at_unix is None


def test_load_one_returns_failed_for_invalid_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    _, failed = hermes_api._load_one(bad)
    assert failed is True


def test_load_all_sorts_newest_first_and_counts_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MC_STATE_DIR", str(tmp_path.parent))
    alerts_dir = tmp_path.parent / "alerts"
    alerts_dir.mkdir(exist_ok=True)

    # Older
    (alerts_dir / "a.json").write_text(
        json.dumps({"last_fired_at": 1_700_000_000, "alert": _alert(alert_id="a")})
    )
    # Newer
    (alerts_dir / "b.json").write_text(
        json.dumps({"last_fired_at": 1_700_000_500, "alert": _alert(alert_id="b")})
    )
    # Malformed
    (alerts_dir / "c.json").write_text("{garbage")

    incidents, warnings, present = hermes_api._load_all()
    assert present is True
    assert warnings == 1
    assert [i.alert_id for i in incidents] == ["b", "a"]


def test_load_all_handles_missing_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MC_STATE_DIR", str(tmp_path / "does-not-exist"))
    incidents, warnings, present = hermes_api._load_all()
    assert incidents == []
    assert warnings == 0
    assert present is False


def test_inspect_checklist_extracts_numbered_lines() -> None:
    prompt = (
        "Backend is failing /health. Inspect:\n"
        "  1. Backend launchd job status\n"
        "  2. Render deploy log\n"
        "  3. Postgres reachability\n"
        "Fix the root cause.\n"
    )
    out = hermes_api._inspect_checklist(prompt)
    assert out == [
        "Backend launchd job status",
        "Render deploy log",
        "Postgres reachability",
    ]


def test_inspect_checklist_returns_empty_when_no_inspect_block() -> None:
    assert hermes_api._inspect_checklist("Just do something.") == []


def test_blocked_actions_map_covers_known_systems() -> None:
    expected = {
        "OpenClaw Gateway",
        "Mission Control Backend",
        "Mission Control Frontend",
        "Postgres Database",
        "Redis",
        "Discord Bot (Hermes notify path)",
        "Telegram Bot (Hermes notify path)",
        "Local Machine",
    }
    assert expected.issubset(hermes_api.BLOCKED_ACTIONS_BY_SYSTEM.keys())


def test_alerts_dir_uses_env_or_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MC_STATE_DIR", "/custom/path")
    assert hermes_api._alerts_dir() == Path("/custom/path/alerts")
    monkeypatch.delenv("MC_STATE_DIR", raising=False)
    assert hermes_api._alerts_dir() == Path("/tmp/mc-system/alerts")
