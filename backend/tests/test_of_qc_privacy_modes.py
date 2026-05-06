# ruff: noqa: INP001
"""Privacy mode scaffold tests.

Pins three things:
  • SAFE_SUMMARY is the default everywhere.
  • Requesting INTERNAL_DETAIL falls back to SAFE_SUMMARY at render time
    until every gate is open AND the renderer is implemented (it isn't).
  • The dispatcher's privacy guards (already pinned by other tests)
    still apply regardless of the requested mode.
"""

from __future__ import annotations

import pytest

from app.services.of_intelligence.qc.privacy_modes import (
    PrivacyMode,
    effective_mode,
    internal_detail_gate_open,
)

# ── PrivacyMode.coerce ─────────────────────────────────────────────────────


def test_coerce_defaults_to_safe_summary_for_blank_or_unknown() -> None:
    assert PrivacyMode.coerce(None) is PrivacyMode.SAFE_SUMMARY
    assert PrivacyMode.coerce("") is PrivacyMode.SAFE_SUMMARY
    assert PrivacyMode.coerce("nonsense") is PrivacyMode.SAFE_SUMMARY


def test_coerce_round_trips_known_values() -> None:
    assert PrivacyMode.coerce("safe_summary") is PrivacyMode.SAFE_SUMMARY
    assert PrivacyMode.coerce(" SAFE_SUMMARY ") is PrivacyMode.SAFE_SUMMARY
    assert PrivacyMode.coerce("internal_detail") is PrivacyMode.INTERNAL_DETAIL
    assert PrivacyMode.coerce(PrivacyMode.SAFE_SUMMARY) is PrivacyMode.SAFE_SUMMARY


# ── Gate ───────────────────────────────────────────────────────────────────


def test_internal_detail_gate_closed_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MC_OF_QC_DISCORD_INTERNAL_DETAIL_CHANNEL_OK", raising=False)
    assert internal_detail_gate_open() is False


def test_internal_detail_gate_opens_with_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MC_OF_QC_DISCORD_INTERNAL_DETAIL_CHANNEL_OK", "1")
    assert internal_detail_gate_open() is True


# ── effective_mode ─────────────────────────────────────────────────────────


def test_effective_mode_returns_safe_when_safe_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MC_OF_QC_DISCORD_INTERNAL_DETAIL_CHANNEL_OK", "1")
    assert (
        effective_mode(requested=PrivacyMode.SAFE_SUMMARY, excerpt_cap=40)
        is PrivacyMode.SAFE_SUMMARY
    )


def test_effective_mode_refuses_internal_detail_when_gate_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MC_OF_QC_DISCORD_INTERNAL_DETAIL_CHANNEL_OK", raising=False)
    assert (
        effective_mode(requested=PrivacyMode.INTERNAL_DETAIL, excerpt_cap=40)
        is PrivacyMode.SAFE_SUMMARY
    )


def test_effective_mode_refuses_internal_detail_with_invalid_excerpt_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MC_OF_QC_DISCORD_INTERNAL_DETAIL_CHANNEL_OK", "1")
    for bad_cap in (None, 0, -1, 9999):
        assert (
            effective_mode(requested=PrivacyMode.INTERNAL_DETAIL, excerpt_cap=bad_cap)
            is PrivacyMode.SAFE_SUMMARY
        )


def test_effective_mode_still_refuses_when_renderer_unimplemented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Final guard: even with channel + excerpt_cap valid, INTERNAL_DETAIL
    rendering is not yet implemented in v1.  ``effective_mode`` MUST stay
    on SAFE_SUMMARY until the renderer ships and this guard is removed."""
    monkeypatch.setenv("MC_OF_QC_DISCORD_INTERNAL_DETAIL_CHANNEL_OK", "1")
    assert (
        effective_mode(requested=PrivacyMode.INTERNAL_DETAIL, excerpt_cap=40)
        is PrivacyMode.SAFE_SUMMARY
    )
