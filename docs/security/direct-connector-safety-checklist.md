# Direct OnlyFans Connector — Safety Checklist

**Use:** Run through this checklist **before connecting even one** real OnlyFans creator account through the direct connector. Every item must be green and signed off.

**Rule:** Any single ❌ blocks activation. No exceptions, no "we'll fix it after the first creator."

**How to use:** copy this file to `docs/security/runs/<creator-id>-<date>.md`, walk through it, paste evidence (commit SHA, screenshot, log line) under each item, and mark ✅ / ❌. Save the completed form. Owner countersigns.

---

## Section 0 — Preconditions (one-time, repo-wide)

These must already be **landed and reviewed** in the codebase before any creator-specific run is attempted.

| # | Requirement | Evidence | Status |
|---|------------|----------|--------|
| 0.1 | `audit_events` table exists, append-only, indexed on `created_at` and `actor_user_id` | migration SHA |  |
| 0.2 | `record_audit()` is called from: credential write, credential delete, role change, login, sync start/finish, export, LLM call, kill switch toggle | grep evidence |  |
| 0.3 | `creator_credentials` table exists with `(creator_id, integration_type, ciphertext, key_version, created_by, rotated_at, last_used_at)` | migration SHA |  |
| 0.4 | `client_consents` table exists with revocation column; sync code blocks on missing/revoked consent | migration SHA + test name |  |
| 0.5 | `connector_instances` table or equivalent with `status (pending → approved → active → suspended)` and `mode (read / read_write / dry_run)` | migration SHA |  |
| 0.6 | Global kill switch row `mc.connectors.frozen` exists and is checked in every sync entry point | grep evidence |  |
| 0.7 | `feature_flags` (or DB-backed equivalent) lets owner disable a single connector at runtime | UI screenshot |  |
| 0.8 | `gateways.token` is encrypted (no plaintext rows in DB) | SQL check |  |
| 0.9 | `app_settings` is org-scoped (`organization_id` column exists, reads filter by it, no cross-tenant read possible) | test name |  |
| 0.10 | `SETTINGS_ENCRYPTION_KEY` is a dedicated secret in production env, NOT falling back to `LOCAL_AUTH_TOKEN` or `CLERK_SECRET_KEY`. Application refuses to start if missing in `ENVIRONMENT=production`. | startup log |  |
| 0.11 | `NEXT_PUBLIC_LOCAL_AUTH_TOKEN` is **not** present in the production frontend build; CI grep blocks it | CI run URL |  |
| 0.12 | LLM redaction layer in `ai_backend.py` strips fan PII; LLM calls are audited | code review SHA |  |
| 0.13 | Retention job (RQ) is scheduled and last-run timestamp is < 24h old in target environment | scheduler dashboard |  |
| 0.14 | `breach-response-plan.md` exists and has been drilled at least once on a staging dataset | drill log |  |
| 0.15 | Backup of production DB is encrypted with a key separate from `SETTINGS_ENCRYPTION_KEY`, restore tested in last 90 days | restore test log |  |

---

## Section 1 — Code & deploy posture

| # | Check | Method | Status |
|---|-------|--------|--------|
| 1.1 | Connector code has zero write/destructive endpoints implemented (no `like`, `subscribe`, `message`, `tip`, `mass_message`, `delete`, `pay_out`, `refund`) | grep on connector module |  |
| 1.2 | Connector library has a default `mode="read"` and refuses any handler tagged `write=true` when mode != `read_write` | unit test |  |
| 1.3 | Connector startup explicitly checks: kill switch off, instance status `approved` or `active`, mode == `read`, consent live | unit test |  |
| 1.4 | Connector cannot be invoked from a queue / cron / webhook without a request-scoped audit context | grep + test |  |
| 1.5 | All HTTP requests outbound from the connector go through one client wrapper that adds rate-limit headers, structured logging, and OF-account-pinning | code review |  |
| 1.6 | Per-IP and per-account rate limits configured below platform thresholds (document the numbers used) | config file |  |
| 1.7 | Pre-commit / CI greps for `print(`, `repr(` of credential model, hardcoded keys, `NEXT_PUBLIC_.*(SECRET|TOKEN|KEY)` | CI run URL |  |
| 1.8 | Production env vars set: `SETTINGS_ENCRYPTION_KEY`, `CLERK_SECRET_KEY`, `DATABASE_URL` (TLS), `RATE_LIMIT_REDIS_URL` | env audit |  |
| 1.9 | TLS terminating only at known reverse proxies; HSTS on; no plain-HTTP listener | curl evidence |  |
| 1.10 | Frontend bundle inspected: no creator credentials, no OF cookies, no Bearer tokens for OF, no integration secrets | bundle grep |  |

---

## Section 2 — Data model & isolation

| # | Check | Method | Status |
|---|-------|--------|--------|
| 2.1 | Every creator-scoped query in the connector path includes `creator_id =` (or org_id) — no global SELECT possible | unit test that fakes a second creator and asserts isolation |  |
| 2.2 | `creator_credentials` rows are unique per `(creator_id, integration_type)` and indexed accordingly | schema check |  |
| 2.3 | `raw` JSON snapshots from OF responses are filtered through an allowlist before persist; no `cookie`, `session`, `auth_token`, `csrf` keys retained | unit test on filter |  |
| 2.4 | Fan PII columns (`username`, `display_name`, `email`, `phone`) are documented; column-level encryption tracked as known gap if not yet shipped | doc link |  |
| 2.5 | Data retention TTLs configured per `onlyfans-intelligence-security-plan.md` §7.2 | config file |  |

---

## Section 3 — Identity, roles, audit

| # | Check | Method | Status |
|---|-------|--------|--------|
| 3.1 | First sync requires `connector_instances.status == approved` AND a separate `audit_events` row "connector.approve" exists, written by an owner, in the last N days | manual SQL |  |
| 3.2 | Every chatter / operator who will see this creator's data has an explicit `creator_grants` row with the right scope; default-deny verified | manual SQL |  |
| 3.3 | No "global" admin can read this creator's data without their grant being recorded | test |  |
| 3.4 | Login audit shows last 7 days of access has no anomalies (unfamiliar IPs, new devices, failed bursts) | log review |  |
| 3.5 | Owner accounts have 2FA enabled at the identity provider (Clerk) | screenshot |  |
| 3.6 | Developer access to production DB is via just-in-time / bastion only; no laptop holds prod creds | proof |  |

---

## Section 4 — Consent & legal

| # | Check | Method | Status |
|---|-------|--------|--------|
| 4.1 | Signed creator consent on file, version current, references "OnlyFans direct connector" by name | document link |  |
| 4.2 | `client_consents` row inserted, `accepted_at` set, `revoked_at` null, `consent_text_hash` matches the signed PDF's SHA-256 | SQL evidence |  |
| 4.3 | Creator briefed (in writing, not just verbally) on: what data we read, how often, what we store, retention windows, how to revoke, how to request deletion | email log |  |
| 4.4 | Agency-side legal review acknowledges the integration is read-only and lists the data scope | email log |  |
| 4.5 | If creator is in EU/UK or other regulated geography: DPA / SCC reviewed | doc link |  |

---

## Section 5 — Connector activation drill (staging first)

Run **in staging**, against a dummy account or scrubbed dataset, before flipping prod. Stage must mirror prod schema and feature-flag wiring.

| # | Drill step | Expected | Status |
|---|-----------|----------|--------|
| 5.1 | Submit credentials with connector still `pending_approval` | Sync is rejected; audit row written |  |
| 5.2 | Try sync without consent row | Rejected; audit row written |  |
| 5.3 | Approve connector + create consent → sync | Reads only; no write endpoints touched (verify via mocked OF surface) |  |
| 5.4 | Toggle `mc.connectors.frozen=true` mid-sync | Sync halts within one iteration; audit row written |  |
| 5.5 | Revoke consent | In-flight sync stops within 60 seconds; audit row written |  |
| 5.6 | Attempt to switch `mode` to `read_write` with single owner approval | Blocked; second owner approval required |  |
| 5.7 | Force decryption error on `creator_credentials` | Loud failure (alert + audit), not silent empty |  |
| 5.8 | Hit credential read endpoint from frontend | Returns `{configured: true, last_used_at}`, **never** the secret |  |
| 5.9 | Trigger an LLM call that includes a fan message body | Redaction layer scrubs PII; audit row records the category and hash, not the body |  |
| 5.10 | Run export endpoint as non-owner | Denied; audit row written |  |
| 5.11 | Run export endpoint as owner with row count > export threshold | Allowed but emits audit + email/Telegram alert to owner |  |

---

## Section 6 — Production go-live (single creator pilot)

| # | Step | Status |
|---|------|--------|
| 6.1 | All Sections 0–5 are ✅ |  |
| 6.2 | Owner sign-off recorded in `audit_events` with action `connector.golive` and `creator_id` set |  |
| 6.3 | Pilot creator notified the connection is going live and given a one-click revocation link/contact |  |
| 6.4 | Read-only mode confirmed (no write capability shipped in this build) |  |
| 6.5 | Dashboards/alerts configured for: sync failure, OF rate-limit response, OF login challenge, kill-switch toggles |  |
| 6.6 | Rollback plan documented: how to revoke credentials, purge data, notify creator within 1 hour |  |
| 6.7 | First sync run reviewed by owner; row counts and sample rows spot-checked against expectation |  |
| 6.8 | Re-check at 24h: no anomalies (unexpected IPs, OF challenge prompts, missing data, surprise writes) |  |
| 6.9 | Re-check at 7d: rate limits stable, no creator account flags, retention job ran on schedule |  |

---

## Section 7 — Sign-off

| Role | Name | Signature / commit SHA | Date |
|------|------|------------------------|------|
| Owner (Mission Control) |  |  |  |
| Owner (Agency, if separate) |  |  |  |
| Creator (consent acknowledgment) |  |  |  |

If any section was completed with caveats, list them here with mitigation and review date:

- _none yet_

---

## Appendix — Items that are deliberately **out of scope** for this checklist

To keep this document the source of truth on safety, not on every nice-to-have:

- KMS migration from env-stored Fernet key.
- Per-creator key partitioning.
- A creator-facing self-serve portal (consent capture is out-of-band for v1).
- Fan-message column encryption (tracked as known gap; will graduate to Section 0 when implemented).
