# Direct OnlyFans Readiness Checklist

**Version:** 1.0
**Last updated:** 2026-04-28
**Owner:** Zachary
**Audience:** Anyone evaluating whether Mission Control is ready to connect a real OnlyFans account — directly or through OnlyMonster.

This is the **gate** between "we have controls in place" and "we may handle creator credentials." Every item must be ✅ (or explicitly ❌ with a tracked owner and date) before ANY of:

- A real OnlyFans creator account is paired in production.
- A real OnlyMonster credential is used to fetch creator data outside of read-only sandbox.
- Any OnlyFans-derived data leaves the OFI staging environment.

If any item is ❌ and the answer is "we'll fix it after the first creator," the answer is no. Re-read `breach-response-plan.md` §0 and come back.

---

## Section A — What is currently blocked (status report, not a checklist item)

These are the controls that **fail closed** today. They are why this checklist can exist at all. If any of them are weakened (env flag flipped, helper bypassed, gate removed), this checklist is invalidated and must be re-walked.

| # | Control | Where it lives | Blocks |
|---|---|---|---|
| A.1 | Connector gate `is_connector_action_allowed()` | `app/core/connector_gate.py` | Any connector action without an approved `connector_approvals` row, live `client_consents`, and kill switches off |
| A.2 | OnlyMonster gated wrapper `gated_onlymonster_creator_sync()` | `app/services/gated_onlymonster_sync.py` | Default-off (`MC_ONLYMONSTER_GATED_SYNC_ENABLED` unset) — even with full approvals, sync refuses unless flag on |
| A.3 | Typed read-only adapter `fetch_creator_snapshot()` | `app/services/onlymonster_integration.py` | The seam asserts `rows_written=0`; future real OnlyMonster client must implement a read-only fetch, no writes |
| A.4 | Direct OnlyFans connector | not present in this branch | The whole module does not exist — no `like`, `subscribe`, `message`, `tip`, `mass_message`, `delete`, `pay_out`, `refund` is implementable today |
| A.5 | Settings encryption guardrail `is_dedicated_encryption_key_configured()` | `app/core/secrets_store.py` | App refuses to start in `ENVIRONMENT=production` if `SETTINGS_ENCRYPTION_KEY` is missing or falling back to `LOCAL_AUTH_TOKEN`/`CLERK_SECRET_KEY` |
| A.6 | Org-scoped settings wrapper | `app/services/settings_scope.py` (`MC_APP_SETTINGS_ORG_SCOPED=1` flag) | When flag on, secrets stored under derived `org:{uuid}.{key}` so cross-tenant reads are not possible |
| A.7 | Denial audit hook with explicit detail | `app/core/denial_audit.py` (`attach_denial_detail()`) | Every 401/403 lands in `audit_events` with a typed reason category, throttled per (ip, path, status) |
| A.8 | LLM PII redactor with labelled-name + street-address patterns | `app/core/pii_redact.py` | Outbound LLM prompts get vendor keys, JWT, emails, phones, labelled names, street addresses scrubbed before the call |
| A.9 | Clerk webhook verifier (Svix-or-isolated) | `app/core/clerk_webhook_verify.py` | Production refuses shared-secret HMAC unless `CLERK_WEBHOOK_ALLOW_SHARED_SECRET=1` is explicitly set |
| A.10 | Audit retention scheduler | `app/services/audit_retention_scheduler.py` (`MC_AUDIT_RETENTION_ENABLED=1` flag) | Default dry-run; never deletes by accident |
| A.11 | Gateway runtime status server-side | `app/api/gateways.py:get_runtime_status` | Frontend reads `token_configured` / `token_source`, never the raw token; `?include_token=1` opt-in audited |
| A.12 | Direct OnlyFans policy module | `app/core/onlyfans_direct_policy.py` | `READ_ACTIONS` / `WRITE_ACTIONS` frozensets, fail-closed for unknown actions; raises on any write request via `require_read_action`. |
| A.13 | Direct OnlyFans disabled connector shell | `app/services/onlyfans_direct_connector.py` | `mode="disabled"`, no network, refuses cookie/session kwargs at construction, no write methods, `fetch()` always raises. |
| A.14 | Direct OnlyFans dry-run + fixture mode | `app/services/onlyfans_direct_fixtures.py`, `OnlyFansDirectConnector.dry_run` | Synthetic fixtures only; payload is computed and discarded; full policy + gate + audit chain on every call. |
| A.15 | Direct OnlyFans credential safety contract | `app/core/onlyfans_direct_credentials.py` | Vault-only; raw cookies forbidden; frontend session storage forbidden (CI scan); revocation/rotation runbooks. |
| A.16 | Direct OnlyFans rate-limit and session-health policy | `app/core/onlyfans_direct_rate_policy.py` | Conservative defaults (10/min, 200/hr, 2s→300s backoff); `SessionHealth` enum; `CHALLENGE_REACTION` (stop+audit+notify+manual review). |

If you flipped any of these off intentionally for a development run, **flip them back before continuing this checklist.**

---

## Section B — Foundation prerequisites (Sprints 1–6)

These must already be **landed and reviewed**. Each line points at the implementation doc that proves it.

| # | Requirement | Source of truth | Status |
|---|---|---|---|
| B.1 | Append-only `audit_events` table with `record_audit()` and `redact_metadata()` | `docs/security/security-sprint-2-implementation.md` |  |
| B.2 | `connector_approvals`, `kill_switches`, `client_consents`, `creator_credentials` tables exist | `docs/security/security-sprint-2-implementation.md` |  |
| B.3 | Connector gate `is_connector_action_allowed()` with `GateVerdict` | `docs/security/security-sprint-2-implementation.md` |  |
| B.4 | Settings scoping wrapper + flag `MC_APP_SETTINGS_ORG_SCOPED` | `docs/security/security-sprint-3-implementation.md` |  |
| B.5 | Audit retention scheduler with `MC_AUDIT_RETENTION_ENABLED` opt-in | `docs/security/security-sprint-4-implementation.md` |  |
| B.6 | Clerk webhook verifier with Svix preference and shared-secret guardrail | `docs/security/security-sprint-5-implementation.md` |  |
| B.7 | LLM PII redactor (labelled names + street addresses) | `docs/security/security-sprint-5-implementation.md` |  |
| B.8 | OnlyMonster gated sync wrapper with `MC_ONLYMONSTER_GATED_SYNC_ENABLED` flag | `docs/security/security-sprint-5-implementation.md` |  |
| B.9 | Typed read-only OnlyMonster integration seam | `docs/security/security-sprint-6-implementation.md` |  |
| B.10 | Gateway runtime status server-side endpoint | `docs/security/security-sprint-6-implementation.md` |  |
| B.11 | Denial-audit explicit detail helper | `docs/security/security-sprint-6-implementation.md` |  |
| B.12 | Token-leak incident drill walked at least once on staging | `docs/security/incident-drill-token-leak.md` |  |
| B.13 | `breach-response-plan.md` exists and has been drilled at least once | `docs/security/breach-response-plan.md` |  |

---

## Section C — Prerequisites for OnlyMonster behind the gated wrapper (test or sandbox account)

Before turning on `MC_ONLYMONSTER_GATED_SYNC_ENABLED=1` against any non-Mission-Control account:

| # | Requirement | Method | Status |
|---|---|---|---|
| C.1 | A real `OnlyMonsterClient` import path is wired into `app/services/onlymonster_integration.py` (replace `_FAKE_CLIENT_PATH`) | code review SHA |  |
| C.2 | The real client is read-only by construction: source review confirms no `POST` / `PUT` / `DELETE` paths to the OnlyMonster API are implemented | code review |  |
| C.3 | OnlyMonster credential is stored encrypted via `set_secret_scoped(... organization_id=<org>)`; never as plaintext env | DB inspection |  |
| C.4 | A `connector_approvals` row exists with `creator_id=<test creator>`, `connector_type='onlymonster'`, `approved_by=<owner>`, `approved_at` set, `revoked_at` null | manual SQL |  |
| C.5 | A `client_consents` row exists with `accepted_at` set, `revoked_at` null, scope covers `onlymonster:read` for that creator | manual SQL |  |
| C.6 | `mc.connectors.frozen` and any per-connector kill switch are OFF | admin UI screenshot |  |
| C.7 | `tests/test_security_readiness.py` passes against the wired-up real client (in CI, not just locally) | CI run URL |  |
| C.8 | `tests/test_security_operations.py` (gate refuse paths) still passes | CI run URL |  |
| C.9 | A single dry-run fetch is executed and an `audit_events` row with `event_type='connector.run.finish'` is observed; `metadata.rows_written == 0` | psql evidence |  |
| C.10 | If any of the above evidence is unavailable, the run is aborted and the env flag returned to OFF | runbook discipline |  |

When all of C.1 → C.10 are ✅, you may run a single sandboxed read against a non-real account. **Do not expand to a real account until Section D is also ✅.**

---

## Section D — Prerequisites for first real creator behind OnlyMonster

Adds on top of Section C:

| # | Requirement | Method | Status |
|---|---|---|---|
| D.1 | Creator has signed the OnlyMonster connector consent (PDF on file, `consent_text_hash` matches the `client_consents.consent_text_hash` row) | document link |  |
| D.2 | Creator has been notified in writing of: what we read, how often, what we store, retention windows, how to revoke | email log |  |
| D.3 | Agency-side legal review acknowledges the integration is read-only and lists the data scope | email log |  |
| D.4 | If creator is in EU/UK or other regulated geography: DPA / SCC reviewed | doc link |  |
| D.5 | Token-leak drill (`incident-drill-token-leak.md`) has been completed within the last 90 days for the OnlyMonster credential variant specifically | drill log |  |
| D.6 | Creator-account-compromise tabletop (`breach-response-plan.md` §4.2) walked through with the agency principal within the last 90 days | drill log |  |
| D.7 | Owner sign-off recorded in `audit_events` with `event_type='connector.golive'`, `creator_id=<id>`, and approving actor | psql evidence |  |
| D.8 | Rollback plan documented: how to revoke credentials, purge data, notify creator within 1 hour | runbook link |  |
| D.9 | First sync run reviewed by owner; row counts and sample rows spot-checked against expectation | review note |  |
| D.10 | 24h re-check: no anomalies (unexpected IPs, OnlyMonster rate-limit responses, surprise mode flips) | review note |  |
| D.11 | 7d re-check: rate limits stable, no creator account flags, retention job ran on schedule | review note |  |

If any item D.1 → D.11 is ❌, do not graduate from sandbox to live. The cost of waiting is a delay; the cost of acting on missing evidence is a sev 1.

---

## Section E — Prerequisites for direct OnlyFans (NOT YET ATTEMPTED)

This section is pre-state. After Sprint 7, the **policy boundary** and **disabled connector shell** exist; the real read-only client and any live network call still do not. Surfacing each line keeps the remaining gaps visible.

| # | Requirement | Status on this branch | Reasoning |
|---|---|---|---|
| E.1 | A direct OnlyFans connector module exists | ⚠ disabled shell present (Sprint 7) | `app.services.onlyfans_direct_connector.OnlyFansDirectConnector` exists with `mode="disabled"`, no network, no write methods. Real read-only client still absent. |
| E.2 | Connector is read-only by construction: zero write/destructive endpoints | ✅ structurally enforced (Sprint 7) | `WRITE_ACTIONS` enumerated at `app.core.onlyfans_direct_policy`; shell exposes no write methods; tests assert no write-shaped public callable. |
| E.3 | All requirements in `direct-connector-safety-checklist.md` Sections 0–5 are ✅ | partial; foundation done, real client not present | See that file for line-by-line status |
| E.4 | Per-account rate limits configured below platform thresholds, documented in code | ✅ Sprint 7 scaffolding | `app.core.onlyfans_direct_rate_policy` defines `DEFAULT_MAX_REQUESTS_PER_MINUTE=10`, `_PER_HOUR=200`, `DEFAULT_BACKOFF`. Live counting is Sprint 8+. |
| E.5 | `creator_credentials` rotation runbook drilled for the OnlyFans variant specifically | ❌ deferred | `revocation_runbook()` and `rotation_runbook()` strings exist in `app.core.onlyfans_direct_credentials`; drill them after a real test account exists. |
| E.6 | OnlyFans creator-account-compromise scenario walked with the creator's call script | ❌ deferred | Done before first creator goes live, not before code lands |
| E.7 | `breach-response-plan.md` §4.2 explicitly references this connector by name and current ToS posture | partial | Will need an addendum when E.1 graduates beyond disabled |
| E.8 | A second owner approval is required to flip `mode='read_write'` (no single-operator privilege escalation) | ⚠ partially structural | `mode="read_write"` is not implementable today; `WRITE_ACTIONS` are policy-blocked; the second-approval gate must still be designed before any write graduation. |
| E.9 | Credential safety contract enforced: no raw cookies, no frontend session storage | ✅ Sprint 7 | `app.core.onlyfans_direct_credentials` enforces refusal at construction; CI test scans `frontend/src` for forbidden patterns. |
| E.10 | Dry-run path with synthetic fixtures proves the gating chain end-to-end | ✅ Sprint 7 | `OnlyFansDirectConnector.dry_run(...)` audits policy + gate + (would-fetch); fixture payload is computed and discarded. |
| E.11 | Real `OnlyFansReadOnlyClient` is implemented and wired into the shell | ❌ does not exist | Sprint 8B work; required before any non-fixture path. |
| E.12 | A real OnlyFans test-only account is paired through the shell | ❌ blocked by E.11 | Section §10 of `security-sprint-7-direct-of-prep.md` lists the full prerequisite chain. |

The honest summary: **direct OnlyFans is still not unblocked.** Sprint 7 lands the policy boundary, the disabled shell, the dry-run path, the credential contract, and the rate-limit/session-health scaffolding. The remaining red gates (E.5, E.6, E.7, E.11, E.12) are explicit; lighting any of them green requires the work named in `security-sprint-7-direct-of-prep.md` §10–§11.

---

## Section F — Sign-off

Before flipping `MC_ONLYMONSTER_GATED_SYNC_ENABLED=1` against the first real creator (Section D), this signature page must be filled in and the file copied to `docs/security/runs/<creator-id>-<date>.md`:

| Role | Name | Signature / commit SHA | Date |
|------|------|------------------------|------|
| Mission Control owner |  |  |  |
| Agency principal |  |  |  |
| Creator (consent acknowledgment) |  |  |  |

Caveats / open items that did not block but were noted:

- _none yet_

---

## Section G — Re-validation triggers

Re-walk this entire checklist (cannot inherit a previous green state) when **any** of the following occur:

1. The OnlyMonster real client import path changes (Section A.3 → C.1).
2. `MC_ONLYMONSTER_GATED_SYNC_ENABLED` is observed as `1` without a paired audit row showing why.
3. `SETTINGS_ENCRYPTION_KEY` is rotated (every secret re-encrypted; smoke test the gate).
4. A new operator joins with `creator_grants` access.
5. A creator revokes consent (Section D.x must be re-evidenced before re-onboarding).
6. Any of the controls in Section A is intentionally weakened or bypassed (this should never happen; if it does, re-walk).
7. A direct OnlyFans connector module is introduced (Section E becomes load-bearing for the first time).
8. The file `app/services/onlymonster_integration.py` is modified — it is the seam, and its invariants (`rows_written = 0`, gated by `gated_onlymonster_creator_sync`) are load-bearing.

A green checklist does not survive any of these triggers. Treat it as an artifact of one moment in time.

---

## Section H — What this checklist deliberately does NOT do

- It does not authorize OnlyMonster writes. The seam asserts `rows_written = 0` and the brief that produced it is explicit: read-only.
- It does not authorize a direct OnlyFans connector. It documents prerequisites; the implementation gate is `direct-connector-safety-checklist.md`.
- It does not replace creator-side legal review. Consent capture is a legal artifact, not a code review.
- It does not certify response capability for a Sev 1. That requires the drills referenced in `breach-response-plan.md`.
- It does not survive code-shape changes silently. If the seam moves, this file must move with it.
