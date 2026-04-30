# Security Gap Audit — Mission Control / OnlyFans Intelligence

**Audit date:** 2026-04-28
**Auditor:** Claude (read-only inspection of `mission-control-main` @ `main` and `mission-control-of-intelligence` @ `feat/of-intelligence`)
**Trigger:** Pre-flight review before any direct OnlyFans connector is built.
**Status:** Documentation only — no code changed, no commit.

---

## 0. Executive summary

Mission Control already has the **bones** of a credential-handling system (Fernet-encrypted `app_settings` table, owner-gated routes, Clerk-or-local auth, organization-scoped boards/gateways). It is **not yet** ready to hold direct OnlyFans creator credentials, fan PII, chat logs, or revenue data with the durability the agency mandate requires.

Six areas are blocking:

1. No connector approval / consent flow.
2. No structured audit log for sensitive ops (export, credential write, LLM send).
3. No global kill switch / feature flag for OF Intelligence or any single connector.
4. No data retention policy or cleanup job — every table grows forever.
5. LLM prompt traffic is unlogged and unfiltered; fan messages can leak to third-party providers.
6. Settings (provider keys, integration keys) are **global**, not org-scoped — one tenant can read another's keys.

The eight core standards from the brief map to current state as follows:

| # | Standard | Current state | Gap |
|---|----------|---------------|-----|
| 1 | Every creator must be isolated | Org-scoped boards/gateways exist; settings are global | Per-creator isolation incomplete |
| 2 | Users only see what they need | Global MC roles + per-org member roles + per-board flags | UI does not surface org role; no per-creator scope |
| 3 | Credentials never touch the frontend | Backend stores Fernet-encrypted in `app_settings`; PUT body carries plaintext over HTTPS | Acceptable in transit; `NEXT_PUBLIC_LOCAL_AUTH_TOKEN` build var is a footgun |
| 4 | Every sensitive action is logged | `ActivityEvent` exists for board/task/agent ops; nothing for credential / export / LLM | Major gap |
| 5 | Connectors start read-only | OnlyMonster client refuses `write=True`; no MC-side `read_only` flag | Partial — OF direct connector will not inherit this |
| 6 | Risky workflows need a kill switch | None | Major gap |
| 7 | Clients consent before account data is connected | None | Major gap |
| 8 | Raw sensitive data minimized / summarized | Fan messages stored plaintext; `raw` JSON snapshots stored verbatim | Major gap |

---

## 1. What already exists (keep, build on)

### 1.1 Auth & identity
- **Dual-mode auth** (Clerk JWT or local bearer) wired through one FastAPI dependency:
  `backend/app/core/auth.py:560` (`get_auth_context`), `:605` (`_optional`).
- **Local token** is constant-time-compared and length-validated (`config.py:44`).
- **User auto-sync** on first sign-in pulls profile from Clerk (`auth.py:110-138`).
- **Frontend provider** swaps between Clerk and local-auth login UI (`frontend/src/components/providers/AuthProvider.tsx:14-46`).

### 1.2 RBAC (two layers, both real)
- **Global Mission Control roles** — `owner | builder | viewer`, table `mc_user_roles` keyed on `clerk_user_id`, default `viewer`, with `disabled` flag.
  Source: `backend/app/models/mc_role.py:12-27`, dependency `backend/app/api/mc_roles.py:78` (`get_mc_role`), `:90` (`require_owner`).
  Owner-only routes: app_settings, telegram, control_agents, allowed_users.
- **Per-organization member roles** — `member | admin | owner` with granular `all_boards_read` / `all_boards_write` flags.
  Source: `backend/app/models/organization_members.py:17-36`, helper `backend/app/services/organizations.py` (`is_org_admin`, `require_board_access`, `ROLE_RANK`).
- **Frontend RoleGuard** — `frontend/src/components/auth/RoleGuard.tsx` with safe default-to-`viewer` on fetch failure (`use-role.ts:45`).

### 1.3 Per-tenant isolation (partial)
- **Organization** is the tenant primitive; boards, gateways, agents all carry `organization_id` FK.
- Board endpoints actually enforce `require_board_access`. Example: `backend/app/api/tasks.py:1446, 1463, 1493`.
- Gateway list endpoint filters by `ctx.organization.id` — `backend/app/api/gateways.py:75-87`.

### 1.4 Encrypted secrets at rest
- `app_settings` table (`backend/app/models/app_setting.py:12`) holds key/value where `value` is **Fernet ciphertext**.
- Cipher derived from `SETTINGS_ENCRYPTION_KEY` env var (preferred) → SHA-256 → Fernet — `backend/app/core/secrets_store.py:5-72`.
- Helpers `set_secret`, `get_secret`, `get_secret_with_source` in same file.
- Already covers: provider API keys (OpenAI, Gemini, Anthropic), AdsPower, PhantomBuster, OnlyMonster, GitHub PAT.

### 1.5 Activity log (light)
- `ActivityEvent` table + `record_activity()` helper — `backend/app/services/activity_log.py:15`.
- Wired into board/task/agent/approval mutations.

### 1.6 Approval primitive
- `Approval` table (`backend/app/models/approvals.py:17`) with `action_type`, `payload`, `confidence`, `status`. Currently used for **task** gating; the schema is reusable for connector approval.

### 1.7 OF Intelligence schema (read-only snapshot today)
- `OfIntelligenceAccount`, `…Fan`, `…Chat`, `…Message`, `…Chatter`, `…MassMessage`, `…Post`, `…TrackingLink`, `…Revenue`, `…QcReport`, `…Alert`, `…SyncLog`, `BusinessMemoryEntry` — all in `backend/app/models/of_intelligence.py:44-352`.
- Critically: **no creator credentials are stored in OF Intelligence tables today**. OnlyMonster is a global aggregator with one tenant-level API key.

---

## 2. What is missing (must be built)

The following are **flat-out absent** from the codebase as of this audit:

| # | Missing | Why it matters |
|---|---------|----------------|
| M1 | **Audit log for sensitive ops** — credential write/delete, export, connector enable, LLM send, role change, login | Cannot answer "who pulled this fan list" after an incident |
| M2 | **Connector approval flow** — `connector_status` (pending → approved → blocked), gate first sync on approval | Today, submitting a key triggers immediate sync |
| M3 | **Client consent record** — table tying creator → integration_type → consent text hash → accepted_at → revocation | No legal record of data access agreement |
| M4 | **Kill switch / feature flags** — DB-driven on/off per integration, plus a global "freeze" | No runtime way to disable a connector without code deploy |
| M5 | **Data retention policy + cleanup job** — TTL on messages, alerts, sync logs, AI logs | All tables append-only; data grows forever |
| M6 | **LLM access logging + redaction layer** — log every prompt, by whom, to which provider, with hash; strip fan PII before send | `_call_anthropic` / `_call_openai` in `backend/app/core/ai_backend.py:167,181` send raw user prompts unaudited |
| M7 | **Read-only / dry-run mode for connectors** — `mode: read \| read_write \| dry_run` on integration config | OnlyMonster client has `write=True` refusal but it's library-side, not an MC-side toggle |
| M8 | **Per-org / per-creator settings scoping** — today, `app_settings` is global; one owner sets keys for everyone | Cross-tenant credential leakage |
| M9 | **Export controls** — rate limiting, owner-only gating, audit log on `/of-intelligence/memory/export` and large `limit=` GETs | Today an owner can dump everything silently |
| M10 | **Developer access limits** — role separation between "operator" (can run sync) and "developer" (can read code/logs but not creator data); break-glass procedure | Anyone with DB access reads everything |
| M11 | **Per-creator credential vault** — table `creator_credentials(creator_id, integration_type, ciphertext, key_version, created_by, rotated_at)` | Required before any direct OF connector |
| M12 | **Frontend route-level redirect on unauth** — today unauth users see "Access denied" UI instead of redirect | Minor UX / phishing surface |

---

## 3. What is risky (exists but unsafe)

| # | Risk | Location | Severity | Recommended action |
|---|------|----------|----------|--------------------|
| R1 | `NEXT_PUBLIC_LOCAL_AUTH_TOKEN` baked into frontend build | `frontend/src/auth/localAuth.ts:37-40` | **High** | Strip from any production build; document as dev-only; refuse to start if set in `NODE_ENV=production` |
| R2 | `SETTINGS_ENCRYPTION_KEY` falls back to `LOCAL_AUTH_TOKEN` then `CLERK_SECRET_KEY` | `backend/app/core/secrets_store.py:48-72` | **High** | Require dedicated key in production; refuse to start if missing; alert on every decryption failure |
| R3 | Decryption failure silently returns `""` | `secrets_store.py:82` | Medium | Raise + alert; never let "missing" and "broken" look identical |
| R4 | `gateways.token` stored plaintext | `backend/app/models/gateways.py:25` | **High** | Encrypt with same Fernet store; migrate existing rows |
| R5 | `app_settings` is global, not per-org | All call sites in `backend/app/api/integrations.py`, `app_settings.py` | **High** | Add `organization_id` (nullable for global) + scope reads/writes; migrate existing rows to "global" |
| R6 | `is_super_admin` field on `User` is unused but exists | `backend/app/models/users.py` | Low | Remove or wire to a real super-admin path with audit |
| R7 | First caller auto-becomes owner if `mc_user_roles` empty | `backend/app/api/mc_roles.py:65` | Medium | Acceptable for self-host; for multi-tenant prod, require explicit bootstrap |
| R8 | `POSTGRES_PASSWORD=postgres` default in root `.env.example` | `.env.example:11` | Medium | Replace with `__CHANGE_ME__` and refuse compose start |
| R9 | Fan message bodies stored plaintext in `of_intelligence_messages.body` | `backend/app/models/of_intelligence.py:127` | Medium | Acceptable read-only snapshot; flag for future column-level encryption when direct connector lands |
| R10 | `raw` JSON columns store full upstream payloads (may include credentials, tokens, internal IDs) | `OfIntelligenceAccount.raw` and siblings | Medium | Strip credential-like keys before persisting; document allowlist |
| R11 | `delete /api/v1/users/me` requires only authentication, no role check | `backend/app/api/users.py:227-292` | Low | Add audit log; consider grace period / soft delete for orgs |
| R12 | Owner-only `/api/v1/roles/users` returns **all users on the instance**, not org-scoped | `backend/app/api/mc_roles.py:134-162` | Medium | Scope to caller's org once org-scoped settings land |
| R13 | LLM prompt body is the raw user-supplied string with no PII redaction | `backend/app/core/ai_backend.py:167,181` | **High** (once fan data is involved) | Add redaction + audit log per M6 |

---

## 4. What MUST exist before the direct OnlyFans connector

Hard prerequisites. Do not start the connector code without these landed and reviewed:

1. **Per-creator credential vault** (M11) — encrypted, key-versioned, with rotation API.
2. **Connector approval flow** (M2) — connector starts in `pending`, requires owner approval to move to `approved`; only `approved` can sync.
3. **Client consent record** (M3) — must be present and not-revoked at every sync invocation; written to audit log.
4. **Kill switch** (M4) — a single DB row that, when flipped, halts every connector sync immediately and rejects new ones.
5. **Read-only default mode** (M7) — direct connector ships `mode="read"`; `read_write` requires a second owner approval and a separate audit entry.
6. **Audit log table** (M1) — every credential write, sync start/finish, export, and LLM send is recorded with actor, timestamp, hash, and outcome. Append-only.
7. **Org-scoped settings** (M8) — even if only one org exists today, the schema must scope keys to org_id so the OF connector cannot accidentally use another tenant's secret.
8. **Encrypted `gateways.token`** (R4) — fix the existing plaintext field before adding more.
9. **Production encryption key isolation** (R2) — `SETTINGS_ENCRYPTION_KEY` must be a dedicated, rotation-tracked secret. Document rotation procedure.
10. **Breach response plan + drill** (`breach-response-plan.md`) — written, reviewed, drilled at least once.

Stretch but strongly recommended before first live creator:

11. **LLM redaction + audit** (M6 + R13).
12. **Export route audit + rate limit** (M9).
13. **Data retention job** (M5).

---

## 5. What can wait

These improve security but should not block the first direct connector if the prerequisites above are met:

- Frontend route-level auth redirect (R/M12) — current "Access denied" UI is acceptable.
- Removing `is_super_admin` dead field (R6).
- Replacing `POSTGRES_PASSWORD` default in `.env.example` (R8) — already gated by other env validation.
- Granular per-board permission UI exposure for org admins.
- Hardware-backed (KMS / Cloud HSM) encryption key — Fernet + secret-manager-stored key is acceptable for v1.
- Per-tenant separate database — schema-level `organization_id` scoping is acceptable for v1.

---

## 6. Recommended build order

Each step ends with a documented review checkpoint. **Do not skip**.

**Phase A — Foundations (no connector work)**
1. Add `audit_events` table + `record_audit(actor, action, target, payload_hash, outcome)` helper. Wire into existing credential write/delete, export endpoints, role changes, and LLM call sites.
2. Add `feature_flags` table + admin UI row toggles. Add a global `mc.connectors.frozen` flag and check it in every sync entry point.
3. Encrypt `gateways.token`; backfill migration.
4. Add `organization_id` (nullable for "global") to `app_settings`; migrate; scope reads.

**Phase B — Approval & consent rails**
5. Extend `Approval` table usage for connectors: new `action_type='connector.activate'`. Add `connector_status` to a new `connector_instances` table.
6. Add `client_consents` table — `creator_id, integration_type, consent_text_hash, accepted_at, accepted_by, revoked_at`. Block sync if no live consent.
7. Add `mode` field to `connector_instances` (`read | read_write | dry_run`), default `read`. Mode change writes audit + requires second owner.

**Phase C — Data hygiene**
8. Add LLM redaction layer in `ai_backend.py` — strip fan PII, message bodies, revenue numbers unless explicitly opted in. Log every call.
9. Add retention job (RQ scheduled task): purge `of_intelligence_messages` > 180d, `…_alerts` > 90d, `…_sync_logs` > 30d, `audit_events` > 730d (configurable).
10. Add export endpoint guards: rate limit, owner-only, audit on every call, recipient email for >N row exports.

**Phase D — OF direct connector itself (only after A–C green)**
11. `creator_credentials` table (encrypted, key-versioned).
12. Direct OF client, `read` mode only, hits **only** non-mutating endpoints. Sync gated on approval + consent + kill switch + read mode.
13. Drill the breach response plan against this connector before first live creator.

**Phase E — Operational hardening**
14. Developer access split (M10) — production DB read access via just-in-time bastion, no laptop credentials.
15. Hardware-backed key (KMS) migration if scale warrants.
16. Per-creator key partitioning (one Fernet key per creator) for blast-radius reduction.

---

## 6.3 Sprint 3 progress (2026-04-29)

The following items from §2 / §3 are addressed by Security Sprint 3 on
branch `feat/security-hardening-sprint-3`:

- **R4 (plaintext `gateways.token`) — partial.** New writes encrypt
  via `app.services.gateway_tokens.set_token`; legacy rows have a
  one-shot migrator (`migrate_legacy_tokens`). API responses still
  expose `token` for backwards compat (Sprint 4 task to deprecate).
- **R5 (`app_settings` global) — foundation done.** New
  `organization_id` column + `app.services.app_settings_scoped`
  helpers; existing route call sites still global, scheduled for
  migration in Sprint 4.
- **R2 (`SETTINGS_ENCRYPTION_KEY` fallback) — closed for production.**
  `app.core.startup_guard.assert_production_encryption_configured`
  refuses to start the app in production without a dedicated key.
  Local/dev fallback unchanged.
- **G3 (denial audit) — done.** 401/403 throttled audit hook in
  `app.core.denial_audit`. Login-success audit deferred to Clerk
  webhook (Sprint 4).
- **M5 (data retention) — foundation done.** Per-category retention
  helpers in `app.services.audit_retention`; default dry-run.
  Scheduling is Sprint 4.
- **M6 (LLM PII redaction) — done for outbound prompts.**
  `app.core.pii_redact.redact_for_llm` wired into `ask_ai_detailed`.
- **Connector gate wiring — wrapper added, not yet wired.**
  `app.services.connector_run.run_with_gate` is tested but not
  attached to any hot path. First production wiring is Sprint 4.
- **R1 (`NEXT_PUBLIC_LOCAL_AUTH_TOKEN` footgun) — runtime guard
  added.** Fallback is refused with a console warning when
  `NODE_ENV=production`.

Items still open: G1 (`GatewayRead` token exposure), G2 (call-site
migration to org-scoped settings), G3 (login-success audit), G4
(per-dep denial detail), G5 (retention scheduling), G6 (connector gate
wiring into real sync), G10 (per-creator key partitioning), G11
(frontend security dashboard). See
[`security-sprint-3-implementation.md`](./security-sprint-3-implementation.md)
§11 and §12 for the prioritised Sprint 4 plan.

## 6.2 Sprint 2 progress (2026-04-29)

The following items from §2 ("What is missing") and §3 ("What is risky")
are addressed by Security Sprint 2 on branch
`feat/security-prevention-sprint-2`:

- **M2 (connector approval flow) — done.** `connector_approvals` table
  + `app.services.connector_approvals` with state machine
  pending → approved/rejected → revoked/expired, every transition
  audited under category `connector`.
- **M4 (kill switch / feature flags) — done.** `kill_switches` table
  with four scopes (global / connector / organization / creator) +
  `app.services.kill_switch.check_action_allowed` composite check.
  Toggles audit at severity `critical`.
- **M3 (client consent records) — done.** `client_consents` table +
  service (grant / revoke / is_granted), with all 8 consent types from
  the security plan §6.
- **M11 (per-creator credential vault) — foundation done.**
  `creator_credentials` table + service (create / rotate / revoke /
  metadata-only-read). Hard guardrail: the vault refuses writes if
  `SETTINGS_ENCRYPTION_KEY` is not set (closes the worst form of R2 for
  the *new* high-sensitivity surface, while leaving legacy flows
  untouched for dev convenience).
- **M7 (read-only / dry-run mode) — partial.** Vault and gate only
  support read-mode pre-checks today; `mode` enforcement on a
  `connector_instances` table is not yet implemented because there is
  no connector to gate.
- **Composite gate** at `app.core.connector_gate.is_connector_action_allowed`
  — the single chokepoint a future connector must call. Fail-closed in
  every dimension, returns a typed `GateVerdict` so the operator knows
  *why* an action was blocked.
- **Security admin status endpoint** — owner-gated `GET
  /api/v1/security/status`, returns aggregates only (no PII, no
  metadata bodies). Useful for runbook checks and incident drills.

Items still open: M5 (retention), M6 (LLM redaction layer), M8
(org-scope `app_settings`), M9 (export controls), M10 (developer
access split), M12 (frontend route redirect). Risks R1, R4, R5 still
open (see §3). See
[`security-sprint-2-implementation.md`](./security-sprint-2-implementation.md)
§9 and §10 for the full Sprint 3 plan.

## 6.1 Sprint 1 progress (2026-04-29)

The following items from §2 ("What is missing") are addressed by Security
Sprint 1 on branch `feat/security-foundation-sprint-1`:

- **M1 (audit log) — partial.** `audit_events` table + `record_audit()`
  service shipped. Wired into: integration credential save/delete,
  provider API key save/delete, GitHub credential save/delete, role
  set/remove, every LLM provider attempt. **Not yet wired:** login,
  authorization denials, exports, connector runs, approval lifecycle,
  kill-switch toggles, telegram /test probe. See
  [`audit-events-implementation.md`](./audit-events-implementation.md)
  §6 for the full gap list.
- **Metadata redaction** (security plan §7.3 prerequisite) — done. A
  new `redact_metadata()` utility under `app.core.redact` is mandatory
  on every audit write; producers cannot bypass it.
- **Alembic heads** — the pre-existing repo had three diverging heads;
  Sprint 1's audit migration is a 3-way merge so post-Sprint-1 there is
  one head.

Items M2–M12 and risks R1–R13 remain open and feed Sprint 2's plan; see
[`audit-events-implementation.md`](./audit-events-implementation.md) §10
for the prioritized sequence.

---

## 7. Files reviewed

Backend:
- `backend/app/core/auth.py`
- `backend/app/core/config.py`
- `backend/app/core/secrets_store.py`
- `backend/app/core/ai_backend.py`
- `backend/app/models/users.py`
- `backend/app/models/mc_role.py`
- `backend/app/models/organizations.py`
- `backend/app/models/organization_members.py`
- `backend/app/models/gateways.py`
- `backend/app/models/app_setting.py`
- `backend/app/models/approvals.py`
- `backend/app/models/activity_events.py`
- `backend/app/models/of_intelligence.py` (feat/of-intelligence)
- `backend/app/api/mc_roles.py`
- `backend/app/api/app_settings.py`
- `backend/app/api/integrations.py`
- `backend/app/api/gateways.py`
- `backend/app/api/users.py`
- `backend/app/api/of_intelligence.py` (feat/of-intelligence)
- `backend/app/api/tasks.py` (selected handlers)
- `backend/app/api/approvals.py`
- `backend/app/api/agent.py`
- `backend/app/api/messaging.py`, `telegram.py`, `discord.py`, `control_agents.py`
- `backend/app/services/activity_log.py`
- `backend/app/services/organizations.py`
- `backend/app/integrations/onlymonster/client.py` (feat/of-intelligence)

Frontend:
- `frontend/src/components/providers/AuthProvider.tsx`
- `frontend/src/components/auth/RoleGuard.tsx`
- `frontend/src/hooks/use-role.ts`
- `frontend/src/hooks/use-auth-fetch.ts`
- `frontend/src/auth/localAuth.ts`
- `frontend/src/app/settings/page.tsx`
- `frontend/src/app/integrations/page.tsx`

Config:
- `.env.example` (root, backend, frontend)
- `compose.yml`
