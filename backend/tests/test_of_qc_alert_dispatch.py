# ruff: noqa: INP001
"""Unit tests for OF account/sync alert → Discord dispatch.

Pins:
  • One Discord message per code, with a curated action sentence.
  • Severity ladder: blocked / expired / disconnected / api_disconnected =
    critical; account_stale + sync_failure:* = high.
  • Privacy: raw ``error``/``reason`` strings from sync_log NEVER reach the
    rendered message — only the entity name does.
  • Codes outside this dispatcher's scope return None (no Discord call).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from app.services.of_intelligence.qc import dispatch
from app.services.of_intelligence.qc.dispatch import ship_account_or_sync_alert
from app.services.of_intelligence.qc.severity import Severity


@pytest.fixture(autouse=True)
def _stub_publisher(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Capture publish() calls instead of hitting the network."""
    captured: dict[str, Any] = {"calls": []}

    async def _fake_publish(
        rendered_message: str,
        *,
        code: str,
        severity: str,
        forbidden_substrings: tuple[str, ...] = (),
        log_extra: dict[str, Any] | None = None,
        bypass_kill_switch: bool = False,
    ) -> object:
        _ = forbidden_substrings, bypass_kill_switch
        captured["calls"].append(
            {
                "rendered": rendered_message,
                "code": code,
                "severity": severity,
                "log_extra": log_extra or {},
            }
        )

        class _Result:
            ok = True
            status = 204
            attempts = 1
            reason = "ok"
            elapsed_ms = 1

        return _Result()

    monkeypatch.setattr(dispatch, "publish", _fake_publish)
    return captured


# ── Per-code formatting + severity ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_account_blocked_renders_critical_with_action(
    _stub_publisher: dict[str, Any],
) -> None:
    alert_id = uuid4()
    res = await ship_account_or_sync_alert(
        code="account_blocked",
        title="luna_main access blocked",
        account_username="luna_main",
        alert_id=alert_id,
        context={"access_status": "blocked"},
    )
    assert res is not None
    call = _stub_publisher["calls"][-1]
    assert call["code"] == "account_blocked"
    assert call["severity"] == Severity.CRITICAL.value
    assert "🟥 [QC] luna_main access blocked" in call["rendered"]
    assert "Account: luna_main" in call["rendered"]
    assert "Status: blocked" in call["rendered"]
    assert "Action: Re-auth in OF Intelligence → Accounts." in call["rendered"]
    assert f"Ref: qc/alert/{alert_id}" in call["rendered"]


@pytest.mark.asyncio
async def test_account_expired_renders_critical(
    _stub_publisher: dict[str, Any],
) -> None:
    await ship_account_or_sync_alert(
        code="account_expired",
        title="luna_main access expired",
        account_username="luna_main",
        alert_id=uuid4(),
        context={"access_status": "expired"},
    )
    call = _stub_publisher["calls"][-1]
    assert call["severity"] == Severity.CRITICAL.value
    assert "🟥 [QC]" in call["rendered"]
    assert "Status: expired" in call["rendered"]
    assert "Action: Refresh credentials" in call["rendered"]


@pytest.mark.asyncio
async def test_account_disconnected_renders_critical(
    _stub_publisher: dict[str, Any],
) -> None:
    await ship_account_or_sync_alert(
        code="account_disconnected",
        title="luna_main disconnected",
        account_username="luna_main",
        alert_id=uuid4(),
        context={"access_status": "lost"},
    )
    call = _stub_publisher["calls"][-1]
    assert call["severity"] == Severity.CRITICAL.value
    assert "Status: disconnected" in call["rendered"]
    assert "Action: Reconnect account" in call["rendered"]


@pytest.mark.asyncio
async def test_account_stale_renders_high_with_hours(
    _stub_publisher: dict[str, Any],
) -> None:
    await ship_account_or_sync_alert(
        code="account_stale",
        title="luna_main hasn't synced in 6h+",
        account_username="luna_main",
        alert_id=uuid4(),
        context={"hours_since_sync": 8},
    )
    call = _stub_publisher["calls"][-1]
    assert call["severity"] == Severity.HIGH.value
    assert "🟧 [QC]" in call["rendered"]
    assert "Hours since sync: 8" in call["rendered"]


@pytest.mark.asyncio
async def test_api_disconnected_renders_critical(
    _stub_publisher: dict[str, Any],
) -> None:
    await ship_account_or_sync_alert(
        code="api_disconnected",
        title="OnlyMonster API: no successful sync in 24h",
        account_username=None,
        alert_id=uuid4(),
        context=None,
    )
    call = _stub_publisher["calls"][-1]
    assert call["severity"] == Severity.CRITICAL.value
    assert "🟥 [QC] OnlyMonster API" in call["rendered"]
    # No account_username — the ``Account:`` line should be absent.
    assert "Account:" not in call["rendered"]
    assert "Window: last 24h" in call["rendered"]


@pytest.mark.asyncio
async def test_sync_failure_renders_high_with_entity(
    _stub_publisher: dict[str, Any],
) -> None:
    await ship_account_or_sync_alert(
        code="sync_failure:messages",
        title="Sync failed for messages",
        account_username=None,
        alert_id=uuid4(),
        context={"entity": "messages", "run_id": "abc-123"},
    )
    call = _stub_publisher["calls"][-1]
    assert call["severity"] == Severity.HIGH.value
    assert "🟧 [QC] Sync failed for messages" in call["rendered"]
    assert "Entity: messages" in call["rendered"]


# ── Privacy: raw error / reason / fan handles never reach Discord ───────────


@pytest.mark.asyncio
async def test_sync_failure_does_not_leak_raw_error_text(
    _stub_publisher: dict[str, Any],
) -> None:
    """If sync_log.error contains an API response body, it must NOT render.

    The dispatcher reads from ``context``, not ``message``.  We pass a
    realistic error string in context to verify it's still ignored — only
    the entity field is allowed.
    """
    leaky_error = "OnlyMonster 401: {\"error\":\"token bad\",\"fan\":\"@somefan\"}"
    await ship_account_or_sync_alert(
        code="sync_failure:messages",
        title="Sync failed for messages",
        account_username=None,
        alert_id=uuid4(),
        context={"entity": "messages", "error": leaky_error, "fan_handle": "@somefan"},
    )
    rendered = _stub_publisher["calls"][-1]["rendered"]
    assert "OnlyMonster 401" not in rendered
    assert "token bad" not in rendered
    assert "@somefan" not in rendered
    assert "fan_handle" not in rendered.lower()
    # Allowed fields still present.
    assert "Entity: messages" in rendered


@pytest.mark.asyncio
async def test_account_alerts_do_not_leak_extra_context_fields(
    _stub_publisher: dict[str, Any],
) -> None:
    """Even if a future caller stuffs extra keys into context, the
    dispatcher renders only the curated allowlist."""
    await ship_account_or_sync_alert(
        code="account_blocked",
        title="luna_main access blocked",
        account_username="luna_main",
        alert_id=uuid4(),
        context={
            "access_status": "blocked",
            "fan_handle": "@somefan",
            "raw_response": "the entire HTTP body",
        },
    )
    rendered = _stub_publisher["calls"][-1]["rendered"]
    assert "@somefan" not in rendered
    assert "raw_response" not in rendered.lower()
    assert "the entire HTTP body" not in rendered


# ── Out-of-scope codes ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_code_returns_none_and_does_not_publish(
    _stub_publisher: dict[str, Any],
) -> None:
    res = await ship_account_or_sync_alert(
        code="chatter_repeat_offender",  # future code — outside this dispatcher
        title="…",
        account_username=None,
        alert_id=uuid4(),
        context=None,
    )
    assert res is None
    assert _stub_publisher["calls"] == []


# ── log_extra carries alert_id ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publisher_log_extra_includes_alert_id(
    _stub_publisher: dict[str, Any],
) -> None:
    alert_id = uuid4()
    await ship_account_or_sync_alert(
        code="account_blocked",
        title="luna_main access blocked",
        account_username="luna_main",
        alert_id=alert_id,
        context={"access_status": "blocked"},
    )
    assert _stub_publisher["calls"][-1]["log_extra"] == {"alert_id": str(alert_id)}
