# Security Sprint 3 — Hardening

**Status:** Sprint 3 of N. Closes the most dangerous gaps left after
Sprint 2. Builds on the audit foundation (Sprint 1) and the prevention
controls (Sprint 2).
**Branch:** `feat/security-hardening-sprint-3`
**Last updated:** 2026-04-29

This document is the developer-facing companion to
[`onlyfans-intelligence-security-plan.md`](./onlyfans-intelligence-security-plan.md)
and the prior implementation notes:
[Sprint 1 audit foundation](./audit-events-implementation.md) and
[Sprint 2 prevention](./security-sprint-2-implementation.md).

---

## 1. What was added

| Concern | Where |
|---|---|
| Gateway-token encryption (encrypt-on-write, lazy-decrypt-on-read, legacy migrator) | [`backend/app/services/gateway_tokens.py`](../../backend/app/services/gateway_tokens.py) |
| `gateways.encrypted_token` column + `app_settings.organization_id` column | [`backend/migrations/versions/c23d4e5f6a7b_add_security_hardening_columns.py`](../../backend/migrations/versions/c23d4e5f6a7b_add_security_hardening_columns.py) |
| Gateway create/update routes wired through `set_token` | [`backend/app/api/gateways.py`](../../backend/app/api/gateways.py) |
| Org-scoped app-settings reads/writes | [`backend/app/services/app_settings_scoped.py`](../../backend/app/services/app_settings_scoped.py) |
| Production startup guard (refuses to start without `SETTINGS_ENCRYPTION_KEY` in production) | [`backend/app/core/startup_guard.py`](../../backend/app/core/startup_guard.py) (registered in [`backend/app/main.py`](../../backend/app/main.py)) |
| Denial-audit hook for 401 / 403 with throttling | [`backend/app/core/denial_audit.py`](../../backend/app/core/denial_audit.py) (registered in [`backend/app/main.py`](../../backend/app/main.py)) |
| Audit retention preview + dry-run purge | [`backend/app/services/audit_retention.py`](../../backend/app/services/audit_retention.py) |
| PII redactor for outbound LLM prompts (wired into `ask_ai_detailed`) | [`backend/app/core/pii_redact.py`](../../backend/app/core/pii_redact.py), [`backend/app/core/ai_backend.py`](../../backend/app/core/ai_backend.py) |
| Gated-run wrapper that future connectors must use | [`backend/app/services/connector_run.py`](../../backend/app/services/connector_run.py) |
| Frontend `NEXT_PUBLIC_LOCAL_AUTH_TOKEN` production-build guardrail | [`frontend/src/auth/localAuth.ts`](../../frontend/src/auth/localAuth.ts) |
| Expanded `GET /api/v1/security/status` (+ legacy gateway count, retention preview, prod flag) | [`backend/app/api/security_admin.py`](../../backend/app/api/security_admin.py) |
| Tests | [`backend/tests/test_security_hardening.py`](../../backend/tests/test_security_hardening.py) |

---

## 2. Gateway token encryption — status

**Done:** all *new* writes flow through
`app.services.gateway_tokens.set_token`, which encrypts under Fernet
and stores the ciphertext in the new `encrypted_token` column. The
legacy plaintext `token` column is **cleared** on any new write, so
post-Sprint-3 gateway rows never carry both forms.

**Open:** legacy rows that were created before this sprint still have
their plaintext token until an operator runs:

```python
from app.services.gateway_tokens import migrate_legacy_tokens

# Dry run first:
scanned, would_migrate = await migrate_legacy_tokens(session, dry_run=True)

# Then for real:
scanned, migrated = await migrate_legacy_tokens(
    session,
    dry_run=False,
    actor_email="owner@example.com",
)
await session.commit()
```

Each migrated row records a `gateway.token.legacy_migrated` audit
event at severity `high`. The migrator refuses to run if
`SETTINGS_ENCRYPTION_KEY` is not set (encrypting under the auth-token
fallback would create rows that become unreadable on the next
auth-secret rotation).

**Read path:** `get_token(gateway)` returns the plaintext value,
preferring `encrypted_token` (decrypted) and falling back to legacy
`token` for unmigrated rows. A decrypt failure on a corrupt
ciphertext returns `None` rather than silently falling back to the
legacy column.

**Not done:** API responses still expose the `token` field via
`GatewayRead`. Post-Sprint-3 rows have it cleared, so new gateways
return `null`. **Legacy rows (until migrated) still leak** through
the API. The right fix — strip `token` from `GatewayRead` entirely
and add a `token_configured: bool` instead — is a follow-up because
the frontend currently consumes `token`. Tracked as Sprint 4.

---

## 3. App-settings org scoping — status

**Done:** new `organization_id` column on `app_settings` (nullable,
indexed). `app.services.app_settings_scoped` provides
`get_secret_for_org` / `set_secret_for_org` / `delete_secret_for_org`
with org-prefer-then-global semantics.

The module sidesteps the existing `key`-as-PK constraint by using a
**derived storage key** (`org:{uuid}.{key}`) for org-scoped rows.
Legacy global rows keep using the bare key. This means two orgs that
both set `api_key.openai` end up with two distinct rows; neither sees
the other.

**Not done:** existing call sites in
[`backend/app/api/integrations.py`](../../backend/app/api/integrations.py)
and [`backend/app/api/app_settings.py`](../../backend/app/api/app_settings.py)
still write to **global** rows. Migrating those routes to pass an
`organization_id` is straightforward but touches user-visible
behaviour (an owner who sets the OpenAI key for their org would no
longer see the same key from another org). Deferred to Sprint 4 with
a feature flag for the cutover.

The schema is forward-compatible: when Sprint 4 promotes scoping,
existing data does not need to be rewritten. The composite-unique
constraint on `(key, organization_id)` can be added at that time.

---

## 4. Production encryption guardrail

**Done:** `app.core.startup_guard.assert_production_encryption_configured`
is called from the FastAPI lifespan. If `ENVIRONMENT` is `production`
or `prod` and `SETTINGS_ENCRYPTION_KEY` is unset, the app refuses to
start with `InsecureProductionStartupError`. The error message tells
the operator how to generate a key but **never** logs an actual key
value.

Local / dev / test environments still allow the auth-token fallback
for ergonomic reasons — Sprint 3 doesn't break local development.

**Tested:** `test_startup_guard_dev_environment_passes`,
`test_startup_guard_production_without_key_raises`,
`test_startup_guard_production_with_key_passes`.

---

## 5. Auth and denial audit coverage

**Login success:** **not** audited per-request (would generate
massive audit volume). A real login-success event needs a Clerk
webhook integration; documented as Sprint 4 work.

**Denial (401 / 403):** audited via
`app.core.denial_audit.install_denial_audit_handler`, registered on
the FastAPI app at construction time. The handler:

- Wraps every `HTTPException`. For 401 / 403 only, it writes an
  audit row at category `auth`, severity `warning`, with the IP, the
  user-agent (capped at 200 chars), the path, and the method.
- Throttles using a process-local in-memory map keyed by
  `(ip, path, status)` with a 5-minute window. A noisy probing client
  generates one audit row per (ip, path, status) per 5 min, not one
  per request.
- Never includes the `detail` message in audit metadata (it can carry
  user-supplied input that callers may not want round-tripped).

**Tested:** `test_denial_audit_throttle_dedupes`.

**Open:** role-permission denials inside dependencies (e.g.
`require_owner`) currently raise `HTTPException(403)` and so flow
through the denial-audit handler — but they could be more usefully
audited at the dependency itself with the actual denied role string.
That's a Sprint 4 enhancement.

---

## 6. Security admin UI / API

**Done:** the existing owner-gated `GET /api/v1/security/status`
endpoint (added in Sprint 2) now returns three new fields:

- `is_production` — whether the production guardrail is active.
- `legacy_gateway_token_count` — how many gateways still have a
  plaintext `token` column value (i.e. how much legacy migration
  remains).
- `audit_retention_preview` — `{category: row_count}` of rows
  eligible for retention purge under the per-category cutoffs in
  `app.services.audit_retention`.

The `missing_prerequisites` list now flags non-zero
`legacy_gateway_token_count` so an operator scanning the endpoint
sees the migration backlog at a glance.

**Not done:** a dedicated frontend security page. Deferred — the JSON
endpoint is enough for Sprint 3 needs, and a UI requires design
choices (toggles? consent revocation? approval acceptance?) that
should follow Sprint 4's broader admin work.

---

## 7. Audit retention status

**Done — foundation only.** No row is deleted automatically by this
sprint.

`app.services.audit_retention` provides:

- `RETENTION_DAYS_BY_CATEGORY` — per-category retention windows. Auth
  events: 90 days. Most credential / role / connector / creator-data
  events: 730 days. Security events: 1825 days (5 y). Default for
  unlisted: 730 days.
- `cutoff_for_category(category)` — pure helper.
- `preview_purge(session)` — counts eligible rows by category.
  No mutation.
- `purge_old_audit_events(session, dry_run=True)` — `dry_run` defaults
  to True. With `dry_run=False`, deletes per category and returns a
  count summary; caller commits.

**Operational use:** a future RQ-scheduled job calls
`purge_old_audit_events(dry_run=False)` once a week. This sprint
ships the helpers; the schedule is Sprint 4.

**Tested:** `test_audit_retention_preview_counts_old_rows`.

---

## 8. PII redaction before LLM

**Done:** `app.core.pii_redact.redact_for_llm(text)` is called from
`ai_backend.ask_ai_detailed` before the prompt reaches any provider
client. The redactor strips:

- `Bearer …` / `Basic …` headers.
- Vendor key prefixes: `sk-…`, `sk_live_…`, `pk_live_…`,
  `ghp_…`, `AKIA…`, `xoxb-…`, `AIza…`.
- JWT-shaped triple-segment tokens (`eyJ….….….`).
- Email addresses.
- Phone numbers (≥10 digits with optional formatting).
- Long opaque alphanumeric tokens (≥32 chars).

The redactor is conservative — false negatives over false positives.
Strings like `creator-A`, `FY24Q1`, `mm-001` survive. Verified by
`test_pii_redact_preserves_normal_business_strings`.

**Audit:** the LLM audit event now carries
`pii_redaction_applied: bool` and `pii_redaction_counts: {label: n}`.
The original prompt is **never** logged.

**Not done:** structured PII (names, addresses, free-text identifier
scrub). The brief explicitly accepts this scope: "If full LLM
redaction is risky, add helper and wire only to safest wrapper."

---

## 9. Connector gate wiring

**Done — wrapper, not wired.**
`app.services.connector_run.run_with_gate(...)` is the call-site
helper a future connector must use. It composes
`is_connector_action_allowed()` from Sprint 2, runs the supplied
callable on success, and writes a `connector.run.blocked` audit row
on failure (caller commits).

The wrapper is **not** wired into any production hot path on this
branch. The reasons (which the brief explicitly authorised):

- There is no OnlyMonster / OnlyFans connector code on this branch
  (it lives on `feat/of-intelligence`). Wiring there is part of that
  work, not Sprint 3.
- The closest existing integration on this branch — gateway
  `sync_templates` — is a hot production path; gating it without an
  opt-in could break active gateway operations.

**Sprint 4 task:** wire `run_with_gate` into the OnlyMonster sync as
the first production proof, before any direct OF connector code is
written.

**Tested:** `test_run_with_gate_blocks_when_no_approval`,
`test_run_with_gate_runs_when_approval_and_consent_present`.

---

## 10. `NEXT_PUBLIC_LOCAL_AUTH_TOKEN` footgun

**Done:** [`frontend/src/auth/localAuth.ts`](../../frontend/src/auth/localAuth.ts)
now refuses the build-time fallback when
`process.env.NODE_ENV === "production"`, with a loud
`console.warn` so the footgun is visible if it ever ships.

Local / dev builds keep the convenience.

**Not done:** a CI grep that fails the build if any
`NEXT_PUBLIC_*` env var is *set* during a production build is a
broader hardening that's tracked separately. The runtime guard here
is the minimum-viable safety net.

---

## 11. Remaining gaps

| # | Gap | Severity | Sprint |
|---|---|---|---|
| G1 | `GatewayRead` API still exposes the `token` field; legacy rows leak until migrated | high | Sprint 4 (deprecate `token`, add `token_configured`) |
| G2 | Existing `app_settings` routes still write to global, not org-scoped | medium | Sprint 4 (migrate call sites with feature flag) |
| G3 | No login-success audit (Clerk webhook integration needed) | medium | Sprint 4 |
| G4 | Denial audit doesn't capture role/permission detail at dep level | low | Sprint 4 |
| G5 | Audit retention purge runs only when an operator invokes it manually | low | Sprint 4 (RQ schedule) |
| G6 | `connector_run.run_with_gate` not yet wired into any real sync path | medium | Sprint 4 (wire into OnlyMonster sync first) |
| G7 | LLM PII redactor doesn't scrub structured PII (names, addresses) | medium | post-MVP |
| G8 | No CI grep blocking `NEXT_PUBLIC_LOCAL_AUTH_TOKEN` in prod builds | low | infra-tooling sprint |
| G9 | `app_settings_scoped` keeps PK as `key` and uses derived prefixes; future schema should be `(key, organization_id)` unique | low | Sprint 4 |
| G10 | Per-creator key partitioning still missing in `creator_credentials` | medium | future |
| G11 | No frontend security dashboard | low | Sprint 4 |

---

## 12. Recommended Security Sprint 4

In priority order:

1. **Wire `run_with_gate` into the OnlyMonster sync.** First
   production proof of the gate on a real, non-OF integration. Adds
   `connector.run.start` / `connector.run.finish` audit events around
   real I/O without changing the OnlyMonster client itself.
2. **Migrate `app_settings` callers to org-scoped reads/writes** with
   a feature flag for the cutover. Promote `(key, organization_id)`
   to a unique constraint once everyone is on the helper.
3. **Strip `token` from `GatewayRead`** and add `token_configured:
   bool`. Run the legacy migrator; verify zero rows have plaintext
   left.
4. **Schedule audit retention** as an RQ job (weekly, dry-run report
   to admin email; quarterly, real purge).
5. **Login-success audit via Clerk webhook.** New endpoint
   `POST /api/v1/auth/webhooks/clerk` that consumes
   `session.created` events.
6. **Per-dep denial audit detail** — dependencies that 403 should
   write an audit row with the role/permission they were checking.
7. **Frontend security admin page** — read-only first, then add
   approve / kill-switch toggles in a follow-up once the workflow is
   designed.
