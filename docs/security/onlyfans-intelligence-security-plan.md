# OnlyFans Intelligence — Security Plan

**Version:** 1.0 (draft)
**Last updated:** 2026-04-28
**Owner:** Zachary (sole operator)
**Scope:** Mission Control as the internal data brain for a creator-management agency. Covers OF Intelligence (read-only via OnlyMonster today), and the planned **direct OnlyFans connector**, plus future creator data: fan PII, chat logs, vault metadata, revenue, client notes.

This is the durable security plan. Every change to the OF Intelligence stack must be testable against the standards in §2 and the controls in §3–§9. If a proposed change cannot be expressed in those terms, it is out of scope and gets a security review before merge.

---

## 1. Threat model

We protect against, in order of expected likelihood:

1. **Credential theft via developer laptop** — a stolen MacBook with cached secrets, a synced `.env`, or an authenticated session.
2. **Cloud provider account compromise** — an attacker reaches the database, the secret manager, or a deployed worker.
3. **Insider misuse** — a chatter, contractor, or future hire reads creator data they should not, or exports it.
4. **Third-party LLM leakage** — fan PII or revenue figures sent to OpenAI/Anthropic/Gemini and retained.
5. **Connector bug** — an OnlyFans direct connector accidentally writes (deletes, sends, refunds) when it should only read.
6. **Creator account hijack** — OnlyFans creator credentials we hold get used to log in as the creator from an unfamiliar IP, locking them out.
7. **Subpoena / legal compulsion** — we are required to produce data we should not have stored in the first place.
8. **Public exposure** — a misconfigured route, public S3 bucket, or stray PR comment leaks one creator's data.

We are **not** primarily defending against nation-state APTs or supply-chain compromise of the language runtime. Mitigations exist (SBOM, pinned deps) but are not the design driver.

---

## 2. Core standards (rephrased from the brief — non-negotiable)

| # | Standard | Concrete meaning here |
|---|----------|------------------------|
| S1 | Every creator must be isolated | Creator data partitioned by `creator_id`; a query missing the scope is a bug, not a feature |
| S2 | Every user only sees what they need | Roles + per-creator permissions + per-action gates. Default deny. |
| S3 | Credentials never touch the frontend | Frontend only handles user auth tokens. Creator/integration secrets are write-only POST → encrypted DB; never returned, never rendered |
| S4 | Every sensitive action is logged | Append-only audit table; all credential, export, sync, LLM, role-change events recorded |
| S5 | Connectors start read-only | Default mode `read`; `read_write` requires second-owner approval and a separate audit entry |
| S6 | Risky workflows need a kill switch | `mc.connectors.frozen` global flag + per-connector `enabled` flag. Hot-toggleable. |
| S7 | Clients consent before account data is connected | `client_consents` row, signed text hash, revocable. No consent → no sync. |
| S8 | Raw sensitive data minimized / summarized | `raw` JSON snapshots strip credential-like keys; long-tail data summarized via LLM with redaction; retention TTLs enforced |

---

## 3. Identity, roles, and access

### 3.1 Identity
- Production: **Clerk** SSO, JWT-based, single source of truth for user identity.
- Self-host / dev: **local bearer token** with constant-time compare; never reused as encryption key in production.
- No password storage in Mission Control's DB.

### 3.2 Role layers
- **Mission Control global roles**: `owner | builder | viewer`. Owner manages all org membership, builder operates within orgs, viewer is read-only.
- **Per-organization member roles**: `owner | admin | member` with `all_boards_read` / `all_boards_write` granular flags.
- **Per-creator permissions** (new): `creator_grants(user_id, creator_id, scope: read_meta | read_messages | read_revenue | manage_credentials | none)`. Default `none`.

A request must satisfy: global role check → org membership → per-creator scope check. Missing any one → 403, audit entry, no data returned.

### 3.3 Default deny
- New users land at `viewer` + zero org memberships + zero creator grants.
- New endpoints require an explicit RBAC decorator. CI rejects undecorated routes.

### 3.4 Developer / operator separation
- **Operators** (chatters, agency staff): use the UI only. No DB or shell access.
- **Developers** (today: Zach; later: contractors): code repo access is normal, **production data access is just-in-time** via a bastion that records the session. Routine work uses scrubbed staging data.
- Break-glass: documented procedure to grant temporary prod access; logged in audit; auto-expires.

---

## 4. Credentials & secrets

### 4.1 Storage
- All third-party credentials, API keys, OAuth tokens, and creator credentials live in encrypted columns. Two stores:
  - `app_settings` — tenant-global or org-scoped key/value (provider keys, integration keys).
  - `creator_credentials` (new) — `(creator_id, integration_type, ciphertext, key_version, created_by, rotated_at, last_used_at)`.
- Cipher: Fernet over a SHA-256-derived key from `SETTINGS_ENCRYPTION_KEY`.
- `SETTINGS_ENCRYPTION_KEY` MUST be a dedicated value in production. Refuse to start if it falls back to the auth token.
- Key rotation: documented procedure that re-encrypts all rows, bumps `key_version`. No surprise rotations.

### 4.2 Frontend rules
- No credential, OAuth token, OnlyFans cookie, or session_id is ever returned to the browser. Endpoints that touch them return only `{configured: bool, last_rotated_at, last_used_at}`.
- The browser only ever sends credentials in the **write** direction (PUT/POST), over TLS, into a backend route that encrypts before insert.
- No `NEXT_PUBLIC_*_TOKEN`, `NEXT_PUBLIC_*_KEY`, or `NEXT_PUBLIC_*_SECRET` in production builds. CI greps for it.

### 4.3 In-flight
- TLS 1.2+ only. HSTS on the frontend. No HTTP fallback.
- Internal service traffic stays on a private network or mTLS where it must cross the public internet (e.g. OpenClaw remote gateway).

### 4.4 Logs and errors
- Secrets never enter logs. Tracebacks are scrubbed. `repr()` of credential models returns redacted output.
- Decryption failure is loud: alert + audit, never silent empty string.

---

## 5. Connector model

Every external integration (OnlyMonster, OnlyFans direct, Telegram, Discord, AdsPower, PhantomBuster, etc.) is a **connector** that conforms to this lifecycle:

```
proposed → pending_approval → approved → active(read) → [optional] active(read_write) → suspended → revoked
```

### 5.1 Activation gate
- `pending_approval` is the default after credential submission. Sync is blocked.
- Owner moves to `approved` from an admin UI; this writes an `audit_events` row.
- First sync runs only after `approved` AND a non-revoked `client_consents` row exists for the creator(s) this connector touches.

### 5.2 Mode
- Default mode = `read`. Connector library refuses any write/destructive call.
- `read_write` requires a **second** owner approval and a separate audit row. UI shows a banner that read-write is on.
- `dry_run` mode runs the full pipeline but commits nothing — used for staging and end-to-end test runs.

### 5.3 Kill switch
- A single DB row `mc.connectors.frozen=true` halts every sync entry point on next iteration. New approvals are rejected.
- Per-connector `enabled` flag does the same for one connector.
- Both togglable from the admin UI by an owner; both write audit rows.

### 5.4 Direct OnlyFans connector — extra rails
- No build, no live account, until the gap audit's "must exist before direct connector" list is green.
- Read-only at first launch. No `like`, `subscribe`, `message`, `tip`, `mass_message`, `delete`, `pay_out`, or `refund` capabilities.
- Per-creator credential entries; no shared OF cookies.
- Per-IP and per-account rate limits, conservative below platform thresholds, to avoid creator account flags.
- Anomaly detection: alert if sync sees a country/device change vs. the creator's expected profile.

---

## 6. Client consent

- `client_consents` row required before any connector touches a creator's data.
- Row contents: `creator_id`, `integration_type`, `consent_text_hash`, `consent_text_url`, `accepted_at`, `accepted_by`, `accepted_via` (DocuSign / signed PDF / in-app), `revoked_at`, `revoked_reason`.
- Revocation is one click from the creator-facing portal **or** from the admin UI; on revocation, all in-flight syncs for that creator stop within 60 seconds, audit row is written, and a follow-up retention job purges or anonymizes data per the consent's data-scope clause.
- Consent text is versioned; new version requires re-acceptance.

---

## 7. Data minimization, retention, and AI

### 7.1 Minimize
- `raw` JSON snapshots from upstream APIs are filtered before persist: an explicit allowlist of safe fields. Anything that looks like a credential, cookie, session, or token is stripped at the integration boundary.
- Fan messages are stored as plaintext today; phase-2 introduces column-level encryption for `of_intelligence_messages.body` once the per-creator key model lands.
- We do not store full media files in the primary DB; references only.

### 7.2 Retain
| Table family | Retention | Rationale |
|---|---|---|
| `of_intelligence_messages` | 180 days | Long enough for QC and trend analysis, short enough to limit blast radius |
| `of_intelligence_alerts` | 90 days | Operational only |
| `of_intelligence_sync_logs` | 30 days | Debugging window |
| `of_intelligence_revenue` | 7 years | Financial record-keeping |
| `business_memory_entries` | indefinite, manually curated | Summaries are low-blast-radius |
| `audit_events` | 2 years (configurable) | Investigations sometimes go back 12+ months |
| `creator_credentials` | until rotated/revoked, then immediate purge | No reason to keep stale tokens |

A scheduled job (RQ) enforces these. Manual override requires audit.

### 7.3 AI / LLM access
- Every LLM call is logged: actor, provider, model, prompt hash, prompt category, response hash, retention setting on the provider account.
- A redaction layer between MC and the LLM strips fan usernames, full names, phone numbers, emails, and message bodies unless the call category is explicitly `summarize_messages` and the creator's consent allows it.
- We prefer providers with documented zero-retention modes for inference. We never sign up for a free tier that trains on customer data for fan-message-bearing prompts.
- LLM calls are subject to the same kill switch (`mc.ai.frozen`) as connectors.

---

## 8. Audit logging

A new `audit_events` table:

```
id (uuid) | created_at | actor_user_id | actor_org_id | action
        | target_type | target_id | creator_id (nullable)
        | payload_hash | outcome (ok | denied | error) | ip | user_agent
        | metadata (jsonb, redacted)
```

Wired into:
- Login (success + failure).
- Role change (global, org, per-creator).
- Credential write / read (read with `last_used_at` only — never the secret) / delete / rotate.
- Connector approve / suspend / revoke / mode change / enable / disable.
- Consent accept / revoke.
- Sync start / finish / abort.
- Export — full and paginated >N.
- LLM call (category + provider + hash; never prompt body in clear).
- Kill switch toggles.

Append-only. Read access requires `owner`. Backups are encrypted and offsite.

---

## 9. Operational practices

### 9.1 Environments
- `prod` — locked-down, real creator data.
- `staging` — schema-equivalent, scrubbed/synthetic data only. No real credentials.
- `dev` — local, no real credentials, no real fan data.

### 9.2 Backups
- Encrypted at rest with a separate key from the application encryption key.
- Tested restore quarterly; restore drill is part of the breach plan.

### 9.3 Monitoring
- Alerts: failed-login burst, decryption failure, kill-switch toggle, mass-export, outbound LLM call without redaction, connector drift from `read` to `read_write`, gateway token mismatch.

### 9.4 Change control
- Migrations that touch `app_settings`, `creator_credentials`, `audit_events`, `client_consents`, or any `of_intelligence_*` table require a security-review note in the PR description matching this plan.
- Pre-commit hook scans for: `print()` of credential model fields, `repr()` of the same, `NEXT_PUBLIC_*` of secret-shaped names, hardcoded keys.
- Production deploy requires the connector kill switch state to be reported in the deploy log.

### 9.5 Incident response
- Per `breach-response-plan.md`. Drilled at least once before the first live OF direct creator.

---

## 10. Out of scope (explicit)

To prevent scope creep:

- We are **not** building a customer-facing creator portal in this phase. Creator consent capture for v1 happens out-of-band (signed PDF or DocuSign), recorded in `client_consents`.
- We are **not** building per-creator HSM partitions in v1. One Fernet key, one rotation procedure.
- We are **not** building automated PII detection on inbound `raw` payloads in v1; we use an explicit allowlist of safe fields per integration.
- We are **not** offering self-serve user signup; every account is provisioned by the owner.

---

## 11. Open questions

- Where does the consent text live and who maintains its versioning?
- Do we need an SCC / DPA for international creators? (Probably yes — flag for legal.)
- Backup encryption key custody — split between Zach + agency principal, or 1Password vault?
- Long-term: switch from Fernet/env-key to AWS KMS / GCP KMS / 1Password-managed key? Decide before HSM-grade clients onboard.
