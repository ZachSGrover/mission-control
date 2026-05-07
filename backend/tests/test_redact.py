"""Tests for app.core.redact.redact_metadata.

Lives in backend/tests/ following the existing test layout. mypy is
disabled for the tests directory (see pyproject.toml), so we keep the
typing light.
"""

from __future__ import annotations

from app.core.redact import (
    MAX_TOTAL_BYTES,
    REDACTED_PLACEHOLDER,
    redact_metadata,
)


def test_redacts_exact_forbidden_keys() -> None:
    payload = {"username": "alice", "password": "p@ssw0rd"}
    out, redacted = redact_metadata(payload)
    assert redacted is True
    assert out["username"] == "alice"
    assert out["password"] == REDACTED_PLACEHOLDER


def test_redacts_substring_forbidden_keys() -> None:
    payload = {"oauth_access_token": "abc", "stripe_secret_key": "sk_live_x"}
    out, redacted = redact_metadata(payload)
    assert redacted is True
    assert out["oauth_access_token"] == REDACTED_PLACEHOLDER
    assert out["stripe_secret_key"] == REDACTED_PLACEHOLDER


def test_redacts_recursively_in_nested_dicts() -> None:
    payload = {"outer": {"inner": {"api_key": "k"}}}
    out, redacted = redact_metadata(payload)
    assert redacted is True
    assert out["outer"]["inner"]["api_key"] == REDACTED_PLACEHOLDER  # type: ignore[index]


def test_redacts_inside_lists() -> None:
    payload = {"items": [{"label": "ok"}, {"client_secret": "x"}]}
    out, redacted = redact_metadata(payload)
    assert redacted is True
    items = out["items"]
    assert isinstance(items, list)
    assert items[0] == {"label": "ok"}
    assert items[1] == {"client_secret": REDACTED_PLACEHOLDER}


def test_does_not_mutate_input() -> None:
    payload = {"token": "leaky"}
    snapshot = dict(payload)
    redact_metadata(payload)
    assert payload == snapshot


def test_redacted_flag_false_when_clean() -> None:
    payload = {"action": "login", "result": "success"}
    out, redacted = redact_metadata(payload)
    assert redacted is False
    assert out == payload
    # New object, not the same reference (no mutation).
    assert out is not payload


def test_top_level_non_dict_is_wrapped() -> None:
    out, _ = redact_metadata(["a", "b", "c"])
    assert out == {"value": ["a", "b", "c"]}


def test_credential_shaped_value_is_redacted_even_with_safe_key() -> None:
    payload = {"header": "Bearer eyJhbGciOiJ..."}
    out, redacted = redact_metadata(payload)
    assert redacted is True
    assert out["header"] == REDACTED_PLACEHOLDER


def test_size_cap_replaces_oversized_metadata_with_summary() -> None:
    # Use many short keys so per-value truncation doesn't hide the cap.
    payload = {f"k{i}": "x" * 256 for i in range((MAX_TOTAL_BYTES // 256) + 4)}
    out, redacted = redact_metadata(payload)
    assert redacted is True
    assert out.get("redaction_note") == "metadata exceeded size cap"
    # Importantly: the original payload is NOT in the output.
    assert all(not k.startswith("k") for k in out)


def test_unserialisable_value_is_redacted_to_repr() -> None:
    class Weird:
        def __repr__(self) -> str:
            return "Weird()"

    out, _ = redact_metadata({"thing": Weird()})
    assert out["thing"] == "Weird()"


def test_set_input_is_walked_and_sorted() -> None:
    out, _ = redact_metadata({"set_field": {"b", "a"}})
    set_field = out["set_field"]
    assert isinstance(set_field, list)
    assert sorted(set_field) == ["a", "b"]
