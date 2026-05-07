# Security Sprint 8E — Direct OnlyFans Sandbox Transport

**Status:** Sprint 8E of N. Wires the **real HTTP transport** for the
three Sprint 8D account-level reads, behind hard environment flags,
credential vault references, and the full Sprint 8C sandbox gate.
The transport itself is real (uses `httpx`), but it is impossible to
construct unless every gate is satisfied. **No real OnlyFans
account is connected by this branch; no client account is reachable;
production mode does not exist.**
**Branch:** `feat/of-direct-sandbox-transport-sprint-8e`
**Last updated:** 2026-04-30

Companion to:
- [Sprint 8C direct OF sandbox](./security-sprint-8c-of-sandbox.md)
- [Sprint 8D direct OF sandbox reads](./security-sprint-8d-of-sandbox-reads.md)
- [Direct OnlyFans readiness checklist](./direct-onlyfans-readiness-checklist.md)

---

## 1. What was added

| Concern | Where |
|---|---|
| Real HTTP transport using `httpx` | [`backend/app/services/onlyfans_direct_transport.py`](../../backend/app/services/onlyfans_direct_transport.py) |
| Vault-backed credential loader | [`backend/app/services/onlyfans_direct_credential_loader.py`](../../backend/app/services/onlyfans_direct_credential_loader.py) |
| `build_safe_notify_payload` helper | [`backend/app/services/onlyfans_direct_session_health.py`](../../backend/app/services/onlyfans_direct_session_health.py) |
| Owner sign-off admin endpoint | [`backend/app/api/security_admin.py`](../../backend/app/api/security_admin.py) |
| Method allowlist + early refusal in sandbox path | [`backend/app/services/onlyfans_direct_connector.py`](../../backend/app/services/onlyfans_direct_connector.py) |
| Status fields: `real_client_env_flag_set`, `sandbox_transport_configured`, `sandbox_signoff_endpoint_path` | [`backend/app/api/security_admin.py`](../../backend/app/api/security_admin.py), [`frontend/src/lib/security/api.ts`](../../frontend/src/lib/security/api.ts), [`frontend/src/app/security/page.tsx`](../../frontend/src/app/security/page.tsx) |
| Sprint 8E tests | [`backend/tests/test_of_direct_sandbox_transport.py`](../../backend/tests/test_of_direct_sandbox_transport.py) |
| Walker tests updated with per-file allowlist for `httpx` | [`backend/tests/test_of_direct_dryrun.py`](../../backend/tests/test_of_direct_dryrun.py), [`backend/tests/test_of_direct_sandbox_reads.py`](../../backend/tests/test_of_direct_sandbox_reads.py), [`backend/tests/test_of_direct_sandbox.py`](../../backend/tests/test_of_direct_sandbox.py) |

---

## 2. Transport rules

`RealHTTPTransport` enforces the following invariants:

1. **Construction is gated.** Refuses unless ALL of:
   - Non-production environment.
   - `MC_OF_DIRECT_SANDBOX_ALLOWED=1` (Sprint 8C).
   - `MC_OF_DIRECT_REAL_CLIENT_ALLOWED=1` (Sprint 8D constant; now
     enforced).
   - Non-empty `base_url` constructor arg.
2. **Constructor signature is value-free.** `base_url: str` and
   `credential_loader: CredentialLoader` are the only kwargs; no
   cookie / session / password / token kwarg can be passed
   (Python's keyword-only signature alone enforces this).
3. **No HTTP attribute leaks.** The transport stores only `_base_url`
   and `_loader`. No cookie / session / material attribute exists
   after construction (verified by test
   `test_real_transport_has_no_credential_attribute_after_construction`).
4. **`fetch` is the only method.** The Protocol has one method:
   `async fetch(*, path, params=None) -> TransportResponse`.
5. **Header summary filter.** `safe_header_summary()` drops every
   key not in `_SAFE_HEADER_KEYS` = `{content-type, content-length,
   x-ratelimit-remaining, x-ratelimit-limit, retry-after}`. No
   `Set-Cookie`, no `Authorization`, no `X-BC` ever appears in a
   response summary.
6. **Module-level `httpx` import is allowlisted to this one file.**
   Three walker tests (Sprint 8B, 8C, 8D) carry an explicit
   per-file allowlist that names `onlyfans_direct_transport.py` and
   only that file. Any other OF-direct module that imports `httpx`
   fails CI.
7. **`follow_redirects=False`.** A 3xx is itself a challenge signal
   (login redirects). Returned as
   `ChallengeDetectedError(reason_category="other")`.
8. **Conservative timeouts.** Connect 10s, read 20s. Lower values
   require code review.

---

## 3. Credential resolution rules

`VaultBackedCredentialLoader` (in
`onlyfans_direct_credential_loader.py`) is the only Sprint 8E
implementation of `CredentialLoader`. Rules:

1. **Input is a `CredentialReference` only.** No credential value
   passed through frontend, no value-shaped kwarg in any call site.
2. **Decryption inside `load()`.** The plaintext lives in a local
   variable for the duration of the JSON parse and material build,
   then is replaced by an empty string before return.
3. **No credential value returned.** The loader returns
   `CredentialMaterial(cookie?, authorization?, user_agent?)` —
   header-shaped only, bounded length, parsed through an allowlist.
4. **Wire-shape allowlist.** The encrypted blob must decrypt to a
   JSON object. Only the keys `cookie`, `authorization`,
   `user_agent` are read. Unknown keys are dropped silently.
5. **Refusals.** Missing row → `CredentialLoaderError`. Revoked /
   rotated / stale / wrong-provider → same. Non-JSON / non-dict
   plaintext → same.
6. **Audit only metadata.** The loader does not audit; the
   transport / connector wrapper handles audit. When the loader
   raises, the transport translates to either
   `CredentialLoaderError` (propagated to the connector wrapper)
   or `UnexpectedStatusError` (for opaque failures so the connector
   audits a failure row without leaking the loader's exception text).
7. **No attribute holds plaintext.** The dataclass has only
   `session` and `ref`; both are inputs the operator already has.

The transport's `fetch` clears the `headers` dict in a `finally`
block so the credential values placed there for the request are
dropped before any subsequent code path can see them.

---

## 4. Challenge detection

`RealHTTPTransport.classify_status` is a pure function (the test
suite drives the matrix without standing up an httpx mock):

| Status | Behavior |
|---|---|
| 200 + JSON content-type + non-empty body | success → return `TransportResponse` |
| 401 | `ChallengeDetectedError("login_required")` |
| 403 | `ChallengeDetectedError("captcha")` |
| 429 | `ChallengeDetectedError("rate_limit_response")` |
| 500–599 | `UnexpectedStatusError(status)` |
| 200 + HTML content-type | `ChallengeDetectedError("unexpected_html")` |
| 200 + empty body | `UnexpectedStatusError(status)` |
| 3xx redirect (with `follow_redirects=False`) | `ChallengeDetectedError("other")` |
| 200 + malformed JSON | `UnexpectedStatusError(status)` |

The connector wrapper (`dry_run_sandbox`) catches each:

- `ChallengeDetectedError` → `connector.session.challenged` audit
  row + `DEFAULT_NOTIFIER.notify(...)` + `SandboxResult(blocked_reason="challenge_detected")`.
- `UnexpectedStatusError` → `connector.sandbox.failed` audit row
  (status code only) + `SandboxResult(blocked_reason="unexpected_status")`.
- `CredentialLoaderError` → caught at transport, surfaced as
  the appropriate result.

**No raw response body / cookies / session values are ever logged
or audited.** Verified by Sprint 8D's
`test_no_raw_body_or_cookies_in_any_audit_row_after_sandbox_success`
plus Sprint 8E's `safe_header_summary` test.

---

## 5. Notifier status

Sprint 8E does NOT wire a real Slack/Telegram channel because no
existing safe abstraction is present in the repo. The Sprint 8C
`ChallengeNotifier` Protocol + `NoOpChallengeNotifier` default
remain in place. New in Sprint 8E:

- `build_safe_notify_payload(reason_category, creator_id,
  connector_type, timestamp_iso, safe_action_label) -> dict[str, str]`
  — constructs an audit-safe payload dict with bounded values and
  no forbidden keys. A future real notifier serialises this dict
  to its channel format.
- The Sprint 8E test `test_build_safe_notify_payload_strips_sensitive_fields`
  asserts no `cookie`, `set_cookie`, `session*`, `auth_token`,
  `csrf`, `x-bc`, `response_body`, `raw_body`, `html`,
  `headers`, `credential_value`, or `encrypted_value` key is in
  the output.
- Sprint 8F (or operator-driven config) will replace
  `DEFAULT_NOTIFIER` with `SlackChallengeNotifier(webhook_url)` or
  `TelegramChallengeNotifier(bot_token, chat_id)` behind the same
  Protocol — without touching call sites.

---

## 6. Owner sign-off endpoint

`POST /api/v1/security/onlyfans-direct/sandbox-signoff`:

- Owner-gated via `require_owner`.
- Body: `{ creator_id: str, notes: str | null }`.
- Records `connector.golive.sandbox` audit row (severity `high`)
  via Sprint 8C's `record_owner_signoff()`.
- Returns `{ creator_id, audit_event_id, notes_recorded }`.
- Refuses empty `creator_id` with HTTP 400.
- Does NOT auto-approve the connector or grant consent.
- Does NOT run a read.
- Does NOT auto-call from production code; tests use the helper
  fixtures, operators call the endpoint by hand.

The Sprint 8C sandbox gate refuses to run unless this audit row
exists for the creator.

---

## 7. Three allowed reads

Defined in `ALLOWED_SANDBOX_ACTIONS` (in `onlyfans_direct_connector.py`):

- `account_profile_read`
- `account_stats_read`
- `revenue_summary_read`

The sandbox gate now does an **early refusal** for any other
action, before the connector gate is consulted. The result still
audits `connector.sandbox.blocked` with reason
`real_client_not_enabled`, but the message is more useful for
runbooks: it names the allowlist and says "other read methods are
still unimplemented."

---

## 8. Blocked reads

These remain blocked at three layers:

1. **Sprint 8E allowlist** — early refusal in `dry_run_sandbox`.
2. **Sprint 8B abstract base** — every method on
   `AbstractOnlyFansReadOnlyClient` raises `NotImplementedError`.
3. **Sprint 8D unimplemented bodies** — the seven unimplemented
   read methods on `RealOnlyFansReadOnlyClient` raise
   `RealClientNotEnabledError` with no transport interaction.

Names: `read_fan_list_metadata`, `read_chat_thread_metadata`,
`read_chat_messages`, `read_vault_metadata`, `read_post_metadata`,
`read_story_metadata`, `read_mass_message_metadata`.

---

## 9. Requirements before one test account

Status now (Sprint 8E):

- ✅ Real HTTP transport wired (httpx).
- ✅ Vault-backed credential loader.
- ✅ Challenge detection matrix (401/403/429/5xx/HTML/empty/redirect/malformed).
- ✅ Owner sign-off endpoint.
- ✅ Method allowlist for sandbox.
- ❌ Real `ChallengeNotifier` (Slack webhook / Telegram bot).
- ❌ Pair test-only OnlyFans credential into the encrypted vault
  (operator action).
- ❌ Confirm the operator's chosen `base_url` resolves correctly
  to the test sandbox endpoint (not production OnlyFans).
- ❌ Replace the synthetic path constants in
  `onlyfans_direct_real_client.py` (`/sandbox/account/profile`
  etc.) with the actual endpoint URLs the test sandbox server
  accepts.
- ❌ Owner records `connector.golive.sandbox` for the test
  creator via the new endpoint.
- ❌ Run sandbox dry-run with the real transport against the test
  sandbox; verify safe metadata only and `rows_written=0`.
- ❌ Token-leak drill targeting the test-account credential.
- ❌ 24h then 7d re-checks.

---

## 10. Endpoint review checklist (binding before any real fetch)

Before the operator points `RealHTTPTransport` at a real
OnlyFans-compatible endpoint:

1. ❌ Replace `_PATH_ACCOUNT_PROFILE`, `_PATH_ACCOUNT_STATS`,
   `_PATH_REVENUE_SUMMARY` in
   `app/services/onlyfans_direct_real_client.py` with the actual
   sandbox endpoint paths.
2. ❌ Validate sample synthetic responses against
   `AccountProfileSummary`, `AccountStatsSummary`,
   `RevenueSummary` using
   `tests/test_of_direct_sandbox_transport.py` or a fresh
   integration test before any real-account fetch.
3. ❌ Verify the test sandbox server returns
   `Content-Type: application/json` (otherwise the transport
   will classify the response as `unexpected_html`).
4. ❌ Verify the test sandbox server's authentication shape: the
   Sprint 8E credential loader expects the encrypted blob to be a
   JSON object with `cookie` / `authorization` / `user_agent`
   keys. If the test sandbox uses a different auth shape, extend
   `CredentialMaterial` and `_ALLOWED_KEYS` in
   `onlyfans_direct_credential_loader.py` deliberately, with a
   reviewed reason.

Until each line is documented as ✅, no real fetch should run.

---

## 11. Requirements before client accounts

Adds on top of §9 + §10:

1. ❌ At least 7 days of clean sandbox runs against the test
   account.
2. ❌ Real `ChallengeNotifier` wired, with on-call routing.
3. ❌ Section D of readiness checklist completed for one real
   creator (signed consent, agency legal review, geography
   review).
4. ❌ Token-leak drill walked within last 90 days for the
   OnlyFans-direct credential variant.
5. ❌ Creator-account-compromise tabletop walked with agency
   principal.
6. ❌ Owner sign-off in `audit_events` with
   `event_type='connector.golive'` (distinct from `.sandbox`).
7. ❌ Rollback plan documented and rehearsed.
8. ❌ 24h and 7d post-go-live re-checks.
9. ❌ Legal opinion on platform ToS posture.

---

## 12. Recommended Sprint 8F

Operator-driven validation of the sandbox path against the test
account. Specifically:

1. Replace synthetic path constants with the test sandbox
   endpoints (Sprint 8E §10).
2. Wire a real `SlackChallengeNotifier` (simplest first cut).
3. Pair the test-only credential into the encrypted vault.
4. Owner records the sandbox sign-off via the new admin endpoint.
5. Run all three reads end-to-end against the test sandbox.
6. Verify each `connector.sandbox.success` audit row.
7. 24h then 7d soak; document any challenge / unexpected events.
8. Run the token-leak drill targeting the test credential.

Sprint 8F should NOT add the other 7 read methods. Each of those
is its own sprint scope (chat / fan / vault / post / story /
mass-message reads each carry per-method PII review).

---

## 13. Sign-off scope

This sprint:

- ✅ Wires `RealHTTPTransport.fetch()` using the existing repo
  dependency `httpx`.
- ✅ Adds `VaultBackedCredentialLoader` that decrypts inside
  `load()` and drops plaintext before return.
- ✅ Implements challenge / unexpected classification matrix.
- ✅ Adds `build_safe_notify_payload` (no real channel wired).
- ✅ Adds the owner sign-off admin endpoint.
- ✅ Adds an explicit method allowlist for sandbox runs.
- ✅ Surfaces transport readiness in the security admin UI.
- ✅ Adds 34 tests covering: constructor refusal matrix,
  classify_status matrix, fetch end-to-end with httpx
  MockTransport (success / 401 / 429 / HTML / 3xx / malformed
  JSON / loader error), credential-cookie-never-in-response,
  vault loader (active / revoked / wrong provider / non-JSON),
  safe header summary, safe notify payload, owner sign-off
  endpoint, sandbox allowlist refusal, no-write / no-network on
  new files.
- ✅ Updates 3 walker tests with a per-file allowlist that names
  `onlyfans_direct_transport.py` and only that file.

This sprint does **not** authorise:

- Connecting a real OnlyFans account.
- Connecting a client account.
- Production mode.
- Lifting any kill switch, approval, consent, vault, or
  owner-sign-off gate.
- A real challenge notify channel.
- Any read method beyond the three already implemented.
