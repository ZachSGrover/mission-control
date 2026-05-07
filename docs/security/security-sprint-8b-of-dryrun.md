# Security Sprint 8B — Direct OnlyFans Read-Only Client + Dry-Run

**Status:** Sprint 8B of N. Adds the **typed read-only client
interface**, a **fake implementation**, a **dry-run mode** that
calls the fake through the connector gate, and a
**`connector.session.challenged`** audit category with a
notification stub. Real OnlyFans accounts are still not connectable;
real cookies/sessions are still refused; production mode does not
exist on this branch.
**Branch:** `feat/of-direct-readonly-dryrun-sprint-8b`
**Last updated:** 2026-04-30

Companion to:
- [Sprint 7 direct OF read-only prep](./security-sprint-7-direct-of-prep.md)
- [Sprint 8A OnlyMonster gated proof](./security-sprint-8a-onlymonster-gate.md)
- [Direct OnlyFans readiness checklist](./direct-onlyfans-readiness-checklist.md)

---

## 1. What was added

| Concern | Where |
|---|---|
| Read-only client Protocol + abstract base | [`backend/app/core/onlyfans_direct_client.py`](../../backend/app/core/onlyfans_direct_client.py) |
| Fake read-only client (synthetic, fixture-backed) | [`backend/app/services/onlyfans_direct_fake_client.py`](../../backend/app/services/onlyfans_direct_fake_client.py) |
| `mode="dry_run"` extension to the disabled connector shell | [`backend/app/services/onlyfans_direct_connector.py`](../../backend/app/services/onlyfans_direct_connector.py) |
| `connector.session.challenged` audit + notify stub | [`backend/app/services/onlyfans_direct_session_health.py`](../../backend/app/services/onlyfans_direct_session_health.py) |
| Security admin status surface (Sprint 8B fields) | [`backend/app/api/security_admin.py`](../../backend/app/api/security_admin.py) |
| Frontend status card (Sprint 8B fields) | [`frontend/src/app/security/page.tsx`](../../frontend/src/app/security/page.tsx), [`frontend/src/lib/security/api.ts`](../../frontend/src/lib/security/api.ts) |
| Sprint 8B tests | [`backend/tests/test_of_direct_dryrun.py`](../../backend/tests/test_of_direct_dryrun.py) |

---

## 2. Read-only client shape

`app.core.onlyfans_direct_client` exposes two surfaces:

- **`OnlyFansReadOnlyClient`** — a `typing.Protocol` (runtime
  checkable). Ten async methods, one per Sprint 7 `READ_ACTIONS`
  entry:
  - `read_account_profile`
  - `read_account_stats`
  - `read_revenue_summary`
  - `read_fan_list_metadata`
  - `read_chat_thread_metadata`
  - `read_chat_messages`
  - `read_vault_metadata`
  - `read_post_metadata`
  - `read_story_metadata`
  - `read_mass_message_metadata`
- **`AbstractOnlyFansReadOnlyClient`** — a concrete abstract base.
  Every method raises `NotImplementedError`. A real implementation
  must subclass and override each method individually. The abstract
  base is the structural lock: no callable that isn't a read method
  can be on the base class without being noticed.

**Mapping table.** `READ_ACTION_TO_METHOD: dict[str, str]` lets the
connector dispatch a single `dry_run(action=...)` call to the right
client method without a giant elif tree. Keys are exactly
`READ_ACTIONS` (verified by test).

**Forbidden surface (verified by test):** neither the Protocol nor
the abstract base may expose any callable named after a write
action or starting with a write-shaped verb (`send`, `post`,
`tip`, `delete`, `upload`, `block`, `follow`, etc.).

---

## 3. Fake client behavior

`FakeOnlyFansReadOnlyClient` (in
`app.services.onlyfans_direct_fake_client`):

- **Subclasses `AbstractOnlyFansReadOnlyClient`** — overrides each
  read method with a fixture lookup.
- **Constructor refuses cookie / session / password / x-bc /
  csrf / etc.** kwargs via
  `assert_no_forbidden_credential_keys` from Sprint 7. Same
  contract as the connector shell.
- **Production refusal.** Raises
  `FakeClientRefusedInProductionError` in production unless the
  operator explicitly sets `MC_OF_DIRECT_ALLOW_FAKE_CLIENT=1`.
- **Synthetic only.** Each method returns a fresh dict copy of the
  matching Sprint 7 fixture, with a `creator_id_echo` field added
  so a leak into logs / audit is unmistakable. The function
  refuses to return any payload that doesn't already carry
  `synthetic: True`.
- **No I/O imports.** A test walks every `onlyfans_direct_*` module
  and fails CI if any line imports `httpx`, `requests`, `aiohttp`,
  `urllib`, `http.client`, `playwright`, `selenium`,
  `browser_use`, `selenium_wire`, or `puppeteer`.

---

## 4. Dry-run behavior

`OnlyFansDirectConnector` now accepts two constructor kwargs:

- `mode: ConnectorMode = "disabled"` — `"disabled"` (Sprint 7
  default) or `"dry_run"`. Anything else raises `ValueError`. There
  is no `"production"` mode.
- `client: OnlyFansReadOnlyClient | None = None` — required when
  `mode="dry_run"`; refused otherwise (the constructor doesn't
  silently store an unused client).

The existing `dry_run(action, creator_id, ...)` method now branches:

```
1. policy check (Sprint 7)
   — write/unknown action: raise BlockedActionError or return blocked
2. connector gate (Sprint 2)
   — kill switch / approval / consent / vault
   — block: audit connector.run.blocked, return blocked DryRunResult
3a. mode == "dry_run" with client:
   — look up READ_ACTION_TO_METHOD[action] → method name
   — call client.<method>(creator_id=...)
   — compute SAFE rows_read scalar from payload (max len of any
     known list field) and DISCARD payload
   — audit connector.dry_run.pass with mode=dry_run, used_fake_client=true
   — return DryRunResult with rows_read populated, used_fake_client=true
3b. mode == "disabled" (Sprint 7 path):
   — compute fixture, discard, audit connector.dry_run.pass with
     fixture_only=true, used_fake_client=false
   — return DryRunResult with used_fake_client=false, rows_read=0
```

**Invariants:**

- The result type (`DryRunResult`) has no `payload` / `data` /
  `body` / `raw` / `messages` / `fans` field. Verified by test.
- The audit row metadata cannot leak fan PII or message bodies.
  Verified by test: `forbidden_audit_keys.isdisjoint(metadata.keys())`
  on every audit row across an allowed run.
- Sprint 7's write-refusal still raises before the gate is consulted.
- `mode="dry_run"` is **not** "real network mode." The fake client
  is the only client this sprint can construct.

---

## 5. `connector.session.challenged` audit + notify stub

`app.services.onlyfans_direct_session_health` exposes:

- `record_session_challenged(session, reason_category, ...)` —
  writes one audit row at severity `warning`, category
  `connector`, event_type `connector.session.challenged`. Metadata
  is fixed-vocabulary and small. Refuses any `extra_metadata` key
  that could leak a response body, header, cookie, or session
  token — raises `ChallengeMetadataContractViolation`.
- `notify_challenge_stub(reason_category, creator_id)` — returns
  `"not_configured"` and logs one debug line. Sends nothing in
  Sprint 8B. A future Sprint 8C+ replaces the body with a Slack /
  Telegram / email send.
- `notify_channel_status()` — returns `"not_configured"` for the
  admin UI.

**Reason vocabulary** (`ChallengeReason` Literal):
`captcha`, `login_required`, `rate_limit_response`,
`unexpected_status`, `unexpected_html`, `session_expired`,
`session_revoked`, `platform_block`, `other`.

The vocabulary is small on purpose. Future operators filtering
audit rows by `reason_category` see a finite set of buckets —
not free-form strings carrying details. New buckets must be added
in code with a corresponding test.

---

## 6. What remains blocked

| Surface | Status |
|---|---|
| Real OnlyFansReadOnlyClient implementation | **Absent.** Abstract base raises on every method. |
| Real OnlyFans account connection | **Blocked.** No client to call; no credential resolution wired. |
| Real OnlyFans credentials | **Refused.** Cookie / session / password kwargs refused at construction. |
| Real network call from any OF-direct module | **None.** No HTTP client imported in any Sprint 8B file. |
| Production mode (`mode="real"` / `"production"`) | **Does not exist.** Constructor raises `ValueError` for any mode other than `"disabled"` or `"dry_run"`. |
| Write actions | **Structurally absent.** No write method on the Protocol, the abstract base, the fake, or the connector shell. Tests assert. |
| Cookies, session storage, frontend session exposure | **Forbidden by contract.** Sprint 7's `FRONTEND_FORBIDDEN_PATTERNS` test still scans `frontend/src` for forbidden storage patterns. |
| Notification channel | **Stub only.** `notify_channel_status() == "not_configured"` until Sprint 8C+. |

---

## 7. Why production mode is still unavailable

- **The abstract base raises on every method.** A subclass that
  performed a real network call would need to be written, which is
  not on this branch. The `_REAL_CLIENT_TODO` constant in the
  connector shell still points at a non-existent module.
- **No credential resolution.** Even if a real client existed, the
  shell does not resolve a `creator_credentials` row — that wiring
  is Sprint 8C work.
- **No `mode="production"`.** Sprint 8B's `ConnectorMode` Literal is
  `disabled` or `dry_run`. Any other value raises at construction.
  Adding production mode would require a code change reviewed
  against the readiness checklist, then a fresh sprint to run a
  test account, then another sprint to graduate to a single real
  creator.
- **No challenge notifier.** Until a Slack / Telegram / email
  channel is wired, a CAPTCHA or session expiration would land in
  audit rows but no human would see it in real time. Production
  mode without a notifier is unsafe by Sprint 7's own
  `CHALLENGE_REACTION` policy.
- **No retention drill, no rotation drill, no go-live tabletop.**
  Section §9 below lists the prerequisites.

---

## 8. Requirements before one test account

In order:

1. ❌ Implement a real `OnlyFansReadOnlyClient` that subclasses
   `AbstractOnlyFansReadOnlyClient` and overrides each read
   method. The implementation lives outside this branch on a
   feature-branch named `feat/of-readonly-client` (or similar).
   The class MUST refuse cookie / session / password kwargs
   (reuse `assert_no_forbidden_credential_keys`) and MUST resolve
   credentials only via the creator credential vault.
2. ❌ Wire the real client into a Sprint 8C `mode="real"` (or
   `mode="sandbox"` — pick one; document which) that:
   - Refuses to construct unless `MC_OF_DIRECT_REAL_CLIENT_ALLOWED=1`
     is explicitly set.
   - Refuses to run unless `connector_approvals` row +
     `client_consents` row + dedicated encryption key + no kill
     switch.
   - Audits `connector.run.finish` (allow) /
     `connector.run.blocked` (block).
   - Emits `connector.session.challenged` and calls
     `notify_challenge_stub` on any non-200, non-expected response.
3. ❌ Wire a real notify channel (Slack webhook / Telegram bot /
   email) behind `notify_challenge_stub`. The audit row remains
   the source of truth; the notify is best-effort.
4. ❌ A dedicated test-only OnlyFans account whose credential is
   stored in `creator_credentials` (Fernet-encrypted, vault
   guard).
5. ❌ Owner-approved `connector_approvals` row +
   `client_consents` row for the test creator.
6. ❌ Sprint 8B dry-run with the **fake** client returns
   `allowed=true, used_fake_client=true` for the test creator
   (this Sprint can verify it).
7. ❌ Sprint 8C dry-run with the **real** client returns
   `allowed=true, used_fake_client=false` for the test creator,
   audited at `connector.run.finish` with safe metadata only.
8. ❌ Token-leak drill walked targeting the test-account
   credential.
9. ❌ Walk the readiness checklist Section D for the test
   account (sandbox-graduation).
10. ❌ 24h re-check, then 7d re-check.

Until each line is documented as ✅ in `docs/security/runs/`,
no real OnlyFans account — even a test one — should be paired.

---

## 9. Recommended Sprint 8C

**Direct OnlyFans `mode="sandbox"` graduation against one
test-only account.** Mirrors Sprint 8B's structure for the
*real* client:

- Implement `RealOnlyFansReadOnlyClient` (subclass of
  `AbstractOnlyFansReadOnlyClient`). Read-only by construction.
  Behind a separate env flag (e.g.
  `MC_OF_DIRECT_REAL_CLIENT_ALLOWED=1`) that defaults off.
- Add `mode="sandbox"` to the connector. Constructor refuses real
  client unless the env flag is set AND a sandbox-mode flag is
  set. Same gate chain as Sprint 8B.
- Wire a real notify channel (Slack webhook is the simplest first
  cut). The audit row is still the source of truth; the notify is
  for human awareness.
- Add `connector.session.challenged` emission inside the real
  client on any non-200, non-expected response. The notify is
  fire-once per session-challenge per creator per hour
  (operator-friendly cadence).
- Owner sign-off in `audit_events` with
  `event_type='connector.golive.sandbox'` and the sandbox creator
  id. Required before flipping the env flag in production.
- Walk readiness checklist Section D for the sandbox account.
- 7-day soak.

Sprint 8C should NOT touch a real creator account. That is
Sprint 8D, after at least 7 days of clean sandbox runs.

---

## 10. Sign-off scope

This sprint:

- ✅ Pins the read-only client shape (Protocol + abstract base).
- ✅ Provides a fake client with full Sprint 7 invariants
  (synthetic only, no creds, production refusal).
- ✅ Adds `mode="dry_run"` to the connector that calls the fake
  through the gate.
- ✅ Adds `connector.session.challenged` audit category with
  forbidden-key contract enforcement.
- ✅ Adds notification stub and channel-status helper.
- ✅ Surfaces all Sprint 8B fields in the security admin UI.
- ✅ Adds 29 tests (read-only shape, fake refusal in production,
  blocked / allowed paths, audit safety, no network imports,
  no write methods on any of the new surfaces).

This sprint does **not** authorise:

- A real OnlyFansReadOnlyClient implementation.
- A real OnlyFans account connection.
- Any `mode="production"` / `mode="real"` / `mode="sandbox"`.
- A live network call from any OF-direct surface.
- Lifting any kill switch, approval, consent, or vault gate.
