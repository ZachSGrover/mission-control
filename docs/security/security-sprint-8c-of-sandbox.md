# Security Sprint 8C — Direct OnlyFans Sandbox Read-Only Graduation

**Status:** Sprint 8C of N. Adds the **structural sandbox path** for
a future test-only OnlyFans account: a real read-only client
**skeleton** behind hard env flags, a vault credential reference
that is value-free by construction, an owner-sign-off audit
contract, and a 9-step prerequisite gate. This sprint **does not
connect** any real account, **does not run** any live network
call, and **does not implement** any read method body — every read
on the real client skeleton raises until Sprint 8D.
**Branch:** `feat/of-direct-sandbox-readonly-sprint-8c`
**Last updated:** 2026-04-30

Companion to:
- [Sprint 7 direct OF read-only prep](./security-sprint-7-direct-of-prep.md)
- [Sprint 8A OnlyMonster gated proof](./security-sprint-8a-onlymonster-gate.md)
- [Sprint 8B direct OF dry-run](./security-sprint-8b-of-dryrun.md)
- [Direct OnlyFans readiness checklist](./direct-onlyfans-readiness-checklist.md)

---

## 1. What was added

| Concern | Where |
|---|---|
| Real read-only client skeleton (every method raises) | [`backend/app/services/onlyfans_direct_real_client.py`](../../backend/app/services/onlyfans_direct_real_client.py) |
| Typed credential vault reference (value-free) | [`backend/app/core/onlyfans_direct_credential_ref.py`](../../backend/app/core/onlyfans_direct_credential_ref.py) |
| `mode="sandbox"` + `dry_run_sandbox()` | [`backend/app/services/onlyfans_direct_connector.py`](../../backend/app/services/onlyfans_direct_connector.py) |
| Challenge notifier Protocol + NoOp default | [`backend/app/services/onlyfans_direct_session_health.py`](../../backend/app/services/onlyfans_direct_session_health.py) |
| Owner sign-off audit helpers | [`backend/app/services/onlyfans_direct_owner_signoff.py`](../../backend/app/services/onlyfans_direct_owner_signoff.py) |
| Security admin sandbox-readiness fields | [`backend/app/api/security_admin.py`](../../backend/app/api/security_admin.py) |
| Frontend sandbox status UI | [`frontend/src/app/security/page.tsx`](../../frontend/src/app/security/page.tsx), [`frontend/src/lib/security/api.ts`](../../frontend/src/lib/security/api.ts) |
| Sprint 8C tests | [`backend/tests/test_of_direct_sandbox.py`](../../backend/tests/test_of_direct_sandbox.py) |

---

## 2. What remains blocked

- **Real network call.** No HTTP / browser-automation library is
  imported by any `onlyfans_direct_*` module (verified by test).
- **Real read method bodies.** Every method on
  `RealOnlyFansReadOnlyClient` raises `RealClientNotEnabledError`.
- **Real account connection.** No code path resolves a credential
  to plaintext in this sprint.
- **Production mode.** `mode="real"` / `mode="production"` raise
  `ValueError` at construction. Only `disabled`, `dry_run`, and
  `sandbox` are valid.
- **Production sandbox attempts.** `dry_run_sandbox` audits a block
  with reason `production_environment` if `is_production()` returns
  true, regardless of any other flag.
- **Cookies, raw sessions, plaintext credentials.** Refused at
  every constructor on the path: real client, fake client,
  connector shell. The `CredentialReference` shape itself has no
  field for them.
- **Write actions.** No `send_message`, `post`, `tip`,
  `mass_message`, `vault_*`, `follow`, etc. on any new surface.

---

## 3. Sandbox mode prerequisites

`OnlyFansDirectConnector(mode="sandbox", ...).dry_run_sandbox(...)`
runs the following 9-step chain. The first miss returns a
`SandboxResult` with `allowed=False`, populated `blocked_reason`,
and writes a `connector.sandbox.blocked` audit row:

| # | Check | `blocked_reason` on miss |
|---|---|---|
| 1 | `MC_OF_DIRECT_SANDBOX_ALLOWED=1` env flag | `env_flag_disabled` |
| 2 | Non-production environment | `production_environment` |
| 3 | Action is in Sprint 7 `READ_ACTIONS` (write actions also raise `BlockedActionError`) | `policy_refused` |
| 4 | Approval row live for `(onlyfans_direct, read, creator_id)` | `no_approval` |
| 5 | Consent live for `onlyfans_direct_read` / `creator_id` | `no_consent` |
| 6 | No kill switch active at any scope | `kill_switch` |
| 7 | Vault available (`SETTINGS_ENCRYPTION_KEY` configured) | `vault_unavailable` |
| 8 | Credential vault row resolved through the configured `CredentialReference` is `"active"` | `credential_missing` / `credential_revoked` / `credential_rotated` / `credential_stale` / `credential_wrong_provider` |
| 9 | Owner sign-off audit row exists (`connector.golive.sandbox`) for the creator | `no_owner_signoff` |

If all 9 prerequisites pass, the gate invokes the configured
client's read method. The Sprint 8C `RealOnlyFansReadOnlyClient`
skeleton's method raises `RealClientNotEnabledError`; the gate
catches that and audits a `connector.sandbox.blocked` with
`blocked_reason="real_client_not_enabled"`. There is **no path
through `dry_run_sandbox` that performs a real network call**.

The `SandboxResult` includes a full prereq snapshot (env flag,
production status, credential status, approval present, consent
present, kill-switch blocking scope, vault availability, owner
sign-off, notify channel status) so the admin UI can render
exactly *which* gate failed.

---

## 4. Credential vault reference rules

`app.core.onlyfans_direct_credential_ref.CredentialReference` is
the only credential-shaped argument the real client accepts. It
carries `(creator_id, credential_id, provider, credential_type)`
— **no value, no preview, no length, no encrypted blob**. Any
attempt to construct the real client with cookie / session /
password kwargs raises `CredentialContractViolation`.

`check_credential_status(session, ref)` returns a
`CredentialStatusReport` with kind ∈ `missing` / `active` /
`rotated` / `revoked` / `stale` / `wrong_provider`. The report is
the only thing the sandbox gate sees from this layer; it cannot
leak the credential value because the function does not touch
`encrypted_value` at all.

The vault row has no `expires_at` column today; "stale" is
inferred from `(status="active" AND rotated_at IS NOT NULL)` —
the active-but-superseded half-state. A future migration can add
explicit expiry; the gate semantics will not need to change.

---

## 5. Owner sign-off requirement

Sandbox mode refuses to run unless an audit row with
`event_type="connector.golive.sandbox"` exists for the creator.
`record_owner_signoff(...)` writes one row at severity `high`
with metadata `{connector_type, scope, notes?}` (no creator
data, no credential data, notes capped at 500 chars).
`has_owner_signoff(...)` is a single SELECT — no decryption, no
side effects.

Production code MUST NOT auto-record an owner sign-off. Sign-off
is operator-driven: an admin endpoint, a manual psql command, or
a deliberate test fixture. The Sprint 8C audit row is the source
of truth; the sandbox gate is its only consumer.

When Sprint 8D adds the admin endpoint that records sign-off:

```
POST /api/v1/security/onlyfans-direct/sandbox-signoff
  body: { creator_id, notes }
  audit: connector.golive.sandbox  severity=high
  caller: require_owner
```

— this is documented but not implemented in 8C.

---

## 6. Challenge notification plan

`onlyfans_direct_session_health` exposes:

- `ChallengeNotifier` Protocol (runtime-checkable). Two methods:
  `status()` and `notify(reason_category, creator_id)`. Both
  return one of `not_configured` / `skipped` / `would_notify`.
- `NoOpChallengeNotifier` — Sprint 8C default. `status()` returns
  `"not_configured"`; `notify(...)` logs one info line and
  returns `"not_configured"`. **Sends nothing.**
- `DEFAULT_NOTIFIER` — module-level singleton. Sprint 8D wiring
  replaces this attribute (not the Protocol) to activate
  Slack / Telegram / email without touching call sites.

Sprint 8D should:

1. Implement `SlackChallengeNotifier(channel: str, webhook_url: str)`
   that sends a single short message per call. The message
   includes only `reason_category` and `creator_id` — never a
   response body, header, cookie, or session value.
2. Replace `DEFAULT_NOTIFIER` based on env flag (e.g.
   `MC_OF_DIRECT_NOTIFY_CHANNEL=slack` + a webhook secret in
   the encrypted settings vault).
3. Add a status surface in the security admin UI for the active
   channel name and last-notify timestamp.
4. Audit row remains the source of truth; notify is best-effort.

---

## 7. Requirements before one real test account

In order:

1. ❌ Implement `RealOnlyFansReadOnlyClient` read-method bodies
   (Sprint 8D). One method body at a time, each reviewed against:
   - Read-only by construction (no POST / PUT / DELETE / PATCH).
   - Decryption happens inside the method body, scoped to the
     call, never returned.
   - Output dict is filtered through an allowlist before persist
     (no fan PII, no message bodies).
2. ❌ Wire a real `ChallengeNotifier` (Slack webhook simplest).
3. ❌ Verify Sprint 8C `dry_run_sandbox` returns
   `blocked_reason="real_client_not_enabled"` for the test
   creator (this sprint can verify it).
4. ❌ Pair the test-only OnlyFans credential into the encrypted
   vault.
5. ❌ Owner-approved `connector_approvals` row +
   `client_consents` row for the test creator.
6. ❌ Owner records `connector.golive.sandbox` for the test
   creator via `record_owner_signoff`.
7. ❌ Run Sprint 8D's first real read against the test creator;
   verify `connector.run.finish` with safe metadata only and
   `rows_written=0`.
8. ❌ Token-leak drill walked targeting the test-account
   credential.
9. ❌ Walk readiness checklist Section D for the test account.
10. ❌ 24h then 7d re-checks.

Until each line is documented as ✅ in `docs/security/runs/`, no
real OnlyFans account — even a test one — should be paired.

---

## 8. Requirements before client accounts

Adds on top of §7:

1. ❌ At least 7 days of clean sandbox runs against the test
   account.
2. ❌ Section D of readiness checklist completed for one real
   creator (signed consent, agency legal review, geography
   review).
3. ❌ Token-leak drill walked within last 90 days for the
   OnlyFans-direct credential variant.
4. ❌ Creator-account-compromise tabletop walked with agency
   principal.
5. ❌ Owner sign-off in `audit_events` with
   `event_type='connector.golive'` (note: distinct from
   `connector.golive.sandbox` — production go-live is a separate
   audit event).
6. ❌ Rollback plan documented and rehearsed.
7. ❌ 24h and 7d post-go-live re-checks scheduled.
8. ❌ Legal opinion on platform ToS posture.

---

## 9. Recommended Sprint 8D

**Direct OnlyFans real read implementation against the
test-only sandbox account.** Focus: turn the Sprint 8C skeleton
into a real read-only client, one method at a time, behind the
sandbox gate.

Suggested order:

1. **`read_account_profile`** — lowest blast radius (public-style
   metadata). One PR for: real method body, allowlist filter,
   audit row writer, real-call test, integration with sandbox
   gate.
2. **`read_account_stats`** — same shape, tightly scoped numbers.
3. **`read_revenue_summary`** — needs careful allowlisting. No
   fan-level breakdowns.
4. **`read_chat_thread_metadata`** — index only; no message
   bodies.
5. **`read_post_metadata`**, **`read_story_metadata`**,
   **`read_vault_metadata`**, **`read_mass_message_metadata`**
   — same pattern.
6. **`read_chat_messages`** — last; PII redaction layer must
   already be running on every captured message body.
7. **`read_fan_list_metadata`** — last on the list because fan
   handles are the most leak-prone field; review the allowlist
   filter most carefully here.

Sprint 8D should NOT introduce production mode or a real client
account. Both are Sprint 8E+ concerns.

Sprint 8D additions besides the methods:

- Real `SlackChallengeNotifier` (or Telegram).
- Admin endpoint for `record_owner_signoff(...)`.
- Per-method audit-metadata schema review (one schema per
  method, reviewed for PII).
- 7-day soak in sandbox before considering Sprint 8E.

---

## 10. Sign-off scope

This sprint:

- ✅ Adds the read-only client skeleton.
- ✅ Adds the typed credential vault reference (value-free).
- ✅ Adds `mode="sandbox"` to the connector with a 9-step
  prerequisite gate.
- ✅ Promotes the notify stub to a Protocol-typed interface with
  a `NoOpChallengeNotifier` default.
- ✅ Adds the `connector.golive.sandbox` audit event and
  `record_owner_signoff` / `has_owner_signoff` helpers.
- ✅ Surfaces sandbox readiness in the security admin UI with a
  human-readable missing-prereq list.
- ✅ Adds 26 tests covering every refusal path, the all-pass
  refusal (real-client-skeleton), and the Sprint 7/8B
  invariants.

This sprint does **not** authorise:

- A real OnlyFans network call.
- A real OnlyFans account connection.
- Real read method bodies.
- A real notifier.
- Lifting any kill switch, approval, consent, or vault gate.
- Any production mode.
