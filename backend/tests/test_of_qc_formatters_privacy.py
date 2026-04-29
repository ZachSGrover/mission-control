# ruff: noqa: INP001
"""Unit tests for QC formatters and privacy guard.

The privacy contract is enforced by formatters.assert_privacy_safe.  These
tests pin its behavior so a future template change cannot silently leak fan
handles, message bodies, webhook URLs, or bot tokens.
"""

from __future__ import annotations

import pytest

from app.services.of_intelligence.qc.formatters import (
    MAX_MESSAGE_CHARS,
    AlertPayload,
    PrivacyViolation,
    RolledUpPayload,
    assert_privacy_safe,
    format_alert,
    format_rollup,
)
from app.services.of_intelligence.qc.severity import Severity


# ── format_alert ─────────────────────────────────────────────────────────────


def test_format_alert_renders_glyph_and_required_fields() -> None:
    rendered = format_alert(
        AlertPayload(
            severity=Severity.CRITICAL,
            code="account_blocked",
            title="luna_main may have lost access",
            account_username="luna_main",
            facts=(("Status", "blocked"), ("Last sync", "2h ago")),
            action="Re-auth in OF Intelligence → Accounts → luna_main",
            ref="qc/abc123",
        )
    )
    assert rendered.startswith("🟥 [QC] luna_main may have lost access")
    assert "Account: luna_main" in rendered
    assert "Status: blocked" in rendered
    assert "Action: Re-auth" in rendered
    assert "Ref: qc/abc123" in rendered
    # Critical glyph for critical severity, never falls back.
    assert "🟦" not in rendered


def test_format_alert_omits_blank_optional_fields() -> None:
    rendered = format_alert(
        AlertPayload(
            severity=Severity.MEDIUM,
            code="sync_failure",
            title="Sync failed: messages",
        )
    )
    assert "Account:" not in rendered
    assert "Chatter:" not in rendered
    assert "Action:" not in rendered
    assert "Ref:" not in rendered


def test_format_alert_skips_facts_with_empty_value() -> None:
    rendered = format_alert(
        AlertPayload(
            severity=Severity.HIGH,
            code="account_stale",
            title="luna_main hasn't synced in 6h+",
            account_username="luna_main",
            facts=(("Last sync", ""), ("Hours", "8")),
        )
    )
    assert "Last sync" not in rendered
    assert "Hours: 8" in rendered


def test_format_alert_truncates_to_max_message_chars() -> None:
    huge_title = "x" * 2000
    rendered = format_alert(
        AlertPayload(
            severity=Severity.MEDIUM,
            code="x",
            title=huge_title,
        )
    )
    assert len(rendered) <= MAX_MESSAGE_CHARS


def test_format_alert_is_privacy_safe_for_normal_input() -> None:
    rendered = format_alert(
        AlertPayload(
            severity=Severity.CRITICAL,
            code="refund_risk",
            title="Refund risk on luna_main",
            account_username="luna_main",
            chatter_name="Mia",
            action="Review last hour of messages in dashboard.",
            ref="qc/xyz",
        )
    )
    # Should not raise — no fan handle in the input, no patterns in output.
    assert_privacy_safe(rendered, forbidden_substrings=("fan_handle_xyz", "@somefan"))


# ── format_rollup ────────────────────────────────────────────────────────────


def test_format_rollup_renders_summary_lines_and_refs() -> None:
    rendered = format_rollup(
        RolledUpPayload(
            severity=Severity.MEDIUM,
            window_label="last 30 min",
            total_findings=12,
            chatter_count=3,
            account_count=2,
            lines=(
                "luna_main / Mia: 4× lazy_reply, 1× missed_buying_signal",
                "luna_main / Sam: 3× slow_response (median 9 min)",
            ),
            action="Review Mia's last hour first.",
            refs=("qc/1", "qc/2"),
        )
    )
    assert "🟧 [QC] Chatter QC — last 30 min" in rendered
    assert "12 issues across 3 chatter(s), 2 account(s)" in rendered
    assert "• luna_main / Mia" in rendered
    assert "Refs: qc/1, qc/2" in rendered


# ── assert_privacy_safe ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "leaky_text",
    [
        "see https://discord.com/api/webhooks/123456789/abcDEF_ghi-jkl",
        "see https://discordapp.com/api/webhooks/9/secret",
        "see https://canary.discord.com/api/v10/webhooks/1/abc",
        "see https://ptb.discord.com/api/webhooks/1/abc",
    ],
)
def test_privacy_guard_rejects_webhook_urls(leaky_text: str) -> None:
    with pytest.raises(PrivacyViolation):
        assert_privacy_safe(leaky_text)


def test_privacy_guard_rejects_discord_bot_token_pattern() -> None:
    # 24+.6+.27+ base64url segments — synthetic but matches the shape.
    fake_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0.AbCdEf.thisIsTwentySevenCharsLong___"
    with pytest.raises(PrivacyViolation):
        assert_privacy_safe(f"token leak: {fake_token}")


def test_privacy_guard_rejects_caller_supplied_substring() -> None:
    with pytest.raises(PrivacyViolation):
        assert_privacy_safe("Chatter Mia replied to fan_handle_xyz", forbidden_substrings=("fan_handle_xyz",))


def test_privacy_guard_ignores_blank_substrings() -> None:
    # Empty strings must not trigger — "" in any text is always True.
    assert_privacy_safe("safe text", forbidden_substrings=("", "  ", None))  # type: ignore[arg-type]


def test_privacy_guard_passes_clean_text() -> None:
    assert_privacy_safe(
        "🟥 [QC] Account access lost — luna_main\nAction: re-auth\nRef: qc/abc",
        forbidden_substrings=("fan_handle_xyz",),
    )
