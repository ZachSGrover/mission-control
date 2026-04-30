# Security Sprint 4 — Operations

**Status:** Sprint 4 of N. Turns the Sprint 1–3 foundation into something
an operator can actually drive: admin endpoints, a frontend security
page, login-success audit hook, audit-retention scheduler, denial-audit
enrichment, and stricter frontend production guards.
**Branch:** `feat/security-operations-sprint-4`
**Last updated:** 2026-04-29

Companion to:
- [Sprint 1 audit foundation](./audit-events-implementation.md)
- [Sprint 2 prevention](./security-sprint-2-implementation.md)
- [Sprint 3 hardening](./security-sprint-3-implementation.md)

---

## 1. What was added

| Concern | Where |
|---|---|
| Admin endpoints (kill-switch toggles, approval decisions, consent revocation, gateway-token migration, gate preview) | [`backend/app/api/security_admin.py`](../../backend/app/api/security_admin.py) (extended in place) |
| `GatewayRead.token_configured` boolean | [`backend/app/schemas/gateways.py`](../../backend/app/schemas/gateways.py) |
| Denial-audit enrichment (route pattern, reason category, best-effort actor) | [`backend/app/core/denial_audit.py`](../../backend/app/core/denial_audit.py) |
| Audit retention scheduler (foundation, opt-in, default dry-run) | [`backend/app/services/audit_retention_scheduler.py`](../../backend/app/services/audit_retention_scheduler.py) |
| Clerk webhook receiver (login-success audit) | [`backend/app/api/clerk_webhooks.py`](../../backend/app/api/clerk_webhooks.py), registered in [`backend/app/main.py`](../../backend/app/main.py) |
| PII redactor improvements (Anthropic `sk-ant-`, GitHub gh{p,o,u,r,s}_, Stripe test keys, Twilio AC, SendGrid SG., generic `X-API-Key:` header pairs) | [`backend/app/core/pii_redact.py`](../../backend/app/core/pii_redact.py) |
| Frontend `/security` admin page | [`frontend/src/app/security/page.tsx`](../../frontend/src/app/security/page.tsx) |
| Typed frontend security API client | [`frontend/src/lib/security/api.ts`](../../frontend/src/lib/security/api.ts) |
| Strengthened `NEXT_PUBLIC_LOCAL_AUTH_TOKEN` guard | [`frontend/src/auth/localAuth.ts`](../../frontend/src/auth/localAuth.ts) |
| Tests | [`backend/tests/test_security_operations.py`](../../backend/tests/test_security_operations.py) |

---

## 2. Connector gate wiring — status

**Done:** the gate is now reachable from a real admin endpoint at
`POST /api/v1/security/connector-gate/preview`. Operators (and a
future direct connector) can run the gate end-to-end without
executing any real connector action. The endpoint records a
`connector.gate.preview` audit row at category `connector` so every
"would this be allowed?" check is visible in the trail.

**Not done — explicit deferral:** wiring the gate as a *required*
pre-check on a hot existing path. The brief explicitly authorised
deferring this when the existing path is risky. There is **no**
OnlyMonster client on this branch (it lives on `feat/of-intelligence`),
and the closest existing integration on this branch — gateway
`sync_templates` — is too critical to gate without an opt-in. Sprint 5
will wire the gate into the OnlyMonster sync as the first production
proof, before any direct OF connector code is written.

The wrapper at [`backend/app/services/connector_run.py`](../../backend/app/services/connector_run.py)
(Sprint 3) is the seam future connectors must use; the new preview
endpoint demonstrates it works end-to-end.

---

## 3. Gateway token migration — status

**Done:**
- New owner-only endpoint `POST /api/v1/security/gateway-tokens/migrate?dry_run=...`
  calls `migrate_legacy_tokens` from Sprint 3 and audits the
  invocation (every dry-run + every real run).
- New `GatewayRead.token_configured: bool` derived via a
  `model_validator` from either `token` or `encrypted_token`, so the
  frontend can display "configured" without reading the value.
- Frontend `/security` page exposes a dry-run + real-run button.

**Not done — explicit deferral:** the legacy `token` field is still in
`GatewayRead` for backwards compatibility with existing frontend code.
Sprint 5 will deprecate and remove it after the frontend has migrated
to `token_configured`.

---

## 4. Security admin UI — status

**Done.** Single owner-gated page at `/security` consumes
`/api/v1/security/status` plus the Sprint 4 listing endpoints
(`/approvals`, `/consents`) and shows:

- Production / dedicated-encryption-key flags
- Audit events (24h) count
- Legacy gateway token count
- Global kill-switch state with a confirm-modal toggle
- Full kill-switch list
- Recent connector approvals with approve/reject/revoke actions on each
- Recent client consents with revoke action on live ones
- Gateway token migration controls (dry-run + real)
- Audit-retention preview (per-category counts)
- Missing-prerequisites list

**Hard rules followed:** never displays secrets, never displays raw
audit metadata, never displays creator private data, every state
change goes through a backend service which audits it, every
destructive button has a confirmation modal.

---

## 5. Security control management — status

**Done — read + write for the controls listed in the brief:**

| Control | Read | Write |
|---|---|---|
| Global kill switch | ✅ | ✅ enable / disable |
| Connector kill switch | ✅ | (toggle UI deferred — backend supports it) |
| Connector approval | ✅ | ✅ approve / reject / revoke |
| Consent | ✅ | ✅ revoke |
| Credential vault | ✅ status | (no UI for adding creator credentials — Sprint 5+) |

**Not done — explicit deferral:** UI to *create* connector approvals
or grant consents (today they're created server-side or out-of-band).
Sprint 5 can add intake forms once the agency consent process is
documented.

---

## 6. Login success audit — status

**Done as a webhook stub** at `POST /api/v1/webhooks/clerk/`:

- Disabled by default. Refuses every request with HTTP 503 unless
  `CLERK_WEBHOOK_SECRET` is set in the env.
- When enabled, validates the request via constant-time HMAC
  comparison against `X-Mission-Control-Webhook-Secret` header.
  This is **not** the full Svix signature scheme Clerk uses; Sprint 5
  will replace it with `svix.Webhook(secret).verify(...)` once the
  package is approved as a dependency.
- On `session.created` events, writes an `auth.login.success` audit
  row at category `auth`, severity `info`, with the user id, email
  (when Clerk surfaces it), IP, and capped user-agent. **No tokens,
  no cookies, no session ids logged.**
- On non-`session.created` events (e.g. `user.created`), writes a
  `result="skipped"` audit so the operator can see the webhook is
  alive but we don't audit those event types yet.

**To enable in production:** set `CLERK_WEBHOOK_SECRET`, point Clerk
at `https://<host>/api/v1/webhooks/clerk/`, and pass the secret in the
`X-Mission-Control-Webhook-Secret` header on the Clerk Dashboard's
custom-headers configuration. Sprint 5 will swap to proper Svix
verification.

---

## 7. Denial audit — improvements

**Done.** The Sprint 3 `auth.denied.{unauthorized,forbidden}` audit
row now carries:

- `route_pattern` — the parameterised path (e.g. `/items/{id}`)
  instead of the concrete URL, so dashboards aggregate cleanly.
- `reason_category` — coarse bucket: `unauthenticated`,
  `role_required_owner`, `role_required_admin`, `allowlist`,
  `user_disabled`, `forbidden`. Inferred from the status code + a
  short fixed-keyword scan of the detail message; the original detail
  is still **not** logged.
- `actor_user_id` / `actor_email` — best-effort from
  `request.state` if a dependency happened to resolve them before
  the 401/403 was raised. Falls back to `None`.

Throttle is unchanged (1 audit per `(ip, route_pattern, status)` per
5 minutes, process-local).

---

## 8. Audit retention scheduling — status

**Done — opt-in foundation only.** The new
[`audit_retention_scheduler.py`](../../backend/app/services/audit_retention_scheduler.py)
exposes:

- `run_retention_pass(dry_run=...)` — single pass; defaults to dry-run;
  always audits the invocation.
- `run_retention_supervisor(stop_event)` — long-running async loop
  matching the existing `telegram_polling.run_supervisor` pattern.
  **Refuses to start unless `MC_AUDIT_RETENTION_ENABLED=1`.**
- `is_dry_run()` — defaults to True unless
  `MC_AUDIT_RETENTION_DRY_RUN=0` is explicitly set.

**Deliberately not registered in the FastAPI lifespan in this sprint.**
Sprint 5 will register the supervisor once the operations team has
signed off on the per-category retention windows in
`app.services.audit_retention.RETENTION_DAYS_BY_CATEGORY`.

---

## 9. Frontend auth guardrail — status

**Done.** [`localAuth.ts`](../../frontend/src/auth/localAuth.ts)
now refuses the `NEXT_PUBLIC_LOCAL_AUTH_TOKEN` build-time fallback
unless **all three** of:

1. `NODE_ENV !== "production"`,
2. `NEXT_PUBLIC_AUTH_MODE === "local"` (the token is meaningless in
   Clerk mode),
3. The runtime hostname is loopback / `.local` / `192.168.*` /
   `10.*` / `172.*` (best-effort defence in depth).

When the fallback is rejected, a loud `console.warn` makes the
condition visible. Sprint 5 will add a CI grep that fails the
production build if the variable is set at all.

---

## 10. PII redaction improvements

**Done — additive only, no changes to existing matches.** The vendor
key pattern now also catches:

- `sk-ant-…` (Anthropic)
- `gh[psour]_…` (GitHub PAT / install / oauth / refresh / server)
- `sk_test_…`, `pk_test_…` (Stripe test keys)
- `xox[bpaors]-…` (Slack)
- `AC[a-f0-9]{32}` (Twilio Account SID)
- `SG\.…\.…` (SendGrid)

Plus a new `header_pair` pattern that catches `X-API-Key: …`,
`Api-Key: …`, `Authorization: …` substrings inline in prose.

The redactor is still conservative — false negatives over false
positives — and the existing tests verifying `creator-A`, `mm-001`
etc. survive untouched.

---

## 11. Remaining gaps

| # | Gap | Severity | Sprint |
|---|---|---|---|
| G1 | `GatewayRead.token` field still exposed for backwards compat | high | Sprint 5 (deprecate after frontend uses `token_configured`) |
| G2 | Existing `app_settings` / `integrations` route call sites still write to global rows | medium | Sprint 5 |
| G3 | Clerk webhook uses shared-secret HMAC, not Svix | medium | Sprint 5 |
| G4 | Connector gate not wired into a real production hot path | medium | Sprint 5 (OnlyMonster sync first) |
| G5 | Audit-retention supervisor not registered in lifespan | low | Sprint 5 |
| G6 | No CI grep blocking `NEXT_PUBLIC_LOCAL_AUTH_TOKEN` in prod builds | low | infra-tooling sprint |
| G7 | Per-creator key partitioning still missing in `creator_credentials` | medium | future |
| G8 | Per-dep denial audit detail (specific role/permission strings at the dep) | low | Sprint 5 |
| G9 | No UI to *create* approvals / grant consents (read + revoke only) | low | Sprint 5 if intake flow is finalised |
| G10 | LLM PII redactor doesn't scrub structured names/addresses | medium | post-MVP |

---

## 12. Recommended Security Sprint 5

In priority order:

1. **Wire `run_with_gate` into the OnlyMonster sync** when the OFI
   branch merges. First production proof of the gate on a real,
   non-OF integration. Adds `connector.run.start` /
   `connector.run.finish` audit events around real I/O without
   changing the OnlyMonster client.
2. **Deprecate `GatewayRead.token`.** Migrate the frontend off it,
   run the legacy migrator in production once, then drop the field
   from the schema.
3. **Migrate `app_settings` / `integrations` callers to org-scoped
   reads/writes** with a feature flag for the cutover. Promote
   `(key, organization_id)` to a unique constraint.
4. **Replace the Clerk webhook shared-secret check with Svix
   verification.**
5. **Schedule the audit-retention supervisor** in the lifespan with
   `MC_AUDIT_RETENTION_ENABLED=1` set in production.
6. **Per-dep denial audit detail.** Owner-required deps that 403
   should write the role string they were checking.
7. **CI grep** that fails the production frontend build if any
   `NEXT_PUBLIC_*` env var with a secret-shaped name is set.
