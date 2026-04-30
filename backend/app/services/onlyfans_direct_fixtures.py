"""Direct OnlyFans connector — fixture data for dry-run mode.

Sprint 7: synthetic, deterministic fixtures used by the disabled
connector shell's ``dry_run`` path. **No real OnlyFans names,
handles, fans, messages, revenue figures, or images are present in
this file.** Anyone reading it should be able to tell at a glance
that nothing here came from a real account.

Naming discipline:

- Creator handle prefix: ``test-creator-``.
- Fan handle prefix: ``test-fan-``.
- Message bodies: short generic placeholders. No emoji, no
  endearments, no product names — even synthetic content can leak
  intent if it sounds real.
- Revenue numbers: round, low, obviously synthetic.

These fixtures are returned only by
:func:`fixture_payload_for`. The disabled connector shell currently
*computes and discards* the fixture in its dry-run path; the
function exists so that a Sprint 8+ dry-run-with-display flow can
plug it into a UI without leaking real data.
"""

from __future__ import annotations

from typing import Any, Final

# Per-action fixture payloads. Keys MUST be a subset of
# :data:`app.core.onlyfans_direct_policy.READ_ACTIONS`. Any read action
# that is later added but does not have a fixture here will fall through
# to :data:`_DEFAULT_FIXTURE` so the dry-run path keeps working.
_FIXTURES: Final[dict[str, dict[str, Any]]] = {
    "account_profile_read": {
        "creator_handle": "test-creator-001",
        "display_name": "Test Creator (synthetic)",
        "joined_iso": "2024-01-15T00:00:00+00:00",
        "subscription_tier_count": 1,
        "synthetic": True,
    },
    "account_stats_read": {
        "creator_handle": "test-creator-001",
        "subscriber_count": 100,
        "renewal_rate_pct": 50,
        "active_chats": 5,
        "synthetic": True,
    },
    "revenue_summary_read": {
        "creator_handle": "test-creator-001",
        "currency": "USD",
        "month_to_date": 100,
        "previous_month": 200,
        "tips_subtotal": 0,
        "ppv_subtotal": 0,
        "subscription_subtotal": 100,
        "synthetic": True,
    },
    "fan_list_metadata_read": {
        "creator_handle": "test-creator-001",
        "fan_count_metadata": 100,
        "fans_sample_metadata": [
            {
                "fan_handle": "test-fan-001",
                "tier": "monthly",
                "active_since_iso": "2024-02-01T00:00:00+00:00",
            },
            {
                "fan_handle": "test-fan-002",
                "tier": "monthly",
                "active_since_iso": "2024-03-01T00:00:00+00:00",
            },
        ],
        "synthetic": True,
    },
    "chat_thread_metadata_read": {
        "creator_handle": "test-creator-001",
        "thread_count": 2,
        "threads": [
            {
                "thread_id": "thread-001",
                "fan_handle": "test-fan-001",
                "last_event_iso": "2024-04-01T00:00:00+00:00",
            },
            {
                "thread_id": "thread-002",
                "fan_handle": "test-fan-002",
                "last_event_iso": "2024-04-02T00:00:00+00:00",
            },
        ],
        "synthetic": True,
    },
    "chat_message_read": {
        "creator_handle": "test-creator-001",
        "thread_id": "thread-001",
        "messages": [
            {
                "message_id": "m-001",
                "from": "fan",
                "body_redaction_status": "synthetic_placeholder",
                "sent_iso": "2024-04-01T00:00:00+00:00",
            },
            {
                "message_id": "m-002",
                "from": "creator",
                "body_redaction_status": "synthetic_placeholder",
                "sent_iso": "2024-04-01T00:01:00+00:00",
            },
        ],
        "synthetic": True,
    },
    "vault_metadata_read": {
        "creator_handle": "test-creator-001",
        "vault_item_count": 3,
        "items": [
            {
                "vault_item_id": "v-001",
                "kind": "image",
                "uploaded_iso": "2024-01-20T00:00:00+00:00",
            },
            {
                "vault_item_id": "v-002",
                "kind": "video",
                "uploaded_iso": "2024-02-10T00:00:00+00:00",
            },
            {
                "vault_item_id": "v-003",
                "kind": "image",
                "uploaded_iso": "2024-03-05T00:00:00+00:00",
            },
        ],
        "synthetic": True,
    },
    "post_metadata_read": {
        "creator_handle": "test-creator-001",
        "post_count": 2,
        "posts": [
            {"post_id": "p-001", "kind": "image", "scheduled_iso": "2024-04-10T00:00:00+00:00"},
            {"post_id": "p-002", "kind": "text", "scheduled_iso": "2024-04-15T00:00:00+00:00"},
        ],
        "synthetic": True,
    },
    "story_metadata_read": {
        "creator_handle": "test-creator-001",
        "story_count": 0,
        "stories": [],
        "synthetic": True,
    },
    "mass_message_metadata_read": {
        "creator_handle": "test-creator-001",
        "campaign_count": 1,
        "campaigns": [
            {
                "campaign_id": "c-001",
                "kind": "ppv",
                "scheduled_iso": "2024-04-20T00:00:00+00:00",
                "recipient_count_metadata": 50,
            },
        ],
        "synthetic": True,
    },
}


_DEFAULT_FIXTURE: Final[dict[str, Any]] = {
    "synthetic": True,
    "note": "default_fixture_for_unspecified_read_action",
}


def fixture_payload_for(action: str) -> dict[str, Any]:
    """Return a synthetic, read-only fixture payload for ``action``.

    The returned dict is a fresh copy each call so callers can
    annotate it without mutating the canonical fixture. Every payload
    carries ``synthetic: True`` so any leak into logs / UI / audit
    metadata is unambiguously a fixture.
    """
    payload = _FIXTURES.get(action, _DEFAULT_FIXTURE)
    return dict(payload)
