# Security Sprint 8D — Direct OnlyFans Sandbox Read Methods, Part 1

**Status:** Sprint 8D of N. First sprint to add **real read method
bodies** for the direct OnlyFans sandbox client. Scope is
deliberately narrow: three account-level reads only
(`read_account_profile`, `read_account_stats`,
`read_revenue_summary`). The other 7 read methods still raise
`RealClientNotEnabledError`. **No real network call is made; the
fake transport is the only working transport in this branch.**
**Branch:** `feat/of-direct-sandbox-reads-sprint-8d`
**Last updated:** 2026-04-30

Companion to:
- [Sprint 8B direct OF dry-run](./security-sprint-8b-of-dryrun.md)
- [Sprint 8C direct OF sandbox](./security-sprint-8c-of-sandbox.md)
- [Direct OnlyFans readiness checklist](./direct-onlyfans-readiness-checklist.md)

---

## 1. What was added

| Concern | Where |
|---|---|
| Safe transport abstraction | [`backend/app/services/onlyfans_direct_transport.py`](../../backend/app/services/onlyfans_direct_transport.py) |
| Strict response schemas + allowlist parsers | [`backend/app/core/onlyfans_direct_schemas.py`](../../backend/app/core/onlyfans_direct_schemas.py) |
| Three read method bodies on the real client | [`backend/app/services/onlyfans_direct_real_client.py`](../../backend/app/services/onlyfans_direct_real_client.py) |
| Sandbox run handles success / challenge / unexpected | [`backend/app/services/onlyfans_direct_connector.py`](../../backend/app/services/onlyfans_direct_connector.py) |
| Admin status: implemented vs blocked read methods | [`backend/app/api/security_admin.py`](../../backend/app/api/security_admin.py), [`frontend/src/lib/security/api.ts`](../../frontend/src/lib/security/api.ts), [`frontend/src/app/security/page.tsx`](../../frontend/src/app/security/page.tsx) |
| Sprint 8D tests | [`backend/tests/test_of_direct_sandbox_reads.py`](../../backend/tests/test_of_direct_sandbox_reads.py) |

---

## 2. Implemented read methods

| Action | Method | Path |
|---|---|---|
| `account_profile_read` | `read_account_profile` | `/sandbox/account/profile` |
| `account_stats_read` | `read_account_stats` | `/sandbox/account/stats` |
| `revenue_summary_read` | `read_revenue_summary` | `/sandbox/account/revenue-summary` |

Each method:

1. Calls the configured transport's `fetch(path=...)`.
2. On HTTP 200, runs the allowlist parser to build a typed
   dataclass (`AccountProfileSummary`, `AccountStatsSummary`,
   `RevenueSummary`).
3. Returns `summary_to_safe_dict(summary)` — a flat dict of the
   parsed fields. The raw response body never escapes the method.
4. On HTTP 401 → raises `ChallengeDetectedError("login_required")`.
5. On any other non-200 → raises `UnexpectedStatusError`.
6. On parse failure → raises `UnexpectedStatusError(status_code=200)`
   so the connector wrapper can audit failure without leaking the
   parse error.

The connector wrapper (`dry_run_sandbox`) catches each of these
and audits the appropriate row. There is no path that returns
the raw response or the parser's error details.

---

## 3. Methods that remain blocked

These still raise `RealClientNotEnabledError`, even with a
transport configured:

- `read_fan_list_metadata`
- `read_chat_thread_metadata`
- `read_chat_messages`
- `read_vault_metadata`
- `read_post_metadata`
- `read_story_metadata`
- `read_mass_message_metadata`

The Sprint 8D test
`test_other_seven_read_methods_still_raise_real_client_not_enabled`
asserts this. Each of these methods is its own future sprint task
because each carries higher leak risk (fan handles, message
bodies, vault content) and needs its own allowlist filter,
audit-metadata schema, and test plan.

---

## 4. Transport safety model

`app.services.onlyfans_direct_transport` exposes:

- `Transport` — runtime-checkable Protocol with one method:
  `async fetch(*, path, params=None) -> TransportResponse`.
- `TransportResponse` — frozen dataclass with `status_code`,
  `json_body`, `content_type`. **No `raw_body`, `cookies`,
  `headers`, or `set_cookie` field.**
- `FakeTransport` — deterministic synthetic transport. Tests pass
  a `path → TransportResponse` map. Captures `calls` so tests can
  assert which paths were hit.
- `RealHTTPTransport` — placeholder. Constructor refuses unless
  BOTH `MC_OF_DIRECT_SANDBOX_ALLOWED=1` AND
  `MC_OF_DIRECT_REAL_CLIENT_ALLOWED=1` are set AND we're not in
  production. Even on construction success, `fetch` raises
  `TransportNotEnabledError` — Sprint 8E will replace the body
  with a real HTTP call.

Module-level rules:

- No HTTP / browser-automation imports.
- The fake transport is the only working implementation.
- Future Sprint 8E real transport must put the HTTP client import
  inside `fetch()` so the module-level no-network-import test
  continues to pass during the transitional commit.

---

## 5. Response schemas

`app.core.onlyfans_direct_schemas` defines:

- `AccountProfileSummary` — `creator_handle`, `display_name`,
  `joined_iso`, `subscription_tier_count`. No fan data, no
  revenue, no follower lists.
- `AccountStatsSummary` — `subscriber_count`, `renewal_rate_pct`
  (clamped 0–100), `active_chats`. No per-fan breakdown.
- `RevenueSummary` — `currency` (3-letter code), `month_to_date`,
  `previous_month`, `tips_subtotal`, `ppv_subtotal`,
  `subscription_subtotal`. No transaction-level data.

All three parsers:

- Reject non-dict input with `SchemaParseError`.
- Use only allowlisted keys; unknown keys are dropped at function
  exit.
- Coerce values: strings bounded at 200 chars, ints clamped to
  non-negative, currency normalized to 3-letter uppercase or
  default `USD`.
- Return frozen dataclasses; raw input dict is dropped.

`safe_field_counts(summary)` returns audit-safe scalar counts —
**never** strings (handles, display names) — for the audit
metadata.

---

## 6. Audit metadata rules

| Event | When | Severity | Metadata |
|---|---|---|---|
| `connector.sandbox.success` | Read passes all gates AND returns | info | `connector_type`, `requested_action`, `mode="sandbox"`, `field_counts: dict[str, int]`, `rows_written: 0` |
| `connector.session.challenged` | `ChallengeDetectedError` from real client | warning | `connector_type`, `reason_category` (Sprint 8B vocabulary), `mode="sandbox"`, `status_code`, `requested_action` |
| `connector.sandbox.failed` | `UnexpectedStatusError` from real client | warning | `connector_type`, `requested_action`, `mode="sandbox"`, `status_code`, `blocked_reason="unexpected_status"` |
| `connector.sandbox.blocked` | Any prereq failure (Sprint 8C set) | info | `connector_type`, `requested_action`, `mode="sandbox"`, `blocked_reason` |

**Forbidden in audit metadata** (asserted by test
`test_no_raw_body_or_cookies_in_any_audit_row_after_sandbox_success`):
`raw_body`, `response_body`, `html`, `set_cookie`, `cookies`,
`cookie`, `session`, `session_token`, `auth_token`, `x-bc`,
`csrf`, `csrf_token`, `fan_id`, `fan_username`, `fan_handle`,
`message_body`, `messages`, `credential_value`, `encrypted_value`,
`follower_emails`, `fan_emails`, `internal_id`,
`per_fan_breakdown`.

---

## 7. Challenge handling

When the real read raises `ChallengeDetectedError`:

1. The Sprint 8B `record_session_challenged()` writes one
   `connector.session.challenged` row with the normalised reason.
2. The Sprint 8C `DEFAULT_NOTIFIER.notify(...)` is called. In
   Sprint 8D this is `NoOpChallengeNotifier`, which logs and
   returns `"not_configured"`. Sprint 8E will replace this with
   a real Slack / Telegram notifier.
3. The sandbox gate returns `SandboxResult(allowed=False,
   blocked_reason="challenge_detected", ...)`.

The notify call is best-effort; the audit row is the source of
truth. Even if the notifier raises in a future implementation,
the audit row is already committed.

---

## 8. Requirements before sandbox test account

Status now (Sprint 8D):

- ✅ Real read method bodies for the three lowest-risk reads.
- ✅ Transport abstraction; fake transport for tests.
- ✅ Allowlist parsers + safe field counts.
- ✅ Sandbox connector wiring for success / challenge /
  unexpected paths.
- ❌ Real `RealHTTPTransport.fetch()` body (Sprint 8E).
- ❌ Real `ChallengeNotifier` wired (Sprint 8E — Slack webhook
  most likely).
- ❌ Pair test-only OnlyFans credential into the encrypted vault.
- ❌ Owner-approved `connector_approvals` row + live
  `client_consents` row + `connector.golive.sandbox` audit row
  for the test creator.
- ❌ Run sandbox dry-run with the **fake** transport against the
  test creator (Sprint 8D wiring proves this works in tests).
- ❌ Run sandbox dry-run with the **real** transport against the
  test creator (Sprint 8E onward).
- ❌ 24h then 7d soak in sandbox.
- ❌ Token-leak drill targeting the test-account credential.

---

## 9. Requirements before client accounts

Adds on top of §8:

1. ❌ At least 7 days of clean sandbox runs against the test
   account.
2. ❌ Section D of readiness checklist completed for one real
   creator (signed consent, agency legal review, geography
   review).
3. ❌ Token-leak drill walked within last 90 days for
   OnlyFans-direct credential variant.
4. ❌ Creator-account-compromise tabletop walked with agency
   principal.
5. ❌ Owner sign-off in `audit_events` with
   `event_type='connector.golive'` (distinct from
   `connector.golive.sandbox`).
6. ❌ Rollback plan documented and rehearsed.
7. ❌ 24h and 7d post-go-live re-checks.
8. ❌ Legal opinion on platform ToS posture.

---

## 10. Recommended Sprint 8E

**Wire `RealHTTPTransport.fetch()` against the test sandbox
account.** Specifically:

1. Add `httpx` (or another deliberately narrow async HTTP
   client) inside `RealHTTPTransport.fetch()` only. The
   module-level no-network-import test is expanded explicitly
   to allow this single import; the expansion is reviewed
   against `security-sprint-8d-of-sandbox-reads.md` §4.
2. Implement credential resolution inside `fetch`:
   - Load the encrypted credential from the vault using
     `CredentialReference`.
   - Decrypt at call time.
   - Build the request headers (Cookie / X-BC / etc.) inside
     `fetch`.
   - Drop the decrypted value on stack exit. No attribute on
     the transport instance carries it.
3. Implement challenge detection:
   - HTTP 401 → `ChallengeDetectedError("login_required")`.
   - HTTP 403 → `ChallengeDetectedError("captcha")` or
     `"platform_block"` based on body shape.
   - HTML response when JSON expected → `unexpected_html`.
   - HTTP 429 → `rate_limit_response`.
4. Implement a real `ChallengeNotifier` (Slack webhook is
   simplest first cut). Replace `DEFAULT_NOTIFIER`.
5. Wire an admin endpoint for `record_owner_signoff(...)` so
   operators don't need psql.
6. Pair the test-only OnlyFans account credential into the
   encrypted vault (operator-driven; not in code).
7. Run the sandbox path end-to-end against the test account.
   Verify no fan PII in any audit row, `rows_written=0`, and
   a clean `connector.sandbox.success` for each of the three
   reads.
8. 24h re-check, then 7d re-check.

Sprint 8E should NOT add the other 7 read methods. Each is its
own sprint scope.

---

## 11. Sign-off scope

This sprint:

- ✅ Implements the three lowest-risk account-level read
  methods.
- ✅ Adds the safe transport abstraction (Protocol + fake +
  refused real).
- ✅ Adds strict allowlist response schemas.
- ✅ Wires sandbox success / challenge / unexpected paths.
- ✅ Audits each path with safe scalar metadata only.
- ✅ Surfaces sandbox read coverage in the security admin UI.
- ✅ Adds 26 tests covering transport, schemas, real client,
  sandbox prereq chain (with real reads), challenge / unexpected
  paths, audit safety, and no-write / no-network invariants.

This sprint does **not** authorise:

- A real network call.
- Any other read method beyond the three named.
- Production mode.
- Lifting any kill switch, approval, consent, vault, or
  owner-sign-off gate.
- A real challenge notify channel.
- Storing the credential value anywhere outside the vault.
