# Security Sprint 7 — Direct OnlyFans Read-Only Preparation

**Status:** Sprint 7 of N. Builds the **policy boundary** between
"controls exist" (Sprints 1–6) and a future direct OnlyFans
read-only connector. This sprint **does not** connect, scrape, read,
write, or even reach the network. It writes the contract a future
implementation must conform to and proves the contract holds today.
**Branch:** `feat/of-direct-readonly-prep-sprint-7`
**Last updated:** 2026-04-30

Companion to:
- [Sprint 1 audit foundation](./audit-events-implementation.md)
- [Sprint 2 prevention](./security-sprint-2-implementation.md)
- [Sprint 3 hardening](./security-sprint-3-implementation.md)
- [Sprint 4 operations](./security-sprint-4-implementation.md)
- [Sprint 5 enforcement](./security-sprint-5-implementation.md)
- [Sprint 6 readiness](./security-sprint-6-implementation.md)
- [Direct OnlyFans readiness checklist](./direct-onlyfans-readiness-checklist.md)
- [Token-leak incident drill](./incident-drill-token-leak.md)

---

## 1. What was added

| Concern | Where |
|---|---|
| Policy module — read vs write vs unknown, fail-closed | [`backend/app/core/onlyfans_direct_policy.py`](../../backend/app/core/onlyfans_direct_policy.py) |
| Disabled connector shell — no network, no real creds | [`backend/app/services/onlyfans_direct_connector.py`](../../backend/app/services/onlyfans_direct_connector.py) |
| Synthetic fixtures for dry-run path | [`backend/app/services/onlyfans_direct_fixtures.py`](../../backend/app/services/onlyfans_direct_fixtures.py) |
| Rate-limit + session-health policy scaffolding | [`backend/app/core/onlyfans_direct_rate_policy.py`](../../backend/app/core/onlyfans_direct_rate_policy.py) |
| Credential safety contract + frontend pattern guardrails | [`backend/app/core/onlyfans_direct_credentials.py`](../../backend/app/core/onlyfans_direct_credentials.py) |
| Owner-only status endpoint | [`backend/app/api/security_admin.py`](../../backend/app/api/security_admin.py) |
| Security admin UI status card | [`frontend/src/app/security/page.tsx`](../../frontend/src/app/security/page.tsx), [`frontend/src/lib/security/api.ts`](../../frontend/src/lib/security/api.ts) |
| Sprint 7 readiness tests | [`backend/tests/test_of_direct_readiness.py`](../../backend/tests/test_of_direct_readiness.py) |

---

## 2. What is still blocked

Everything that touches a real OnlyFans account is still blocked.
Specifically:

- **Connector enabled:** no. `OnlyFansDirectConnector.status().enabled` is hard-coded `False`.
- **Real client wired:** no. `OnlyFansDirectConnector.fetch()` raises `ConnectorNotEnabledError`.
- **Real credentials:** none stored, none accepted. Constructor refuses cookie/session keys.
- **Cookies, session blobs, frontend session storage:** all forbidden by contract; CI test scans the frontend for forbidden patterns.
- **Live network calls:** no HTTP client is attached to the shell.
- **Write actions:** structurally absent. The shell exposes no method named after any write action; the policy refuses any write action at the verdict layer.
- **Mass message, tipping, post/story create/edit/delete, vault edit/upload/delete, fan block, follow, account settings, payouts, login change:** all in `WRITE_ACTIONS`; refusal verified by tests.

---

## 3. Allowed future read categories

Defined in `app.core.onlyfans_direct_policy.READ_ACTIONS`. Adding a
read action requires editing this set in code, which is reviewable.

| Action | Intent |
|---|---|
| `account_profile_read` | Public-style profile metadata |
| `account_stats_read` | Subscriber count, renewal rate, active chat count |
| `revenue_summary_read` | Aggregate revenue by category for a window |
| `fan_list_metadata_read` | Fan handles + tier metadata, no message bodies |
| `chat_thread_metadata_read` | Thread index for one creator |
| `chat_message_read` | Body of one chat message (PII redaction layer applies) |
| `vault_metadata_read` | Vault item index — id, kind, upload time |
| `post_metadata_read` | Post index + scheduling state |
| `story_metadata_read` | Story index + expiry state |
| `mass_message_metadata_read` | Campaign index — counts, scheduling |

Even when an action is in this list, the connector gate must still
pass (kill switches off, approval present, consent live, vault
available) before any future implementation actually performs it.

---

## 4. Hard-blocked write categories

Defined in `app.core.onlyfans_direct_policy.WRITE_ACTIONS`. The 20
actions named in the brief are all present; a unit test asserts the
exact set.

| Group | Actions |
|---|---|
| Messaging | `message_send`, `mass_message_send` |
| Posts / stories | `post_create`, `post_edit`, `post_delete`, `story_create`, `story_delete` |
| Vault | `vault_upload`, `vault_edit`, `vault_delete` |
| Money | `tip_send`, `price_change`, `subscription_change`, `payout_update` |
| Fan management | `fan_block`, `fan_unblock`, `follow`, `unfollow` |
| Account | `account_settings_update`, `login_change` |

Even if a future operator removed an action from this set, the
connector shell still has no method that could perform it. Both the
policy layer and the shell would have to be modified for a write to
ship; the Sprint 7 test
`test_connector_exposes_no_write_method` would catch any new
write-shaped public method.

---

## 5. Dry-run and fixture mode

`OnlyFansDirectConnector.dry_run(...)` is the **only** execution
surface this sprint exposes. It runs the full safety chain without
touching the network:

1. **Policy check.** Write actions raise `BlockedActionError` *before*
   the gate is consulted. Unknown actions are returned as a blocked
   verdict (no raise — so unit tests of unknown-input handling don't
   need to rebuild a try/except).
2. **Connector gate check.** Composes kill-switches, approval,
   consent, and vault availability via
   `is_connector_action_allowed(connector_type="onlyfans_direct", requested_action="read", ...)`.
3. **Fixture compute-and-discard.** On full pass-through, the shell
   computes a synthetic fixture payload from
   `app.services.onlyfans_direct_fixtures` and **immediately discards
   it**. The audit row records that the chain passed; no payload is
   persisted, returned, or rendered.

Dry-run output (`DryRunResult`) includes:

- `allowed` (bool)
- `classification` — `read` / `write` / `unknown`
- `policy_reason` — short machine-readable string
- `gate_reason` and `gate_detail` — from the connector gate verdict
- `connector_type`, `requested_action`, `creator_id`, `organization_id`
- `audit_event_id` — id of the row written to `audit_events`
- `used_fixture` — bool; only `True` when the chain fully passed
- `notes` — short safe label for UI / runbook

There is no `payload`, `data`, `body`, or `raw` field. Tests assert
no such field exists on the dataclass.

Fixture data uses `test-creator-NNN` / `test-fan-NNN` placeholder
prefixes, round/low revenue numbers, and explicit `synthetic: true`
markers. No real OnlyFans names, handles, fans, messages, or revenue
appear anywhere in the codebase.

---

## 6. Credential safety rules

`app.core.onlyfans_direct_credentials` codifies the contract:

1. **Vault-only.** Future credentials must use
   `app.services.creator_credentials` (encrypted Fernet at rest,
   `is_dedicated_encryption_key_configured()` guard required).
2. **No raw cookies.** `Set-Cookie`, browser-export blobs, OnlyFans
   `x-bc`, `auth_id`, `sess` etc. — never enter the vault as a
   credential value or metadata field.
3. **No frontend session storage.**
   `localStorage.setItem('of_session*')`,
   `sessionStorage.setItem('of_session*')`,
   `document.cookie = 'of_session*'`, and the literals
   `OF_RAW_COOKIE` / `ONLYFANS_RAW_SESSION` are forbidden. A test
   scans `frontend/src` and fails CI on a hit.
4. **No credential value in API responses.** Status surfaces return
   booleans and enums only. The Sprint 7 endpoint
   `GET /security/onlyfans-direct/status` is the canonical example.
5. **Revocation runbook** and **rotation runbook** are encoded as
   strings the admin UI can render — the procedure stays close to
   the code so it cannot drift.

Constructor refusal on `cookie` / `session` / `password` / `x_bc` / etc.
is verified by `test_connector_refuses_cookie_or_session_kwargs`.

---

## 7. Rate-limit plan

Defined in `app.core.onlyfans_direct_rate_policy`:

- `DEFAULT_MAX_REQUESTS_PER_MINUTE = 10`
- `DEFAULT_MAX_REQUESTS_PER_HOUR = 200`
- `DEFAULT_BACKOFF = BackoffPolicy(initial=2.0s, max=300.0s, jitter=20%, retries=4)`

Conservative by design. Any future implementation should:

- Start at `initial_seconds` for the first retry.
- Double on each subsequent retry.
- Cap at `max_seconds`.
- Add up to `jitter_fraction * delay` random jitter to desynchronise
  multi-instance retries.
- Stop after `max_retries` and write a session-health audit.

A Sprint 7 test catches silent inflation of any of these constants.

---

## 8. Session health plan

Narrow `SessionHealth` enum:
`disabled` | `not_configured` | `healthy` | `challenged` | `expired` | `revoked` | `blocked` | `error`.

`is_unhealthy(status)` returns `True` for everything except
`healthy` / `disabled` / `not_configured`.

`CHALLENGE_REACTION` is the procedure on a CAPTCHA / login challenge
or other bot-detection signal:

- **stop** — halt in-flight session immediately.
- **audit** — write `connector.session.challenged` row (future Sprint
  8+ implementation).
- **notify** — alert the operator.
- **require_manual_review** — flip session to `challenged`, refuse
  new runs.

The implementation must NOT silently retry a challenge. The Sprint 7
test asserts all four flags are `True`.

---

## 9. Readiness status

| Track | Status |
|---|---|
| Sprint 1–6 foundation | ✅ landed; see prior implementation docs |
| OnlyMonster gated wrapper | ✅ Sprint 5; default-off env flag |
| OnlyMonster real-client seam | ✅ Sprint 6; awaiting OFI-branch merge |
| Direct OnlyFans policy module | ✅ Sprint 7 (this sprint) |
| Direct OnlyFans disabled shell | ✅ Sprint 7 |
| Direct OnlyFans dry-run + fixtures | ✅ Sprint 7 |
| Direct OnlyFans rate-limit policy | ✅ Sprint 7 (constants + types) |
| Direct OnlyFans session-health enum | ✅ Sprint 7 |
| Direct OnlyFans credential contract | ✅ Sprint 7 |
| Direct OnlyFans real client | ❌ does not exist on this branch |
| Real OnlyFans account connection | ❌ blocked |
| Direct OnlyFans write actions | ❌ structurally absent |

---

## 10. Requirements before a real test account

Before turning on a real but **non-creator** test OnlyFans account
behind the future read-only connector:

1. ✅ Sprint 1–7 foundation in place (this sprint completes the
   structural prep).
2. ❌ Implement a real `OnlyFansReadOnlyClient` that satisfies:
   - Implements only methods named after `READ_ACTIONS` entries.
   - Has no method that performs a write of any kind.
   - Goes through the connector shell's dry-run path first against
     synthetic fixtures, then is wrapped into a `mode="dry_run"`
     graduation behind the readiness checklist.
3. ❌ Add `mode="dry_run"` to the shell that calls the real client
   for read-only fetches against the test account.
4. ❌ Set up a dedicated test-only OnlyFans account whose credential
   lives in the creator credential vault.
5. ❌ Owner approval row in `connector_approvals` for the test
   creator with `connector_type="onlyfans_direct"`,
   `requested_action="read"`.
6. ❌ Live `client_consents` row with `consent_type="onlyfans_direct_read"`
   for the test creator, signed by the operator (test-account
   self-consent is acceptable here).
7. ❌ Wire `connector.session.challenged` audit category and an
   actual notify path (Slack/Telegram) so a challenge cannot go
   unnoticed.
8. ❌ Walk the `direct-onlyfans-readiness-checklist.md` Sections A–D
   end-to-end with this test account; document the result in
   `docs/security/runs/`.
9. ❌ Run the token-leak drill (`incident-drill-token-leak.md`)
   targeting the test-account credential to prove rotation works.

Until every line above is ✅, no real OnlyFans account — even a
test one — should be paired.

---

## 11. Requirements before real client accounts

Adds on top of §10:

1. ✅ Sprint 1–7 foundation.
2. ❌ Section D of `direct-onlyfans-readiness-checklist.md` complete
   for one real creator (signed consent, agency legal review,
   geography review).
3. ❌ Token-leak drill walked within the last 90 days for the
   OnlyFans-direct credential variant specifically.
4. ❌ Creator-account-compromise tabletop walked with the agency
   principal within the last 90 days.
5. ❌ Owner sign-off recorded in `audit_events` with
   `event_type='connector.golive'`, `creator_id=<id>`, and approving
   actor.
6. ❌ Rollback plan documented and rehearsed (revoke credential +
   purge data + notify creator within 1 hour).
7. ❌ 24h and 7d post-go-live re-checks scheduled and assigned.
8. ❌ A legal opinion on platform ToS posture for the read-only
   integration (referenced in `breach-response-plan.md` §4.2).

---

## 12. Recommended Sprint 8

Two paths the next sprint can take. They are not mutually exclusive
but should not be combined into one sprint.

### Sprint 8A — OnlyMonster-first (low-risk graduation)

Wire the real OnlyMonster client into Sprint 6's seam
(`fetch_creator_snapshot`), behind
`MC_ONLYMONSTER_GATED_SYNC_ENABLED=1` and an approval+consent for a
single sandbox creator. No direct OnlyFans work. Output: the first
end-to-end gated read against a non-Mission-Control account, with
real audit rows.

Why first: it exercises the full chain on a less-hostile platform
(OnlyMonster API exists; OnlyFans direct does not). The patterns
proved here are the patterns Sprint 8B will copy.

### Sprint 8B — Direct OnlyFans `mode="dry_run"` graduation

Add `mode="dry_run"` to `OnlyFansDirectConnector` that calls a
real (but isolated) OnlyFans read-only client against a single
test-only account. Still no production mode, no client accounts.
Adds the `connector.session.challenged` audit category, the
challenge notify path, and a session-health background probe that
runs at most once per 24h.

Why second: it depends on the read-only client existing, which is
the largest piece of unbuilt code in the system. Doing 8A first
proves we can run Sprint 8 cleanly on a platform we have access to;
then 8B does the harder work knowing the patterns work.

### Sprint 8C (deferred, do NOT combine)

A direct OnlyFans `mode="real"` graduation against one real client
creator. Requires §11 above to be ✅ end-to-end. Should be its own
sprint with a single goal: take one creator live behind the
read-only connector and prove 7-day stability.

---

## 13. Sign-off scope

This sprint:

- ✅ Defines the read/write/unknown action vocabulary.
- ✅ Disables the connector by structure and tests the disabling.
- ✅ Provides a fixture-only dry-run that proves the safety chain.
- ✅ Codifies rate-limit, session-health, and credential safety
  policies.
- ✅ Surfaces the disabled state in the security admin UI.
- ✅ Adds 23 tests proving every refusal path.

This sprint does **not** authorise:

- A real OnlyFans account connection.
- A real `OnlyFansReadOnlyClient` import.
- A `mode="dry_run"` that actually calls the network.
- Any write of any kind through the OnlyFans direct path.
- Lifting any kill switch, approval, or consent gate.
